# ui_strava.py
import json
import pandas as pd
import numpy as np
import plotly.express as px
import streamlit as st
from datetime import datetime, timezone
from sqlalchemy import text  # <-- FIX: нужен за pd.read_sql(text(...))

from strava_oauth import build_auth_url, exchange_code_for_token, refresh_token, token_is_expired
from strava_api import StravaClient
from processing import to_30s_bins, per_activity_summary
from zoning import ZoneConfig, zone_tables
from acwr import compute_daily_acwr
import database as db

from profiles import (
    ensure_profiles_schema, upsert_user_minimal, save_hrmax, save_cs,
    get_profile, zones_df_from_profile, save_speed_zones_perc
)
from models import (
    HRSpeedModelConfig, update_model, fatigue_index_for_workout, derive_hr_zones_from_speed
)

# ---------------- helpers ----------------
def _get_token_from_state():
    tok = st.session_state.get("strava_token_json")
    if isinstance(tok, dict): return tok
    if isinstance(tok, str):
        try: return json.loads(tok)
        except Exception: return None
    return None

def _save_token_to_state(tok: dict):
    st.session_state["strava_token_json"] = tok

def _get_query_param(name: str):
    try: return st.query_params.get(name)
    except Exception:
        qp = st.experimental_get_query_params()
        v = qp.get(name)
        return v[0] if isinstance(v, list) and v else v

def _clear_query_params():
    try: st.query_params.clear()
    except Exception:
        try: st.experimental_set_query_params()
        except Exception: pass

def _handle_oauth_redirect():
    code = _get_query_param("code")
    error = _get_query_param("error")
    if error and not _get_token_from_state():
        st.error(f"Strava auth error: {error}")
        return
    if not code: return
    if _get_token_from_state():
        _clear_query_params(); return
    try:
        token = exchange_code_for_token(code)
        _save_token_to_state(token)
        st.success("Strava connected!")
    except Exception:
        st.info("Already authorized (refresh).")
    finally:
        _clear_query_params()

def _client_from_token(token: dict) -> StravaClient:
    if token_is_expired(token):
        try:
            token = refresh_token(token["refresh_token"])
            _save_token_to_state(token)
        except Exception as e:
            st.warning(f"Token refresh failed ({e}). Reconnect if needed.")
    return StravaClient(token["access_token"])

def _pace_from_kmh(v_kmh: float) -> str:
    if v_kmh is None or v_kmh <= 0: return "-"
    pace_min = 60.0 / v_kmh
    mm = int(pace_min)
    ss = int(round((pace_min - mm) * 60))
    if ss == 60: mm += 1; ss = 0
    return f"{mm}:{ss:02d}/км"

