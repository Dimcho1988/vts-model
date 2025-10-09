import os
import streamlit as st

# Вземи DB URL директно от Secrets и го сложи в env,
# за да го видят всички модули (вкл. database.py)
if "DATABASE_URL" in st.secrets:
    os.environ["DATABASE_URL"] = st.secrets["DATABASE_URL"]

from __future__ import annotations
import os
from sqlalchemy import create_engine, text
from sqlalchemy.exc import ProgrammingError, OperationalError

# ------------------------------------------------------------
# Connection
# ------------------------------------------------------------
DATABASE_URL = (
    os.getenv("SUPABASE_DB_URL")
    or os.getenv("DATABASE_URL")
    or "sqlite:///onflows.db"
)

# старият префикс postgres:// → поправяме към postgresql://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL, future=True, pool_pre_ping=True, echo=False)

# ------------------------------------------------------------
# Schema (авто-миграции) – работи за SQLite и Postgres
# ------------------------------------------------------------
SCHEMA_SQL = """
-- onFlows schema (idempotent)
CREATE TABLE IF NOT EXISTS profiles (
    athlete_key TEXT PRIMARY KEY,
    hr_max INTEGER
);

CREATE TABLE IF NOT EXISTS workouts (
    id SERIAL PRIMARY KEY,
    athlete_key TEXT,
    start_time TEXT,
    duration_s REAL,
    distance_m REAL,
    avg_hr REAL,
    avg_speed_mps REAL,
    notes TEXT,
    strava_id BIGINT,
    has_streams BOOLEAN DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_workouts_ath_time ON workouts(athlete_key, start_time);
CREATE UNIQUE INDEX IF NOT EXISTS uq_workouts_strava_id ON workouts(strava_id);

CREATE TABLE IF NOT EXISTS hr_speed_points (
    id SERIAL PRIMARY KEY,
    workout_id INTEGER,
    t_bin_start TEXT,
    mean_hr REAL,
    mean_vflat REAL
);

CREATE INDEX IF NOT EXISTS idx_hrv_workout ON hr_speed_points(workout_id);

CREATE TABLE IF NOT EXISTS tokens (
    athlete_key TEXT PRIMARY KEY,
    strava_athlete_id TEXT,
    access_token TEXT,
    refresh_token TEXT,
    expires_at BIGINT
);
"""


def ensure_schema():
    """
    Създава/актуализира схемата:
      - SQLite: винаги
      - Postgres (Supabase): опитва; ако ролята няма CREATE, вдига информативно съобщение
    """
    backend = engine.url.get_backend_name()

    if backend.startswith("sqlite"):
        with engine.begin() as conn:
            # SERIAL → INTEGER за SQLite
            sqlite_sql = SCHEMA_SQL.replace("SERIAL", "INTEGER")
            conn.exec_driver_sql(sqlite_sql)
        return True

    try:
        with engine.begin() as conn:
            conn.execute(text("set search_path to public"))
            conn.execute(text(SCHEMA_SQL))
        return True
    except (ProgrammingError, OperationalError) as e:
        raise RuntimeError(
            "DB schema create failed (role likely lacks CREATE). "
            "В Supabase ползвай service-role в Secrets, или пусни schema.sql ръчно."
        ) from e


def init_db():
    return ensure_schema()

# ------------------------------------------------------------
# Profiles
# ------------------------------------------------------------
def upsert_profile(athlete_key: str, hr_max: int):
    with engine.begin() as conn:
        backend = engine.url.get_backend_name()
        if backend.startswith("sqlite"):
            conn.exec_driver_sql(
                "INSERT INTO profiles (athlete_key, hr_max) VALUES (?, ?)"
                " ON CONFLICT(athlete_key) DO UPDATE SET hr_max=excluded.hr_max",
                (athlete_key, int(hr_max)),
            )
        else:
            conn.execute(
                text("""
                    INSERT INTO profiles (athlete_key, hr_max)
                    VALUES (:athlete_key, :hr_max)
                    ON CONFLICT (athlete_key) DO UPDATE SET hr_max = excluded.hr_max
                """),
                dict(athlete_key=athlete_key, hr_max=int(hr_max)),
            )

