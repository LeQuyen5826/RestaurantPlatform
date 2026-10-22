"""Gợi ý món mức 0 (phổ biến theo khung giờ) và mức 1 (content-based), có reason_code.
Dị ứng/ăn kiêng luôn là bộ lọc CỨNG, không bao giờ trả về danh sách rỗng."""
import math
from collections import defaultdict
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Interaction, MenuItem, Recommendation, User
from ..security import get_allergies
from ..timeutil import now_local

WEIGHT = {"view": 0.2, "add_to_cart": 1.0, "order": 3.0, "reorder": 4.0}
HALF_LIFE_DAYS = 14.0

REASON_TEXT = {
    "POPULAR_AT_THIS_TIME": "Được gọi nhiều vào khung giờ này",
    "FEATURED": "Món nổi bật của nhà hàng",
    "MATCH_FAVORITE_CUISINE": "Hợp với ẩm thực bạn yêu thích",
    "MATCH_SPICY_LEVEL": "Đúng mức cay bạn chọn",
    "WITHIN_BUDGET": "Phù hợp ngân sách của bạn",
    "SIMILAR_TO_ORDERED": "Giống món bạn từng gọi",
}


def meal_period(hour: int) -> str:
    return "morning" if hour < 10 else "lunch" if hour < 15 else "afternoon" if hour < 18 else "dinner"


def _decay(age_days: float) -> float:
    return 0.5 ** (age_days / HALF_LIFE_DAYS)


def is_safe(item: MenuItem, allergens: set[str], diet: str) -> bool:
    if allergens & {a.lower() for a in (item.allergens or [])}:
        return False
    tags = {t.lower() for t in (item.tags or [])}
    if diet == "vegan" and "vegan" not in tags:
        return False
    if diet == "vegetarian" and not (tags & {"vegetarian", "vegan"}):
        return False
    return True


def _item_features(item: MenuItem) -> set[str]:
    price_bucket = "low" if item.price < 50000 else "mid" if item.price < 100000 else "high"
    feats = {f"tag:{t}" for t in (item.tags or [])}
    feats |= {f"cuisine:{item.cuisine}", f"spicy:{item.spicy_level}", f"price:{price_bucket}"}
    return feats


def _popularity(db: Session, items: list[MenuItem]) -> dict[int, float]:
    now = now_local()
    period = meal_period(now.hour)
    score: dict[int, float] = defaultdict(float)
    rows = db.scalars(select(Interaction).where(Interaction.created_at >= now - timedelta(days=90))).all()
    for r in rows:
        if meal_period(r.created_at.hour) == period:
            score[r.menu_item_id] += WEIGHT.get(r.type, 0) * _decay((now - r.created_at).total_seconds() / 86400)
    return score


def level0(db: Session, items: list[MenuItem], limit: int) -> list[dict]:
    pop = _popularity(db, items)
    ranked = sorted(items, key=lambda i: (-pop.get(i.id, 0.0), i.id))  # món chưa có dữ liệu vẫn xếp sau -> không rỗng
    return [{"item": i, "score": pop.get(i.id, 0.0), "level": 0,
             "reason_code": "POPULAR_AT_THIS_TIME" if pop.get(i.id, 0) > 0 else "FEATURED"} for i in ranked[:limit]]


