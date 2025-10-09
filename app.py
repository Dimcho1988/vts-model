import streamlit as st
import pandas as pd
import numpy as np
import altair as alt
from datetime import datetime
import os

from . import vts_model, database as db, models, processing, acwr

st.set_page_config(page_title="onFlows – VTS & Training Control", layout="wide")
db.init_db()

st.sidebar.title("onFlows")
athlete_key = st.sidebar.text_input("Athlete ID", value="demo_user")
hr_max = st.sidebar.number_input("HRmax (bpm)", 100, 220, 190)
if st.sidebar.button("Save profile"):
    db.upsert_profile(athlete_key, int(hr_max))
    st.sidebar.success("Profile saved.")

st.title("Velocity–Time–Speed (VTS) and Training Control")

# Ideal curve
default_ideal_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "ideal_distance_time_speed.csv")
ideal_file = st.file_uploader("Upload *ideal* curve CSV (distance_m,time_s,speed_mps)", type=["csv"], key="ideal")
if ideal_file is not None:
    ideal_df = vts_model.load_ideal(ideal_file)
else:
    ideal_df = vts_model.load_ideal(default_ideal_path)

st.subheader("1) Ideal curve preview")
st.dataframe(ideal_df.head(20))

# Personalize
st.subheader("2) Personalize with two tests / optional % offsets")
colA, colB, colC = st.columns(3)
with colA:
    t1 = st.number_input("Test 1 time (s)", value=180, min_value=30)
    d1 = st.number_input("Test 1 distance (m)", value=900)
with colB:
    t2 = st.number_input("Test 2 time (s)", value=720, min_value=60)
    d2 = st.number_input("Test 2 distance (m)", value=3000)
with colC:
    dev_str = st.text_input("Offsets JSON (e.g. {60:-0.1, 600:-0.05})", value="")

cs_res = vts_model.fit_cs_wprime([(t1,d1),(t2,d2)])
st.info(f"CS = {cs_res.cs:.2f} m/s ({cs_res.cs*3.6:.2f} km/h) • W′ = {cs_res.w_prime:.0f} m")

percent_offsets = {}
if dev_str.strip():
    try:
        percent_offsets = {int(k): float(v) for k,v in eval(dev_str, {}, {}).items()}
    except Exception as e:
        st.warning(f"Invalid offsets JSON: {e}")
pers_df = vts_model.personalized_from_ideal(ideal_df, percent_offsets)

st.subheader("VTS curve")
line1 = alt.Chart(ideal_df).mark_line().encode(x="time_s", y=alt.Y("speed_mps", title="Speed (m/s)"), color=alt.value("#1f77b4"))
line2 = alt.Chart(pers_df).mark_line().encode(x="time_s", y="v_personal", color=alt.value("#2ca02c"))
st.altair_chart((line1 + line2).interactive(), use_container_width=True)

zones = vts_model.zones_from_cs(cs_res.cs)
st.subheader("3) Zones by speed")
zdf = pd.DataFrame([{"zone": z, "from_mps": a, "to_mps": b, "from_kmh": a*3.6, "to_kmh": b*3.6} for z,(a,b) in zones.items()])
st.dataframe(zdf)

# Workouts upload
st.subheader("4) Workouts (metadata)")
wk_file = st.file_uploader("CSV: start_time,duration_s,distance_m,avg_hr(optional),avg_speed_mps(optional),notes(optional)", type=["csv"], key="wkmeta")
if wk_file is not None and st.button("Import workouts"):
    wdf = pd.read_csv(wk_file)
    wdf["athlete_key"] = athlete_key
    wdf["start_time"] = pd.to_datetime(wdf["start_time"]).dt.tz_localize("UTC", nonexistent='shift_forward', ambiguous='NaT').astype(str)
    rows = wdf[["athlete_key","start_time","duration_s","distance_m","avg_hr","avg_speed_mps","notes"]].to_dict(orient="records")
    n = db.insert_workouts(rows)
    st.success(f"Imported {n} workouts.")

wk = db.fetch_workouts(athlete_key)
wk_df = pd.DataFrame(wk)
if not wk_df.empty:
    wk_df["start_time"] = pd.to_datetime(wk_df["start_time"])
st.dataframe(wk_df)

