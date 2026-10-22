import base64
import hashlib
import hmac
import os
import time
from collections import defaultdict, deque

import jwt
from cryptography.fernet import Fernet
from fastapi import Depends, Header, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .models import TableSession, User

ALG = "HS256"
bearer = HTTPBearer(auto_error=False)


# ---------- mật khẩu ----------
def hash_password(pw: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.scrypt(pw.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return f"scrypt${salt.hex()}${dk.hex()}"


def verify_password(pw: str, stored: str) -> bool:
    try:
        _, salt, dk = stored.split("$")
        calc = hashlib.scrypt(pw.encode(), salt=bytes.fromhex(salt), n=2**14, r=8, p=1, dklen=32)
        return hmac.compare_digest(calc.hex(), dk)
    except Exception:
        return False


# ---------- JWT ----------
def make_token(claims: dict, ttl_seconds: int, secret: str | None = None) -> str:
    payload = {**claims, "exp": int(time.time()) + ttl_seconds}
    return jwt.encode(payload, secret or settings.jwt_secret, algorithm=ALG)


def decode_token(token: str, secret: str | None = None) -> dict | None:
    try:
        return jwt.decode(token, secret or settings.jwt_secret, algorithms=[ALG])
    except jwt.PyJWTError:
        return None


def user_token(user: User) -> str:
    return make_token({"k": "user", "sub": str(user.id), "role": user.role}, settings.jwt_expire_minutes * 60)


def table_qr_token(table_id: int) -> str:
    """Token ký cố định in trên QR của bàn (không hết hạn; chỉ định danh bàn, không cấp quyền gọi món)."""
    return jwt.encode({"k": "qr", "t": table_id}, settings.qr_secret, algorithm=ALG)


def read_table_qr(token: str) -> int | None:
    try:
        data = jwt.decode(token, settings.qr_secret, algorithms=[ALG])
        return int(data["t"]) if data.get("k") == "qr" else None
    except (jwt.PyJWTError, KeyError, ValueError):
        return None


# ---------- mã hóa dữ liệu nhạy cảm (dị ứng) ----------
def _fernet() -> Fernet:
    key = settings.data_key.encode() if settings.data_key else base64.urlsafe_b64encode(
        hashlib.sha256(settings.jwt_secret.encode()).digest()
    )
    return Fernet(key)


def encrypt_text(s: str) -> str:
    return _fernet().encrypt(s.encode()).decode() if s else ""


def decrypt_text(s: str) -> str:
    try:
        return _fernet().decrypt(s.encode()).decode() if s else ""
    except Exception:
        return ""


def get_allergies(user: User | None) -> list[str]:
    if not user or not user.profile:
        return []
    raw = decrypt_text(user.profile.allergies_enc)
    return [a for a in raw.split(",") if a]


# ---------- dependencies ----------
def current_user_optional(
    cred: HTTPAuthorizationCredentials | None = Depends(bearer), db: Session = Depends(get_db)
) -> User | None:
    if not cred:
        return None
    data = decode_token(cred.credentials)
    if not data or data.get("k") != "user":
        return None
    user = db.get(User, int(data["sub"]))
    return user if user and user.is_active else None


def current_user(user: User | None = Depends(current_user_optional)) -> User:
    if not user:
        raise HTTPException(401, "Cần đăng nhập")
    return user


def require_roles(*roles: str):
    def dep(user: User = Depends(current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(403, "Không đủ quyền")
        return user

    return dep


def current_table_session(
    x_session_token: str | None = Header(default=None), db: Session = Depends(get_db)
) -> tuple[TableSession, int | None]:
    """Token phiên bàn (khách quét QR) gửi qua header X-Session-Token. Trả (phiên, user_id hoặc None)."""
    data = decode_token(x_session_token) if x_session_token else None
    if not data or data.get("k") != "sess":
        raise HTTPException(401, "Cần quét QR của bàn")
    sess = db.get(TableSession, int(data["sid"]))
    if not sess or sess.status != "open":
        raise HTTPException(410, "Phiên bàn đã đóng")
    return sess, data.get("uid")


# ---------- rate limit đơn giản trong bộ nhớ (đủ cho 1 tiến trình; dùng Redis nếu scale) ----------
_hits: dict[str, deque] = defaultdict(deque)


def hit(key: str, limit: int, window_s: int) -> None:
    now = time.monotonic()
    q = _hits[key]
    while q and now - q[0] > window_s:
        q.popleft()
    if len(q) >= limit:
        raise HTTPException(429, "Thao tác quá nhanh, thử lại sau")
    q.append(now)
