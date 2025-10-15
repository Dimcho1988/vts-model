import os, json, math, time, io
import numpy as np, pandas as pd, plotly.express as px, streamlit as st
from datetime import datetime, timedelta, timezone

from utils import db
from utils import strava as su
from utils import etl as etl
from utils import vts as vts

st.set_page_config(page_title="onFlows — Running Load", layout="wide")

# --------- Helper config ---------
ZONES = {
    "Z1": (st.secrets["app"].get("z1_low",0.60), st.secrets["app"].get("z1_high",0.80)),
    "Z2": (st.secrets["app"].get("z2_low",0.80), st.secrets["app"].get("z2_high",0.90)),
    "Z3": (st.secrets["app"].get("z3_low",0.90), st.secrets["app"].get("z3_high",1.00)),
    "Z4": (st.secrets["app"].get("z4_low",1.00), st.secrets["app"].get("z4_high",1.05)),
    "Z5": (st.secrets["app"].get("z5_low",1.05), st.secrets["app"].get("z5_high",1.20)),
}

@st.cache_data
def load_ideal():
    return vts.load_ideal_csv("data/ideal_distance_time_speed.csv")

def zone_labels():
    return list(ZONES.keys())

# --------- Sidebar (Auth + Controls) ---------
st.sidebar.title("onFlows")
st.sidebar.caption("Control & Evaluation of Running Load")

if "tokens" not in st.session_state:
    params = st.query_params
    if "code" in params:
        try:
            tokens = su.exchange_token(params["code"])
            st.session_state["tokens"] = tokens

            # --- NEW: create/find user by Strava athlete id and store tokens
            athlete = tokens.get("athlete", {})  # Strava връща атлет в token payload
            athlete_id = athlete.get("id")
            prof_row = db.get_or_create_user(athlete_id, extra={
                # по желание можеш да пазиш малко метаданни
                # "created_at": datetime.now(timezone.utc).isoformat(),
            })
            st.session_state["user_id"] = prof_row["id"]
            db.save_tokens(prof_row["id"], tokens)

            st.success("Strava connected & user profile created.")
        except Exception as e:
            st.error(f"Token exchange failed: {e}")


# --------- Load / refresh activities ---------
def ensure_profile():
    if "user_id" in st.session_state:
        return {"user_id": st.session_state["user_id"]}
    # fallback за локални тестове (но вече няма да се ползва)
    return {"user_id": "00000000-0000-0000-0000-000000000000"}

def sync_recent_activities():
    """Fetch last 30 activities and store metadata in Supabase; fetch streams lazily when needed."""
    if "tokens" not in st.session_state: 
        st.warning("Connect Strava to sync activities")
        return
    access = st.session_state["tokens"]["access_token"]
    acts = su.list_activities(access_token=access, per_page=30, page=1)
    rows = []
    prof = ensure_profile()
    uid = prof["user_id"]
    for a in acts:
        rows.append({
            "id": a["id"],
            "user_id": uid,
            "start_date_utc": a["start_date"],
            "name": a.get("name","Run"),
            "distance_km": round(a.get("distance",0)/1000.0,3),
            "moving_time_s": a.get("moving_time",0),
            "has_streams": False
        })
    try:
        db.upsert("activities", rows)
        st.success(f"Synced {len(rows)} activities.")
    except Exception as e:
        st.warning(f"Could not write to Supabase yet ({e}). Showing data only in memory.")
    return rows

if st.sidebar.button("🔄 Sync recent Strava"):
    sync_recent_activities()

# --------- Tabs Logic ---------

if view == "Dashboard":
    st.header("Dashboard")
    st.write("• Connect Strava, sync activities, compute CS/W′ and baseline VTS.")
    if st.button("Load ideal VTS CSV sample"):
        st.dataframe(load_ideal().head())

