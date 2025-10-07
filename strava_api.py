
import requests
from typing import List, Dict, Any

API_BASE = "https://www.strava.com/api/v3"

class StravaClient:
    def __init__(self, access_token: str):
        self.access_token = access_token

    def _get(self, path: str, params=None):
        headers = {"Authorization": f"Bearer {self.access_token}"}
        resp = requests.get(f"{API_BASE}{path}", headers=headers, params=params or {}, timeout=60)
        resp.raise_for_status()
        return resp.json()

    def get_athlete(self) -> Dict[str, Any]:
        return self._get("/athlete")

    def list_activities(self, per_page=30, page=1) -> List[Dict[str, Any]]:
        return self._get("/athlete/activities", params={"per_page": per_page, "page": page})

    def get_activity(self, activity_id: int) -> Dict[str, Any]:
        return self._get(f"/activities/{activity_id}", params={"include_all_efforts": False})

    def get_streams(self, activity_id: int, keys=None) -> Dict[str, Any]:
        if keys is None:
            keys = ["time", "velocity_smooth", "heartrate", "grade_smooth", "distance", "altitude"]
        headers = {"Authorization": f"Bearer {self.access_token}"}
        params = {"keys": ",".join(keys), "key_by_type": "true"}
        resp = requests.get(f"{API_BASE}/activities/{activity_id}/streams", headers=headers, params=params, timeout=60)
        resp.raise_for_status()
        return resp.json()
