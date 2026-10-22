"""python -m app.seed  – dữ liệu demo: thực đơn Việt, bàn, tài khoản nhân sự, ít tương tác mẫu."""
import random
from datetime import timedelta

from sqlalchemy import select

from .db import SessionLocal
from .main import init_db
from .models import Category, DiningTable, Interaction, MenuItem, User
from .security import hash_password
from .timeutil import now_local

MENU = {
    "Món nước": [
        ("Phở bò tái", 65000, ["nuoc", "bo"], [], 0, "viet"),
        ("Bún chả Hà Nội", 60000, ["nuong", "heo"], [], 1, "viet"),
        ("Bún riêu cua", 55000, ["nuoc", "hai-san"], ["shellfish"], 1, "viet"),
        ("Bún bò Huế", 65000, ["nuoc", "bo"], [], 3, "viet"),
    ],
    "Món chính": [
        ("Cơm tấm sườn bì chả", 70000, ["com", "heo"], ["egg"], 0, "viet"),
        ("Gà nướng sả ớt", 120000, ["nuong", "ga"], [], 3, "viet"),
        ("Cá kho tộ", 110000, ["kho", "ca"], ["fish"], 1, "viet"),
        ("Đậu phụ sốt cà chua", 55000, ["vegetarian", "dau-hu"], ["soy"], 0, "viet"),
        ("Rau muống xào tỏi", 45000, ["vegan", "rau"], [], 0, "viet"),
        ("Tôm rang me", 150000, ["hai-san"], ["shellfish"], 1, "viet"),
    ],
    "Khai vị & tráng miệng": [
        ("Gỏi cuốn tôm thịt", 50000, ["goi-cuon", "hai-san"], ["shellfish", "peanut"], 0, "viet"),
        ("Nem rán", 55000, ["chien", "heo"], ["egg"], 0, "viet"),
        ("Chè khúc bạch", 35000, ["trang-mieng", "vegetarian"], ["milk", "treenut"], 0, "viet"),
        ("Cà phê trứng", 40000, ["do-uong"], ["egg", "milk"], 0, "viet"),
    ],
}


def run() -> None:
    init_db()
    with SessionLocal() as db:
        if db.scalar(select(MenuItem.id).limit(1)):
            print("Đã có dữ liệu, bỏ qua seed.")
            return
        for n, cap in enumerate([2, 2, 4, 4, 4, 6, 6, 8], start=1):
            db.add(DiningTable(name=f"Bàn {n}", capacity=cap, area="Tầng 1" if n <= 5 else "Tầng 2"))
        items: list[MenuItem] = []
        for sort, (cat_name, rows) in enumerate(MENU.items()):
            cat = Category(name=cat_name, sort=sort)
            db.add(cat)
            db.flush()
            for name, price, tags, allergens, spicy, cuisine in rows:
                mi = MenuItem(category_id=cat.id, name=name, price=price, tags=tags, allergens=allergens,
                              spicy_level=spicy, cuisine=cuisine, description=name)
                db.add(mi)
                items.append(mi)
        for email, role in (("manager@demo.vn", "manager"), ("waiter@demo.vn", "waiter"), ("kitchen@demo.vn", "kitchen")):
            db.add(User(email=email, password_hash=hash_password("demo1234"), full_name=role.title(), role=role))
        db.flush()
        rnd, now = random.Random(7), now_local()
        for _ in range(300):  # tương tác MẪU không gắn người dùng (chỉ để demo mức 0 phổ biến theo giờ)
            it = rnd.choice(items)
            when = now - timedelta(days=rnd.randint(0, 60))
            when = when.replace(hour=rnd.choice([11, 12, 13, 18, 19, 20]))
            db.add(Interaction(user_id=None, menu_item_id=it.id, type=rnd.choice(["order", "order", "add_to_cart", "view"]),
                               created_at=when))
        db.commit()
        print("Seed xong. Tài khoản: manager@demo.vn / waiter@demo.vn / kitchen@demo.vn, mật khẩu demo1234")


if __name__ == "__main__":
    run()