def fetch_profile(athlete_key: str):
    with engine.begin() as conn:
        res = conn.execute(
            text("SELECT athlete_key, hr_max FROM profiles WHERE athlete_key=:k"),
            dict(k=athlete_key),
        ).mappings().first()
    return dict(res) if res else None

# ------------------------------------------------------------
# Tokens (Strava)
# ------------------------------------------------------------
def upsert_token(athlete_key: str, strava_athlete_id: str,
                 access_token: str, refresh_token: str, expires_at: int):
    with engine.begin() as conn:
        backend = engine.url.get_backend_name()
        if backend.startswith("sqlite"):
            conn.exec_driver_sql("""
                CREATE TABLE IF NOT EXISTS tokens (
                    athlete_key TEXT PRIMARY KEY,
                    strava_athlete_id TEXT,
                    access_token TEXT,
                    refresh_token TEXT,
                    expires_at BIGINT
                )
            """)
            conn.exec_driver_sql(
                "INSERT INTO tokens (athlete_key, strava_athlete_id, access_token, refresh_token, expires_at)"
                " VALUES (?, ?, ?, ?, ?)"
                " ON CONFLICT(athlete_key) DO UPDATE SET "
                " strava_athlete_id=excluded.strava_athlete_id,"
                " access_token=excluded.access_token,"
                " refresh_token=excluded.refresh_token,"
                " expires_at=excluded.expires_at",
                (athlete_key, strava_athlete_id, access_token, refresh_token, int(expires_at)),
            )
        else:
            conn.execute(
                text("""
                    INSERT INTO tokens (athlete_key, strava_athlete_id, access_token, refresh_token, expires_at)
                    VALUES (:athlete_key, :sid, :at, :rt, :exp)
                    ON CONFLICT (athlete_key) DO UPDATE SET
                      strava_athlete_id=excluded.strava_athlete_id,
                      access_token=excluded.access_token,
                      refresh_token=excluded.refresh_token,
                      expires_at=excluded.expires_at
                """),
                dict(athlete_key=athlete_key, sid=strava_athlete_id,
                     at=access_token, rt=refresh_token, exp=int(expires_at)),
            )

def get_token(athlete_key: str):
    with engine.begin() as conn:
        res = conn.execute(
            text("""
                SELECT strava_athlete_id, access_token, refresh_token, expires_at
                FROM tokens WHERE athlete_key=:k
            """),
            dict(k=athlete_key),
        ).mappings().first()
    return dict(res) if res else None

# ------------------------------------------------------------
# Workouts
# ------------------------------------------------------------
def insert_workouts(rows: list[dict]):
    if not rows:
        return 0
    with engine.begin() as conn:
        backend = engine.url.get_backend_name()
        for r in rows:
            payload = {
                "athlete_key": r.get("athlete_key"),
                "start_time": r.get("start_time"),
                "duration_s": r.get("duration_s"),
                "distance_m": r.get("distance_m"),
                "avg_hr": r.get("avg_hr"),
                "avg_speed_mps": r.get("avg_speed_mps"),
                "notes": r.get("notes"),
                "strava_id": r.get("strava_id"),
                "has_streams": r.get("has_streams", False),
            }
            if backend.startswith("sqlite"):
                conn.exec_driver_sql(
                    "INSERT OR IGNORE INTO workouts "
                    "(athlete_key,start_time,duration_s,distance_m,avg_hr,avg_speed_mps,notes,strava_id,has_streams) "
                    "VALUES (?,?,?,?,?,?,?,?,?)",
                    tuple(payload.values()),
                )
            else:
                conn.execute(text("""
                    INSERT INTO workouts
                    (athlete_key,start_time,duration_s,distance_m,avg_hr,avg_speed_mps,notes,strava_id,has_streams)
                    VALUES (:athlete_key,:start_time,:duration_s,:distance_m,:avg_hr,:avg_speed_mps,:notes,:strava_id,:has_streams)
                    ON CONFLICT (strava_id) DO NOTHING
                """), payload)
    return len(rows)

