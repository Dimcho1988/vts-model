
import os
import json
import pandas as pd
import numpy as np
import plotly.express as px
import streamlit as st
from datetime import datetime, timezone

from strava_oauth import build_auth_url, exchange_code_for_token, refresh_token, token_is_expired
from strava_api import StravaClient
from processing import to_30s_bins, per_activity_summary
from zoning import ZoneConfig, zone_tables
from acwr import zone_loads, compute_daily_acwr
from models import HRSpeedModelConfig, HRSpeedModelState, update_model, fatigue_index_for_workout
import database as db

def _get_token_from_state():
    tok = st.session_state.get("strava_token_json")
    if isinstance(tok, dict):
        return tok
    if isinstance(tok, str):
        try:
            return json.loads(tok)
        except Exception:
            return None
    return None

def _save_token_to_state(tok: dict):
    st.session_state["strava_token_json"] = tok

def _handle_oauth_redirect():
    code = st.query_params.get("code")
    if code:
        try:
            token = exchange_code_for_token(code)
            _save_token_to_state(token)
            st.success("Strava connected! You can clear the URL params now.")
        except Exception as e:
            st.error(f"OAuth exchange failed: {e}")

def _client_from_token(token: dict) -> StravaClient:
    if token_is_expired(token):
        try:
            token = refresh_token(token["refresh_token"])
            _save_token_to_state(token)
        except Exception as e:
            st.warning(f"Token refresh failed ({e}). Try reconnecting.")
    return StravaClient(token["access_token"])

