from __future__ import annotations
import requests
from typing import Dict, List

API_BASE = "https://www.strava.com/api/v3"

def _headers(token: str) -> Dict:
    return {"Authorization": f"Bearer {token}"}

def get_athlete(token: str) -> Dict:
    r = requests.get(f"{API_BASE}/athlete", headers=_headers(token), timeout=20)
    r.raise_for_status()
    return r.json()

def list_activities(token: str, per_page: int = 30) -> List[Dict]:
    r = requests.get(f"{API_BASE}/athlete/activities", headers=_headers(token), params={"per_page": per_page}, timeout=20)
    r.raise_for_status()
    return r.json()

def get_streams(token: str, activity_id: int, keys=("time","distance","altitude","heartrate")) -> Dict[str, Dict]:
    params = {"keys": ",".join(keys), "key_by_type": "true"}
    r = requests.get(f"{API_BASE}/activities/{activity_id}/streams", headers=_headers(token), params=params, timeout=30)
    r.raise_for_status()
    return r.json()
