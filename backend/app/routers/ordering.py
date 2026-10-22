"""Gọi món QR tại bàn: phiên bàn có token, giỏ chung, đẩy món tới bếp/phục vụ qua WebSocket."""
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import DiningTable, MenuItem, OrderItem, Reservation, TableSession, User
from ..realtime import hub
from ..security import (current_table_session, current_user_optional, get_allergies, hit, make_token,
                        read_table_qr, require_roles)
from ..services.recommend import log_interaction
from ..timeutil import now_local

router = APIRouter(prefix="/api", tags=["ordering"])
staff = require_roles("waiter", "manager")
STAFF_ALL = require_roles("waiter", "manager", "kitchen")
BILLABLE = ("submitted", "preparing", "ready", "served")


def _item_out(oi: OrderItem) -> dict:
    return {"id": oi.id, "menu_item_id": oi.menu_item_id, "name": oi.name, "price": oi.price, "qty": oi.qty,
            "note": oi.note, "status": oi.status, "allergens": oi.menu_item.allergens if oi.menu_item else []}


def _total(items: list[OrderItem]) -> int:
    return sum(i.price * i.qty for i in items if i.status in BILLABLE)


def open_session(db: Session, table_id: int, reservation_id: int | None = None) -> TableSession:
    existing = db.scalar(select(TableSession).where(TableSession.table_id == table_id, TableSession.status == "open"))
    if existing:
        return existing
    s = TableSession(table_id=table_id, reservation_id=reservation_id)
    db.add(s)
    try:
        db.commit()
    except IntegrityError:  # unique index "một phiên mở cho mỗi bàn" – người khác vừa mở
        db.rollback()
        return db.scalar(select(TableSession).where(TableSession.table_id == table_id, TableSession.status == "open"))
    return s


# ---------- nhân viên mở / đóng phiên ----------
class OpenIn(BaseModel):
    table_id: int
    reservation_id: int | None = None


@router.post("/sessions/open")
def open_table(body: OpenIn, _: User = Depends(staff), db: Session = Depends(get_db)):
    if not db.get(DiningTable, body.table_id):
        raise HTTPException(404, "Không tìm thấy bàn")
    s = open_session(db, body.table_id, body.reservation_id)
    return {"session_id": s.id, "table_id": s.table_id}


@router.get("/sessions/open")
def list_open(_: User = Depends(staff), db: Session = Depends(get_db)):
    out = []
    for s in db.scalars(select(TableSession).where(TableSession.status == "open").order_by(TableSession.id)):
        items = db.scalars(select(OrderItem).where(OrderItem.session_id == s.id, OrderItem.status != "cancelled")).all()
        out.append({"session_id": s.id, "table": s.table.name, "table_id": s.table_id, "total": _total(items),
                    "items": [_item_out(i) for i in items if i.status != "in_cart"]})
    return out


@router.post("/sessions/{sid}/close")
def close_session(sid: int, _: User = Depends(staff), db: Session = Depends(get_db)):
    s = db.get(TableSession, sid)
    if not s or s.status != "open":
        raise HTTPException(404, "Phiên không tồn tại hoặc đã đóng")
    db.execute(update(OrderItem).where(OrderItem.session_id == sid, OrderItem.status == "in_cart")
               .values(status="cancelled"))
    items = db.scalars(select(OrderItem).where(OrderItem.session_id == sid)).all()
    s.status, s.closed_at = "closed", now_local()
    if s.reservation_id:
        db.execute(update(Reservation).where(Reservation.id == s.reservation_id, Reservation.status == "checked_in")
                   .values(status="completed"))
    db.commit()
    hub.publish(f"session:{sid}", {"type": "session_closed"})
    return {"session_id": sid, "total": _total(items)}


class StaffOrderIn(BaseModel):
    menu_item_id: int
    qty: int = Field(1, ge=1, le=50)
    note: str = Field("", max_length=255)


