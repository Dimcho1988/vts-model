import os
import numpy as np
import pandas as pd
import altair as alt
import streamlit as st

# наши модули
import vts_model
import models
import processing
import acwr
import database as db

from strava_auth import oauth_link, exchange_code_for_token
import strava_ingest as s_ing

st.set_page_config(page_title="onFlows – VTS & Training Control", layout="wide")

# ---------- DB init ----------
try:
    db.init_db()
except Exception as e:
    st.sidebar.warning(f"DB init: {e}")

# ---------- Sidebar / Profile ----------
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

# ---------- Ideal curve ----------
st.subheader("Ideal Distance–Time–Speed curve")
default_ideal_path = os.path.join(os.path.dirname(__file__), "ideal_distance_time_speed.csv")
try:
    ideal_raw = pd.read_csv(default_ideal_path)
except Exception as e:
    st.error(f"Couldn't load ideal curve CSV: {e}")
    st.stop()
ideal_df = vts_model._normalize_ideal(ideal_raw)
st.dataframe(ideal_raw.head(), use_container_width=True)

# ---------- Personalization ----------
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

# ---------- Workouts CSV import ----------
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
        wdf["start_time"] = pd.to_datetime(wdf["start_time"]).dt.tz_localize(
            "UTC", nonexistent="shift_forward", ambiguous="NaT"
        ).astype(str)
        rows = wdf[[
            "athlete_key","start_time","duration_s","distance_m","avg_hr","avg_speed_mps","notes"
        ]].to_dict(orient="records")
        n = db.insert_workouts(rows)
        st.success(f"Imported {n} workouts.")
    except Exception as e:
        st.error(f"Import failed: {e}")

wk = db.fetch_workouts(athlete_key)
wk_df = pd.DataFrame(wk)
if not wk_df.empty:
    wk_df["start_time"] = pd.to_datetime(wk_df["start_time"])
st.dataframe(wk_df, use_container_width=True)

# ---------- Optional 1 Hz upload → 30s HR–V ----------
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

# ---------- HR–V regression ----------
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

# ---------- ACWR ----------
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
    st.dataframe(ac.sort_values("week_start").tail(12), use_container_width=True)
    if not ac.empty:
        total = ac[ac["zone"] == 0].copy().sort_values("week_start")
        try:
            cutoff = pd.Timestamp.utcnow().tz_localize("UTC") - pd.Timedelta(days=365)
            total = total[total["week_start"] >= cutoff]
        except Exception:
            pass
        chart = (
            alt.Chart(total).mark_line().encode(
                x=alt.X("week_start:T", title="Week start", axis=alt.Axis(format="%Y-%m-%d")),
                y=alt.Y("acwr:Q", title="ACWR", scale=alt.Scale(domain=[0,2])),
                tooltip=[alt.Tooltip("week_start:T", format="%Y-%m-%d"), alt.Tooltip("acwr:Q", format=".2f")]
            ).properties(height=320)
        )
        st.altair_chart(chart, use_container_width=True)
else:
    st.info("Import workouts to compute ACWR.")

# ---------- Load by zones + v_flat trend ----------
st.subheader("Load by zones (time, distance, avg speed)")
wk_base = wk_df.copy()
if not wk_base.empty:
    wk_base["avg_speed_mps"] = wk_base.get("avg_speed_mps", wk_base["distance_m"] / wk_base["duration_s"])
    points = pd.DataFrame(db.fetch_hr_points(wk_base["id"].tolist()))
    have_vflat = False
    if not points.empty and "mean_vflat" in points.columns:
        have_vflat = True
        pts_agg = points.groupby("workout_id", as_index=False)["mean_vflat"].mean()
        wk_base = wk_base.merge(pts_agg.rename(columns={"mean_vflat": "vflat_mps"}),
                                left_on="id", right_on="workout_id", how="left")
        wk_base["work_speed_mps"] = wk_base["vflat_mps"].fillna(wk_base["avg_speed_mps"])
    else:
        wk_base["work_speed_mps"] = wk_base["avg_speed_mps"]

    def zone_of_speed(v):
        for z,(a,b) in {z:(float(r.from_mps), float(r.to_mps)) for z,r in zones_df.set_index("zone").iterrows()}.items():
            if a <= v < b: return z
        return 1 if v < zones_df.iloc[0]["from_mps"] else 5

    wk_base["zone"] = wk_base["work_speed_mps"].apply(zone_of_speed)
    wk_base["time_min"] = wk_base["duration_s"] / 60.0
    wk_base["distance_km"] = wk_base["distance_m"] / 1000.0

    zone_summary = (
        wk_base.groupby("zone", as_index=False)
        .agg(time_min=("time_min","sum"),
             distance_km=("distance_km","sum"),
             sessions=("id","count"),
             avg_speed_mps=("work_speed_mps","mean"))
        .sort_values("zone")
    )
    zone_summary["avg_speed_kmh"] = zone_summary["avg_speed_mps"] * 3.6
    st.dataframe(zone_summary[["zone","sessions","time_min","distance_km","avg_speed_kmh"]],
                 use_container_width=True)

    st.subheader("Equalized speed (v_flat) trend")
    try:
        trend_df = wk_base[["start_time","work_speed_mps"]].copy()
        trend_df["start_time"] = pd.to_datetime(trend_df["start_time"])
        trend_df = trend_df.sort_values("start_time")
        trend_df["week_start"] = trend_df["start_time"].dt.to_period("W").apply(lambda p: p.start_time)
        t_week = trend_df.groupby("week_start", as_index=False)["work_speed_mps"].mean()
        chart2 = (
            alt.Chart(t_week).mark_line().encode(
                x=alt.X("week_start:T", title="Week"),
                y=alt.Y("work_speed_mps:Q", title=("v_flat (m/s)" if have_vflat else "avg speed (m/s)"))
            ).properties(height=280)
        )
        st.altair_chart(chart2, use_container_width=True)
    except Exception as e:
        st.info(f"No data for speed trend yet. {e}")