def fetch_workouts(athlete_key: str):
    with engine.begin() as conn:
        res = conn.execute(
            text("""
                SELECT id, athlete_key, start_time, duration_s, distance_m, avg_hr, avg_speed_mps, notes, strava_id, has_streams
                FROM workouts
                WHERE athlete_key = :athlete_key
                ORDER BY start_time ASC
            """),
            dict(athlete_key=athlete_key),
        ).mappings().all()
    return [dict(r) for r in res]

def workouts_needing_streams(athlete_key: str, limit: int = 25):
    with engine.begin() as conn:
        res = conn.execute(text("""
            SELECT id, strava_id, start_time
            FROM workouts
            WHERE athlete_key=:k AND has_streams = FALSE AND strava_id IS NOT NULL
            ORDER BY start_time DESC
            LIMIT :lim
        """), dict(k=athlete_key, lim=limit)).mappings().all()
    return [dict(r) for r in res]

def set_has_streams(workout_id: int, value: bool = True):
    with engine.begin() as conn:
        conn.execute(text("UPDATE workouts SET has_streams=:v WHERE id=:id"),
                     dict(v=value, id=workout_id))

# ------------------------------------------------------------
# HR–speed points
# ------------------------------------------------------------
def insert_hr_points(rows: list[dict]):
    if not rows:
        return 0
    with engine.begin() as conn:
        backend = engine.url.get_backend_name()
        for r in rows:
            if backend.startswith("sqlite"):
                conn.exec_driver_sql(
                    "INSERT INTO hr_speed_points (workout_id, t_bin_start, mean_hr, mean_vflat)"
                    " VALUES (?, ?, ?, ?)",
                    (
                        r.get("workout_id"),
                        r.get("t_bin_start"),
                        r.get("mean_hr"),
                        r.get("mean_vflat"),
                    ),
                )
            else:
                conn.execute(
                    text("""
                        INSERT INTO hr_speed_points (workout_id, t_bin_start, mean_hr, mean_vflat)
                        VALUES (:workout_id, :t_bin_start, :mean_hr, :mean_vflat)
                    """),
                    r,
                )
    return len(rows)

def fetch_hr_points(workout_ids: list[int]):
    if not workout_ids:
        return []
    backend = engine.url.get_backend_name()
    with engine.begin() as conn:
        if backend.startswith("sqlite"):
            placeholders = ",".join(["?"] * len(workout_ids))
            sql = f"""
                SELECT workout_id, t_bin_start, mean_hr, mean_vflat
                FROM hr_speed_points
                WHERE workout_id IN ({placeholders})
            """
            res = conn.exec_driver_sql(sql, tuple(workout_ids)).mappings().all()
        else:
            res = conn.execute(
                text("""
                    SELECT workout_id, t_bin_start, mean_hr, mean_vflat
                    FROM hr_speed_points
                    WHERE workout_id = ANY(:ids)
                """),
                dict(ids=workout_ids),
            ).mappings().all()
    return [dict(r) for r in res]

# ------------------------------------------------------------
# Generic select (optional)
# ------------------------------------------------------------
def generic_select(table: str, where: str = "1=1"):
    with engine.begin() as conn:
        try:
            res = conn.execute(text(f"SELECT * FROM {table} WHERE {where}")).mappings().all()
            return [dict(r) for r in res]
        except Exception as e:
            print(f"⚠️ Error selecting from {table}:", e)
            return []

if __name__ == "__main__":
    print("Initializing DB…")
    init_db()
