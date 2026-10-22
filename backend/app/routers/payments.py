from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Payment, User, WebhookLog
from ..security import require_roles
from ..services.payment import process_sepay_webhook, verify_webhook_auth

router = APIRouter(prefix="/api", tags=["payments"])
manager = require_roles("manager")


@router.post("/webhooks/sepay")
def sepay_webhook(payload: dict, authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
    verify_webhook_auth(authorization)
    process_sepay_webhook(db, payload)
    return {"success": True}  # luôn 200 khi đã nhận để nhà cung cấp không gửi lại; kết quả xử lý nằm trong log


@router.get("/payments/queue")
def unmatched_queue(_: User = Depends(manager), db: Session = Depends(get_db)):
    """Giao dịch chưa khớp: sai nội dung, thiếu, thừa, trả sau hạn, chuyển trùng."""
    rows = db.scalars(select(WebhookLog).where(WebhookLog.resolved.is_(False)).order_by(WebhookLog.id.desc())).all()
    return [{"id": r.id, "transaction_id": r.transaction_id, "amount": r.amount, "result": r.result,
             "payment_id": r.payment_id, "content": r.payload.get("content"), "note": r.note,
             "created_at": r.created_at.isoformat()} for r in rows]


class NoteIn(BaseModel):
    note: str = ""


@router.post("/payments/queue/{log_id}/resolve")
def resolve(log_id: int, body: NoteIn, _: User = Depends(manager), db: Session = Depends(get_db)):
    log = db.get(WebhookLog, log_id)
    if not log:
        raise HTTPException(404, "Không tìm thấy giao dịch")
    log.resolved, log.note = True, body.note[:255]
    db.commit()
    return {"ok": True}


@router.get("/payments/refunds")
def refunds(_: User = Depends(manager), db: Session = Depends(get_db)):
    rows = db.scalars(select(Payment).where(Payment.refund_status.in_(("refund_pending", "refunded", "forfeited")))
                      .order_by(Payment.id.desc())).all()
    return [{"id": p.id, "reservation_id": p.reservation_id, "amount": p.amount,
             "refund_status": p.refund_status, "note": p.refund_note} for p in rows]


@router.post("/payments/{pid}/refund-recorded")
def refund_recorded(pid: int, body: NoteIn, _: User = Depends(manager), db: Session = Depends(get_db)):
    """Hoàn cọc thủ công bằng chuyển khoản ngoài hệ thống; hệ thống chỉ ghi vết."""
    p = db.get(Payment, pid)
    if not p or p.refund_status != "refund_pending":
        raise HTTPException(409, "Khoản này không ở trạng thái chờ hoàn")
    p.refund_status, p.refund_note = "refunded", body.note[:255]
    db.commit()
    return {"ok": True}


@router.post("/payments/reconcile")
def reconcile(transactions: list[dict], _: User = Depends(manager), db: Session = Depends(get_db)):
    """Đối soát bù webhook mất: đưa danh sách giao dịch (định dạng SePay) qua đúng bộ xử lý idempotent."""
    return [process_sepay_webhook(db, t) for t in transactions]
