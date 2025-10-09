import os
from fastapi import FastAPI, Request
from sqlalchemy import create_engine, text
import pandas as pd

app = FastAPI()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///onflows.db")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
engine = create_engine(DATABASE_URL, future=True, pool_pre_ping=True)

@app.get("/health")
def health():
    return {"ok": True}

@app.get("/strava/webhook")
def verify(hub_mode: str=None, hub_challenge: str=None, hub_verify_token: str=None, **kw):
    # Strava expects: return {"hub.challenge": hub_challenge}
    return {"hub.challenge": hub_challenge}

@app.post("/strava/webhook")
async def notify(req: Request):
    payload = await req.json()
    owner_id = payload.get("owner_id")
    object_id = payload.get("object_id")
    with engine.begin() as conn:
        conn.exec_driver_sql("""
            create table if not exists strava_events (
                id bigserial primary key,
                athlete_strava_id bigint,
                activity_id bigint,
                received_at timestamptz default now()
            );
        """)
        conn.execute(text("insert into strava_events (athlete_strava_id, activity_id) values (:sid,:aid)"),
                     dict(sid=owner_id, aid=object_id))
    return {"queued": True}
