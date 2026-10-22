from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Reservation, User
from ..schemas import reservation_out
from ..security import current_user, require_roles
from ..services import booking
from ..timeutil import now_local
from .ordering import open_session
from .restaurant import get_restaurant

router = APIRouter(prefix="/api", tags=["reservations"])
staff = require_roles("waiter", "manager")


@router.get("/availability")
def availability(date_: date = Query(alias="date"), party: int = Query(2, ge=1, le=50),
                 db: Session = Depends(get_db)):
    return booking.availability(db, get_restaurant(db), date_, party)


class ReserveIn(BaseModel):
    party_size: int = Field(ge=1, le=50)
    start_at: datetime


@router.post("/reservations")
def create(body: ReserveIn, user: User = Depends(require_roles("customer")), db: Session = Depends(get_db)):
    res = booking.create_reservation(db, get_restaurant(db), user, body.party_size, body.start_at.replace(tzinfo=None))
    return reservation_out(res)


@router.get("/reservations/mine")
def mine(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(Reservation).where(Reservation.user_id == user.id)
                      .order_by(Reservation.start_at.desc())).all()
    return [reservation_out(r) for r in rows]


@router.get("/reservations/today")
def today(date_: date | None = Query(None, alias="date"), _: User = Depends(staff), db: Session = Depends(get_db)):
    d = date_ or now_local().date()
    start, end = datetime.combine(d, datetime.min.time()), datetime.combine(d, datetime.max.time())
    rows = db.scalars(select(Reservation).where(Reservation.start_at.between(start, end))
                      .order_by(Reservation.start_at)).all()
    return [reservation_out(r, staff_view=True) for r in rows]


def _load(db: Session, rid: int, user: User) -> Reservation:
    res = db.get(Reservation, rid)
    if not res or (user.role == "customer" and res.user_id != user.id):
        raise HTTPException(404, "Không tìm thấy đặt bàn")
    if user.role == "kitchen":
        raise HTTPException(403, "Không đủ quyền")
    return res


@router.get("/reservations/{rid}")
def get_one(rid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    booking.expire_holds(db)
    return reservation_out(_load(db, rid, user), staff_view=user.role != "customer")


@router.post("/reservations/{rid}/cancel")
def cancel(rid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    res = _load(db, rid, user)
    return booking.cancel_reservation(db, get_restaurant(db), res, by_staff=user.role != "customer")


class RescheduleIn(BaseModel):
    start_at: datetime


@router.post("/reservations/{rid}/reschedule")
def reschedule(rid: int, body: RescheduleIn, user: User = Depends(require_roles("customer")),
               db: Session = Depends(get_db)):
    res = _load(db, rid, user)
    return reservation_out(booking.reschedule_reservation(db, get_restaurant(db), res,
                                                          body.start_at.replace(tzinfo=None)))


# ---------- thao tác của nhân viên ----------
@router.post("/reservations/{rid}/check-in")
def check_in(rid: int, user: User = Depends(staff), db: Session = Depends(get_db)):
    res = _load(db, rid, user)
    if res.status != "confirmed":
        raise HTTPException(409, "Chỉ check-in được đặt bàn đã cọc/xác nhận")
    res.status = "checked_in"
    db.commit()
    s = open_session(db, res.table_id, res.id)  # có đặt bàn hợp lệ -> mở phiên bàn để khách quét QR gọi món
    return {**reservation_out(res, True), "session_id": s.id}


@router.post("/reservations/{rid}/no-show")
def no_show(rid: int, user: User = Depends(staff), db: Session = Depends(get_db)):
    res = _load(db, rid, user)
    if res.status != "confirmed" or now_local() < res.start_at:
        raise HTTPException(409, "Chỉ đánh dấu no-show sau giờ hẹn với đặt bàn đã xác nhận")
    res.status = "no_show"
    if res.payment and res.payment.status == "paid":
        res.payment.refund_status = "forfeited"
    db.commit()
    return reservation_out(res, True)


class AssignIn(BaseModel):
    table_id: int


@router.post("/reservations/{rid}/assign-table")
def assign_table(rid: int, body: AssignIn, user: User = Depends(staff), db: Session = Depends(get_db)):
    res = _load(db, rid, user)
    return reservation_out(booking.move_table(db, get_restaurant(db), res, body.table_id), True)
