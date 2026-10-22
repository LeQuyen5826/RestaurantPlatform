from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import select

from app.db import SessionLocal
from app.models import Payment, Reservation
from app.services import booking
from app.services.payment import process_sepay_webhook
from app.timeutil import now_local

from .conftest import login, register


def _slot(db, hour=19):
    r = db.get(booking.Restaurant, 1)
    day = (now_local() + timedelta(days=2)).date()
    return r, next(s for s in booking.slot_starts(r, day) if s.hour == hour and s.minute == 0)


def test_no_double_booking_under_concurrency(client):
    """NFR-01: chỉ 1 bàn 8 chỗ -> 20 request đồng thời chỉ được 1 thành công."""
    with SessionLocal() as db:
        r, start = _slot(db, 20)

    def attempt(_):
        with SessionLocal() as db:
            try:
                booking.create_reservation(db, r, None, 8, start)
                return "ok"
            except HTTPException as e:
                return e.status_code

    with ThreadPoolExecutor(20) as ex:
        results = list(ex.map(attempt, range(20)))
    assert results.count("ok") == 1
    assert all(x in ("ok", 409) for x in results)


def test_webhook_idempotent_and_amount_checked(client):
    with SessionLocal() as db:
        r, start = _slot(db, 18)
        res = booking.create_reservation(db, r, None, 2, start)
        pay = db.scalar(select(Payment).where(Payment.reservation_id == res.id))
        code, need = pay.code, pay.amount
        rid = res.id

    def payload(tx, amt):
        return {"id": tx, "transferType": "in", "transferAmount": amt, "content": f"CK {code} cam on"}

    with SessionLocal() as db:
        assert process_sepay_webhook(db, payload(9001, need - 1000))["result"] == "underpaid"
        assert db.get(Reservation, rid).status == "pending_deposit"
    with SessionLocal() as db:
        assert process_sepay_webhook(db, payload(9002, 1000))["result"] == "confirmed"  # cộng dồn đủ tiền
        assert db.get(Reservation, rid).status == "confirmed"
    with SessionLocal() as db:
        assert process_sepay_webhook(db, payload(9002, 1000))["result"] == "duplicate"  # cùng transaction_id
    with SessionLocal() as db:
        assert process_sepay_webhook(db, payload(9003, need))["result"] == "duplicate_payment"
    with SessionLocal() as db:
        assert process_sepay_webhook(db, {"id": 9004, "transferType": "in", "transferAmount": 5, "content": "khong ma"})[
            "result"] == "unmatched"


def test_webhook_endpoint_rejects_bad_key(client):
    assert client.post("/api/webhooks/sepay", json={"id": 1}, headers={"Authorization": "Apikey sai"}).status_code == 401


def test_allergy_hard_filter_and_cold_start(client):
    h = register(client, "di-ung@example.com")
    client.put("/api/me/profile", headers=h, json={"spicy_level": 1, "diet": "none", "allergies": ["Peanut", "shellfish"],
                                                    "cuisines": ["viet"], "budget_max": 0})
    client.put("/api/me/consent", headers=h, json={"personalization": True})
    recs = client.get("/api/recommendations?limit=10", headers=h).json()
    assert recs, "không được trả danh sách rỗng"
    assert all(not ({"peanut", "shellfish"} & set(x["item"]["allergens"])) for x in recs)
    assert all(x["reason_code"] for x in recs)

    new = register(client, "moi@example.com")  # chưa onboarding, chưa đồng ý -> vẫn có gợi ý mức 0
    assert client.get("/api/recommendations", headers=new).json()


def test_role_isolation(client):
    kitchen, customer = login(client, "kitchen@demo.vn"), register(client, "khach-rbac@example.com")
    assert client.get("/api/reservations/today", headers=kitchen).status_code == 403
    assert client.get("/api/dashboard", headers=customer).status_code == 403
    assert client.get("/api/kitchen/orders", headers=customer).status_code == 403
    assert client.get("/api/kitchen/orders", headers=kitchen).status_code == 200


def test_qr_order_flow_to_kitchen(client):
    waiter, kitchen = login(client, "waiter@demo.vn"), login(client, "kitchen@demo.vn")
    tables = client.get("/api/tables", headers=login(client, "manager@demo.vn")).json()
    tid = tables[0]["id"]
    token = client.get(f"/api/tables/{tid}/qr", headers=login(client, "manager@demo.vn")).json()["token"]
    assert client.post("/api/sessions/join", json={"table_token": token}).status_code == 409  # bàn chưa mở
    client.post("/api/sessions/open", headers=waiter, json={"table_id": tid})
    sess = client.post("/api/sessions/join", json={"table_token": token}).json()["session_token"]
    sh = {"X-Session-Token": sess}
    menu_id = client.get("/api/menu").json()[0]["items"][0]["id"]
    assert client.post("/api/session/cart", headers=sh, json={"menu_item_id": menu_id, "qty": 2}).status_code == 200
    assert client.post("/api/session/submit", headers=sh).json()["submitted"] == 1
    orders = client.get("/api/kitchen/orders", headers=kitchen).json()
    item = next(o for o in orders if o["menu_item_id"] == menu_id)
    assert client.patch(f"/api/order-items/{item['id']}/status", headers=waiter, json={"status": "preparing"}).status_code == 403
    assert client.patch(f"/api/order-items/{item['id']}/status", headers=kitchen, json={"status": "preparing"}).status_code == 200
    assert client.patch(f"/api/order-items/{item['id']}/status", headers=kitchen, json={"status": "ready"}).status_code == 200
    assert client.patch(f"/api/order-items/{item['id']}/status", headers=waiter, json={"status": "served"}).status_code == 200


def test_compute_deposit():
    r = booking.Restaurant(deposit_per_guest=50000)
    assert booking.compute_deposit(r, 1) == 50000
    assert booking.compute_deposit(r, 4) == 200000