def render_strava_tab():
    st.header("Strava • Data → Zones → ACWR → Dynamic HR–Speed Model")

    db_ok = True
    try:
        engine = db.get_engine()
        db.ensure_schema(engine)
    except Exception as e:
        db_ok = False
        st.error(f"Database not ready: {e}")

    # Auth UI
    with st.expander("1) Connect to Strava", expanded=True):
        # OAuth path
        auth_url = build_auth_url()
        if auth_url:
            st.markdown(f"[Authorize with Strava]({auth_url})")
            _handle_oauth_redirect()
        st.caption("If OAuth is not configured, paste an access token below for quick testing.")
        manual_token = st.text_input("Temporary access token (optional)", type="password")

    token = _get_token_from_state()
    if not token and manual_token:
        token = {"access_token": manual_token, "expires_at": 9999999999}
        _save_token_to_state(token)

    if not token:
        st.info("Connect to Strava to continue.")
        return

    client = _client_from_token(token)
    athlete = None
    try:
        athlete = client.get_athlete()
        st.success(f"Connected as: {athlete.get('firstname','')} {athlete.get('lastname','')} (id {athlete.get('id')})")
    except Exception as e:
        st.error(f"Failed to fetch athlete: {e}")
        return

    cfg = ZoneConfig(
        hrmax=st.number_input("HRmax", min_value=100, max_value=220, value=200, step=1),
    )
    st.caption("Adjust speed zone thresholds (m/s) as needed:")
    colz = st.columns(5)
    labels = ["Z1","Z2","Z3","Z4","Z5"]
    default_bounds = [cfg.speed_thresholds[z] for z in labels]
    new_bounds = []
    for i,lab in enumerate(labels):
        with colz[i]:
            new_bounds.append(st.number_input(lab, value=float(default_bounds[i]), step=0.1, format="%.2f"))
    cfg.speed_thresholds = dict(zip(labels, new_bounds))

    # Activity list
    per_page = st.selectbox("Activities per page", [10,20,30,50], index=2)
    page = st.number_input("Page", min_value=1, value=1, step=1)

    try:
        acts = client.list_activities(per_page=per_page, page=page)
    except Exception as e:
        st.error(f"Failed to list activities: {e}")
        return

    st.write(f"Loaded {len(acts)} activities")
    act_map = {f"{a['start_date'][:19]} • {a['name']} • {a['id']}": a for a in acts}
    choice = st.selectbox("Pick an activity to process", list(act_map.keys()))
    sel = act_map.get(choice)

    if sel is None:
        st.stop()

    # Fetch streams
    if st.button("Process selected activity"):
        with st.spinner("Fetching & processing..."):
            try:
                streams = client.get_streams(sel["id"])
                start_time = pd.to_datetime(sel["start_date"])
                bdf = to_30s_bins(streams, start_time)
                avg_hr, avg_vflat, duration_s = per_activity_summary(bdf)

                # Zone tables
                hr_tbl, spd_tbl = zone_tables(bdf, cfg)

                # Visuals
                st.subheader("Per-activity zone tables")
                st.dataframe(hr_tbl)
                st.dataframe(spd_tbl)

                # Save to DB
                if db_ok:
                    rid = db.upsert_workout(
                        engine,
                        athlete_id=athlete["id"],
                        activity_id=sel["id"],
                        start_time=start_time.to_pydatetime(),
                        duration_s=duration_s,
                        avg_hr=avg_hr,
                        avg_speed_flat=avg_vflat,
                        raw_payload={"activity": sel}
                    )
                    db.insert_zone_stats(engine, sel["id"], hr_tbl)
                    db.insert_zone_stats(engine, sel["id"], spd_tbl)
                    db.insert_hr_speed_points(engine, athlete["id"], sel["id"], bdf)
                    st.success(f"Saved workout #{rid} and zone stats.")

                # Charts
                st.subheader("HR / Speed (flat) over time – 30s bins")
                line_df = bdf.reset_index().rename(columns={"time":"Time","hr":"HR","v_flat":"Speed (flat m/s)"})
                fig = px.line(line_df, x="Time", y=["HR","Speed (flat m/s)"])
                st.plotly_chart(fig, use_container_width=True)

                # Fatigue index (requires model)
                st.subheader("Dynamic HR→Speed model")
                # Fetch all historic points for this athlete to fit/update a model
                if db_ok:
                    pts = db.fetch_all_zone_daily(engine)  # placeholder reuse; we will instead read hr_speed_points
                # We'll do a quick on-the-fly model from this athlete's previous workouts avg values:
                # (In production, query workouts table and maintain a stored model snapshot.)

                # Quick & simple: fit/update from last N workouts avg pairs
                # For demo: use current workout only to compute fatigue vs a default model
                state = HRSpeedModelState(slope=0.02, intercept=0.0)
                cfgm = HRSpeedModelConfig(ew_alpha=0.2)
                # In a full pipeline you would aggregate past workouts' (avg_hr, avg_vflat) to update the model.
                fi = fatigue_index_for_workout(state, avg_hr, avg_vflat)
                st.metric("Fatigue index (v_real - v_pred)", f"{fi:.3f} m/s", help="Negative => slower than expected (fatigue)")

            except Exception as e:
                st.error(f"Processing failed: {e}")

    st.markdown("---")
    st.subheader("ACWR by zone")
    if db_ok:
        try:
            all_zone = db.fetch_all_zone_daily(engine)
            if all_zone.empty:
                st.info("No zone data saved yet. Process an activity first.")
            else:
                acwr_df = compute_daily_acwr(all_zone, day_col="day", athlete_col="athlete_id")
                st.dataframe(acwr_df.tail(30))

                # Chart ACWR ratio per zone (selectable)
                zones = sorted(acwr_df["zone_label"].unique())
                zpick = st.selectbox("Zone", zones, index=0)
                sub = acwr_df[(acwr_df["zone_label"]==zpick) & (acwr_df["zone_type"]=="speed")]
                fig2 = px.line(sub.sort_values("day"), x="day", y="ratio", title=f"ACWR ratio – {zpick}")
                st.plotly_chart(fig2, use_container_width=True)
        except Exception as e:
            st.error(f"ACWR compute error: {e}")
    else:
        st.info("Database not configured. Set DATABASE_URL to enable ACWR.")
