import secrets

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field, model_validator
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Interaction, OrderItem, Recommendation, Reservation, User, UserProfile
from ..schemas import reservation_out, user_out
from ..security import (current_user, encrypt_text, get_allergies, hash_password, hit, require_roles,
                        user_token, verify_password)
from ..timeutil import now_local

router = APIRouter(prefix="/api", tags=["auth"])


class RegisterIn(BaseModel):
    email: EmailStr | None = None
    phone: str | None = Field(None, pattern=r"^\+?\d{9,15}$")
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field("", max_length=120)

    @model_validator(mode="after")
    def need_contact(self):
        if not self.email and not self.phone:
            raise ValueError("Cần email hoặc số điện thoại")
        return self


class LoginIn(BaseModel):
    identifier: str
    password: str


@router.post("/auth/register")
def register(body: RegisterIn, db: Session = Depends(get_db)):
    if body.email and db.scalar(select(User.id).where(User.email == body.email.lower())):
        raise HTTPException(409, "Email đã được dùng")
    if body.phone and db.scalar(select(User.id).where(User.phone == body.phone)):
        raise HTTPException(409, "Số điện thoại đã được dùng")
    u = User(email=body.email.lower() if body.email else None, phone=body.phone,
             password_hash=hash_password(body.password), full_name=body.full_name, role="customer")
    db.add(u)
    db.commit()
    return {"access_token": user_token(u), "user": user_out(u)}


@router.post("/auth/login")
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)):
    hit(f"login:{request.client.host if request.client else '?'}", 10, 60)
    ident = body.identifier.strip().lower()
    u = db.scalar(select(User).where((User.email == ident) | (User.phone == ident)))
    if not u or not u.is_active or not verify_password(body.password, u.password_hash):
        raise HTTPException(401, "Sai thông tin đăng nhập")
    return {"access_token": user_token(u), "user": user_out(u)}


@router.get("/me")
def me(user: User = Depends(current_user)):
    return user_out(user)


# ---------- onboarding khẩu vị + đồng ý ----------
class ProfileIn(BaseModel):
    spicy_level: int = Field(1, ge=0, le=3)
    diet: str = Field("none", pattern="^(none|vegetarian|vegan)$")
    allergies: list[str] = []
    cuisines: list[str] = []
    budget_max: int = Field(0, ge=0)


@router.get("/me/profile")
def get_profile(user: User = Depends(current_user)):
    p = user.profile
    if not p:
        return None
    return {"spicy_level": p.spicy_level, "diet": p.diet, "allergies": get_allergies(user),
            "cuisines": p.cuisines, "budget_max": p.budget_max, "consent_personalization": p.consent_personalization}


@router.put("/me/profile")
def put_profile(body: ProfileIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    p = user.profile or UserProfile(user_id=user.id)
    p.spicy_level, p.diet, p.cuisines, p.budget_max = body.spicy_level, body.diet, body.cuisines, body.budget_max
    p.allergies_enc = encrypt_text(",".join(sorted({a.strip().lower() for a in body.allergies if a.strip()})))
    db.add(p)
    db.commit()
    return {"ok": True}


class ConsentIn(BaseModel):
    personalization: bool


@router.put("/me/consent")
def put_consent(body: ConsentIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    p = user.profile or UserProfile(user_id=user.id)
    p.consent_personalization = body.personalization
    p.consent_at = now_local()
    db.add(p)
    if not body.personalization:  # rút đồng ý: dừng dùng và xóa dữ liệu hành vi để không vào lần tính sau
        db.execute(delete(Interaction).where(Interaction.user_id == user.id))
        db.execute(update(Recommendation).where(Recommendation.user_id == user.id).values(user_id=None))
    db.commit()
    return {"ok": True}


@router.get("/me/export")
def export_data(user: User = Depends(current_user), db: Session = Depends(get_db)):
    res = db.scalars(select(Reservation).where(Reservation.user_id == user.id)).all()
    inter = db.scalars(select(Interaction).where(Interaction.user_id == user.id)).all()
    return {"user": user_out(user), "profile": get_profile(user), "reservations": [reservation_out(r) for r in res],
            "interactions": [{"menu_item_id": i.menu_item_id, "type": i.type, "at": i.created_at.isoformat()}
                             for i in inter]}


@router.delete("/me")
def delete_me(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Xóa dữ liệu cá nhân; giữ bản ghi đặt bàn/thanh toán đã ẩn danh để đối soát tiền."""
    if user.role != "customer":
        raise HTTPException(403, "Tài khoản nhân sự do quản lý xử lý")
    db.execute(delete(Interaction).where(Interaction.user_id == user.id))
    db.execute(update(Recommendation).where(Recommendation.user_id == user.id).values(user_id=None))
    db.execute(update(OrderItem).where(OrderItem.user_id == user.id).values(user_id=None))
    db.execute(update(Reservation).where(Reservation.user_id == user.id).values(user_id=None))
    if user.profile:
        db.delete(user.profile)
    user.email = user.phone = None
    user.full_name = "Đã xóa"
    user.password_hash = hash_password(secrets.token_urlsafe(24))
    user.is_active = False
    db.commit()
    return {"ok": True}


# ---------- quản lý nhân sự (chỉ quản lý) ----------
class StaffIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str = ""
    role: str = Field(pattern="^(waiter|kitchen)$")


class StaffPatch(BaseModel):
    is_active: bool | None = None
    role: str | None = Field(None, pattern="^(waiter|kitchen)$")


@router.get("/staff")
def list_staff(_: User = Depends(require_roles("manager")), db: Session = Depends(get_db)):
    rows = db.scalars(select(User).where(User.role.in_(("waiter", "kitchen"))).order_by(User.id)).all()
    return [{**user_out(u), "is_active": u.is_active} for u in rows]


@router.post("/staff")
def create_staff(body: StaffIn, _: User = Depends(require_roles("manager")), db: Session = Depends(get_db)):
    if db.scalar(select(User.id).where(User.email == body.email.lower())):
        raise HTTPException(409, "Email đã được dùng")
    u = User(email=body.email.lower(), password_hash=hash_password(body.password),
             full_name=body.full_name, role=body.role)
    db.add(u)
    db.commit()
    return user_out(u)


@router.patch("/staff/{uid}")
def patch_staff(uid: int, body: StaffPatch, _: User = Depends(require_roles("manager")), db: Session = Depends(get_db)):
    u = db.get(User, uid)
    if not u or u.role not in ("waiter", "kitchen"):
        raise HTTPException(404, "Không tìm thấy nhân viên")
    if body.is_active is not None:
        u.is_active = body.is_active
    if body.role:
        u.role = body.role
    db.commit()
    return {**user_out(u), "is_active": u.is_active}
