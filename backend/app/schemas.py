from pydantic import BaseModel, Field

from .models import MenuItem, Reservation, User
from .services.payment import qr_image_url


def item_out(i: MenuItem) -> dict:
    return {"id": i.id, "category_id": i.category_id, "name": i.name, "description": i.description,
            "price": i.price, "image_url": i.image_url, "tags": i.tags or [], "allergens": i.allergens or [],
            "spicy_level": i.spicy_level, "cuisine": i.cuisine, "available": i.available}


def user_out(u: User) -> dict:
    p = u.profile
    return {"id": u.id, "email": u.email, "phone": u.phone, "full_name": u.full_name, "role": u.role,
            "has_profile": bool(p), "consent_personalization": bool(p and p.consent_personalization)}


def reservation_out(r: Reservation, staff_view: bool = False) -> dict:
    out = {"id": r.id, "table_id": r.table_id, "table": r.table.name if r.table else None,
           "party_size": r.party_size, "start_at": r.start_at.isoformat(), "end_at": r.end_at.isoformat(),
           "status": r.status, "hold_until": r.hold_until.isoformat() if r.hold_until else None,
           "deposit_amount": r.deposit_amount, "payment": None}
    p = r.payment
    if p:
        out["payment"] = {"code": p.code, "amount": p.amount, "status": p.status, "refund_status": p.refund_status,
                          "qr_url": qr_image_url(p.code, p.amount) if p.status == "pending" else None}
    if staff_view:
        out["customer"] = r.user_id
    return out


class MenuItemIn(BaseModel):
    category_id: int | None = None
    name: str = Field(min_length=1, max_length=120)
    description: str = ""
    price: int = Field(ge=0)
    image_url: str = ""
    tags: list[str] = []
    allergens: list[str] = []
    spicy_level: int = Field(0, ge=0, le=3)
    cuisine: str = "viet"
    available: bool = True
