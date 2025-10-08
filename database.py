import os
import json
import pandas as pd
from sqlalchemy import create_engine, text

# --------------------------
# Connection
# --------------------------
def get_engine():
    url = os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError("Set DATABASE_URL env var for Postgres (Supabase).")
    return create_engine(url, pool_pre_ping=True)

# --------------------------
# Schema init (reads schema.sql)
# --------------------------
def ensure_schema(engine):
    schema_path = "schema.sql"
    if not os.path.exists(schema_path):
        raise RuntimeError("schema.sql not found in repo root.")
    with open(schema_path, "r", encoding="utf-8") as f:
        schema_sql = f.read()
    with engine.begin() as conn:
        conn.execute(text(schema_sql))

# --------------------------
# Upsert workout
# --------------------------
def upsert_workout(engine, athlete_id, activity_id, start_time, duration_s, avg_hr, avg_speed_flat, raw_payload):
    sql = text("""
        insert into workouts(athlete_id, activity_id, start_time, duration_s, avg_hr, avg_speed_flat, raw_payload)
        values (:athlete_id, :activity_id, :start_time, :duration_s, :avg_hr, :avg_speed_flat, :raw_payload)
        on conflict (activity_id) do update set
          duration_s = excluded.duration_s,
          avg_hr = excluded.avg_hr,
          avg_speed_flat = excluded.avg_speed_flat,
          raw_payload = excluded.raw_payload
        returning id;
    """)
    with engine.begin() as conn:
        rid = conn.execute(sql, {
            "athlete_id": athlete_id,
            "activity_id": activity_id,
            "start_time": start_time,
            "duration_s": duration_s,
            "avg_hr": float(avg_hr) if avg_hr is not None else None,
            "avg_speed_flat": float(avg_speed_flat) if avg_speed_flat is not None else None,
            "raw_payload": json.dumps(raw_payload),
        }).scalar()
    return rid

# --------------------------
# Insert zone stats (DataFrame from zoning.zone_tables)
# --------------------------
def insert_zone_stats(engine, activity_id, zone_tbl):
    with engine.begin() as conn:
        conn.execute(text("delete from workout_zone_stats where activity_id=:aid"), {"aid": activity_id})
        for _, r in zone_tbl.iterrows():
            conn.execute(text("""
                insert into workout_zone_stats(activity_id, zone_type, zone_label, time_s, mean_hr, mean_speed_flat)
                values (:aid, :ztype, :zlabel, :time_s, :mean_hr, :mean_speed_flat)
            """), {
                "aid": activity_id,
                "ztype": r["zone_type"],
                "zlabel": r["zone_label"],
                "time_s": int(r["time_s"] or 0),
                "mean_hr": float(r["mean_hr"]) if pd.notna(r["mean_hr"]) else None,
                "mean_speed_flat": float(r["mean_speed_flat"]) if pd.notna(r["mean_speed_flat"]) else None,
            })

# --------------------------
# Store 30s points (for model)
# --------------------------
def insert_hr_speed_points(engine, athlete_id, activity_id, bin_df):
    with engine.begin() as conn:
        conn.execute(text("delete from hr_speed_points where activity_id=:aid"), {"aid": activity_id})
        for t, r in bin_df.iterrows():
            conn.execute(text("""
                insert into hr_speed_points(athlete_id, activity_id, point_time, hr, speed_flat)
                values (:athlete_id, :activity_id, :point_time, :hr, :speed_flat)
            """), {
                "athlete_id": athlete_id,
                "activity_id": activity_id,
                "point_time": t.to_pydatetime(),
                "hr": float(r["hr"]) if pd.notna(r["hr"]) else None,
                "speed_flat": float(r["v_flat"]) if pd.notna(r["v_flat"]) else None,
            })

# --------------------------
# Save model snapshot (optional)
# --------------------------
def upsert_model_snapshot(engine, athlete_id, model_json):
    with engine.begin() as conn:
        conn.execute(text("""
            insert into model_snapshots(athlete_id, model_json)
            values (:athlete_id, :model_json)
        """), {"athlete_id": athlete_id, "model_json": model_json})

# --------------------------
# Helper for ACWR page
# --------------------------
def fetch_all_zone_daily(engine):
    q = text("""
        select w.athlete_id,
               date(w.start_time) as day,
               s.zone_type, s.zone_label,
               sum((s.mean_speed_flat * (s.time_s/3600.0))) as zone_load
          from workouts w
          join workout_zone_stats s on s.activity_id = w.activity_id
         group by 1,2,3,4
         order by 1,2,3,4
    """)
    with engine.begin() as conn:
        return pd.read_sql(q, conn)
