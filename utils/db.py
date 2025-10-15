from typing import Optional, Dict, Any, List
import os
from supabase import create_client, Client
import streamlit as st

def get_supabase() -> Client:
    url = st.secrets["supabase"]["url"]
    key = st.secrets["supabase"]["anon_key"]
    return create_client(url, key)

def upsert(table: str, rows: List[Dict[str,Any]]):
    if not rows:
        return None
    sb = get_supabase()
    return sb.table(table).upsert(rows, on_conflict="id").execute()

def insert(table: str, rows: List[Dict[str,Any]]):
    if not rows:
        return None
    sb = get_supabase()
    return sb.table(table).insert(rows).execute()

def select(table: str, q: Optional[Dict[str, Any]]=None):
    sb = get_supabase()
    query = sb.table(table).select("*")
    if q:
        for k,v in q.items():
            query = query.eq(k, v)
    return query.execute().data

def replace_table(table: str, rows: List[Dict[str,Any]]):
    """Dangerous helper for first-time loads: deletes and inserts."""
    sb = get_supabase()
    sb.table(table).delete().neq("id","__all__").execute()
    if rows:
        sb.table(table).insert(rows).execute()
# --- NEW: users & tokens helpers -------------------------------------------

from uuid import UUID
from typing import Optional, Dict, Any

def get_or_create_user(strava_athlete_id: int, extra: Optional[Dict[str, Any]]=None) -> Dict[str, Any]:
    """
    Returns a row from users_profile for this Strava athlete.
    If missing, creates it and returns the created row.
    """
    sb = get_supabase()
    # 1) try find by strava_athlete_id
    got = sb.table("users_profile").select("*").eq("strava_athlete_id", strava_athlete_id).limit(1).execute().data
    if got:
        return got[0]

    payload = {
        "strava_athlete_id": int(strava_athlete_id),
    }
    if extra:
        payload.update(extra)

    created = sb.table("users_profile").insert(payload).execute().data
    if not created:
        raise RuntimeError("Could not create users_profile")
    return created[0]

def save_tokens(user_id: str, tokens: Dict[str, Any]) -> None:
    """
    Upserts access/refresh tokens for this user_id into user_tokens.
    """
    sb = get_supabase()
    row = {
        "user_id": user_id,
        "access_token": tokens.get("access_token"),
        "refresh_token": tokens.get("refresh_token"),
        "expires_at": tokens.get("expires_at"),  # epoch seconds
    }
    sb.table("user_tokens").upsert(row, on_conflict="user_id").execute()
