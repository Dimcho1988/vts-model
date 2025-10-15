import os, json, time
from datetime import datetime, timezone, timedelta

import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st

# --- imports: work both with utils/ and root modules
try:
    from utils import db
    from utils import strava as su
    from utils import etl
    from utils import vts
except ModuleNotFoundError:
    import db                  # type: ignore
    import strava as su        # type: ignore
    import etl                 # type: ignore
    import vts                 # type: ignore

st.set_page_config(page_title="onFlows — Running Load", layout="wide")

# ================== Config ==================
APP = dict(st.secrets.get("app", {}))
ZONES = {
    "Z1": (APP.get("z1_low", 0.60), APP.get("z1_high", 0.80)),
    "Z2": (APP.get("z2_low", 0.80), APP.get("z2_high", 0.90)),
    "Z3": (APP.get("z3_low", 0.90), APP.get("z3_high", 1.00)),
    "Z4": (APP.get("z4_low", 1.00), APP.get("z4_high", 1.05)),
    "Z5": (APP.get("z5_low", 1.05), APP.get("z5_high", 1.20)),
}

@st.cache_data
def load_ideal():
    for p in ("data/ideal_distance_time_speed.csv", "ideal_distance_time_speed.csv"):
        if os.path.exists(p):
            return vts.load_ideal_csv(p)
    raise FileNotFoundError("ideal_distance_time_speed.csv not found in data/ or repo root")

def ensure_profile():
    if "user_id" in st.session_state:
        return {"user_id": st.session_state["user_id"]}
    return {"user_id": "00000000-0000-0000-0000-000000000000"}

# ================== Sidebar ==================
st.sidebar.title("onFlows")
st.sidebar.caption("Control & Evaluation of Running Load")

# Handle OAuth return (?code=...)
if "tokens" not in st.session_state:
    params = st.query_params
    if "code" in params:
        try:
            tokens = su.exchange_token(params["code"])
            st.session_state["tokens"] = tokens

            athlete = tokens.get("athlete", {})
            athlete_id = int(athlete.get("id"))
            prof_row = db.get_or_create_user(athlete_id)
            st.session_state["user_id"] = prof_row["id"]
            db.save_tokens(prof_row["id"], tokens)

            st.success("Strava connected & user created.")
        except Exception as e:
            st.error(f"Token exchange failed: {e}")

if "tokens" in st.session_state:
    st.sidebar.success("Strava connected.")
    if st.sidebar.button("Disconnect"):
        st.session_state.pop("tokens", None)
        st.session_state.pop("user_id", None)
        st.rerun()
else:
    st.sidebar.info("Connect your Strava account")
    su.connect_button()

def sync_recent_activities():
    if "tokens" not in st.session_state:
        st.warning("Connect Strava first.")
        return
    uid = ensure_profile()["user_id"]
    if uid.startswith("0000"):
        st.warning("No user profile yet — connect Strava first.")
        return
    try:
        access = st.session_state["tokens"]["access_token"]
        acts = su.list_activities(access_token=access, per_page=30, page=1)
        rows = []
        for a in acts:
            if a.get("type", "") not in ("Run", "TrailRun", "VirtualRun"):
                continue
            rows.append({
                "id": a["id"],
                "user_id": uid,
                "start_date_utc": a["start_date"],
                "name": a.get("name", "Run"),
                "distance_km": round(a.get("distance", 0)/1000.0, 3),
                "moving_time_s": a.get("moving_time", 0),
                "has_streams": False
            })
        if rows:
            try:
                db.upsert("activities", rows)
                st.success(f"Synced {len(rows)} activities into Supabase.")
            except Exception as e:
                st.warning(f"Could not write to Supabase ({e}). Showing data only in memory.")
        else:
            st.info("No recent runs found.")
    except Exception as e:
        st.error(f"Strava fetch failed: {e}")

if st.sidebar.button("Sync recent Strava"):
    sync_recent_activities()

# Navigation
view = st.sidebar.radio(
    "View",
    ["Dashboard", "Workloads & Zones", "VTS Profiles", "Plan & Targets"]
)

# ================== Views ==================

# ----- Dashboard -----
if view == "Dashboard":
    st.header("Dashboard")
    st.write("• Connect Strava, sync activities, compute CS/W′ and baseline VTS.")
    if st.button("Load ideal VTS CSV sample"):
        try:
            st.dataframe(load_ideal().head())
        except Exception as e:
            st.error(f"Could not load ideal CSV: {e}")

