from collections import Counter
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Interaction, OrderItem, Payment, Recommendation, Reservation, User
from ..schemas import item_out
from ..security import current_user_optional, require_roles
from ..services.recommend import log_interaction, recommend
from ..timeutil import now_local

router = APIRouter(prefix="/api", tags=["insights"])


@router.get("/recommendations")
def recommendations(limit: int = 5, user: User | None = Depends(current_user_optional), db: Session = Depends(get_db)):
    limit = max(1, min(limit, 10))
    return [{"rec_id": r["rec_id"], "level": r["level"], "reason_code": r["reason_code"],
             "reason_text": r["reason_text"], "item": item_out(r["item"])} for r in recommend(db, user, limit)]


@router.post("/recommendations/{rec_id}/accept")
def accept(rec_id: int, db: Session = Depends(get_db)):
    rec = db.get(Recommendation, rec_id)
    if not rec:
        raise HTTPException(404, "Không tìm thấy gợi ý")
    rec.accepted = True
    db.commit()
    return {"ok": True}


class InteractionIn(BaseModel):
    menu_item_id: int
    type: str = "view"


@router.post("/interactions")
def interaction(body: InteractionIn, user: User | None = Depends(current_user_optional), db: Session = Depends(get_db)):
    if body.type not in ("view", "add_to_cart"):
        raise HTTPException(400, "Loại tương tác không hợp lệ")
    log_interaction(db, user.id if user else None, body.menu_item_id, body.type)
    db.commit()
    return {"ok": True}


@router.get("/dashboard")
def dashboard(from_: date | None = Query(None, alias="from"), to: date | None = None, _: User = Depends(require_roles("manager")),
              db: Session = Depends(get_db)):
    end_d = to or now_local().date()
    start_d = from_ or end_d - timedelta(days=29)
    start, end = datetime.combine(start_d, datetime.min.time()), datetime.combine(end_d, datetime.max.time())

    status = dict(db.execute(select(Reservation.status, func.count()).where(
        Reservation.start_at.between(start, end)).group_by(Reservation.status)).all())
    attended = status.get("checked_in", 0) + status.get("completed", 0)
    noshow = status.get("no_show", 0)
    deposit = db.scalar(select(func.coalesce(func.sum(Payment.received_amount), 0)).where(
        Payment.status == "paid", Payment.paid_at.between(start, end))) or 0

    top = Counter()
    for name, qty in db.execute(select(OrderItem.name, OrderItem.qty).where(
            OrderItem.created_at.between(start, end), OrderItem.status.in_(("submitted", "preparing", "ready", "served")))):
        top[name] += qty

    shown = db.scalar(select(func.count()).select_from(Recommendation).where(
        Recommendation.shown_at.between(start, end))) or 0
    acc = db.scalar(select(func.count()).select_from(Recommendation).where(
        Recommendation.shown_at.between(start, end), Recommendation.accepted.is_(True))) or 0

    return {"from": start_d.isoformat(), "to": end_d.isoformat(),
            "reservations": {"total": sum(status.values()), "by_status": status},
            "no_show_rate": round(noshow / (attended + noshow), 3) if (attended + noshow) else 0,
            "deposit_collected": deposit,
            "top_items": [{"name": n, "qty": q} for n, q in top.most_common(5)],
            "recommendation": {"shown": shown, "accepted": acc, "acceptance_rate": round(acc / shown, 3) if shown else 0}}
