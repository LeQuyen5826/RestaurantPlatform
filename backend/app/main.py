import asyncio
from contextlib import asynccontextmanager

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from .config import settings
from .db import IS_SQLITE, Base, SessionLocal, engine
from .models import Restaurant, TableSession, User
from .realtime import hub
from .routers import auth, ordering, payments, reservations, restaurant, insights
from .security import decode_token
from .services.payment import expire_holds

PG_NO_OVERLAP = """
DO $$ BEGIN
  CREATE EXTENSION IF NOT EXISTS btree_gist;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'no_overlapping_reservations') THEN
    ALTER TABLE reservations ADD CONSTRAINT no_overlapping_reservations EXCLUDE USING gist (
      table_id WITH =, tsrange(start_at, end_at) WITH &&
    ) WHERE (status IN ('pending_deposit', 'confirmed', 'checked_in'));
  END IF;
END $$;
"""
ONE_OPEN_SESSION = "CREATE UNIQUE INDEX IF NOT EXISTS one_open_session_per_table ON table_sessions(table_id) WHERE status = 'open'"


def init_db() -> None:
    """Dev: create_all. Production nên dùng Alembic migration cho cùng các câu lệnh dưới đây."""
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(text(ONE_OPEN_SESSION))
        if not IS_SQLITE:
            conn.execute(text(PG_NO_OVERLAP))
    with SessionLocal() as db:
        if not db.get(Restaurant, 1):
            db.add(Restaurant(id=1, name="Nhà hàng demo"))
            db.commit()


def _expire_job() -> None:
    with SessionLocal() as db:
        expire_holds(db)


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    hub.loop = asyncio.get_running_loop()
    sched = BackgroundScheduler(timezone="Asia/Ho_Chi_Minh")
    sched.add_job(_expire_job, "interval", seconds=60, id="expire_holds")
    sched.start()
    yield
    sched.shutdown(wait=False)


app = FastAPI(title="Đặt bàn & gợi ý món", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins.split(","), allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])
for r in (auth.router, restaurant.router, reservations.router, payments.router, ordering.router, insights.router):
    app.include_router(r)


@app.get("/api/health")
def health():
    return {"ok": True}


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket, token: str):
    """Token người dùng (bếp/phục vụ/quản lý/khách) hoặc token phiên bàn -> vào đúng phòng."""
    data = decode_token(token)
    rooms = ["menu"]
    if data and data.get("k") == "sess":
        rooms.append(f"session:{data['sid']}")
    elif data and data.get("k") == "user":
        role = data.get("role")
        if role == "kitchen":
            rooms.append("kitchen")
        elif role in ("waiter", "manager"):
            rooms += ["staff", "kitchen"]
        rooms.append(f"user:{data['sub']}")
    else:
        await ws.close(code=4401)
        return
    await hub.connect(ws, rooms)
    try:
        while True:
            await ws.receive_text()  # giữ kết nối; client không cần gửi gì
    except WebSocketDisconnect:
        pass
    finally:
        hub.disconnect(ws)
