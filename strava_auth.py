import requests
from urllib.parse import urlencode

STRAVA_OAUTH_BASE = "https://www.strava.com/oauth/authorize"
STRAVA_TOKEN_URL = "https://www.strava.com/oauth/token"


def oauth_link(client_id: str, redirect_uri: str, scope: str = "activity:read_all"):
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "approval_prompt": "auto",
        "scope": scope,
    }
    return f"{STRAVA_OAUTH_BASE}?{urlencode(params)}"


def exchange_code_for_token(client_id, client_secret, code):
    payload = {
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "grant_type": "authorization_code",
    }
    r = requests.post(STRAVA_TOKEN_URL, data=payload, timeout=20)
    r.raise_for_status()
    return r.json()


def refresh_access_token(client_id, client_secret, refresh_token):
    payload = {
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }
    r = requests.post(STRAVA_TOKEN_URL, data=payload, timeout=20)
    r.raise_for_status()
    return r.json()