def level1(db: Session, user: User, items: list[MenuItem], limit: int) -> list[dict] | None:
    prof = user.profile
    onboard: dict[str, float] = defaultdict(float)
    if prof:
        for c in prof.cuisines or []:
            onboard[f"cuisine:{c}"] += 1.0
        onboard[f"spicy:{prof.spicy_level}"] += 1.0
        if prof.budget_max:
            onboard["price:low"] += 0.5
            if prof.budget_max >= 50000:
                onboard["price:mid"] += 0.5
            if prof.budget_max >= 100000:
                onboard["price:high"] += 0.5

    history: dict[str, float] = defaultdict(float)
    hist_source: dict[str, str] = {}
    by_id = {i.id: i for i in items}
    now = now_local()
    rows = db.scalars(select(Interaction).where(Interaction.user_id == user.id)
                      .order_by(Interaction.created_at.desc()).limit(500)).all()
    for r in rows:
        it = by_id.get(r.menu_item_id) or db.get(MenuItem, r.menu_item_id)
        if not it:
            continue
        w = WEIGHT.get(r.type, 0) * _decay((now - r.created_at).total_seconds() / 86400)
        for f in _item_features(it):
            history[f] += w
            if f.startswith("tag:") or f.startswith("cuisine:"):
                hist_source.setdefault(f, it.name)

    if not onboard and not history:
        return None  # chưa có hồ sơ -> dùng mức 0
    hmax = max(history.values(), default=1.0) or 1.0
    uvec = {f: onboard.get(f, 0.0) + history.get(f, 0.0) / hmax for f in set(onboard) | set(history)}
    unorm = math.sqrt(sum(v * v for v in uvec.values())) or 1.0
    pop = _popularity(db, items)
    pmax = max(pop.values(), default=0.0) or 1.0

    out = []
    for it in items:
        feats = _item_features(it)
        dot = sum(uvec.get(f, 0.0) for f in feats)
        cos = dot / (unorm * math.sqrt(len(feats)))
        score = cos + 0.1 * pop.get(it.id, 0.0) / pmax
        # reason_code: đặc trưng đóng góp nhiều nhất
        best = max(feats, key=lambda f: (onboard.get(f, 0.0) + history.get(f, 0.0) / hmax))
        from_hist = history.get(best, 0.0) / hmax > onboard.get(best, 0.0)
        if from_hist and best in hist_source and hist_source[best] != it.name:
            code, param = "SIMILAR_TO_ORDERED", hist_source[best]
        elif best.startswith("cuisine:"):
            code, param = "MATCH_FAVORITE_CUISINE", None
        elif best.startswith("spicy:"):
            code, param = "MATCH_SPICY_LEVEL", None
        elif best.startswith("price:"):
            code, param = "WITHIN_BUDGET", None
        else:
            code, param = ("POPULAR_AT_THIS_TIME" if pop.get(it.id, 0) > 0 else "FEATURED"), None
        out.append({"item": it, "score": score, "level": 1, "reason_code": code, "param": param})
    out.sort(key=lambda x: (-x["score"], x["item"].id))
    return out[:limit]


def recommend(db: Session, user: User | None, limit: int = 5) -> list[dict]:
    items_all = db.scalars(select(MenuItem).where(MenuItem.available.is_(True), MenuItem.deleted.is_(False))).all()
    allergens = {a.lower() for a in get_allergies(user)}
    diet = user.profile.diet if user and user.profile else "none"
    items = [i for i in items_all if is_safe(i, allergens, diet)]  # lọc CỨNG dị ứng / ăn kiêng
    if not items:
        return []
    consent = bool(user and user.profile and user.profile.consent_personalization)
    results = level1(db, user, items, limit) if consent else None
    if not results:
        results = level0(db, items, limit)
    for r in results:
        text = REASON_TEXT[r["reason_code"]]
        r["reason_text"] = f'{text}: {r["param"]}' if r.get("param") else text
        rec = Recommendation(user_id=user.id if consent else None, menu_item_id=r["item"].id,
                             level=r["level"], reason_code=r["reason_code"])
        db.add(rec)
        db.flush()
        r["rec_id"] = rec.id
    db.commit()
    return results


def log_interaction(db: Session, user_id: int | None, menu_item_id: int, type_: str) -> None:
    """Chỉ ghi hành vi khi người dùng đã đồng ý cá nhân hóa (FR-05/FR-06)."""
    if not user_id:
        return
    user = db.get(User, user_id)
    if not (user and user.is_active and user.profile and user.profile.consent_personalization):
        return
    if type_ == "order" and db.scalar(select(Interaction.id).where(
            Interaction.user_id == user_id, Interaction.menu_item_id == menu_item_id,
            Interaction.type.in_(("order", "reorder"))).limit(1)):
        type_ = "reorder"
    db.add(Interaction(user_id=user_id, menu_item_id=menu_item_id, type=type_))
