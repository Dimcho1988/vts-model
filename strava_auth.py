from __future__ import annotations
import urllib.parse as _up
import requests

AUTH_URL = "https://www.strava.com/oauth/authorize"
TOKEN_URL = "https://www.strava.com/oauth/token"

def oauth_link(client_id: str, redirect_uri: str, scope: str="read,activity:read_all") -> str:
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "approval_prompt": "auto",
        "scope": scope,
    }
    return f"{AUTH_URL}?{_up.urlencode(params)}"

def exchange_code_for_token(client_id: str, client_secret: str, code: str, redirect_uri: str):
    payload = {
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri
    }
    r = requests.post(TOKEN_URL, data=payload, timeout=30)
    r.raise_for_status()
    return r.json()