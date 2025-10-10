import os, time
import streamlit as st
import pandas as pd
import numpy as np
import altair as alt

from database import init_db, upsert_profile, get_profile, list_workouts, insert_workout, insert_hr_speed_points, get_hr_speed_points, upsert_token
from vts_model import compute_cs_wprime, zones_from_cs, personal_curve_from_ideal, optimal_time_for_speed
from processing import bin_1hz_to_30s
from models import fit_hr_v_linear, compute_fi, fi_summary
from acwr import weekly_aggregates_with_vflat, compute_acwr
from zone_optimum import weekly_zone_optimum
from strava_auth import oauth_link, exchange_code_for_token
from strava_ingest import fetch_activities, fetch_streams_for_activity, autofetch_streams_for_new_workouts

if "DATABASE_URL" in st.secrets:
    os.environ["DATABASE_URL"] = st.secrets["DATABASE_URL"]
STRAVA_CLIENT_ID = st.secrets.get("STRAVA_CLIENT_ID", "")
STRAVA_CLIENT_SECRET = st.secrets.get("STRAVA_CLIENT_SECRET", "")
STRAVA_REDIRECT_URI = st.secrets.get("STRAVA_REDIRECT_URI", "")

st.set_page_config(page_title="onFlows – VTS & Training Control", layout="wide")
st.title("onFlows – VTS & Training Control")

try:
    init_db()
except Exception as e:
    st.error(f"DB init error: {e}")

# Sidebar
st.sidebar.header("Profile")
athlete_key = st.sidebar.text_input("Athlete ID", value="demo_user")
hr_max = st.sidebar.number_input("HRmax (bpm)", min_value=80, max_value=230, value=190, step=1)
if st.sidebar.button("Save profile"):
    try:
        upsert_profile(athlete_key, int(hr_max))
        st.sidebar.success("Profile saved.")
    except Exception as e:
        st.sidebar.error(f"Save failed: {e}")
if st.sidebar.button("Load profile"):
    prof = get_profile(athlete_key)
    if prof:
        st.sidebar.success(f"Loaded HRmax={prof['hr_max']}")
    else:
        st.sidebar.info("No profile found.")

# 1) VTS
st.header("1) VTS (CS & W′), Zones, Personal Curve")
c1, c2, c3, c4 = st.columns(4)
with c1:
    d1 = st.number_input("3-min distance (m)", min_value=0.0, value=1200.0, step=10.0)
with c2:
    d2 = st.number_input("12-min distance (m)", min_value=0.0, value=3600.0, step=10.0)
with c3:
    t1 = st.number_input("t1 (s)", min_value=1.0, value=180.0, step=1.0)
with c4:
    t2 = st.number_input("t2 (s)", min_value=1.0, value=720.0, step=1.0)

if "cs" not in st.session_state:
    st.session_state["cs"] = None
if "personal_curve" not in st.session_state:
    st.session_state["personal_curve"] = None

