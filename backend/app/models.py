from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base
from .timeutil import now_local

ROLES = ("customer", "manager", "waiter", "kitchen")
ACTIVE_RES = ("pending_deposit", "confirmed", "checked_in")


class Restaurant(Base):
    __tablename__ = "restaurants"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    open_time: Mapped[str] = mapped_column(String(5), default="10:00")
    close_time: Mapped[str] = mapped_column(String(5), default="22:00")
    slot_minutes: Mapped[int] = mapped_column(Integer, default=90)       # độ dài một lượt ngồi
    slot_step_minutes: Mapped[int] = mapped_column(Integer, default=30)  # bước giữa các giờ bắt đầu
    buffer_minutes: Mapped[int] = mapped_column(Integer, default=15)     # đệm dọn bàn
    deposit_per_guest: Mapped[int] = mapped_column(Integer, default=50000)
    cancel_free_hours: Mapped[int] = mapped_column(Integer, default=2)   # hủy trước hạn này thì được hoàn cọc


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), default=1)
    email: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    phone: Mapped[str | None] = mapped_column(String(20), unique=True, nullable=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(120), default="")
    role: Mapped[str] = mapped_column(String(20), default="customer")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_local)
    profile: Mapped["UserProfile | None"] = relationship(back_populates="user", uselist=False)


class UserProfile(Base):
    """Khẩu vị (onboarding 5 câu) + đồng ý cá nhân hóa. Dị ứng được mã hóa khi lưu."""
    __tablename__ = "user_profiles"
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    spicy_level: Mapped[int] = mapped_column(Integer, default=1)  # 0-3
    diet: Mapped[str] = mapped_column(String(20), default="none")  # none | vegetarian | vegan
    allergies_enc: Mapped[str] = mapped_column(Text, default="")
    cuisines: Mapped[list] = mapped_column(JSON, default=list)
    budget_max: Mapped[int] = mapped_column(Integer, default=0)  # 0 = không giới hạn
    consent_personalization: Mapped[bool] = mapped_column(Boolean, default=False)
    consent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    user: Mapped[User] = relationship(back_populates="profile")


class DiningTable(Base):
    __tablename__ = "dining_tables"
    id: Mapped[int] = mapped_column(primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), default=1)
    name: Mapped[str] = mapped_column(String(40))
    area: Mapped[str] = mapped_column(String(40), default="Tầng 1")
    capacity: Mapped[int] = mapped_column(Integer)
    min_guests: Mapped[int] = mapped_column(Integer, default=1)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Category(Base):
    __tablename__ = "categories"
    id: Mapped[int] = mapped_column(primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), default=1)
    name: Mapped[str] = mapped_column(String(80))
    sort: Mapped[int] = mapped_column(Integer, default=0)


class MenuItem(Base):
    __tablename__ = "menu_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), default=1)
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    price: Mapped[int] = mapped_column(Integer)
    image_url: Mapped[str] = mapped_column(String(500), default="")
    tags: Mapped[list] = mapped_column(JSON, default=list)        # ví dụ ["nuoc","bo","vegetarian"]
    allergens: Mapped[list] = mapped_column(JSON, default=list)   # ví dụ ["peanut","shellfish"]
    spicy_level: Mapped[int] = mapped_column(Integer, default=0)
    cuisine: Mapped[str] = mapped_column(String(40), default="viet")
    available: Mapped[bool] = mapped_column(Boolean, default=True)
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)


class Reservation(Base):
    __tablename__ = "reservations"
    id: Mapped[int] = mapped_column(primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), default=1)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    table_id: Mapped[int] = mapped_column(ForeignKey("dining_tables.id"))
    party_size: Mapped[int] = mapped_column(Integer)
    start_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    end_at: Mapped[datetime] = mapped_column(DateTime)  # đã gồm thời gian đệm dọn bàn
    status: Mapped[str] = mapped_column(String(20), default="pending_deposit", index=True)
    # pending_deposit | confirmed | checked_in | completed | cancelled | expired | no_show
    hold_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    deposit_amount: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_local)
    table: Mapped[DiningTable] = relationship()
    payment: Mapped["Payment | None"] = relationship(back_populates="reservation", uselist=False)


class Payment(Base):
    __tablename__ = "payments"
    id: Mapped[int] = mapped_column(primary_key=True)
    reservation_id: Mapped[int] = mapped_column(ForeignKey("reservations.id"), index=True)
    code: Mapped[str] = mapped_column(String(20), unique=True)  # nội dung chuyển khoản, không đoán được
    amount: Mapped[int] = mapped_column(Integer)
    received_amount: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending | paid | expired | cancelled
    transaction_id: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    refund_status: Mapped[str] = mapped_column(String(20), default="none")
    # none | refund_pending | refunded | forfeited
    refund_note: Mapped[str] = mapped_column(String(255), default="")
    reservation: Mapped[Reservation] = relationship(back_populates="payment")


class WebhookLog(Base):
    __tablename__ = "webhook_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    transaction_id: Mapped[str] = mapped_column(String(64), unique=True)  # chống xử lý trùng
    payload: Mapped[dict] = mapped_column(JSON)
    amount: Mapped[int] = mapped_column(Integer, default=0)
    payment_id: Mapped[int | None] = mapped_column(ForeignKey("payments.id"), nullable=True)
    result: Mapped[str] = mapped_column(String(30), default="processing")
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)
    note: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_local)


class TableSession(Base):
    __tablename__ = "table_sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    table_id: Mapped[int] = mapped_column(ForeignKey("dining_tables.id"))
    reservation_id: Mapped[int | None] = mapped_column(ForeignKey("reservations.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(10), default="open")  # open | closed
    opened_at: Mapped[datetime] = mapped_column(DateTime, default=now_local)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    table: Mapped[DiningTable] = relationship()


class OrderItem(Base):
    __tablename__ = "order_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("table_sessions.id"), index=True)
    menu_item_id: Mapped[int] = mapped_column(ForeignKey("menu_items.id"))
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(120))   # snapshot
    price: Mapped[int] = mapped_column(Integer)      # snapshot
    qty: Mapped[int] = mapped_column(Integer, default=1)
    note: Mapped[str] = mapped_column(String(255), default="")
    status: Mapped[str] = mapped_column(String(12), default="in_cart")
    # in_cart | submitted | preparing | ready | served | cancelled
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_local)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_local, onupdate=now_local)
    menu_item: Mapped[MenuItem] = relationship()


class Interaction(Base):
    __tablename__ = "interactions"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    menu_item_id: Mapped[int] = mapped_column(ForeignKey("menu_items.id"))
    type: Mapped[str] = mapped_column(String(12))  # view | add_to_cart | order | reorder
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_local, index=True)


class Recommendation(Base):
    __tablename__ = "recommendations"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    menu_item_id: Mapped[int] = mapped_column(ForeignKey("menu_items.id"))
    level: Mapped[int] = mapped_column(Integer)
    reason_code: Mapped[str] = mapped_column(String(40))
    shown_at: Mapped[datetime] = mapped_column(DateTime, default=now_local)
    accepted: Mapped[bool] = mapped_column(Boolean, default=False)
