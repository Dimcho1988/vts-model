import os, time, requests, streamlit as st
from urllib.parse import urlencode, urlparse, parse_qs

OAUTH_AUTHORIZE = "https://www.strava.com/oauth/authorize"
OAUTH_TOKEN = "https://www.strava.com/oauth/token"
API_BASE = "https://www.strava.com/api/v3"

SCOPES = ["read,activity:read_all"]

def connect_button():
    params = {
        "client_id": st.secrets["strava"]["client_id"],
        "redirect_uri": st.secrets["strava"]["redirect_uri"],
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "approval_prompt": "auto"
    }
    auth_url = f"{OAUTH_AUTHORIZE}?{urlencode(params)}"
    st.link_button("🔗 Connect Strava", auth_url, type="primary")

def exchange_token(auth_code: str):
    payload = {
        "client_id": st.secrets["strava"]["client_id"],
        "client_secret": st.secrets["strava"]["client_secret"],
        "code": auth_code,
        "grant_type": "authorization_code"
    }
    r = requests.post(OAUTH_TOKEN, data=payload, timeout=30)
    r.raise_for_status()
    return r.json()

def refresh_token(refresh_token: str):
    payload = {
        "client_id": st.secrets["strava"]["client_id"],
        "client_secret": st.secrets["strava"]["client_secret"],
        "grant_type": "refresh_token",
        "refresh_token": refresh_token
    }
    r = requests.post(OAUTH_TOKEN, data=payload, timeout=30)
    r.raise_for_status()
    return r.json()

def api_get(path: str, access_token: str, params=None):
    headers = {"Authorization": f"Bearer {access_token}"}
    r = requests.get(f"{API_BASE}{path}", headers=headers, params=params or {}, timeout=30)
    r.raise_for_status()
    return r.json()

def list_activities(access_token: str, after: int=None, per_page=30, page=1):
    params = {"per_page": per_page, "page": page}
    if after:
        params["after"] = after
    return api_get("/athlete/activities", access_token, params)

def get_streams(activity_id: int, access_token: str):
    # distance, time, velocity_smooth, altitude, heartrate might not all be present
    keys = "time,distance,velocity_smooth,altitude,heartrate"
    return api_get(f"/activities/{activity_id}/streams", access_token, params={"keys": keys, "key_by_type": "true"})
