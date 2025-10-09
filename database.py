from __future__ import annotations
import os
import pandas as pd
from datetime import datetime
from sqlalchemy import create_engine, text
from sqlalchemy.exc import ProgrammingError

# ------------------------- CONNECTION -------------------------

# Използва Supabase Postgres, ако има URL, иначе локална SQLite база
DATABASE_URL = os.getenv("SUPABASE_DB_URL") or os.getenv("DATABASE_URL") or "sqlite:///onflows.db"

engine = create_engine(DATABASE_URL, future=True, echo=False)


# ------------------------- INITIALIZATION -------------------------

def init_db():
    """
    Създава таблиците, ако ги няма (само за SQLite).
    При Postgres се очаква schema.sql да е вече изпълнен.
    """
    backend = engine.url.get_backend_name()
    if not backend.startswith("sqlite"):
        return  # не пипаме Postgres

    with engine.begin() as conn:
        conn.exec_driver_sql("""
        CREATE TABLE IF NOT EXISTS profiles (
            athlete_key TEXT PRIMARY KEY,
            hr_max INTEGER
        );
        """)
        conn.exec_driver_sql("""
        CREATE TABLE IF NOT EXISTS workouts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            athlete_key TEXT,
            start_time TEXT,
            duration_s REAL,
            distance_m REAL,
            avg_hr REAL,
            avg_speed_mps REAL,
            notes TEXT
        );
        """)
        conn.exec_driver_sql("""
        CREATE TABLE IF NOT EXISTS hr_speed_points (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            workout_id INTEGER,
            t_bin_start TEXT,
            mean_hr REAL,
            mean_vflat REAL
        );
        """)
        conn.exec_driver_sql("""
        CREATE TABLE IF NOT EXISTS tokens (
            athlete_key TEXT PRIMARY KEY,
            strava_athlete_id TEXT,
            access_token TEXT,
            refresh_token TEXT,
            expires_at BIGINT
        );
        """)
    print("✅ Database initialized.")


# ------------------------- PROFILES -------------------------

def upsert_profile(athlete_key: str, hr_max: int):
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO profiles (athlete_key, hr_max)
            VALUES (:athlete_key, :hr_max)
            ON CONFLICT(athlete_key) DO UPDATE SET hr_max=:hr_max
        """), dict(athlete_key=athlete_key, hr_max=hr_max))


def fetch_profile(athlete_key: str):
    with engine.begin() as conn:
        res = conn.execute(text("SELECT * FROM profiles WHERE athlete_key=:k"), dict(k=athlete_key)).mappings().first()
    return dict(res) if res else None


# ------------------------- TOKENS (Strava) -------------------------

def upsert_token(athlete_key: str, strava_athlete_id: str, access_token: str, refresh_token: str, expires_at: int):
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO tokens (athlete_key, strava_athlete_id, access_token, refresh_token, expires_at)
            VALUES (:athlete_key, :strava_athlete_id, :access_token, :refresh_token, :expires_at)
            ON CONFLICT(athlete_key) DO UPDATE
            SET strava_athlete_id=:strava_athlete_id,
                access_token=:access_token,
                refresh_token=:refresh_token,
                expires_at=:expires_at
        """), dict(
            athlete_key=athlete_key,
            strava_athlete_id=strava_athlete_id,
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=expires_at,
        ))


def get_token(athlete_key: str):
    with engine.begin() as conn:
        res = conn.execute(text("SELECT * FROM tokens WHERE athlete_key=:k"), dict(k=athlete_key)).mappings().first()
    return dict(res) if res else None


# ------------------------- WORKOUTS -------------------------

def insert_workouts(rows: list[dict]):
    if not rows:
        return 0
    with engine.begin() as conn:
        for r in rows:
            conn.execute(text("""
                INSERT INTO workouts (athlete_key, start_time, duration_s, distance_m, avg_hr, avg_speed_mps, notes)
                VALUES (:athlete_key, :start_time, :duration_s, :distance_m, :avg_hr, :avg_speed_mps, :notes)
            """), r)
    return len(rows)


def fetch_workouts(athlete_key: str):
    with engine.begin() as conn:
        try:
            res = conn.execute(text("""
                SELECT * FROM workouts
                WHERE athlete_key = :athlete_key
                ORDER BY start_time ASC
            """), dict(athlete_key=athlete_key)).mappings().all()
            return [dict(r) for r in res]
        except ProgrammingError as e:
            print("⚠️ Table workouts missing:", e)
            return []


# ------------------------- HR–SPEED POINTS -------------------------

def insert_hr_points(rows: list[dict]):
    if not rows:
        return 0
    with engine.begin() as conn:
        for r in rows:
            conn.execute(text("""
                INSERT INTO hr_speed_points (workout_id, t_bin_start, mean_hr, mean_vflat)
                VALUES (:workout_id, :t_bin_start, :mean_hr, :mean_vflat)
            """), r)
    return len(rows)


def fetch_hr_points(workout_ids: list[int]):
    """
    Работи и на SQLite, и на Postgres. Връща HR–V точки по workout_id.
    """
    if not workout_ids:
        return []
    backend = engine.url.get_backend_name()
    with engine.begin() as conn:
        if backend.startswith("sqlite"):
            placeholders = ",".join(["?"] * len(workout_ids))
            sql = f"SELECT workout_id, t_bin_start, mean_hr, mean_vflat FROM hr_speed_points WHERE workout_id IN ({placeholders})"
            res = conn.exec_driver_sql(sql, tuple(workout_ids)).mappings().all()
        else:
            res = conn.execute(text("""
                SELECT workout_id, t_bin_start, mean_hr, mean_vflat
                FROM hr_speed_points
                WHERE workout_id = ANY(:ids)
            """), dict(ids=workout_ids)).mappings().all()
    return [dict(r) for r in res]


# ------------------------- GENERIC SELECTOR -------------------------

def generic_select(table: str, where: str = "1=1"):
    with engine.begin() as conn:
        try:
            res = conn.execute(text(f"SELECT * FROM {table} WHERE {where}")).mappings().all()
            return [dict(r) for r in res]
        except Exception as e:
            print(f"⚠️ Error selecting from {table}:", e)
            return []


# ------------------------- DEBUG / TEST -------------------------

if __name__ == "__main__":
    print("Initializing database...")
    init_db()
    print("Profiles:", fetch_profile("demo_user"))
