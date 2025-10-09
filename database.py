import os
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

DEFAULT_SQLITE = "sqlite:///onflows.db"

def get_engine():
    url = os.getenv("DATABASE_URL", DEFAULT_SQLITE)
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return create_engine(url, future=True, pool_pre_ping=True)

engine = get_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

def init_db():
    # Create tables for SQLite. For Postgres, run schema.sql manually.
    if engine.url.get_backend_name().startswith("sqlite"):
        with engine.begin() as conn:
            conn.exec_driver_sql("""
            create table if not exists user_profiles (
              id integer primary key autoincrement,
              athlete_key text unique not null,
              hr_max integer,
              created_at text default CURRENT_TIMESTAMP
            );
            create table if not exists workouts (
              id integer primary key autoincrement,
              athlete_key text not null,
              start_time text not null,
              duration_s integer not null,
              distance_m real not null,
              avg_hr real,
              avg_speed_mps real,
              notes text
            );
            create index if not exists idx_workouts_athlete_time on workouts(athlete_key, start_time);
            create table if not exists hr_speed_points (
              id integer primary key autoincrement,
              workout_id integer,
              t_bin_start text,
              mean_hr real,
              mean_vflat real
            );
            create table if not exists zone_stats (
              id integer primary key autoincrement,
              athlete_key text not null,
              week_start text not null,
              zone integer not null,
              time_min real not null default 0,
              distance_km real not null default 0
            );
            """)
    return engine

def upsert_profile(athlete_key, hr_max):
    with engine.begin() as conn:
        if engine.url.get_backend_name().startswith("sqlite"):
            conn.execute(text("""
            insert into user_profiles (athlete_key, hr_max)
            values (:athlete_key, :hr_max)
            on conflict(athlete_key) do update set hr_max=excluded.hr_max
            """), dict(athlete_key=athlete_key, hr_max=hr_max))
        else:
            conn.execute(text("""
            insert into user_profiles (athlete_key, hr_max)
            values (:athlete_key, :hr_max)
            on conflict (athlete_key) do update set hr_max = excluded.hr_max
            """), dict(athlete_key=athlete_key, hr_max=hr_max))

def insert_workouts(rows):
    if not rows: return 0
    with engine.begin() as conn:
        conn.execute(text("""
        insert into workouts (athlete_key, start_time, duration_s, distance_m, avg_hr, avg_speed_mps, notes)
        values (:athlete_key, :start_time, :duration_s, :distance_m, :avg_hr, :avg_speed_mps, :notes)
        """), rows)
    return len(rows)

def fetch_workouts(athlete_key):
    with engine.begin() as conn:
        res = conn.execute(text("""
        select id, athlete_key, start_time, duration_s, distance_m, avg_hr, avg_speed_mps, notes
        from workouts where athlete_key = :athlete_key order by start_time
        """), dict(athlete_key=athlete_key)).mappings().all()
    return [dict(r) for r in res]

def insert_hr_points(points):
    if not points: return 0
    with engine.begin() as conn:
        conn.execute(text("""
        insert into hr_speed_points (workout_id, t_bin_start, mean_hr, mean_vflat)
        values (:workout_id, :t_bin_start, :mean_hr, :mean_vflat)
        """), points)
    return len(points)

def fetch_hr_points(workout_ids):
    if not workout_ids: return []
    with engine.begin() as conn:
        res = conn.execute(text("""
        select workout_id, t_bin_start, mean_hr, mean_vflat
        from hr_speed_points
        where workout_id = any(:ids)
        """), dict(ids=workout_ids)).mappings().all()
    return [dict(r) for r in res]

# ---- Strava tokens helpers ----
def upsert_token(athlete_key, strava_athlete_id, access_token, refresh_token, expires_at):
    with engine.begin() as conn:
        if engine.url.get_backend_name().startswith("sqlite"):
            conn.exec_driver_sql("""
            create table if not exists strava_tokens (
              athlete_key text primary key,
              strava_athlete_id integer,
              access_token text,
              refresh_token text,
              expires_at text
            );
            """)
            conn.execute(text("""
            insert into strava_tokens (athlete_key, strava_athlete_id, access_token, refresh_token, expires_at)
            values (:athlete_key,:sid,:at,:rt,:exp)
            on conflict(athlete_key) do update set
              strava_athlete_id=excluded.strava_athlete_id,
              access_token=excluded.access_token,
              refresh_token=excluded.refresh_token,
              expires_at=excluded.expires_at
            """), dict(athlete_key=athlete_key, sid=strava_athlete_id, at=access_token, rt=refresh_token, exp=str(expires_at)))
        else:
            conn.execute(text("""
            insert into strava_tokens (athlete_key, strava_athlete_id, access_token, refresh_token, expires_at)
            values (:athlete_key,:sid,:at,:rt,:exp)
            on conflict (athlete_key) do update set
              strava_athlete_id=excluded.strava_athlete_id,
              access_token=excluded.access_token,
              refresh_token=excluded.refresh_token,
              expires_at=excluded.expires_at
            """), dict(athlete_key=athlete_key, sid=strava_athlete_id, at=access_token, rt=refresh_token, exp=expires_at))

def get_token(athlete_key):
    with engine.begin() as conn:
        res = conn.execute(text("""
        select strava_athlete_id, access_token, refresh_token, expires_at
        from strava_tokens where athlete_key=:athlete_key
        """), dict(athlete_key=athlete_key)).mappings().first()
    return dict(res) if res else None
