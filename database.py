from __future__ import annotations
import os
from typing import Optional, Dict, Any, List
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
import streamlit as st

def get_database_url() -> str:
    if "DATABASE_URL" in st.secrets:
        return st.secrets["DATABASE_URL"]
    url = os.getenv("DATABASE_URL", "")
    if not url:
        raise RuntimeError("DATABASE_URL not configured.")
    return url

@st.cache_resource
def get_engine() -> Engine:
    engine = create_engine(get_database_url(), pool_pre_ping=True)
    return engine

def init_schema():
    engine = get_engine()
    schema_path = os.path.join(os.path.dirname(__file__), "..", "schema.sql")
    with open(schema_path, "r", encoding="utf-8") as f:
        ddl = f.read()
    with engine.begin() as conn:
        conn.execute(text(ddl))

def fetch_one(query: str, params: dict) -> Optional[Dict[str, Any]]:
    with get_engine().begin() as conn:
        res = conn.execute(text(query), params).mappings().first()
        return dict(res) if res else None

def execute(query: str, params: dict) -> None:
    with get_engine().begin() as conn:
        conn.execute(text(query), params)

def fetch_all(query: str, params: dict) -> List[Dict[str, Any]]:
    with get_engine().begin() as conn:
        res = conn.execute(text(query), params).mappings().all()
        return [dict(r) for r in res]
