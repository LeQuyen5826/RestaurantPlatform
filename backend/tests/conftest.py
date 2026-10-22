import os

os.environ["DATABASE_URL"] = "sqlite:///./test.db"
if os.path.exists("test.db"):
    os.remove("test.db")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.seed import run as seed  # noqa: E402


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:  # chạy lifespan -> init_db
        seed()
        yield c


def login(client, email: str, password: str = "demo1234") -> dict:
    r = client.post("/api/auth/login", json={"identifier": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def register(client, email: str) -> dict:
    r = client.post("/api/auth/register", json={"email": email, "password": "matkhau123", "full_name": "Khách"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}
