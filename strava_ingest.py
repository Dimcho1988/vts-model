import requests, time, pandas as pd, numpy as np
from datetime import datetime, timezone
import database as db
from .strava_auth import refresh_access_token

API_BASE = "https://www.strava.com/api/v3"

def _ensure_valid_token(tok, client_id, client_secret):
    exp = tok.get("expires_at")
    try:
        exp_ts = int(exp)
    except Exception:
        try:
            exp_ts = int(pd.Timestamp(exp).timestamp())
        except Exception:
            exp_ts = 0
    if time.time() > exp_ts - 60:
        fres = refresh_access_token(client_id, client_secret, tok["refresh_token"])
        tok["access_token"] = fres["access_token"]
        tok["refresh_token"] = fres["refresh_token"]
        tok["expires_at"] = fres["expires_at"]
    return tok

def fetch_activities(athlete_key, after_ts=None, before_ts=None, client_id=None, client_secret=None):
    tok = db.get_token(athlete_key)
    if not tok: return []
    tok = _ensure_valid_token(tok, client_id, client_secret)
    headers = {"Authorization": f"Bearer {tok['access_token']}"}
    params = {"per_page": 100, "page": 1}
    if after_ts: params["after"] = int(after_ts)
    if before_ts: params["before"] = int(before_ts)
    all_rows = []
    while True:
        r = requests.get(f"{API_BASE}/athlete/activities", headers=headers, params=params, timeout=30)
        r.raise_for_status()
        data = r.json()
        if not data: break
        for a in data:
            row = {
                "athlete_key": athlete_key,
                "start_time": pd.to_datetime(a["start_date"]).tz_convert("UTC").isoformat(),
                "duration_s": int(a.get("moving_time",0)),
                "distance_m": float(a.get("distance",0.0)),
                "avg_hr": float(a.get("average_heartrate")) if a.get("average_heartrate") is not None else None,
                "avg_speed_mps": float(a.get("average_speed")) if a.get("average_speed") is not None else None,
                "notes": a.get("name","")[:255]
            }
            row["_id"] = a["id"]
            all_rows.append(row)
        params["page"] += 1
    db.insert_workouts([{k:v for k,v in r.items() if not k.startswith("_")} for r in all_rows])
    return [r["_id"] for r in all_rows]

def fetch_streams_for_activity(athlete_key, activity_id, client_id=None, client_secret=None, attach_workout_id=None):
    tok = db.get_token(athlete_key)
    if not tok: return 0
    tok = _ensure_valid_token(tok, client_id, client_secret)
    headers = {"Authorization": f"Bearer {tok['access_token']}"}
    keys = "time,velocity_smooth,grade_smooth,heartrate"
    r = requests.get(f"{API_BASE}/activities/{activity_id}/streams",
                     headers=headers, params={"keys": keys, "key_by_type": "true"}, timeout=60)
    if r.status_code == 404:
        return 0
    r.raise_for_status()
    js = r.json()
    t = js.get("time",{}).get("data",[])
    v = js.get("velocity_smooth",{}).get("data",[])
    g = js.get("grade_smooth",{}).get("data",[])
    hr = js.get("heartrate",{}).get("data",[])
    if not t or not v: return 0

    wk = db.fetch_workouts(athlete_key)
    import pandas as pd
    wk_df = pd.DataFrame(wk)
    if attach_workout_id is None and not wk_df.empty:
        attach_workout_id = int(wk_df.iloc[-1]["id"])
    start_time = pd.to_datetime(wk_df[wk_df["id"]==attach_workout_id]["start_time"].values[0])
    ts = pd.to_datetime(start_time) + pd.to_timedelta(pd.Series(t), unit="s")
    import numpy as np
    df = pd.DataFrame({
        "timestamp": ts,
        "speed_mps": pd.Series(v, dtype=float),
        "grade": pd.Series(g, dtype=float) if len(g)==len(v) else 0.0,
        "hr": pd.Series(hr, dtype=float) if len(hr)==len(v) else np.nan
    })
    from .processing import bin_30s
    binned = bin_30s(df)
    rows = [dict(workout_id=int(attach_workout_id),
                 t_bin_start=row.t_bin_start.isoformat(),
                 mean_hr=None if pd.isna(row.mean_hr) else float(row.mean_hr),
                 mean_vflat=float(row.mean_vflat)) for _,row in binned.iterrows()]
    return db.insert_hr_points(rows)
