from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import Category, DiningTable, MenuItem, Restaurant, User
from ..realtime import hub
from ..schemas import MenuItemIn, item_out
from ..security import require_roles, table_qr_token

router = APIRouter(prefix="/api", tags=["restaurant"])
manager = require_roles("manager")


def get_restaurant(db: Session) -> Restaurant:
    r = db.get(Restaurant, 1)
    if not r:
        raise HTTPException(500, "Chưa cấu hình nhà hàng (chạy python -m app.seed)")
    return r


class RestaurantIn(BaseModel):
    name: str
    open_time: str = Field(pattern=r"^\d{2}:\d{2}$")
    close_time: str = Field(pattern=r"^\d{2}:\d{2}$")
    slot_minutes: int = Field(ge=30, le=240)
    slot_step_minutes: int = Field(ge=15, le=120)
    buffer_minutes: int = Field(ge=0, le=60)
    deposit_per_guest: int = Field(ge=0)
    cancel_free_hours: int = Field(ge=0, le=72)


def _r_out(r: Restaurant) -> dict:
    return {c: getattr(r, c) for c in RestaurantIn.model_fields} | {"id": r.id}


@router.get("/restaurant")
def read_restaurant(db: Session = Depends(get_db)):
    return _r_out(get_restaurant(db))


@router.put("/restaurant")
def update_restaurant(body: RestaurantIn, _: User = Depends(manager), db: Session = Depends(get_db)):
    r = get_restaurant(db)
    for k, v in body.model_dump().items():
        setattr(r, k, v)
    db.commit()
    return _r_out(r)


# ---------- bàn ----------
class TableIn(BaseModel):
    name: str
    area: str = "Tầng 1"
    capacity: int = Field(ge=1)
    min_guests: int = Field(1, ge=1)
    active: bool = True


def _t_out(t: DiningTable) -> dict:
    return {"id": t.id, "name": t.name, "area": t.area, "capacity": t.capacity,
            "min_guests": t.min_guests, "active": t.active}


@router.get("/tables")
def list_tables(_: User = Depends(require_roles("manager", "waiter")), db: Session = Depends(get_db)):
    return [_t_out(t) for t in db.scalars(select(DiningTable).order_by(DiningTable.id))]


@router.post("/tables")
def create_table(body: TableIn, _: User = Depends(manager), db: Session = Depends(get_db)):
    t = DiningTable(**body.model_dump())
    db.add(t)
    db.commit()
    return _t_out(t)


@router.put("/tables/{tid}")
def update_table(tid: int, body: TableIn, _: User = Depends(manager), db: Session = Depends(get_db)):
    t = db.get(DiningTable, tid)
    if not t:
        raise HTTPException(404, "Không tìm thấy bàn")
    for k, v in body.model_dump().items():
        setattr(t, k, v)
    db.commit()
    return _t_out(t)


@router.get("/tables/{tid}/qr")
def table_qr(tid: int, _: User = Depends(manager), db: Session = Depends(get_db)):
    """Trả token đã ký + URL để in thành mã QR cố định cho bàn."""
    t = db.get(DiningTable, tid)
    if not t:
        raise HTTPException(404, "Không tìm thấy bàn")
    token = table_qr_token(t.id)
    base = settings.public_url.rstrip("/")
    return {"table": t.name, "token": token, "url": f"{base}/t/{token}"}


# ---------- thực đơn ----------
@router.get("/menu")
def menu(db: Session = Depends(get_db)):
    cats = db.scalars(select(Category).order_by(Category.sort, Category.id)).all()
    items = db.scalars(select(MenuItem).where(MenuItem.deleted.is_(False)).order_by(MenuItem.id)).all()
    out = [{"id": c.id, "name": c.name, "items": [item_out(i) for i in items if i.category_id == c.id]} for c in cats]
    loose = [item_out(i) for i in items if i.category_id is None]
    if loose:
        out.append({"id": None, "name": "Khác", "items": loose})
    return out


class CategoryIn(BaseModel):
    name: str
    sort: int = 0


@router.post("/menu/categories")
def create_category(body: CategoryIn, _: User = Depends(manager), db: Session = Depends(get_db)):
    c = Category(**body.model_dump())
    db.add(c)
    db.commit()
    return {"id": c.id, "name": c.name}


def _norm(body: MenuItemIn) -> dict:
    d = body.model_dump()
    d["tags"] = sorted({t.strip().lower() for t in d["tags"] if t.strip()})
    d["allergens"] = sorted({a.strip().lower() for a in d["allergens"] if a.strip()})
    return d


@router.post("/menu/items")
def create_item(body: MenuItemIn, _: User = Depends(manager), db: Session = Depends(get_db)):
    i = MenuItem(**_norm(body))
    db.add(i)
    db.commit()
    return item_out(i)


@router.put("/menu/items/{iid}")
def update_item(iid: int, body: MenuItemIn, _: User = Depends(manager), db: Session = Depends(get_db)):
    i = db.get(MenuItem, iid)
    if not i or i.deleted:
        raise HTTPException(404, "Không tìm thấy món")
    for k, v in _norm(body).items():
        setattr(i, k, v)
    db.commit()
    hub.publish("menu", {"type": "menu_changed", "item_id": i.id, "available": i.available})
    return item_out(i)


@router.delete("/menu/items/{iid}")
def delete_item(iid: int, _: User = Depends(manager), db: Session = Depends(get_db)):
    i = db.get(MenuItem, iid)
    if not i:
        raise HTTPException(404, "Không tìm thấy món")
    i.deleted = True  # xóa mềm để giữ lịch sử gọi món
    db.commit()
    hub.publish("menu", {"type": "menu_changed", "item_id": i.id, "available": False})
    return {"ok": True}


class AvailabilityIn(BaseModel):
    available: bool


@router.patch("/menu/items/{iid}/availability")
def set_availability(iid: int, body: AvailabilityIn, _: User = Depends(require_roles("kitchen", "manager")),
                     db: Session = Depends(get_db)):
    i = db.get(MenuItem, iid)
    if not i or i.deleted:
        raise HTTPException(404, "Không tìm thấy món")
    i.available = body.available
    db.commit()
    hub.publish("menu", {"type": "menu_changed", "item_id": i.id, "available": i.available})
    return item_out(i)
