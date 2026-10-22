"""Đặt bàn theo slot, gán bàn best-fit, chống đặt trùng.

Chống trùng 2 lớp:
  1) Khóa dòng bàn (SELECT ... FOR UPDATE) rồi kiểm tra chồng lấn trong cùng transaction.
  2) PostgreSQL: ràng buộc EXCLUDE USING gist trên (table_id, khoảng thời gian) – lưới an toàn cuối cùng.
SQLite (dev/test) không có khóa dòng nên dùng thêm khóa tiến trình.
"""
import threading
from contextlib import nullcontext
from datetime import date, datetime, time, timedelta

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import settings
from ..db import IS_SQLITE
from ..models import ACTIVE_RES, DiningTable, Payment, Reservation, Restaurant, User
from ..timeutil import now_local
from .payment import expire_holds, new_payment_code

_sqlite_lock = threading.Lock()
MIN_LEAD = timedelta(minutes=15)


def _lock():
    return _sqlite_lock if IS_SQLITE else nullcontext()


def _hhmm(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


def slot_starts(r: Restaurant, day: date) -> list[datetime]:
    t = datetime.combine(day, _hhmm(r.open_time))
    close = datetime.combine(day, _hhmm(r.close_time))
    out = []
    while t + timedelta(minutes=r.slot_minutes) <= close:
        out.append(t)
        t += timedelta(minutes=r.slot_step_minutes)
    return out


def compute_deposit(r: Restaurant, party: int) -> int:
    """Tiền cọc = mức cọc mỗi khách x số khách."""
    return r.deposit_per_guest * party


def block_end(r: Restaurant, start: datetime) -> datetime:
    return start + timedelta(minutes=r.slot_minutes + r.buffer_minutes)


def _busy_table_ids(db: Session, start: datetime, end: datetime, exclude_id: int | None = None) -> set[int]:
    q = select(Reservation.table_id).where(
        Reservation.status.in_(ACTIVE_RES), Reservation.start_at < end, Reservation.end_at > start)
    if exclude_id:
        q = q.where(Reservation.id != exclude_id)
    return set(db.scalars(q))


def candidate_table_ids(db: Session, r: Restaurant, start: datetime, party: int,
                        exclude_id: int | None = None) -> list[int]:
    """Bàn trống phù hợp, xếp best-fit: bàn nhỏ nhất đủ chỗ trước."""
    busy = _busy_table_ids(db, start, block_end(r, start), exclude_id)
    rows = db.scalars(select(DiningTable).where(
        DiningTable.restaurant_id == r.id, DiningTable.active.is_(True),
        DiningTable.capacity >= party, DiningTable.min_guests <= party,
    ).order_by(DiningTable.capacity, DiningTable.id)).all()
    return [t.id for t in rows if t.id not in busy]


def availability(db: Session, r: Restaurant, day: date, party: int) -> list[dict]:
    expire_holds(db)
    now = now_local()
    out = []
    for s in slot_starts(r, day):
        if s < now + MIN_LEAD:
            continue
        n = len(candidate_table_ids(db, r, s, party))
        out.append({"start": s.isoformat(), "available": n > 0, "tables_left": n})
    return out


def _validate_start(r: Restaurant, start: datetime) -> None:
    if start not in slot_starts(r, start.date()):
        raise HTTPException(400, "Giờ không nằm trong các slot của nhà hàng")
    if start < now_local() + MIN_LEAD:
        raise HTTPException(400, "Giờ đặt đã qua hoặc quá gần")


def create_reservation(db: Session, r: Restaurant, user: User | None, party: int, start: datetime) -> Reservation:
    if party < 1:
        raise HTTPException(400, "Số khách không hợp lệ")
    _validate_start(r, start)
    expire_holds(db)
    end = block_end(r, start)
    deposit = compute_deposit(r, party)
    now = now_local()

    for table_id in candidate_table_ids(db, r, start, party):
        try:
            with _lock():
                # Khóa dòng bàn: request đồng thời vào cùng bàn phải xếp hàng, rồi kiểm tra lại chồng lấn
                db.execute(select(DiningTable.id).where(DiningTable.id == table_id).with_for_update())
                if table_id in _busy_table_ids(db, start, end):
                    db.rollback()
                    continue
                res = Reservation(
                    restaurant_id=r.id, user_id=user.id if user else None, table_id=table_id,
                    party_size=party, start_at=start, end_at=end, deposit_amount=deposit,
                    status="pending_deposit" if deposit else "confirmed",
                    hold_until=now + timedelta(minutes=settings.hold_minutes) if deposit else None,
                )
                db.add(res)
                db.flush()
                if deposit:
                    db.add(Payment(reservation_id=res.id, code=new_payment_code(), amount=deposit))
                db.commit()
                return res
        except IntegrityError:  # ràng buộc EXCLUDE của PostgreSQL bắt được trường hợp lọt kiểm tra
            db.rollback()
            continue
    raise HTTPException(409, "Hết bàn ở khung giờ này, vui lòng chọn giờ khác")


def cancel_reservation(db: Session, r: Restaurant, res: Reservation, by_staff: bool = False) -> dict:
    if res.status not in ("pending_deposit", "confirmed"):
        raise HTTPException(409, "Không thể hủy đặt bàn ở trạng thái này")
    free = res.start_at - now_local() >= timedelta(hours=r.cancel_free_hours)
    refund = "none"
    pay = res.payment
    if pay and pay.status == "paid":
        refund = "refund_pending" if (free or by_staff) else "forfeited"  # hoàn thủ công, hệ thống chỉ ghi vết
        pay.refund_status = refund
    elif pay and pay.status == "pending":
        pay.status = "cancelled"
    res.status = "cancelled"
    db.commit()
    return {"refund": refund, "free_cancel": free}


def reschedule_reservation(db: Session, r: Restaurant, res: Reservation, new_start: datetime) -> Reservation:
    if res.status not in ("pending_deposit", "confirmed"):
        raise HTTPException(409, "Không thể đổi giờ ở trạng thái này")
    if res.start_at - now_local() < timedelta(hours=r.cancel_free_hours):
        raise HTTPException(409, f"Chỉ được đổi giờ trước {r.cancel_free_hours} giờ; cọc được giữ nguyên khi đổi")
    _validate_start(r, new_start)
    end = block_end(r, new_start)
    for table_id in candidate_table_ids(db, r, new_start, res.party_size, exclude_id=res.id):
        try:
            with _lock():
                db.execute(select(DiningTable.id).where(DiningTable.id == table_id).with_for_update())
                if table_id in _busy_table_ids(db, new_start, end, exclude_id=res.id):
                    db.rollback()
                    continue
                res.table_id, res.start_at, res.end_at = table_id, new_start, end
                db.commit()
                return res
        except IntegrityError:
            db.rollback()
            continue
    raise HTTPException(409, "Không còn bàn ở giờ mới")


def move_table(db: Session, r: Restaurant, res: Reservation, table_id: int) -> Reservation:
    """Nhân viên xếp/đổi bàn thủ công."""
    if res.status not in ACTIVE_RES:
        raise HTTPException(409, "Đặt bàn không còn hiệu lực")
    t = db.get(DiningTable, table_id)
    if not t or not t.active or t.capacity < res.party_size:
        raise HTTPException(400, "Bàn không phù hợp")
    try:
        with _lock():
            db.execute(select(DiningTable.id).where(DiningTable.id == table_id).with_for_update())
            if table_id in _busy_table_ids(db, res.start_at, res.end_at, exclude_id=res.id):
                db.rollback()
                raise HTTPException(409, "Bàn đang có đặt bàn khác")
            res.table_id = table_id
            db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Bàn đang có đặt bàn khác")
    return res