# ---------- Strava Sync ----------
st.header("Strava Sync")
STRAVA_CLIENT_ID = st.secrets.get("STRAVA_CLIENT_ID", os.getenv("STRAVA_CLIENT_ID", ""))
STRAVA_CLIENT_SECRET = st.secrets.get("STRAVA_CLIENT_SECRET", os.getenv("STRAVA_CLIENT_SECRET", ""))
STRAVA_REDIRECT_URI = st.secrets.get("STRAVA_REDIRECT_URI", os.getenv("STRAVA_REDIRECT_URI", ""))

if not STRAVA_CLIENT_ID or not STRAVA_CLIENT_SECRET or not STRAVA_REDIRECT_URI:
    st.warning("Set STRAVA_CLIENT_ID / STRAVA_CLIENT_SECRET / STRAVA_REDIRECT_URI in Secrets.")
else:
    st.markdown(f"[Connect Strava]({oauth_link(STRAVA_CLIENT_ID, STRAVA_REDIRECT_URI, scope='read,activity:read_all')})")

# авто-link от ?code=
try:
    try:
        qp = st.query_params
        if hasattr(qp, "to_dict"):
            qp = qp.to_dict()
    except Exception:
        qp = st.experimental_get_query_params()

    code_from_url = None
    if isinstance(qp, dict) and "code" in qp:
        v = qp["code"]
        code_from_url = v[0] if isinstance(v, list) else v

    if code_from_url and not st.session_state.get("strava_linked_ok"):
        try:
            js = exchange_code_for_token(
                STRAVA_CLIENT_ID, STRAVA_CLIENT_SECRET, code_from_url, STRAVA_REDIRECT_URI
            )
            sid = js["athlete"]["id"]
            db.upsert_token(
                athlete_key=athlete_key,
                strava_athlete_id=sid,
                access_token=js["access_token"],
                refresh_token=js["refresh_token"],
                expires_at=js["expires_at"],
            )
            st.session_state["strava_linked_ok"] = True
            st.success(f"Linked athlete {sid}.")
            try:
                st.experimental_set_query_params()
            except Exception:
                pass

            # авто-импорт последните 180 дни + авто 1 Hz
            try:
                days = 180
                after_ts = int((pd.Timestamp.utcnow() - pd.Timedelta(days=days))
                               .tz_localize("UTC").timestamp())
                ids = s_ing.fetch_activities(
                    athlete_key, after_ts=after_ts, before_ts=None,
                    client_id=STRAVA_CLIENT_ID, client_secret=STRAVA_CLIENT_SECRET
                )
                fetched = s_ing.autofetch_streams_for_new_workouts(
                    athlete_key, client_id=STRAVA_CLIENT_ID,
                    client_secret=STRAVA_CLIENT_SECRET, limit=10
                )
                st.info(f"Auto-imported {len(ids)} acts, auto 1 Hz for {fetched}.")
            except Exception as imp_e:
                st.warning(f"Linked OK, auto-import skipped: {imp_e}")

        except Exception as link_e:
            st.error(f"Strava linking failed: {link_e}")
except Exception as autolink_e:
    st.warning(f"Auto-link note: {autolink_e}")

# ръчен импорт
c1, c2 = st.columns(2)
after = c1.date_input("After (optional)")
before = c2.date_input("Before (optional)")

def to_ts(d):
    if not d: return None
    return int(pd.Timestamp(d).tz_localize("UTC").timestamp())

aft = to_ts(after)
bef = to_ts(before)
now_ts = int(pd.Timestamp.utcnow().tz_localize("UTC").timestamp())
if aft and bef and aft > bef:  # размяна ако са обърнати
    aft, bef = bef, aft
if aft and aft > now_ts:  # бъдеща дата → игнор
    aft = None

if st.button("Import Strava activities"):
    try:
        ids = s_ing.fetch_activities(
            athlete_key, after_ts=aft, before_ts=bef,
            client_id=STRAVA_CLIENT_ID, client_secret=STRAVA_CLIENT_SECRET
        )
        fetched = s_ing.autofetch_streams_for_new_workouts(
            athlete_key, client_id=STRAVA_CLIENT_ID,
            client_secret=STRAVA_CLIENT_SECRET, limit=10
        )
        st.success(f"Imported {len(ids)} activities. Fetched 1 Hz for {fetched} workouts.")
    except Exception as e:
        st.error(f"Import failed: {e}")

act_id = st.text_input("Strava activity id (for 1 Hz fetch)", value="")
if st.button("Fetch 1 Hz for activity"):
    try:
        wk_df2 = pd.DataFrame(db.fetch_workouts(athlete_key))
        n = s_ing.fetch_streams_for_activity(
            athlete_key, int(act_id or 0),
            client_id=STRAVA_CLIENT_ID, client_secret=STRAVA_CLIENT_SECRET,
            attach_workout_id=wk_df2["id"].iloc[-1] if not wk_df2.empty else None,
        )
        st.success(f"Attached {n} HR–V 30s points.")
    except Exception as e:
        st.error(f"Streams failed: {e}")

if st.button("Fetch 1 Hz for missing workouts"):
    try:
        n = s_ing.autofetch_streams_for_new_workouts(
            athlete_key, client_id=STRAVA_CLIENT_ID,
            client_secret=STRAVA_CLIENT_SECRET, limit=50
        )
        st.success(f"Fetched 1 Hz for {n} workouts.")
    except Exception as e:
        st.error(f"{e}")