elif view == "Workloads & Zones":
    st.header("Workloads & Zones")
    st.write("Pick one recent activity to compute 30s bins, v_flat, and zone stats.")
    if "tokens" not in st.session_state:
        st.info("Connect Strava first.")
    else:
        access = st.session_state["tokens"]["access_token"]
        acts = su.list_activities(access, per_page=10)
        options = {f'{a["name"]} — {a["start_date"][:10]} ({round(a["distance"]/1000,1)} km)': a for a in acts if a.get("type","") in ("Run","TrailRun","VirtualRun")}
        if options:
            choice = st.selectbox("Activity", list(options.keys()))
            a = options[choice]
            streams = su.get_streams(a["id"], access)
            df = etl.resample_to_1hz(streams)
            df = etl.compute_grade(df)
            bins = etl.bin30(df)
            st.subheader("Bins (30s) preview")
            st.dataframe(bins.head(20))
            # CS from previous section or quick estimate from best windows (rough MVP: use 3/12/30 min)
            # Find best mean vflat in windows
            def best_mean_speed(df, window):
                x = df["v"].rolling(window, min_periods=window).mean().dropna()
                if x.empty:
                    return None
                return float(3.6*x.max())
            pts = []
            for w in [180, 720, 1800]:
                sp = best_mean_speed(df, w)
                if sp:
                    pts.append((w, sp))
            if len(pts) >= 3:
                cs_kmh, wprime_m = vts.estimate_cs_wprime(pts)
                st.info(f"Estimated CS={cs_kmh:.2f} km/h, W'={int(wprime_m)} m")
            else:
                cs_kmh, wprime_m = 12.0, 15000.0
                st.warning("Not enough steady windows; using defaults (CS=12 km/h, W'=15000 m).")
            zt = etl.zone_table(bins, cs_kmh, ZONES)
            st.subheader("Zone aggregates")
            st.dataframe(zt)
            fig = px.bar(zt, x="zone", y="time_s", title="Time by zone (s)")
            st.plotly_chart(fig, use_container_width=True)

elif view == "VTS Profiles":
    st.header("VTS Profiles")
    st.write("Baseline VTS from CS/W′ plus modeled variants.")
    cs_kmh = st.number_input("CS (km/h)", value=12.0, step=0.1)
    wprime_m = st.number_input("W′ (m)", value=15000, step=100)
    base = vts.baseline_vts(cs_kmh, wprime_m)
    # Volume warp
    st.subheader("Volume deltas ΔTz (−0.5..+0.5)")
    cols = st.columns(5)
    deltas = {}
    for i, z in enumerate(["Z1","Z2","Z3","Z4","Z5"]):
        with cols[i]:
            deltas[z] = st.slider(z, -0.5, 0.5, 0.0, 0.05)
    vol = vts.modeled_vts_volume(base, deltas)
    # HR/V gain
    dI = st.slider("ΔIglob (−0.10..+0.10)", -0.10, 0.10, 0.0, 0.01)
    vol_hrv = vts.apply_hrv_gain(vol, dI)
    df_plot = pd.DataFrame({
        "v_kmh": base["v_kmh"],
        "Baseline": base["t_sec"]/60,
        "Modeled (Volume)": vol["t_sec"]/60,
        "Modeled (Volume + HR/V)": vol_hrv["t_sec"]/60,
    })
    df_melt = df_plot.melt(id_vars="v_kmh", var_name="Curve", value_name="t_min")
    fig = px.line(df_melt, x="v_kmh", y="t_min", color="Curve", title="VTS curves (time-to-exhaustion in minutes)")
    st.plotly_chart(fig, use_container_width=True)
    st.caption("Guards: the model caps changes to ±20–25% vs baseline per speed.")

elif view == "Plan & Targets":
    st.header("Plan & Targets")
    st.write("Simple weekly targets based on CS and ideal curve (prototype).")
    cs_kmh = st.number_input("CS (km/h)", value=12.0, step=0.1, key="cs_plan")
    ideal = load_ideal()
    # Reference speeds around the center of each zone
    ref = pd.DataFrame({
        "zone": ["Z1","Z2","Z3","Z4","Z5"],
        "r_cs": [0.70,0.85,0.95,1.02,1.12]
    })
    ref["v_kmh"] = ref["r_cs"]*cs_kmh
    ref["t_opt_min"] = np.interp(ref["v_kmh"], ideal["speed_kmh"], ideal["time_min"])
    k = {"Z1":2.2, "Z2":1.6, "Z3":1.0, "Z4":0.5, "Z5":0.25}
    ref["T_target_h"] = ref["zone"].map(k) * (ref["t_opt_min"]/60.0)
    st.dataframe(ref[["zone","v_kmh","t_opt_min","T_target_h"]])
    fig = px.bar(ref, x="zone", y="T_target_h", title="Weekly target time by zone (hours)")
    st.plotly_chart(fig, use_container_width=True)
