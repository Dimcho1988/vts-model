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
