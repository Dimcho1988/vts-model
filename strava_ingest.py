from __future__ import annotations
from typing import List, Optional
import time
import requests
from datetime import datetime, timezone
import pandas as pd

from database import (
    insert_workout, list_workouts, mark_workout_has_streams,
    upsert_token, get_token, insert_hr_speed_points
)
from processing import bin_1hz_to_30s

BASE = "https://www.strava.com/api/v3"

def _headers(access_token: str) -> dict:
    return {"Authorization": f"Bearer {access_token}"}

def fetch_activities(athlete_key: str, after_ts: int, before_ts: int,
                     client_id: str, client_secret: str) -> List[int]:
    tok = get_token(athlete_key)
    if not tok:
        raise RuntimeError("No token for athlete. Connect Strava first.")

    now = int(time.time())
    if tok["expires_at"] and tok["expires_at"] <= now + 60:
        from strava_auth import refresh_token
        new_tok = refresh_token(client_id, client_secret, tok["refresh_token"])
        upsert_token(
            athlete_key, str(new_tok["athlete"]["id"]),
            new_tok["access_token"], new_tok["refresh_token"],
            int(new_tok["expires_at"])
        )
        tok = get_token(athlete_key)

    params = {"after": after_ts, "before": before_ts, "per_page": 100, "page": 1}
    ids: List[int] = []
    while True:
        r = requests.get(
            f"{BASE}/athlete/activities",
            headers=_headers(tok["access_token"]),
            params=params, timeout=30
        )
        r.raise_for_status()
        arr = r.json()
        if not arr:
            break

        for a in arr:
            if a.get("type") not in ("Run", "TrailRun"):
                continue
            start_iso = datetime.fromisoformat(a["start_date"].replace("Z", "+00:00"))\
                                .astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            duration_s = float(a.get("elapsed_time", 0) or 0)
            distance_m = float(a.get("distance", 0) or 0)
            avg_hr = float(a.get("average_heartrate") or 0) or None
            avg_speed = float(a.get("average_speed") or 0) or None
            strava_id = int(a["id"])
            try:
                insert_workout(
                    athlete_key, start_iso, duration_s, distance_m,
                    avg_hr, avg_speed, a.get("name"), strava_id
                )
            except Exception:
                # най-често: вече съществува (unique по strava_id)
                pass
            ids.append(strava_id)

        params["page"] += 1

    return ids

def fetch_streams_for_activity(athlete_key: str, strava_id: int,
                               client_id: str, client_secret: str,
                               attach_workout_id: Optional[int] = None) -> int:
    tok = get_token(athlete_key)
    if not tok:
        raise RuntimeError("No token for athlete. Connect Strava first.")

    headers = _headers(tok["access_token"])
    keys = "time,velocity_smooth,heartrate,grade_smooth"
    r = requests.get(
        f"{BASE}/activities/{strava_id}/streams",
        headers=headers, params={"keys": keys, "key_by_type": "true"}, timeout=60
    )
    r.raise_for_status()
    js = r.json()

    n = len(js.get("time", {}).get("data", []))
    if n == 0:
        return 0

    df = pd.DataFrame({
        "time": pd.to_datetime(js["time"]["data"], unit="s", utc=True),
        "velocity_smooth": js.get("velocity_smooth", {}).get("data", [None]*n),
        "grade_smooth": js.get("grade_smooth", {}).get("data", [0.0]*n),
        "heartrate": js.get("heartrate", {}).get("data", [None]*n),
    })
    bins = bin_1hz_to_30s(df)

    if attach_workout_id is None:
        wks = list_workouts(athlete_key, limit=500)
        wid = None
        for w in wks:
            if w.get("strava_id") == strava_id:
                wid = w["id"]
                break
        if wid is None:
            start_iso = df["time"].min().strftime("%Y-%m-%dT%H:%M:%SZ")
            wid = insert_workout(
                athlete_key, start_iso, 0.0, 0.0, None, None,
                f"Auto from streams {strava_id}", strava_id
            )
    else:
        wid = attach_workout_id

    pts = [{
        "t_bin_start": r["t_bin_start"],
        "mean_hr": float(r["mean_hr"]) if pd.notna(r["mean_hr"]) else None,
        "mean_vflat": float(r["mean_vflat"]) if pd.notna(r["mean_vflat"]) else None
    } for _, r in bins.iterrows()]
    ins = insert_hr_speed_points(int(wid), pts)
    mark_workout_has_streams(int(wid), True)
    return ins

def autofetch_streams_for_new_workouts(athlete_key: str, limit: int,
                                       client_id: str, client_secret: str) -> int:
    """
    Взима 1 Hz потоци за последните N тренировки, които имат strava_id и нямат прикачени streams.
    Връща брой тренировки, за които е записал точки.
    """
    wks = list_workouts(athlete_key, limit=limit)
    fetched = 0
    for w in wks:
        if w.get("has_streams"):
            continue
        sid = w.get("strava_id")
        if not sid:
            continue
        try:
            c = fetch_streams_for_activity(
                athlete_key, int(sid), client_id, client_secret, attach_workout_id=int(w["id"])
            )
            if c > 0:
                fetched += 1
        except Exception:
            # игнорирай грешки за конкретната активност и продължи
            pass
    return fetched
