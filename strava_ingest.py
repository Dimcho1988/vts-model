import time
import requests
import pandas as pd
import numpy as np

import database as db
from strava_auth import refresh_access_token

BASE = "https://www.strava.com/api/v3"

def _ensure_valid_token(tok, client_id, client_secret):
    # ако е изтекъл – поднови
    now = int(pd.Timestamp.utcnow().timestamp())
    if tok["expires_at"] and int(tok["expires_at"]) - now < 60:
        js = refresh_access_token(client_id, client_secret, tok["refresh_token"])
        db.upsert_token(tok.get("athlete_key",""), tok.get("strava_athlete_id",""),
                        js["access_token"], js["refresh_token"], js["expires_at"])
        tok = {
            "athlete_key": tok.get("athlete_key",""),
            "strava_athlete_id": tok.get("strava_athlete_id",""),
            "access_token": js["access_token"],
            "refresh_token": js["refresh_token"],
            "expires_at": js["expires_at"],
        }
    return tok

def fetch_activities(athlete_key, after_ts=None, before_ts=None, client_id=None, client_secret=None):
    tok = db.get_token(athlete_key)
    if not tok: raise RuntimeError("No Strava token for this athlete.")
    tok["athlete_key"] = athlete_key
    tok = _ensure_valid_token(tok, client_id, client_secret)
    headers = {"Authorization": f"Bearer {tok['access_token']}"}

    params = {"per_page": 100, "page": 1}
    if after_ts: params["after"] = int(after_ts)
    if before_ts: params["before"] = int(before_ts)

    inserted = 0
    all_ids = []

    while True:
        r = requests.get(f"{BASE}/athlete/activities", headers=headers, params=params, timeout=30)
        r.raise_for_status()
        data = r.json()
        if not data: break

        rows = []
        for a in data:
            sid = a["id"]
            all_ids.append(sid)
            start = pd.to_datetime(a["start_date"]).tz_convert("UTC").isoformat()
            dist = float(a.get("distance", 0.0))
            dur = float(a.get("elapsed_time", 0.0))
            avg_spd = float(a.get("average_speed", 0.0)) if a.get("average_speed") is not None else None
            avg_hr = float(a.get("average_heartrate", np.nan)) if a.get("has_heartrate") else None
            rows.append(dict(
                athlete_key=athlete_key,
                start_time=start,
                duration_s=dur,
                distance_m=dist,
                avg_hr=avg_hr,
                avg_speed_mps=avg_spd,
                notes=a.get("name"),
                strava_id=sid,
                has_streams=False,
            ))
        inserted += db.insert_workouts(rows)
        params["page"] += 1
        time.sleep(0.1)

    return all_ids  # списък Strava IDs

def fetch_streams_for_activity(athlete_key, strava_activity_id, client_id=None, client_secret=None, attach_workout_id=None):
    tok = db.get_token(athlete_key)
    if not tok: raise RuntimeError("No Strava token for this athlete.")
    tok["athlete_key"] = athlete_key
    tok = _ensure_valid_token(tok, client_id, client_secret)
    headers = {"Authorization": f"Bearer {tok['access_token']}"}

    types = "time,latlng,altitude,heartrate,velocity_smooth,grade_smooth"
    r = requests.get(f"{BASE}/activities/{int(strava_activity_id)}/streams",
                     headers=headers, params={"keys": types, "key_by_type": True}, timeout=30)
    r.raise_for_status()
    js = r.json()

    # създаваме 1 Hz DataFrame
    t = js.get("time", {}).get("data", [])
    v = js.get("velocity_smooth", {}).get("data", [])
    g = js.get("grade_smooth", {}).get("data", [])
    hr = js.get("heartrate", {}).get("data", [])

    if not t or not v:
        return 0  # няма достатъчно данни

    ts = pd.to_datetime(t, unit="s", origin="unix", utc=True)
    df = pd.DataFrame({"timestamp": ts, "speed_mps": v})
    if g: df["grade"] = pd.Series(g, dtype="float32")
    else: df["grade"] = 0.0
    if hr: df["hr"] = pd.Series(hr, dtype="float32")
    else: df["hr"] = np.nan

    # биниране на 30 s: средна HR и equalized speed (тук можеш да си ползваш твоя метод)
    df["t_bin"] = (df["timestamp"].view("int64") // 10**9 // 30) * 30
    agg = (
        df.groupby("t_bin", as_index=False)
          .agg(mean_hr=("hr","mean"),
               mean_vflat=("speed_mps","mean"))  # ако имаш корекция по наклон, сложи я тук
    )
    agg["t_bin_start"] = pd.to_datetime(agg["t_bin"], unit="s", utc=True)

    # ако не е подаден workout_id, намираме по strava_id
    wk_id = attach_workout_id
    if wk_id is None:
        # взимаме последния запис с този strava_id
        wk = [w for w in db.fetch_workouts(athlete_key) if w.get("strava_id")==int(strava_activity_id)]
        if wk:
            wk_id = wk[-1]["id"]

    rows = [dict(workout_id=int(wk_id),
                 t_bin_start=row.t_bin_start.isoformat(),
                 mean_hr=None if pd.isna(row.mean_hr) else float(row.mean_hr),
                 mean_vflat=float(row.mean_vflat)) for _,row in agg.iterrows()]
    n = db.insert_hr_points(rows)
    if wk_id: db.set_has_streams(int(wk_id), True)
    return n

def autofetch_streams_for_new_workouts(athlete_key, client_id=None, client_secret=None, limit=10):
    todo = db.workouts_needing_streams(athlete_key, limit=limit)
    total = 0
    for w in todo:
        try:
            total += fetch_streams_for_activity(athlete_key, w["strava_id"],
                                                client_id=client_id, client_secret=client_secret,
                                                attach_workout_id=w["id"])
        except Exception:
            pass
        time.sleep(0.2)
    return total