# ----- Workloads & Zones -----
elif view == "Workloads & Zones":
    st.header("Workloads & Zones")
    if "tokens" not in st.session_state:
        st.info("Connect Strava first.")
    else:
        access = st.session_state["tokens"]["access_token"]
        try:
            acts = su.list_activities(access, per_page=10)
        except Exception as e:
            st.error(f"Could not list activities: {e}")
            acts = []

        options = {
            f'{a["name"]} — {a["start_date"][:10]} ({round(a.get("distance",0)/1000,1)} km)': a
            for a in acts if a.get("type","") in ("Run","TrailRun","VirtualRun")
        }

        if not options:
            st.info("No recent runs. Hit 'Sync recent Strava' first.")
        else:
            choice = st.selectbox("Activity", list(options.keys()))
            a = options[choice]
            try:
                streams = su.get_streams(a["id"], access)
                df = etl.resample_to_1hz(streams)
                df = etl.compute_grade(df)
                bins = etl.bin30(df)
            except Exception as e:
                st.error(f"Failed to process streams: {e}")
                bins = pd.DataFrame()

            if not bins.empty:
                st.subheader("Bins (30s) preview")
                st.dataframe(bins.head(20))

                # Quick CS/W′ from best rolling windows
                def best_mean_speed(df, window):
                    x = df["v"].rolling(window, min_periods=window).mean().dropna()
                    if x.empty:
                        return None
                    return float(3.6 * x.max())

                pts = []
                for w in [180, 720, 1800]:
                    sp = best_mean_speed(df, w)
                    if sp:
                        pts.append((w, sp))

                if len(pts) >= 3:
                    cs_kmh, wprime_m = vts.estimate_cs_wprime(pts)
                    st.info(f"Estimated CS={cs_kmh:.2f} km/h, W′={int(wprime_m)} m")
                else:
                    cs_kmh, wprime_m = 12.0, 15000.0
                    st.warning("Not enough steady windows; using defaults (CS=12 km/h, W′=15000 m).")

                zt = etl.zone_table(bins, cs_kmh, ZONES)
                st.subheader("Zone aggregates")
                st.dataframe(zt)

                fig = px.bar(zt, x="zone", y="time_s", title="Time by zone (s)")
                st.plotly_chart(fig, use_container_width=True)

# ----- VTS Profiles -----
elif view == "VTS Profiles":
    st.header("VTS Profiles")
    st.write("Baseline VTS from CS/W′ plus modeled variants, with Ideal CSV overlay.")
    cs_kmh = st.number_input("CS (km/h)", value=12.0, step=0.1)
    wprime_m = st.number_input("W′ (m)", value=15000, step=100)

    base = vts.baseline_vts(cs_kmh, wprime_m)

    st.subheader("Volume deltas ΔTz (−0.5..+0.5)")
    cols = st.columns(5)
    deltas = {}
    for i, z in enumerate(["Z1","Z2","Z3","Z4","Z5"]):
        with cols[i]:
            deltas[z] = st.slider(z, -0.5, 0.5, 0.0, 0.05)

    vol = vts.modeled_vts_volume(base, deltas)
    dI = st.slider("ΔIglob (−0.10..+0.10)", -0.10, 0.10, 0.0, 0.01)
    vol_hrv = vts.apply_hrv_gain(vol, dI)

    # Personal curves (min)
    df_plot = pd.DataFrame({
        "v_kmh": base["v_kmh"],
        "Baseline": base["t_sec"] / 60.0,
        "Modeled (Volume)": vol["t_sec"] / 60.0,
        "Modeled (Volume + HR/V)": vol_hrv["t_sec"] / 60.0,
    })
    personal = df_plot.melt(id_vars="v_kmh", var_name="Curve", value_name="t_min")

    # Ideal overlay (if available)
    try:
        ideal = load_ideal().rename(columns={"speed_kmh": "v_kmh", "time_min": "t_min"})
        ideal["Curve"] = "Ideal"
        to_plot = pd.concat([personal, ideal], ignore_index=True)
    except Exception:
        to_plot = personal

    fig = px.line(to_plot, x="v_kmh", y="t_min", color="Curve",
                  title="VTS curves (time-to-exhaustion in minutes)")
    st.plotly_chart(fig, use_container_width=True)
    st.caption("Guards: time is capped for stability; modeled curves are clipped to ±25% vs baseline.")

# ----- Plan & Targets -----
elif view == "Plan & Targets":
    st.header("Plan & Targets")
    st.write("Simple weekly targets based on CS and your ideal curve (prototype).")
    cs_kmh = st.number_input("CS (km/h)", value=12.0, step=0.1, key="cs_plan")
    ideal = load_ideal()

    ref = pd.DataFrame({
        "zone": ["Z1","Z2","Z3","Z4","Z5"],
        "r_cs": [0.70, 0.85, 0.95, 1.02, 1.12]
    })
    ref["v_kmh"] = ref["r_cs"] * cs_kmh
    ref["t_opt_min"] = np.interp(ref["v_kmh"], ideal["speed_kmh"], ideal["time_min"])
    k = {"Z1": 2.2, "Z2": 1.6, "Z3": 1.0, "Z4": 0.5, "Z5": 0.25}
    ref["T_target_h"] = ref["zone"].map(k) * (ref["t_opt_min"] / 60.0)

    st.dataframe(ref[["zone", "v_kmh", "t_opt_min", "T_target_h"]])
    fig = px.bar(ref, x="zone", y="T_target_h", title="Weekly target time by zone (hours)")
    st.plotly_chart(fig, use_container_width=True)
