import os
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
import json

# ===============================================
# Database connection
# ===============================================

def get_engine():
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        raise RuntimeError("DATABASE_URL not set. Please configure Supabase URL in Streamlit secrets.")
    return create_engine(db_url, pool_pre_ping=True)

engine = get_engine()

# ===============================================
# Initialize tables (if not exist)
# ===============================================

def init_db():
    schema_sql = """
    create table if not exists workouts (
        id serial primary key,
        athlete_id bigint,
        activity_id bigint unique,
        start_time timestamptz,
        duration_s float,
        avg_hr float,
        avg_speed_flat float,
        raw_payload jsonb
    );

    create table if not exists zone_stats (
        id serial primary key,
        workout_id int references workouts(id) on delete cascade,
        zone_label text,
        zone_type text,
        time_s float,
        mean_hr float,
        mean_speed_flat float
    );
    """
    with engine.begin() as conn:
        conn.execute(text(schema_sql))

# ===============================================
# Insert or update workout
# ===============================================

def upsert_workout(athlete_id, activity_id, start_time, duration_s, avg_hr, avg_speed_flat, raw_payload):
    try:
        with engine.begin() as conn:
            insert_stmt = text("""
                insert into workouts(athlete_id, activity_id, start_time, duration_s, avg_hr, avg_speed_flat, raw_payload)
                values (:athlete_id, :activity_id, :start_time, :duration_s, :avg_hr, :avg_speed_flat, :raw_payload)
                on conflict (activity_id) do update set
                    duration_s = excluded.duration_s,
                    avg_hr = excluded.avg_hr,
                    avg_speed_flat = excluded.avg_speed_flat,
                    raw_payload = excluded.raw_payload
                returning id;
            """)

            result = conn.execute(insert_stmt, {
                "athlete_id": athlete_id,
                "activity_id": activity_id,
                "start_time": start_time,
                "duration_s": duration_s,
                "avg_hr": avg_hr,
                "avg_speed_flat": avg_speed_flat,
                "raw_payload": json.dumps(raw_payload)
            })

            workout_id = result.scalar_one()
            return workout_id
    except SQLAlchemyError as e:
        print("DB error in upsert_workout:", e)
        return None

# ===============================================
# Insert zone stats (one workout → many zones)
# ===============================================

def insert_zone_stats(workout_id, zone_stats):
    try:
        with engine.begin() as conn:
            # Delete old zones for this workout
            conn.execute(text("delete from zone_stats where workout_id = :wid"), {"wid": workout_id})

            # Insert new
            for z in zone_stats:
                conn.execute(text("""
                    insert into zone_stats(workout_id, zone_label, zone_type, time_s, mean_hr, mean_speed_flat)
                    values (:workout_id, :zone_label, :zone_type, :time_s, :mean_hr, :mean_speed_flat)
                """), {
                    "workout_id": workout_id,
                    "zone_label": z.get("zone_label"),
                    "zone_type": z.get("zone_type"),
                    "time_s": z.get("time_s"),
                    "mean_hr": z.get("mean_hr"),
                    "mean_speed_flat": z.get("mean_speed_flat"),
                })
    except SQLAlchemyError as e:
        print("DB error in insert_zone_stats:", e)

# ===============================================
# Load all zone stats for ACWR analysis
# ===============================================

def load_all_zone_stats():
    try:
        with engine.begin() as conn:
            query = text("""
                select w.start_time, z.zone_label, z.zone_type, z.time_s, z.mean_hr, z.mean_speed_flat
                from zone_stats z
                join workouts w on w.id = z.workout_id
                order by w.start_time desc
            """)
            rows = conn.execute(query).fetchall()
            return [dict(r._mapping) for r in rows]
    except SQLAlchemyError as e:
        print("DB error in load_all_zone_stats:", e)
        return []
