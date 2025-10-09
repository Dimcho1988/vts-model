import os
import streamlit as st
import pandas as pd
import numpy as np
import altair as alt
from datetime import datetime

# импорти за нашите модули (всички файлове са в корена)
import vts_model
import database as db
import models
import processing
import acwr
from strava_auth import oauth_link, exchange_code_for_token
import strava_ingest as s_ing

st.set_page_config(page_title="onFlows – VTS & Training Control", layout="wide")

# >>> НОВО: инициализация на БД (създава таблици за SQLite; за Postgres/Supabase очаква изпълнен schema.sql)
try:
    db.init_db()
except Exception as e:
    st.sidebar.warning(f"DB init notice: {e}")

# ----------------------- НАСТРОЙКИ/ПРОФИЛ -----------------------
st.sidebar.title("onFlows")
athlete_key = st.sidebar.text_input("Athlete ID", value="demo_user")
hr_max = st.sidebar.number_input("HRmax (bpm)", min_value=100, max_value=220, value=190)
if st.sidebar.button("Save profile"):
    try:
        db.upsert_profile(athlete_key, int(hr_max))
        st.sidebar.success("Profile saved.")
    except Exception as e:
        st.sidebar.error(f"DB error: {e}")

st.title("Velocity–Time–Speed (VTS) Model & Training Control")

# ----------------------- ИДЕАЛНА КРИВА -----------------------
default_ideal_path = os.path.join(os.path.dirname(__file__), "ideal_distance_time_speed.csv")

st.subheader("Ideal Distance–Time–Speed curve")
try:
    ideal_raw = pd.read_csv(default_ideal_path)
except Exception as e:
    st.error(f"Couldn't load ideal curve CSV: {e}")
    st.stop()

ideal_df = vts_model._normalize_ideal(ideal_raw)
st.dataframe(ideal_raw.head(), use_container_width=True)

# ----------------------- ПЕРСОНАЛИЗАЦИЯ -----------------------
st.subheader("Create personalized VTS curve")
c1, c2 = st.columns(2)
dist_3min = c1.number_input("Distance in 3-min test (m)", min_value=200, max_value=3000, value=1202)
dist_12min = c2.number_input("Distance in 12-min test (m)", min_value=1000, max_value=8000, value=3600)

cs, w_prime = vts_model.compute_cs(dist_3min, dist_12min, t1=180, t2=720)
st.markdown(f"**Critical Speed (CS):** {cs:.2f} m/s  **W′:** {w_prime:.2f} m")

personal_df = vts_model.build_personal_curve(ideal_df, cs)

st.subheader("VTS curve (Ideal vs Personalized)")
if not ideal_df.empty and not personal_df.empty:
    chart = (
        alt.Chart(ideal_df).mark_line().encode(
            x=alt.X("time_s:Q", title="Time (s)"),
            y=alt.Y("speed_mps:Q", title="Speed (m/s)"),
            color=alt.value("#888"),
            tooltip=["time_s","speed_mps"]
        )
        + alt.Chart(personal_df).mark_line().encode(
            x="time_s:Q",
            y="speed_mps:Q",
            color=alt.value("#f39c12"),
            tooltip=["time_s","speed_mps"]
        )
    ).properties(height=320).interactive()
    st.altair_chart(chart, use_container_width=True)
else:
    st.info("Ideal or personal curve is empty.")

st.subheader("Zones by speed (from CS)")
zones_df = vts_model.compute_zones(cs)
st.dataframe(zones_df, use_container_width=True)

# ----------------------- ИМПОРТ НА ТРЕНИРОВКИ -----------------------
st.subheader("Workouts: import CSV")
wk_file = st.file_uploader(
    "CSV with columns: start_time, duration_s, distance_m, avg_hr(optional), avg_speed_mps(optional), notes(optional)",
    type=["csv"],
    key="wkmeta",
)
if wk_file is not None and st.button("Import workouts"):
    try:
        wdf = pd.read_csv(wk_file)
        wdf["athlete_key"] = athlete_key
        wdf["start_time"] = pd.to_datetime(wdf["start_time"]).dt.tz_localize("UTC", nonexistent="shift_forward", ambiguous="NaT").astype(str)
        rows = wdf[["athlete_key","start_time","duration_s","distance_m","avg_hr","avg_speed_mps","notes"]].to_dict(orient="records")
        n = db.insert_workouts(rows)
        st.success(f"Imported {n} workouts.")
    except Exception as e:
        st.error(f"Import failed: {e}")

wk = db.fetch_workouts(athlete_key)
wk_df = pd.DataFrame(wk)
if not wk_df.empty:
    wk_df["start_time"] = pd.to_datetime(wk_df["start_time"])
st.dataframe(wk_df, use_container_width=True)

