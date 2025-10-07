
import os
import time
import requests
from urllib.parse import urlencode

STRAVA_AUTH_URL = "https://www.strava.com/oauth/authorize"
STRAVA_TOKEN_URL = "https://www.strava.com/oauth/token"

def build_auth_url(scope="read,activity:read_all", state="onflows"):
    client_id = os.getenv("STRAVA_CLIENT_ID")
    redirect = os.getenv("STRAVA_REDIRECT_URI")
    if not client_id or not redirect:
        return None
    params = {
        "client_id": client_id,
        "redirect_uri": redirect,
        "response_type": "code",
        "approval_prompt": "auto",
        "scope": scope,
        "state": state,
    }
    return f"{STRAVA_AUTH_URL}?{urlencode(params)}"

def exchange_code_for_token(code: str):
    client_id = os.getenv("STRAVA_CLIENT_ID")
    client_secret = os.getenv("STRAVA_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise RuntimeError("Missing STRAVA_CLIENT_ID/STRAVA_CLIENT_SECRET")
    resp = requests.post(STRAVA_TOKEN_URL, data={
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "grant_type": "authorization_code"
    }, timeout=30)
    resp.raise_for_status()
    return resp.json()

def refresh_token(refresh_token: str):
    client_id = os.getenv("STRAVA_CLIENT_ID")
    client_secret = os.getenv("STRAVA_CLIENT_SECRET")
    resp = requests.post(STRAVA_TOKEN_URL, data={
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }, timeout=30)
    resp.raise_for_status()
    return resp.json()

def token_is_expired(token: dict) -> bool:
    return time.time() >= token.get("expires_at", 0)