if st.button("Compute CS & W′"):
    try:
        cs, w_prime = compute_cs_wprime(d1, t1, d2, t2)
        st.session_state["cs"] = cs
        st.success(f"CS = {cs:.2f} m/s | W′ = {w_prime:.0f} m")

        zdf = zones_from_cs(cs)
        def pace_fmt(x):
            if x is None or (isinstance(x, float) and np.isnan(x)):
                return ""
            m = int(x // 60); s = int(round(x - 60*m)); return f"{m:02d}:{s:02d} /km"
        zdf["min_pace"] = zdf["min_pace_s_per_km"].apply(pace_fmt)
        zdf["max_pace"] = zdf["max_pace_s_per_km"].apply(pace_fmt)
        st.dataframe(zdf[["zone","min_speed_mps","max_speed_mps","min_pace","max_pace"]], use_container_width=True)

        try:
            ideal = pd.read_csv("ideal_distance_time_speed.csv")
            if "time_s" not in ideal.columns or "speed_mps" not in ideal.columns:
                if {"time_min", "speed_kmh"}.issubset(ideal.columns):
                    ideal["time_s"] = ideal["time_min"] * 60.0
                    ideal["speed_mps"] = ideal["speed_kmh"] / 3.6
                else:
                    st.info("ideal_distance_time_speed.csv missing required columns.")
                    ideal = None
            if ideal is not None:
                ideal = ideal.sort_values("time_s").reset_index(drop=True)
                curv = personal_curve_from_ideal(ideal[["time_s","speed_mps"]], cs)
                chart_df = curv.melt(id_vars=["time_s"], value_vars=["speed_mps","speed_mps_personal"],
                                     var_name="series", value_name="speed_mps")
                st.altair_chart(
                    alt.Chart(chart_df).mark_line().encode(
                        x=alt.X("time_s:Q", title="Time (s)"),
                        y=alt.Y("speed_mps:Q", title="Speed (m/s)"),
                        color="series:N"
                    ).properties(height=300),
                    use_container_width=True
                )
                st.dataframe(curv.head(12), use_container_width=True)
                st.session_state["personal_curve"] = curv
        except Exception as e:
            st.warning(f"Curve error: {e}")
    except Exception as e:
        st.error(f"Error: {e}")

# 2) Workouts CSV
st.header("2) Workouts (CSV import)")
st.caption("Columns: start_time (ISO), duration_s, distance_m, avg_hr, avg_speed_mps, notes")
wcsv = st.file_uploader("Upload workouts CSV", type=["csv"], key="wcsv")
if wcsv is not None:
    try:
        wdf = pd.read_csv(wcsv)
        st.dataframe(wdf.head(10), use_container_width=True)
        if st.button("Insert workouts"):
            n_ok = 0
            for _, r in wdf.iterrows():
                try:
                    insert_workout(
                        athlete_key, str(r.get("start_time")), float(r.get("duration_s", 0)),
                        float(r.get("distance_m", 0)),
                        float(r["avg_hr"]) if pd.notna(r.get("avg_hr")) else None,
                        float(r["avg_speed_mps"]) if pd.notna(r.get("avg_speed_mps")) else None,
                        str(r.get("notes") or "")
                    ); n_ok += 1
                except Exception:
                    pass
            st.success(f"Inserted {n_ok} workouts.")
    except Exception as e:
        st.error(f"CSV error: {e}")

st.subheader("Recent workouts")
try:
    wks = list_workouts(athlete_key, limit=100)
    st.dataframe(pd.DataFrame(wks), use_container_width=True)
except Exception:
    st.info("No workouts or DB issue.")

# 3) 1 Hz CSV
st.header("3) 1 Hz Streams (CSV import)")
st.caption("Columns: time (ISO), velocity_smooth, grade_smooth, heartrate")
c1, c2 = st.columns([2,1])
with c1:
    scsv = st.file_uploader("Upload 1 Hz CSV", type=["csv"], key="scsv")
with c2:
    attach_wid = st.number_input("Attach to Workout ID", min_value=0, value=0, step=1)
if scsv is not None:
    try:
        sdf = pd.read_csv(scsv)
        bins = bin_1hz_to_30s(sdf)
        st.dataframe(bins.head(20), use_container_width=True)
        if st.button("Attach 30s bins to workout"):
            if attach_wid <= 0:
                st.error("Provide valid Workout ID.")
            else:
                pts = [{"t_bin_start": r["t_bin_start"], "mean_hr": float(r["mean_hr"]) if pd.notna(r["mean_hr"]) else None,
                        "mean_vflat": float(r["mean_vflat"]) if pd.notna(r["mean_vflat"]) else None}
                       for _, r in bins.iterrows()]
                try:
                    n = insert_hr_speed_points(int(attach_wid), pts)
                    st.success(f"Inserted {n} HR–V points.")
                except Exception as e:
                    st.error(f"Insert error: {e}")
    except Exception as e:
        st.error(f"1 Hz CSV error: {e}")

# 4) HR–V + Fitness Index (FI-based)
st.header("4) HR–V regression, FI & Fitness Index")
wid_for_hrv = st.number_input("Workout ID for HR–V analysis", min_value=0, value=0, step=1)
if st.button("Compute HR–V & FI"):
    try:
        pts = pd.DataFrame(get_hr_speed_points(int(wid_for_hrv))) if wid_for_hrv>0 else pd.DataFrame()
        if pts.empty:
            st.info("No HR–V points for this workout.")
        else:
            a, b = (0.0, 0.0)
            try:
                a, b = fit_hr_v_linear(pts.rename(columns={"mean_vflat":"mean_vflat","mean_hr":"mean_hr"}))
                st.success(f"HR = {a:.3f} * v_flat + {b:.1f}")
            except Exception as re:
                st.warning(f"Regression error: {re}")
            fi_df = compute_fi(pts.rename(columns={"mean_vflat":"mean_vflat","mean_hr":"mean_hr"}), a, b)
            st.dataframe(fi_df.head(20), use_container_width=True)
            s = fi_summary(fi_df)
            st.write(f"FI mean: {s['fi_mean']:.4f} (n={s['n']})")
            st.altair_chart(
                alt.Chart(fi_df).mark_circle().encode(
                    x=alt.X("mean_vflat:Q", title="v_flat (m/s)"),
                    y=alt.Y("mean_hr:Q", title="HR (bpm)"),
                    tooltip=["mean_vflat","mean_hr","fi"]
                ).properties(height=300),
                use_container_width=True
            )
    except Exception as e:
        st.error(f"HR–V error: {e}")

# 5) ACWR
st.header("5) Weekly Load & ACWR (v_flat-aware)")
cs_for_zoning = st.number_input("CS for zoning (m/s)", min_value=0.0, value=float(st.session_state.get("cs") or 4.44), step=0.01, key="cs_for_zoning")
if st.button("Compute weekly ACWR"):
    try:
        wks = list_workouts(athlete_key, limit=500)
        mean_vflat_map = {}
        for w in wks:
            if w.get("has_streams"):
                pts = pd.DataFrame(get_hr_speed_points(int(w["id"])))
                if not pts.empty and "mean_vflat" in pts.columns:
                    mv = float(pd.to_numeric(pts["mean_vflat"], errors="coerce").mean())
                    if np.isfinite(mv):
                        mean_vflat_map[int(w["id"])] = mv
        wagg = weekly_aggregates_with_vflat(wks, cs_for_zoning, mean_vflat_map)
        st.subheader("Weekly aggregates by zone (v_flat where available)")
        st.dataframe(wagg, use_container_width=True)
        acwr_df = compute_acwr(wagg)
        st.subheader("ACWR (time-based)")
        st.dataframe(acwr_df, use_container_width=True)
        if not acwr_df.empty:
            st.altair_chart(
                alt.Chart(acwr_df).mark_line().encode(
                    x=alt.X("week:N", sort=None, title="ISO Week"),
                    y=alt.Y("acwr:Q", title="ACWR")
                ).properties(height=300),
                use_container_width=True
            )
    except Exception as e:
        st.error(f"ACWR error: {e}")

# 6) Weekly Zone Optimum
st.header("6) Weekly 'Zone Optimum' (I_Z, I_total)")
k = st.number_input("k (e.g., 1.20 = 120% of optimum)", min_value=0.5, max_value=2.0, step=0.05, value=1.20)
cs_for_opt = st.number_input("CS for VTS (m/s)", min_value=0.0, value=float(st.session_state.get("cs") or 4.44), step=0.01, key="cs_for_opt")
if st.button("Compute Zone Optimum indices"):
    try:
        # Build personal curve
        try:
            ideal = pd.read_csv("ideal_distance_time_speed.csv")
            if "time_s" not in ideal.columns or "speed_mps" not in ideal.columns:
                if {"time_min", "speed_kmh"}.issubset(ideal.columns):
                    ideal["time_s"] = ideal["time_min"] * 60.0
                    ideal["speed_mps"] = ideal["speed_kmh"] / 3.6
                else:
                    st.info("ideal_distance_time_speed.csv missing required columns.")
                    ideal = None
        except Exception as e:
            ideal = None
            st.warning(f"Curve error: {e}")

        if ideal is None:
            st.error("Ideal curve file missing or invalid.")
        else:
            ideal = ideal.sort_values("time_s").reset_index(drop=True)
            personal = personal_curve_from_ideal(ideal[["time_s","speed_mps"]], cs_for_opt)
            # mean v_flat per workout
            wks = list_workouts(athlete_key, limit=500)
            mean_vflat_map = {}
            for w in wks:
                if w.get("has_streams"):
                    pts = pd.DataFrame(get_hr_speed_points(int(w["id"])))
                    if not pts.empty and "mean_vflat" in pts.columns:
                        mv = float(pd.to_numeric(pts["mean_vflat"], errors="coerce").mean())
                        if np.isfinite(mv):
                            mean_vflat_map[int(w["id"])] = mv
            detail, summ = weekly_zone_optimum(wks, cs_for_opt, personal, mean_vflat_map, k=k)
            st.subheader("Per-zone weekly deviation (I_Z)")
            st.dataframe(detail, use_container_width=True)
            st.subheader("Weekly total index (I_total = mean I_Z)")
            st.dataframe(summ, use_container_width=True)

            if not detail.empty:
                heat = alt.Chart(detail).mark_rect().encode(
                    x=alt.X("week:N", sort=None),
                    y=alt.Y("zone:N"),
                    color=alt.Color("IZ:Q", title="I_Z"),
                    tooltip=["week","zone","IZ","treal_min","ttarget_min","vbar_mps"]
                ).properties(height=240)
                st.altair_chart(heat, use_container_width=True)
                st.altair_chart(
                    alt.Chart(summ).mark_line(point=True).encode(
                        x=alt.X("week:N", sort=None, title="ISO Week"),
                        y=alt.Y("I_total:Q", title="I_total")
                    ).properties(height=300),
                    use_container_width=True
                )
    except Exception as e:
        st.error(f"Zone Optimum error: {e}")

# 7) Strava
st.header("7) Strava Sync")
if STRAVA_CLIENT_ID and STRAVA_REDIRECT_URI:
    st.markdown(f"[Connect Strava]({oauth_link(STRAVA_CLIENT_ID, STRAVA_REDIRECT_URI)})")
else:
    st.info("Set STRAVA_CLIENT_ID and STRAVA_REDIRECT_URI in secrets.")
code = st.text_input("Paste Strava OAuth 'code' after authorize")
if st.button("Exchange code for token"):
    try:
        js = exchange_code_for_token(STRAVA_CLIENT_ID, STRAVA_CLIENT_SECRET, code, STRAVA_REDIRECT_URI)
        upsert_token(athlete_key, str(js["athlete"]["id"]), js["access_token"], js["refresh_token"], int(js["expires_at"]))
        st.success("Token saved.")
    except Exception as e:
        st.error(f"OAuth error: {e}")

colA, colB, colC = st.columns(3)
with colA:
    after_days = st.number_input("Days back", min_value=1, max_value=3650, value=30, step=1)
with colB:
    before_days = st.number_input("Days forward", min_value=0, max_value=3650, value=0, step=1)
with colC:
    if st.button("Import Strava activities"):
        try:
            now = int(time.time())
            ids = fetch_activities(athlete_key, now - after_days*24*3600, now + before_days*24*3600,
                                   STRAVA_CLIENT_ID, STRAVA_CLIENT_SECRET)
            st.success(f"Imported/updated {len(ids)} activities.")
        except Exception as e:
            st.error(f"Import error: {e}")

limit = st.number_input("Fetch streams for last N workouts", min_value=1, max_value=500, value=50, step=1)
if st.button("Fetch streams"):
    try:
        c = autofetch_streams_for_new_workouts(athlete_key, int(limit), STRAVA_CLIENT_ID, STRAVA_CLIENT_SECRET)
        st.success(f"Updated {c} workouts with streams.")
    except Exception as e:
        st.error(f"Streams error: {e}")