# ----------------------- 1 Hz СТРИЙМ → 30 s HR–V -----------------------
st.subheader("1 Hz stream (optional) → 30s HR–V")
one_wid = st.selectbox("Attach to workout ID", wk_df["id"].tolist() if not wk_df.empty else [None])
hz_file = st.file_uploader("Upload 1 Hz CSV (timestamp, speed_mps, grade, hr)", type=["csv"], key="hz")
if hz_file is not None and one_wid and st.button("Attach 1 Hz and build 30s HR–V"):
    try:
        hdf = pd.read_csv(hz_file)
        hdf["timestamp"] = pd.to_datetime(hdf["timestamp"])
        if "hr" not in hdf.columns: hdf["hr"] = np.nan
        binned = processing.bin_30s(hdf)
        rows = [dict(workout_id=int(one_wid),
                     t_bin_start=row.t_bin_start.isoformat(),
                     mean_hr=None if pd.isna(row.mean_hr) else float(row.mean_hr),
                     mean_vflat=float(row.mean_vflat)) for _,row in binned.iterrows()]
        ins = db.insert_hr_points(rows)
        st.success(f"Attached {ins} HR–V points.")
    except Exception as e:
        st.error(f"1 Hz attach failed: {e}")

# ----------------------- HR–V & FI -----------------------
st.subheader("HR–V regression & Fatigue Index")
if not wk_df.empty:
    pts = db.fetch_hr_points(wk_df["id"].tolist())
    hp = pd.DataFrame(pts)
    if not hp.empty:
        a, b = models.fit_hr_v(hp["mean_vflat"].to_numpy(), hp["mean_hr"].to_numpy())
        st.write(f"a={a:.2f}, b={b:.2f}")
        hp["fi"] = models.fatigue_index(hp["mean_vflat"].to_numpy(), hp["mean_hr"].to_numpy(), a, b)
        st.line_chart(hp[["fi"]])
        st.caption(f"CS* ≈ {models.cs_star(cs, float(np.nanmean(hp['fi']))):.2f} m/s")
    else:
        st.info("No HR–V points yet.")
else:
    st.info("Import workouts to enable HR–V analysis.")

# ----------------------- ACWR -----------------------
st.subheader("ACWR (weekly)")
if not wk_df.empty:
    if "avg_speed_mps" in wk_df:
        wk_df["avg_speed_mps"] = wk_df["avg_speed_mps"].fillna(wk_df["distance_m"] / wk_df["duration_s"])
    else:
        wk_df["avg_speed_mps"] = wk_df["distance_m"] / wk_df["duration_s"]
    def zone_of(v):
        for z,(a,b) in {z:(float(row.from_mps), float(row.to_mps)) for z,row in zones_df.set_index('zone').iterrows()}.items():
            if a <= v < b: return z
        return 1 if v < zones_df.iloc[0]["from_mps"] else 5
    wk_df["zone"] = wk_df["avg_speed_mps"].apply(zone_of)
    wk_df["date"] = wk_df["start_time"].dt.date
    wk_df["time_min"] = wk_df["duration_s"] / 60.0
    wk_df["distance_km"] = wk_df["distance_m"] / 1000.0

    ac = acwr.weekly_acwr(wk_df[["date","zone","time_min","distance_km"]])
    st.dataframe(ac.tail(12), use_container_width=True)
    if not ac.empty:
        total = ac[ac["zone"]==0]
        ch = alt.Chart(total).mark_line().encode(x="week_start:T", y=alt.Y("acwr:Q", scale=alt.Scale(domain=[0,2])))
        st.altair_chart(ch, use_container_width=True)
else:
    st.info("Import workouts to compute ACWR.")

# ----------------------- STRAVA SYNC -----------------------
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
       js = exchange_code_for_token(STRAVA_CLIENT_ID, STRAVA_CLIENT_SECRET, code, STRAVA_REDIRECT_URI)
        sid = js["athlete"]["id"]
        db.upsert_token(athlete_key, sid, js["access_token"], js["refresh_token"], js["expires_at"])
        st.success(f"Linked athlete {sid}.")
    except Exception as e:
        st.error(f"Failed: {e}")

c1, c2 = st.columns(2)
after = c1.date_input("After (optional)")
before = c2.date_input("Before (optional)")

def to_ts(d):
    if not d: return None
    return int(pd.Timestamp(d).tz_localize("UTC").timestamp())

if st.button("Import Strava activities"):
    try:
        ids = s_ing.fetch_activities(athlete_key, after_ts=to_ts(after), before_ts=to_ts(before),
                                     client_id=STRAVA_CLIENT_ID, client_secret=STRAVA_CLIENT_SECRET)
        st.success(f"Imported {len(ids)} activities.")
    except Exception as e:
        st.error(f"Import failed: {e}")

act_id = st.text_input("Strava activity id (for 1 Hz fetch)", value="")
if st.button("Fetch 1 Hz for activity"):
    try:
        wk_df2 = pd.DataFrame(db.fetch_workouts(athlete_key))
        n = s_ing.fetch_streams_for_activity(
            athlete_key,
            int(act_id or 0),
            client_id=STRAVA_CLIENT_ID,
            client_secret=STRAVA_CLIENT_SECRET,
            attach_workout_id=wk_df2["id"].iloc[-1] if not wk_df2.empty else None
        )
        st.success(f"Attached {n} HR–V 30s points.")
    except Exception as e:
        st.error(f"Streams failed: {e}")

