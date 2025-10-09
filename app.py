import streamlit as st
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import os
from datetime import datetime

# --- Импорти (адаптирани за структура без app/ папка)
import vts_model
import database as db
import models
import processing
import acwr
from strava_auth import oauth_link, exchange_code_for_token
import strava_ingest as s_ing

st.set_page_config(page_title="onFlows – VTS Model", layout="wide")

# --- Инициализация ---
st.title("onFlows – Velocity–Time–Speed (VTS) Model")

athlete_key = st.text_input("Athlete key (e.g., email or name)", value="user1")
hrmax = st.number_input("Max HR", min_value=100, max_value=220, value=190)

# --- Зареждане на идеална крива ---
default_ideal_path = os.path.join(os.path.dirname(__file__), "ideal_distance_time_speed.csv")
ideal_df = pd.read_csv(default_ideal_path)

st.subheader("Ideal Distance–Time–Speed curve")
st.dataframe(ideal_df.head())

# --- Персонализиране на крива ---
st.subheader("Create personalized VTS curve")
col1, col2 = st.columns(2)
dist_3min = col1.number_input("Distance in 3-min test (m)", min_value=500, max_value=2000, value=1200)
dist_12min = col2.number_input("Distance in 12-min test (m)", min_value=1500, max_value=6000, value=3600)

cs, w_prime = vts_model.compute_cs(dist_3min, dist_12min, t1=180, t2=720)
st.markdown(f"**Critical Speed (CS):** {cs:.2f} m/s  **W′:** {w_prime:.2f} J/kg")

personal_df = vts_model.build_personal_curve(ideal_df, cs)
fig, ax = plt.subplots()
ax.plot(ideal_df["time_s"], ideal_df["speed_mps"], label="Ideal", color="gray")
ax.plot(personal_df["time_s"], personal_df["speed_mps"], label="Personalized", color="orange")
ax.set_xlabel("Time (s)")
ax.set_ylabel("Speed (m/s)")
ax.legend()
st.pyplot(fig)

# --- Зони на натоварване ---
zones = vts_model.compute_zones(cs)
st.subheader("Training Zones")
st.dataframe(zones)

# --- Импорт на тренировки (CSV) ---
st.subheader("Import workouts CSV")
uploaded = st.file_uploader("Upload workouts.csv", type=["csv"])
if uploaded:
    workouts_df = pd.read_csv(uploaded)
    db.insert_workouts(workouts_df.to_dict("records"))
    st.success(f"Inserted {len(workouts_df)} workouts into DB.")

# --- Импорт на 1 Hz стрийм ---
st.subheader("Import 1 Hz data")
stream_file = st.file_uploader("Upload 1Hz stream CSV", type=["csv"])
if stream_file:
    df = pd.read_csv(stream_file)
    df_binned = processing.bin_30s(df)
    st.write(df_binned.head())

# --- HR–V регресия и Fatigue Index ---
st.subheader("HR–V Regression and Fatigue Index (FI)")
points = db.fetch_hr_points(athlete_key)
if points:
    dfp = pd.DataFrame(points)
    res = models.hr_v_regression(dfp)
    st.write(res)
    fig2, ax2 = plt.subplots()
    ax2.scatter(dfp["mean_vflat"], dfp["mean_hr"], s=8, alpha=0.6)
    xline = np.linspace(dfp["mean_vflat"].min(), dfp["mean_vflat"].max(), 100)
    ax2.plot(xline, res["a"] * xline + res["b"], color="red")
    ax2.set_xlabel("Speed (v_flat, m/s)")
    ax2.set_ylabel("HR (bpm)")
    st.pyplot(fig2)
else:
    st.info("No HR–V data yet.")

# --- ACWR ---
st.subheader("Acute:Chronic Workload Ratio (ACWR)")
acwr_df = acwr.compute_acwr(athlete_key)
st.dataframe(acwr_df)

# --- STRAVA СЕКЦИЯ ---
st.header("Strava Sync")

STRAVA_CLIENT_ID = st.secrets.get("STRAVA_CLIENT_ID", os.getenv("STRAVA_CLIENT_ID", ""))
STRAVA_CLIENT_SECRET = st.secrets.get("STRAVA_CLIENT_SECRET", os.getenv("STRAVA_CLIENT_SECRET", ""))
STRAVA_REDIRECT_URI = st.secrets.get("STRAVA_REDIRECT_URI", os.getenv("STRAVA_REDIRECT_URI", "http://localhost:8501"))

if STRAVA_CLIENT_ID and STRAVA_CLIENT_SECRET and STRAVA_REDIRECT_URI:
    st.markdown(f"[Connect Strava]({oauth_link(STRAVA_CLIENT_ID, STRAVA_REDIRECT_URI, scope='read,activity:read_all')})")
else:
    st.warning("Set STRAVA_CLIENT_ID / STRAVA_CLIENT_SECRET / STRAVA_REDIRECT_URI in secrets or env.")

code = st.text_input("Paste ?code=... from Strava (first-time link)", value="")
if st.button("Link Strava"):
    try:
        js = exchange_code_for_token(STRAVA_CLIENT_ID, STRAVA_CLIENT_SECRET, code)
        sid = js["athlete"]["id"]
        db.upsert_token(athlete_key, sid, js["access_token"], js["refresh_token"], js["expires_at"])
        st.success(f"Linked athlete {sid}.")
    except Exception as e:
        st.error(f"Failed: {e}")

col1, col2 = st.columns(2)
after = col1.date_input("After (optional)")
before = col2.date_input("Before (optional)")

def to_ts(d):
    if not d:
        return None
    return int(pd.Timestamp(d).tz_localize("UTC").timestamp())

if st.button("Import Strava activities"):
    try:
        ids = s_ing.fetch_activities(athlete_key, after_ts=to_ts(after), before_ts=to_ts(before),
                                     client_id=STRAVA_CLIENT_ID, client_secret=STRAVA_CLIENT_SECRET)
        st.success(f"Imported {len(ids)}.")
    except Exception as e:
        st.error(f"Import failed: {e}")

act_id = st.text_input("Strava activity id (for 1 Hz fetch)", value="")
if st.button("Fetch 1 Hz for activity"):
    try:
        wk_df = pd.DataFrame(db.fetch_workouts(athlete_key))
        n = s_ing.fetch_streams_for_activity(
            athlete_key,
            int(act_id or 0),
            client_id=STRAVA_CLIENT_ID,
            client_secret=STRAVA_CLIENT_SECRET,
            attach_workout_id=wk_df["id"].iloc[-1] if not wk_df.empty else None
        )
        st.success(f"Attached {n} HR–V points.")
    except Exception as e:
        st.error(f"Streams failed: {e}")
