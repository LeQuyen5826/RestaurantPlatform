"""Một nhà hàng tại Hà Nội: mọi thời gian lưu dạng naive theo giờ địa phương (UTC+7)."""
from datetime import datetime
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Ho_Chi_Minh")


def now_local() -> datetime:
    return datetime.now(TZ).replace(tzinfo=None)