@router.post("/sessions/{sid}/items")
def staff_order(sid: int, body: StaffOrderIn, _: User = Depends(staff), db: Session = Depends(get_db)):
    """Phục vụ gọi món hộ khách: vào bếp ngay."""
    s = db.get(TableSession, sid)
    if not s or s.status != "open":
        raise HTTPException(404, "Phiên không tồn tại hoặc đã đóng")
    oi = _add_item(db, s.id, None, body.menu_item_id, body.qty, body.note, status="submitted")
    db.commit()
    _announce_submitted(db, s, [oi])
    return _item_out(oi)


# ---------- khách quét QR ----------
class JoinIn(BaseModel):
    table_token: str


@router.post("/sessions/join")
def join(body: JoinIn, request: Request, user: User | None = Depends(current_user_optional),
         db: Session = Depends(get_db)):
    table_id = read_table_qr(body.table_token)
    if not table_id:
        raise HTTPException(400, "Mã QR không hợp lệ")
    hit(f"join:{table_id}", 20, 60)
    hit(f"join-ip:{request.client.host if request.client else '?'}", 30, 60)
    s = db.scalar(select(TableSession).where(TableSession.table_id == table_id, TableSession.status == "open"))
    if not s:
        raise HTTPException(409, "Bàn chưa được mở, vui lòng gọi nhân viên")
    claims = {"k": "sess", "sid": s.id, "tid": table_id}
    if user:
        claims["uid"] = user.id
    token = make_token(claims, settings.session_ttl_minutes * 60)
    return {"session_token": token, "session_id": s.id, "table": s.table.name}


def _add_item(db: Session, sid: int, uid: int | None, menu_item_id: int, qty: int, note: str,
              status: str = "in_cart") -> OrderItem:
    mi = db.get(MenuItem, menu_item_id)
    if not mi or mi.deleted:
        raise HTTPException(404, "Không tìm thấy món")
    if not mi.available:
        raise HTTPException(409, "Món đã hết")
    if status == "in_cart":
        same = db.scalar(select(OrderItem).where(
            OrderItem.session_id == sid, OrderItem.menu_item_id == menu_item_id, OrderItem.status == "in_cart",
            OrderItem.note == note, OrderItem.user_id == uid))
        if same:
            same.qty += qty
            return same
    oi = OrderItem(session_id=sid, menu_item_id=menu_item_id, user_id=uid, name=mi.name, price=mi.price,
                   qty=qty, note=note, status=status)
    db.add(oi)
    db.flush()
    return oi


@router.get("/session/cart")
def get_cart(ctx=Depends(current_table_session), db: Session = Depends(get_db)):
    s, _uid = ctx
    items = db.scalars(select(OrderItem).where(OrderItem.session_id == s.id, OrderItem.status != "cancelled")
                       .order_by(OrderItem.id)).all()
    return {"session_id": s.id, "table": s.table.name, "total": _total(items),
            "cart": [_item_out(i) for i in items if i.status == "in_cart"],
            "orders": [_item_out(i) for i in items if i.status != "in_cart"]}


class CartAddIn(BaseModel):
    menu_item_id: int
    qty: int = Field(1, ge=1, le=20)
    note: str = Field("", max_length=255)


@router.post("/session/cart")
def add_cart(body: CartAddIn, ctx=Depends(current_table_session), db: Session = Depends(get_db)):
    s, uid = ctx
    hit(f"cart:{s.id}", 60, 60)  # giới hạn tốc độ theo bàn chống lạm dụng QR
    oi = _add_item(db, s.id, uid, body.menu_item_id, body.qty, body.note)
    log_interaction(db, uid, body.menu_item_id, "add_to_cart")
    db.commit()
    hub.publish(f"session:{s.id}", {"type": "cart_changed"})
    return _item_out(oi)


class CartQtyIn(BaseModel):
    qty: int = Field(ge=0, le=20)


@router.patch("/session/cart/{item_id}")
def set_cart_qty(item_id: int, body: CartQtyIn, ctx=Depends(current_table_session), db: Session = Depends(get_db)):
    s, _uid = ctx
    oi = db.get(OrderItem, item_id)
    if not oi or oi.session_id != s.id or oi.status != "in_cart":
        raise HTTPException(404, "Không tìm thấy món trong giỏ")
    if body.qty == 0:
        oi.status = "cancelled"
    else:
        oi.qty = body.qty
    db.commit()
    hub.publish(f"session:{s.id}", {"type": "cart_changed"})
    return {"ok": True}


