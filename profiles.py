# profiles.py
import json
from typing import Dict, Any, Optional, List
import pandas as pd
from sqlalchemy import text

# ---------------- Schema ----------------
PROFILES_SQL = """
create table if not exists user_profiles (
  athlete_id       bigint primary key,
  display_name     text,
  email            text,
  hrmax            integer,
  cs_kmh           numeric,
  speed_zone_perc  jsonb,
  speed_zone_abs   jsonb,
  updated_at       timestamptz default now()
);
"""

DEFAULT_ZONE_PERC = [
    {"zone":"Z1 (възстановяване)","low_%CS":60.0,"high_%CS":80.0,"note":"много леко"},
    {"zone":"Z2 (лека)","low_%CS":80.0,"high_%CS":90.0,"note":"леко"},
    {"zone":"Z3 (темпо)","low_%CS":90.0,"high_%CS":100.0,"note":"устойчиво"},
    {"zone":"Z4 (праг)","low_%CS":100.0,"high_%CS":105.0,"note":"лактатен праг"},
    {"zone":"Z5 (интервали)","low_%CS":105.0,"high_%CS":120.0,"note":"висока интензивност"},
]

def ensure_profiles_schema(engine) -> None:
    with engine.begin() as conn:
        conn.execute(text(PROFILES_SQL))

# ---------------- CRUD helpers ----------------
def upsert_user_minimal(engine, athlete_id: int, display_name: str = "", email: str = "") -> None:
    ensure_profiles_schema(engine)
    sql = text("""
        insert into user_profiles(athlete_id, display_name, email)
        values (:aid, :name, :email)
        on conflict (athlete_id) do update set
          display_name = coalesce(excluded.display_name, user_profiles.display_name),
          email        = coalesce(excluded.email,        user_profiles.email),
          updated_at   = now()
    """)
    with engine.begin() as c:
        c.execute(sql, {"aid": athlete_id, "name": display_name, "email": email})

def save_hrmax(engine, athlete_id: int, hrmax: int) -> None:
    ensure_profiles_schema(engine)
    with engine.begin() as c:
        c.execute(
            text("update user_profiles set hrmax=:hr, updated_at=now() where athlete_id=:aid"),
            {"hr": int(hrmax), "aid": athlete_id}
        )

def save_cs(engine, athlete_id: int, cs_kmh: float) -> None:
    ensure_profiles_schema(engine)
    with engine.begin() as c:
        c.execute(
            text("update user_profiles set cs_kmh=:cs, updated_at=now() where athlete_id=:aid"),
            {"cs": float(cs_kmh), "aid": athlete_id}
        )

def _zones_perc_df_to_json(zdf: pd.DataFrame) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for _, r in zdf.iterrows():
        if pd.isna(r.get("low_%CS")) or pd.isna(r.get("high_%CS")):
            continue
        out.append({
            "zone": str(r.get("zone", "")),
            "low_%CS": float(r.get("low_%CS")),
            "high_%CS": float(r.get("high_%CS")),
            "note": str(r.get("note", "")),
        })
    return out

def _zones_abs_from_perc(zperc: List[Dict[str, Any]], cs_kmh: Optional[float]) -> List[Dict[str, Any]]:
    if not cs_kmh:
        return []
    out: List[Dict[str, Any]] = []
    for z in zperc:
        lo = cs_kmh * (z["low_%CS"] / 100.0)
        hi = cs_kmh * (z["high_%CS"] / 100.0)
        out.append({
            "zone": z["zone"],
            "speed_low_kmh": round(lo, 3),
            "speed_high_kmh": round(hi, 3),
            "note": z.get("note", "")
        })
    return out

def save_speed_zones_perc(engine, athlete_id: int, zones_df: pd.DataFrame, cs_kmh: Optional[float]) -> None:
    """Записва зоните като % от CS + кешира абсолютните граници (km/h)."""
    ensure_profiles_schema(engine)
    zperc = _zones_perc_df_to_json(zones_df)
    zabs  = _zones_abs_from_perc(zperc, cs_kmh)

    with engine.begin() as c:
        # 1) update
        c.execute(text("""
            update user_profiles
               set speed_zone_perc = :zperc,
                   speed_zone_abs  = :zabs,
                   updated_at      = now()
             where athlete_id = :aid
        """), {"aid": athlete_id, "zperc": json.dumps(zperc), "zabs": json.dumps(zabs)})

        # 2) insert if missing
        c.execute(text("""
            insert into user_profiles(athlete_id, speed_zone_perc, speed_zone_abs)
            select :aid, :zperc, :zabs
            where not exists (select 1 from user_profiles where athlete_id=:aid)
        """), {"aid": athlete_id, "zperc": json.dumps(zperc), "zabs": json.dumps(zabs)})

def get_profile(engine, athlete_id: int) -> Dict[str, Any]:
    ensure_profiles_schema(engine)
    with engine.begin() as c:
        row = c.execute(
            text("select * from user_profiles where athlete_id=:aid"),
            {"aid": athlete_id}
        ).mappings().first()

    if not row:
        with engine.begin() as c:
            c.execute(
                text("insert into user_profiles(athlete_id, speed_zone_perc) values (:aid, :z::jsonb) on conflict do nothing"),
                {"aid": athlete_id, "z": json.dumps(DEFAULT_ZONE_PERC)}
            )
        return {"athlete_id": athlete_id, "speed_zone_perc": DEFAULT_ZONE_PERC, "speed_zone_abs": []}

    return dict(row)

def zones_df_from_profile(profile: Dict[str, Any], cs_kmh: Optional[float]) -> pd.DataFrame:
    zperc = profile.get("speed_zone_perc") or DEFAULT_ZONE_PERC
    if isinstance(zperc, str):
        try:
            zperc = json.loads(zperc)
        except Exception:
            zperc = DEFAULT_ZONE_PERC
    df = pd.DataFrame(zperc)
    if cs_kmh:
        df["speed_low_kmh"]  = (df["low_%CS"]  / 100.0) * cs_kmh
        df["speed_high_kmh"] = (df["high_%CS"] / 100.0) * cs_kmh
    cols = ["zone", "low_%CS", "high_%CS", "note"]
    if cs_kmh:
        cols += ["speed_low_kmh", "speed_high_kmh"]
    return df[cols]
