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

# Supabase понякога дава стар префикс
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL, future=True, pool_pre_ping=True, echo=False)


# ------------------------------------------------------------
# Schema (авто-миграции)
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
    notes TEXT
);

CREATE INDEX IF NOT EXISTS idx_workouts_ath_time ON workouts(athlete_key, start_time);

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
    Автоматично създава таблиците.
    - На SQLite: винаги.
    - На Postgres: опитва; ако ролята няма права -> вдига информативно изключение.
    """
    backend = engine.url.get_backend_name()

    # SQLite – винаги можем
    if backend.startswith("sqlite"):
        with engine.begin() as conn:
            # заменяме SERIAL с INTEGER AUTOINCREMENT за съвместимост
            sqlite_sql = SCHEMA_SQL.replace("SERIAL", "INTEGER")
            conn.exec_driver_sql(sqlite_sql)
        return True

    # Postgres / Supabase
    try:
        with engine.begin() as conn:
            # Уверяваме се, че сме в public schema (Supabase)
            conn.execute(text("set search_path to public"))
            conn.execute(text(SCHEMA_SQL))
        return True
    except (ProgrammingError, OperationalError) as e:
        # няма права за DDL – информираме, но не спираме приложението
        raise RuntimeError(
            "DB schema create failed (role likely lacks CREATE privileges). "
            "Ако си в Supabase, ползвай service-role в Streamlit Secrets, "
            "или създай таблиците веднъж от SQL Editor."
        ) from e


# ------------------------------------------------------------
# Public API
# ------------------------------------------------------------
def init_db():
    """Запазваме обратно-совместимото име, вика ensure_schema()."""
    return ensure_schema()


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


def insert_workouts(rows: list[dict]):
    if not rows:
        return 0
    with engine.begin() as conn:
        backend = engine.url.get_backend_name()
        for r in rows:
            if backend.startswith("sqlite"):
                conn.exec_driver_sql(
                    "INSERT INTO workouts (athlete_key, start_time, duration_s, distance_m, avg_hr, avg_speed_mps, notes)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        r.get("athlete_key"),
                        r.get("start_time"),
                        r.get("duration_s"),
                        r.get("distance_m"),
                        r.get("avg_hr"),
                        r.get("avg_speed_mps"),
                        r.get("notes"),
                    ),
                )
            else:
                conn.execute(
                    text("""
                        INSERT INTO workouts
                          (athlete_key, start_time, duration_s, distance_m, avg_hr, avg_speed_mps, notes)
                        VALUES (:athlete_key, :start_time, :duration_s, :distance_m, :avg_hr, :avg_speed_mps, :notes)
                    """),
                    r,
                )
    return len(rows)


def fetch_workouts(athlete_key: str):
    with engine.begin() as conn:
        res = conn.execute(
            text("""
                SELECT id, athlete_key, start_time, duration_s, distance_m, avg_hr, avg_speed_mps, notes
                FROM workouts
                WHERE athlete_key = :athlete_key
                ORDER BY start_time ASC
            """),
            dict(athlete_key=athlete_key),
        ).mappings().all()
    return [dict(r) for r in res]


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


# -------- Strava tokens --------
def upsert_token(athlete_key: str, strava_athlete_id: str,
                 access_token: str, refresh_token: str, expires_at: int):
    with engine.begin() as conn:
        backend = engine.url.get_backend_name()
        if backend.startswith("sqlite"):
            # SQLite: създай таблицата при нужда (идемпотентно)
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
                FROM tokens
                WHERE athlete_key=:k
            """),
            dict(k=athlete_key),
        ).mappings().first()
    return dict(res) if res else None