# 1 Hz
st.subheader("5) 1 Hz stream (optional)")
one_wid = st.selectbox("Workout ID to attach", wk_df["id"].tolist() if not wk_df.empty else [None])
hz_file = st.file_uploader("1 Hz CSV: timestamp, speed_mps, grade, hr(optional)", type=["csv"], key="hz")
if hz_file is not None and one_wid and st.button("Attach 1 Hz and build 30s HR–V"):
    hdf = pd.read_csv(hz_file)
    hdf["timestamp"] = pd.to_datetime(hdf["timestamp"])
    if "hr" not in hdf.columns: hdf["hr"] = np.nan
    binned = processing.bin_30s(hdf)
    rows = [dict(workout_id=int(one_wid),
                 t_bin_start=row.t_bin_start.isoformat(),
                 mean_hr=None if pd.isna(row.mean_hr) else float(row.mean_hr),
                 mean_vflat=float(row.mean_vflat)) for _,row in binned.iterrows()]
    db.insert_hr_points(rows)
    st.success(f"Attached {len(rows)} points.")

# HR–V & FI
st.subheader("6) HR–V & FI")
if not wk_df.empty:
    points = db.fetch_hr_points(wk_df["id"].tolist())
    hp = pd.DataFrame(points)
    if not hp.empty:
        a,b = models.fit_hr_v(hp["mean_vflat"].to_numpy(), hp["mean_hr"].to_numpy())
        st.write(f"a={a:.2f}, b={b:.2f}")
        hp["fi"] = models.fatigue_index(hp["mean_vflat"].to_numpy(), hp["mean_hr"].to_numpy(), a, b)
        st.line_chart(hp[["fi"]])
        st.write("CS* =", f"{models.cs_star(cs_res.cs, float(np.nanmean(hp['fi']))):.2f}", "m/s")
    else:
        st.info("No HR–V points yet.")
else:
    st.info("Import workouts to enable HR–V.")

# ACWR
st.subheader("7) ACWR by zones")
if not wk_df.empty:
    if "avg_speed_mps" in wk_df:
        wk_df["avg_speed_mps"] = wk_df["avg_speed_mps"].fillna(wk_df["distance_m"] / wk_df["duration_s"])
    else:
        wk_df["avg_speed_mps"] = wk_df["distance_m"] / wk_df["duration_s"]
    def zone_of(v):
        for z,(a,b) in zones.items():
            if a <= v < b: return z
        return 1 if v < zones[1][0] else 5
    wk_df["zone"] = wk_df["avg_speed_mps"].apply(zone_of)
    wk_df["date"] = wk_df["start_time"].dt.date
    wk_df["time_min"] = wk_df["duration_s"] / 60.0
    wk_df["distance_km"] = wk_df["distance_m"] / 1000.0

    ac = acwr.weekly_acwr(wk_df[["date","zone","time_min","distance_km"]])
    st.dataframe(ac.tail(12))
    if not ac.empty:
        total = ac[ac["zone"]==0]
        chart = alt.Chart(total).mark_line().encode(
            x="week_start:T", y=alt.Y("acwr:Q", scale=alt.Scale(domain=[0,2]))
        )
        st.altair_chart(chart, use_container_width=True)
else:
    st.info("Import workouts to compute ACWR.")


# ---- STRAVA ----
st.header("Strava Sync")
STRAVA_CLIENT_ID = st.secrets.get("STRAVA_CLIENT_ID", os.getenv("STRAVA_CLIENT_ID", ""))
STRAVA_CLIENT_SECRET = st.secrets.get("STRAVA_CLIENT_SECRET", os.getenv("STRAVA_CLIENT_SECRET", ""))
STRAVA_REDIRECT_URI = st.secrets.get("STRAVA_REDIRECT_URI", os.getenv("STRAVA_REDIRECT_URI", "http://localhost:8501"))

from .strava_auth import oauth_link, exchange_code_for_token
from . import strava_ingest as s_ing

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
    import pandas as pd
    if not d: return None
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
        n = s_ing.fetch_streams_for_activity(athlete_key, int(act_id or 0),
                                             client_id=STRAVA_CLIENT_ID, client_secret=STRAVA_CLIENT_SECRET,
                                             attach_workout_id=wk_df['id'].iloc[-1] if not wk_df.empty else None)
        st.success(f"Attached {n} HR–V points.")
    except Exception as e:
        st.error(f"Streams failed: {e}")