# ================ MAIN ================
def render_strava_tab():
    st.header("Strava • Data → Zones → ACWR → Dynamic HR–Speed Model")

    # DB
    try:
        engine = db.get_engine()
        db.ensure_schema(engine)
        ensure_profiles_schema(engine)
        db_ok = True
    except Exception as e:
        db_ok = False
        st.error(f"Database not ready: {e}")

    # Auth
    with st.expander("Connect to Strava", expanded=True):
        auth_url = build_auth_url()
        if auth_url:
            st.markdown(f"[Authorize with Strava]({auth_url})")
            _handle_oauth_redirect()
        st.caption("If OAuth isn't configured, paste a temporary access token below.")
        manual_token = st.text_input("Temporary access token (optional)", type="password")

    token = _get_token_from_state()
    if not token and manual_token:
        token = {"access_token": manual_token, "expires_at": 9999999999}
        _save_token_to_state(token)

    if not token:
        st.info("Connect to Strava to continue.")
        return

    client = _client_from_token(token)
    try:
        athlete = client.get_athlete()
        st.success(f"Connected as: {athlete.get('firstname','')} {athlete.get('lastname','')} (id {athlete.get('id')})")
    except Exception as e:
        st.error(f"Failed to fetch athlete: {e}")
        return
    athlete_id = int(athlete["id"])

    # ensure profile row
    if db_ok:
        try:
            upsert_user_minimal(engine, athlete_id,
                                display_name=f"{athlete.get('firstname','')} {athlete.get('lastname','')}",
                                email=athlete.get("email",""))
        except Exception as e:
            st.warning(f"Profile ensure failed: {e}")

    # ---- HRmax & CS from profile ----
    prof = get_profile(engine, athlete_id) if db_ok else {}
    hrmax_init = int(prof.get("hrmax") or 200)
    cs_init = float(prof.get("cs_kmh") or 0.0)

    colA, colB = st.columns(2)
    with colA:
        hrmax_val = st.number_input("HRmax", min_value=100, max_value=220, value=hrmax_init, step=1)
        if db_ok:
            try: save_hrmax(engine, athlete_id, hrmax_val)
            except Exception: pass
    with colB:
        cs_kmh_manual = st.number_input("Critical Speed (km/h) – optional override", min_value=0.0, value=float(cs_init), step=0.1)
        if db_ok and cs_kmh_manual > 0:
            try: save_cs(engine, athlete_id, cs_kmh_manual)
            except Exception: pass
    cs_kmh_current = cs_kmh_manual if cs_kmh_manual > 0 else (cs_init if cs_init > 0 else None)

    # ---- Speed zone thresholds (as %CS, persisted) ----
    st.caption("Speed zones are stored as % of CS in your profile. They are converted to absolute km/h when CS is known.")
    zones_default_df = zones_df_from_profile(prof, cs_kmh_current)
    zones_input = st.data_editor(
        zones_default_df[["zone","low_%CS","high_%CS","note"]],
        num_rows="dynamic", use_container_width=True, key="zones_editor_percent_cs_strava"
    )
    if db_ok:
        try: save_speed_zones_perc(engine, athlete_id, zones_input, cs_kmh_current)
        except Exception as e: st.warning(f"Saving zones failed: {e}")

    # ---- Activities ----
    per_page = st.selectbox("Activities per page", [10, 20, 30, 50], index=2)
    page = st.number_input("Page", min_value=1, value=1, step=1)
    try:
        acts = client.list_activities(per_page=per_page, page=page)
    except Exception as e:
        st.error(f"Failed to list activities: {e}"); return

    st.write(f"Loaded {len(acts)} activities")
    act_map = {f"{a['start_date'][:19]} • {a['name']} • {a['id']}": a for a in acts}
    choice = st.selectbox("Pick an activity to process", list(act_map.keys()))
    sel = act_map.get(choice)
    if sel is None: st.stop()

    # ---- Process ----
    if st.button("Process selected activity"):
        with st.spinner("Fetching & processing..."):
            try:
                streams = client.get_streams(sel["id"])
                start_time = pd.to_datetime(sel["start_date"])
                bdf = to_30s_bins(streams, start_time)
                avg_hr, avg_vflat, duration_s = per_activity_summary(bdf)

                # Zone tables (per-activity)
                cfg = ZoneConfig(hrmax=hrmax_val)
                hr_tbl, spd_tbl = zone_tables(bdf, cfg)
                st.subheader("Per-activity zone tables")
                st.dataframe(hr_tbl, use_container_width=True)
                st.dataframe(spd_tbl, use_container_width=True)

                # Save to DB
                if db_ok:
                    rid = db.upsert_workout(
                        engine, athlete_id=athlete_id, activity_id=sel["id"],
                        start_time=start_time.to_pydatetime(), duration_s=duration_s,
                        avg_hr=avg_hr, avg_speed_flat=avg_vflat, raw_payload={"activity": sel},
                    )
                    db.insert_zone_stats(engine, sel["id"], hr_tbl)
                    db.insert_zone_stats(engine, sel["id"], spd_tbl)
                    db.insert_hr_speed_points(engine, athlete_id, sel["id"], bdf)
                    st.success(f"Saved workout #{rid} and zone stats.")

                # HR/Speed time series
                st.subheader("HR / Speed (flat) over time – 30s bins")
                line_df = bdf.reset_index().rename(columns={"time":"Time","hr":"HR","v_flat":"Speed (flat m/s)"})
                st.plotly_chart(px.line(line_df, x="Time", y=["HR","Speed (flat m/s)"]), use_container_width=True)

            except Exception as e:
                st.error(f"Processing failed: {e}")

    # ---- Dynamic model & HR zones table (VTS-style) ----
    st.markdown("---")
    st.subheader("Dynamic HR = a·V + b model (from history)")
    try:
        model_cfg = HRSpeedModelConfig(half_life_days=14.0, min_points=60)
        state = update_model(engine, athlete_id, model_cfg)
        if state is None:
            st.info("Not enough history to fit model yet (need ≥ 60 points).")
        else:
            st.write(f"a = {state.a:.3f} HR/(m/s) • b = {state.b:.1f} bpm • R² = {state.r2:.3f}")

            if cs_kmh_current:
                vts_df = derive_hr_zones_from_speed(zones_input, cs_kmh_current, state)
                st.subheader("Zones (VTS style) + HR ranges")
                st.dataframe(vts_df, use_container_width=True)
            else:
                st.info("Set your CS to see speed/pace + HR zone table.")
    except Exception as e:
        st.error(f"Model error: {e}")

    # ---- Fatigue & Training Index ----
    st.markdown("---")
    st.subheader("Fatigue & Training Index")
    if db_ok:
        try:
            with engine.begin() as conn:
                w = pd.read_sql(
                    text("select start_time, avg_hr, avg_speed_flat from workouts where athlete_id=:aid order by start_time"),
                    conn, params={"aid": athlete_id}
                )
            if w.empty:
                st.info("No saved workouts yet.")
            else:
                # normalize time
                w["start_time"] = pd.to_datetime(w["start_time"])
                # FI per workout
                model_cfg = HRSpeedModelConfig(half_life_days=14.0, min_points=60)
                state = update_model(engine, athlete_id, model_cfg)
                if state is None:
                    st.info("Model not ready -> FI/Training Index need the HR–speed model.")
                else:
                    def _fi_row(r):
                        return fatigue_index_for_workout(state, float(r["avg_hr"]), float(r["avg_speed_flat"]))
                    w["fatigue_index"] = w.apply(_fi_row, axis=1)
                    # daily mean + 7-day rolling average as Training Index
                    d = w.groupby(w["start_time"].dt.date)["fatigue_index"].mean().reset_index()
                    d.rename(columns={"start_time":"day"}, inplace=True)
                    d["training_index_7d"] = d["fatigue_index"].rolling(window=7, min_periods=1).mean()

                    st.dataframe(d.tail(30), use_container_width=True)
                    fig = px.line(d, x="day", y=["fatigue_index","training_index_7d"],
                                  labels={"value":"m/s","variable":""},
                                  title="Daily Fatigue (m/s) and 7-day Training Index")
                    st.plotly_chart(fig, use_container_width=True)
        except Exception as e:
            st.error(f"Training index error: {e}")

    # ---- ACWR by zone ----
    st.markdown("---")
    st.subheader("ACWR by zone")
    if db_ok:
        try:
            all_zone = db.fetch_all_zone_daily(engine)
            if all_zone.empty:
                st.info("No zone data saved yet. Process an activity first.")
            else:
                acwr_df = compute_daily_acwr(all_zone, day_col="day", athlete_col="athlete_id")
                st.dataframe(acwr_df.tail(30), use_container_width=True)
                zones = sorted(acwr_df["zone_label"].unique())
                zpick = st.selectbox("Zone", zones, index=0)
                sub = acwr_df[(acwr_df["zone_label"]==zpick) & (acwr_df["zone_type"]=="speed")]
                st.plotly_chart(px.line(sub.sort_values("day"), x="day", y="ratio",
                                        title=f"ACWR ratio – {zpick}"), use_container_width=True)
        except Exception as e:
            st.error(f"ACWR compute error: {e}")
    else:
        st.info("Database not configured. Set DATABASE_URL.")