@router.post("/session/submit")
def submit_cart(ctx=Depends(current_table_session), db: Session = Depends(get_db)):
    s, _uid = ctx
    hit(f"submit:{s.id}", 10, 60)
    items = db.scalars(select(OrderItem).where(OrderItem.session_id == s.id, OrderItem.status == "in_cart")).all()
    if not items:
        raise HTTPException(400, "Giỏ hàng trống")
    for oi in items:
        mi = db.get(MenuItem, oi.menu_item_id)
        if not mi or not mi.available or mi.deleted:
            raise HTTPException(409, f"Món «{oi.name}» vừa hết, vui lòng bỏ khỏi giỏ")
    for oi in items:
        oi.status = "submitted"
        log_interaction(db, oi.user_id, oi.menu_item_id, "order")
    db.commit()
    _announce_submitted(db, s, items)
    return {"submitted": len(items)}


def _announce_submitted(db: Session, s: TableSession, items: list[OrderItem]) -> None:
    payload = {"type": "order_submitted", "session_id": s.id, "table": s.table.name,
               "items": [_item_out(i) for i in items]}
    hub.publish(["kitchen", "staff", f"session:{s.id}"], payload)


# ---------- bếp & phục vụ ----------
@router.get("/kitchen/orders")
def kitchen_orders(_: User = Depends(STAFF_ALL), db: Session = Depends(get_db)):
    rows = db.scalars(select(OrderItem).where(OrderItem.status.in_(("submitted", "preparing", "ready")))
                      .order_by(OrderItem.created_at, OrderItem.id)).all()
    out = []
    for oi in rows:
        s = db.get(TableSession, oi.session_id)
        alert = []
        if oi.user_id:  # chỉ lộ ra khi món xung đột với dị ứng khách đã khai; bếp không thấy thông tin cá nhân khác
            alert = sorted({a.lower() for a in get_allergies(db.get(User, oi.user_id))}
                           & {a.lower() for a in (oi.menu_item.allergens or [])})
        out.append({**_item_out(oi), "table": s.table.name, "session_id": s.id,
                    "created_at": oi.created_at.isoformat(), "allergy_alert": alert})
    return out


class StatusIn(BaseModel):
    status: str = Field(pattern="^(preparing|ready|served)$")


TRANSITIONS = {  # (từ, sang): vai được phép
    ("submitted", "preparing"): {"kitchen"},
    ("preparing", "ready"): {"kitchen"},
    ("submitted", "ready"): {"kitchen"},
    ("ready", "served"): {"waiter"},
}


@router.patch("/order-items/{item_id}/status")
def set_status(item_id: int, body: StatusIn, user: User = Depends(STAFF_ALL), db: Session = Depends(get_db)):
    oi = db.get(OrderItem, item_id)
    if not oi:
        raise HTTPException(404, "Không tìm thấy món")
    allowed = TRANSITIONS.get((oi.status, body.status))
    if allowed is None:
        raise HTTPException(409, f"Không thể chuyển từ {oi.status} sang {body.status}")
    if user.role not in allowed:  # bếp đổi trạng thái chế biến, phục vụ xác nhận đã bưng; quản lý không làm hộ
        raise HTTPException(403, "Vai trò của bạn không được đổi trạng thái này")
    oi.status = body.status
    db.commit()
    hub.publish(["kitchen", "staff", f"session:{oi.session_id}"],
                {"type": "item_status", "item_id": oi.id, "status": oi.status, "session_id": oi.session_id})
    return _item_out(oi)


@router.post("/order-items/{item_id}/cancel")
def cancel_item(item_id: int, _: User = Depends(staff), db: Session = Depends(get_db)):
    oi = db.get(OrderItem, item_id)
    if not oi or oi.status in ("served", "cancelled"):
        raise HTTPException(409, "Không thể hủy món này")
    oi.status = "cancelled"
    db.commit()
    hub.publish(["kitchen", "staff", f"session:{oi.session_id}"],
                {"type": "item_status", "item_id": oi.id, "status": "cancelled", "session_id": oi.session_id})
    return {"ok": True}
