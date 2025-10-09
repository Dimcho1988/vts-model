from __future__ import annotations
from typing import Optional, Dict, Any
from .database import fetch_one, execute

DEFAULT_SPEED_ZONES = [
    {"zone":"Z1","low_pct":60,"high_pct":80},
    {"zone":"Z2","low_pct":80,"high_pct":90},
    {"zone":"Z3","low_pct":90,"high_pct":100},
    {"zone":"Z4","low_pct":100,"high_pct":105},
    {"zone":"Z5","low_pct":105,"high_pct":120},
]

def get_profile(athlete_id: int) -> Optional[Dict[str, Any]]:
    q = """
    select athlete_id, display_name, email, hrmax, cs_kmh, speed_zone_perc, speed_zone_abs
    from user_profiles where athlete_id=:aid
    "
    "
    return fetch_one(q, {"aid": athlete_id})

def upsert_profile(athlete_id: int, display_name: str, email: str,
                   hrmax: int | None, cs_kmh: float | None,
                   speed_zone_perc: list | None, speed_zone_abs: list | None):
    q = """
    insert into user_profiles(athlete_id, display_name, email, hrmax, cs_kmh, speed_zone_perc, speed_zone_abs)
    values (:aid, :name, :email, :hrmax, :cs, :szp::jsonb, :sza::jsonb)
    on conflict (athlete_id)
    do update set display_name=:name, email=:email, hrmax=:hrmax, cs_kmh=:cs, speed_zone_perc=:szp::jsonb,
                  speed_zone_abs=:sza::jsonb, updated_at=now()
    "
    "
    execute(q, {"aid": athlete_id, "name": display_name, "email": email,
                "hrmax": hrmax, "cs": cs_kmh,
                "szp": None if speed_zone_perc is None else speed_zone_perc,
                "sza": None if speed_zone_abs is None else speed_zone_abs})
