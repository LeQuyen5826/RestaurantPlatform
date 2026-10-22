"""Đặt cọc qua VietQR + webhook SePay (chuyển khoản thật). Bọc sau lớp nhỏ để đổi nhà cung cấp."""
import hmac
import re
import secrets
from urllib.parse import urlencode

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Payment, Reservation, WebhookLog
from ..realtime import hub
from ..timeutil import now_local

CODE_RE = re.compile(r"DB[0-9A-F]{8}")


def new_payment_code() -> str:
    return "DB" + secrets.token_hex(4).upper()  # 4 byte ngẫu nhiên: khó đoán, đủ ngắn để khách gõ/quét


def qr_image_url(code: str, amount: int) -> str:
    """Ảnh VietQR do SePay dựng sẵn (số TK, ngân hàng, số tiền, nội dung = mã thanh toán)."""
    q = urlencode({"acc": settings.bank_account, "bank": settings.bank_code, "amount": amount, "des": code})
    return f"https://qr.sepay.vn/img?{q}"


def verify_webhook_auth(authorization: str | None) -> None:
    """SePay gửi header `Authorization: Apikey <key>`. Chạy thật nên chuyển sang HMAC-SHA256."""
    expected = f"Apikey {settings.sepay_api_key}"
    if not authorization or not hmac.compare_digest(authorization, expected):
        raise HTTPException(401, "Sai khóa webhook")


def extract_code(payload: dict) -> str | None:
    for field in (payload.get("code"), payload.get("content"), payload.get("description")):
        if field:
            m = CODE_RE.search(str(field).upper().replace(" ", ""))
            if m:
                return m.group(0)
    return None


def expire_holds(db: Session) -> int:
    """Nhả slot các đặt bàn quá hạn giữ chỗ (gọi bởi APScheduler mỗi phút và trước khi tính chỗ trống)."""
    now = now_local()
    ids = list(db.scalars(select(Reservation.id).where(
        Reservation.status == "pending_deposit", Reservation.hold_until < now)))
    if not ids:
        return 0
    db.execute(update(Reservation).where(Reservation.id.in_(ids), Reservation.status == "pending_deposit")
               .values(status="expired"))
    db.execute(update(Payment).where(Payment.reservation_id.in_(ids), Payment.status == "pending")
               .values(status="expired"))
    db.commit()
    return len(ids)


def process_sepay_webhook(db: Session, payload: dict) -> dict:
    """Idempotent: transaction_id UNIQUE chặn xử lý trùng; cập nhật có điều kiện status + số tiền."""
    if str(payload.get("transferType", "in")).lower() != "in":
        return {"result": "ignored"}
    tx_id = str(payload.get("id") or payload.get("referenceCode") or "")
    if not tx_id:
        raise HTTPException(400, "Thiếu id giao dịch")
    amount = int(payload.get("transferAmount") or 0)

    log = WebhookLog(transaction_id=tx_id, payload=payload, amount=amount, result="processing")
    db.add(log)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        return {"result": "duplicate"}

    code = extract_code(payload)
    pay = db.scalar(select(Payment).where(Payment.code == code)) if code else None
    reservation_id = None

    if not pay:
        log.result = "unmatched"
    else:
        reservation_id = pay.reservation_id
        log.payment_id = pay.id
        if pay.status == "paid":
            log.result = "duplicate_payment"          # chuyển lần 2 cho cùng mã -> quản lý hoàn thủ công
        else:
            total = (pay.received_amount or 0) + amount
            if total < pay.amount:
                pay.received_amount = total
                log.result = "underpaid"              # giữ chờ, ghi chú; khách có thể chuyển nốt
            else:
                # Xác nhận đặt bàn chỉ khi còn ở trạng thái chờ cọc (chưa hết hạn/hủy)
                changed = db.execute(update(Reservation).where(
                    Reservation.id == pay.reservation_id, Reservation.status == "pending_deposit"
                ).values(status="confirmed", hold_until=None)).rowcount
                if not changed:
                    pay.received_amount = total
                    log.result = "late"               # tiền về sau khi hết hạn/hủy -> quản lý xử lý
                else:
                    db.execute(update(Payment).where(
                        Payment.id == pay.id, Payment.status == "pending", Payment.amount <= total
                    ).values(status="paid", transaction_id=tx_id, paid_at=now_local(), received_amount=total))
                    log.result = "overpaid" if total > pay.amount else "confirmed"
    log.resolved = log.result in ("confirmed", "ignored")
    db.commit()

    if log.result in ("confirmed", "overpaid") and reservation_id:
        res = db.get(Reservation, reservation_id)
        if res and res.user_id:
            hub.publish(f"user:{res.user_id}", {"type": "deposit_paid", "reservation_id": reservation_id})
    return {"result": log.result}
