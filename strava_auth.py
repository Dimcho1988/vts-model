import requests
from urllib.parse import urlencode

STRAVA_OAUTH_BASE = "https://www.strava.com/oauth/authorize"
STRAVA_TOKEN_URL = "https://www.strava.com/oauth/token"


def oauth_link(client_id: str, redirect_uri: str, scope: str = "read,activity:read_all"):
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "approval_prompt": "auto",
        "scope": scope,
    }
    return f"{STRAVA_OAUTH_BASE}?{urlencode(params)}"


def exchange_code_for_token(client_id: str, client_secret: str, code: str, redirect_uri: str):
    """
    Обменя еднократния ?code=... за access/refresh token.
    ВАЖНО: Strava очаква същия redirect_uri, който е използван при authorize.
    Code е валиден ~10 мин и ЕДНОКРАТЕН.
    """
    payload = {
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri,  # <-- добавено
    }
    r = requests.post(STRAVA_TOKEN_URL, data=payload, timeout=20)
    # при грешка Strava връща JSON с 'message'/'errors' – повдигаме с текста
    try:
        r.raise_for_status()
        return r.json()
    except requests.HTTPError as e:
        try:
            detail = r.json()
        except Exception:
            detail = {"text": r.text}
        raise RuntimeError(f"Strava token exchange failed: {detail}") from e


def refresh_access_token(client_id: str, client_secret: str, refresh_token: str):
    payload = {
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }
    r = requests.post(STRAVA_TOKEN_URL, data=payload, timeout=20)
    r.raise_for_status()
    return r.json()
