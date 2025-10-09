
from sqlalchemy import create_engine, text
import os, datetime, random

DB_PATH = os.path.join(os.path.dirname(__file__), "local.db")
engine = create_engine(f"sqlite:///{DB_PATH}", future=True)

def init_schema():
    with engine.begin() as conn:
        conn.exec_driver_sql("""
        create table if not exists workouts(
          activity_id integer primary key,
          start_time  timestamp
        );
        create table if not exists zone_stats(
          id integer primary key autoincrement,
          activity_id integer,
          zone_label text,
          zone_type text,
          distance_m real,
          time_s real,
          mean_speed_flat real
        );
        """)

def seed_demo_data(days_back:int=56):
    with engine.begin() as conn:
        c = conn.execute(text("select count(*) as c from workouts")).mappings().first()
        if c and c["c"] and c["c"] > 0:
            return
        now = datetime.datetime.utcnow().replace(hour=6, minute=0, second=0, microsecond=0)
        act_id = 1000
        zones = ["Z1","Z2","Z3","Z4","Z5"]
        for d in range(days_back):
            day = now - datetime.timedelta(days=(days_back-1-d))
            if random.random() < 0.8:
                conn.execute(text("insert into workouts(activity_id, start_time) values (:id,:t)"),
                             {"id": act_id, "t": day.isoformat()})
                base_minutes = random.choice([40, 55, 70])
                remain = base_minutes
                for z in zones:
                    if z == "Z5":
                        m = max(0, remain)
                    else:
                        m = max(0, int(random.uniform(0.05,0.4)*remain))
                        remain -= m
                    v_map = {"Z1":9.5, "Z2":12.0, "Z3":13.5, "Z4":15.0, "Z5":16.5}
                    v = random.gauss(v_map[z], 0.4)
                    dist_km = v * (m/60.0)
                    time_s = m*60.0
                    dist_m = dist_km*1000.0
                    mean_v = (dist_m/time_s) if time_s>0 else None
                    if m>0:
                        conn.execute(text("""
                            insert into zone_stats(activity_id, zone_label, zone_type, distance_m, time_s, mean_speed_flat)
                            values (:aid,:z,'speed',:dm,:ts,:vs)
                        """), {"aid": act_id, "z": z, "dm": dist_m, "ts": time_s, "vs": mean_v})
                act_id += 1

def fetch_all(query, params=None):
    with engine.begin() as conn:
        res = conn.execute(text(query), params or {})
        return [dict(r) for r in res]

def execute(query, params=None):
    with engine.begin() as conn:
        conn.execute(text(query), params or {})
