from __future__ import annotations
import os, requests, urllib.parse as up
from typing import Dict
import streamlit as st

STRAVA_AUTH_URL = "https://www.strava.com/oauth/authorize"
STRAVA_TOKEN_URL = "https://www.strava.com/oauth/token"

def get_cfg():
    cid = st.secrets.get("STRAVA_CLIENT_ID", os.getenv("STRAVA_CLIENT_ID", ""))
    csec = st.secrets.get("STRAVA_CLIENT_SECRET", os.getenv("STRAVA_CLIENT_SECRET", ""))
    redir = st.secrets.get("STRAVA_REDIRECT_URI", os.getenv("STRAVA_REDIRECT_URI", ""))
    return cid, csec, redir

def auth_link(scopes=("read","activity:read_all")) -> str:
    cid, _, redir = get_cfg()
    params = {
        "client_id": cid,
        "redirect_uri": redir,
        "response_type": "code",
        "approval_prompt": "auto",
        "scope": " ".join(scopes)
    }
    return f"{STRAVA_AUTH_URL}?{up.urlencode(params)}"

def exchange_token(code: str) -> Dict:
    cid, csec, redir = get_cfg()
    data = {
        "client_id": cid,
        "client_secret": csec,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": redir
    }
    r = requests.post(STRAVA_TOKEN_URL, data=data, timeout=20)
    r.raise_for_status()
    return r.json()

def refresh_token(refresh_token: str) -> Dict:
    cid, csec, _ = get_cfg()
    data = {"client_id": cid, "client_secret": csec, "grant_type":"refresh_token", "refresh_token": refresh_token}
    r = requests.post(STRAVA_TOKEN_URL, data=data, timeout=20)
    r.raise_for_status()
    return r.json()
