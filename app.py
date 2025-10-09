
import os, json
import numpy as np
import pandas as pd
import streamlit as st
import altair as alt
from datetime import datetime

from app.database import init_schema, fetch_all, fetch_one, execute
from app.profiles import get_profile, upsert_profile, DEFAULT_SPEED_ZONES
from app.vts_model import VTSCurve
from app.processing import compute_v_flat
from app.models import weighted_linreg_v_hr, fatigue_index_for_workout
from app.strava_oauth import auth_link, exchange_token, refresh_token
from app.strava_api import get_athlete, list_activities, get_streams
from app.acwr import compute_acwr

st.set_page_config(page_title="onFlows VTS + Strava", layout="wide")
st.title("onFlows • VTS модел + Strava интеграция")

try:
    init_schema()
except Exception as e:
    st.warning(f"DB schema init failed: {e}")

if "tokens" not in st.session_state:
    st.session_state["tokens"] = None
if "athlete" not in st.session_state:
    st.session_state["athlete"] = None
if "athlete_id" not in st.session_state:
    st.session_state["athlete_id"] = None

with st.sidebar:
    st.header("Вход / Профил")
    st.markdown(f"[Свържи Strava]({auth_link()})", unsafe_allow_html=True)
    code = st.text_input("Постави ?code=... параметъра от redirect URL", key="oauth_code")
    if st.button("Обмени токен") and code:
        try:
            tokens = exchange_token(code.strip())
            st.session_state.tokens = tokens
            st.session_state.athlete = tokens.get("athlete", None)
            st.session_state.athlete_id = (st.session_state.athlete or {}).get("id", None)
            st.success("Успешна авторизация!")
        except Exception as e:
            st.error(f"Грешка при обмен на токен: {e}")
    if st.session_state.tokens and st.button("Рефреш токен"):
        try:
            tokens = refresh_token(st.session_state.tokens["refresh_token"])
            st.session_state.tokens.update(tokens)
            st.success("Рефрешнат токен.")
        except Exception as e:
            st.error(f"Refresh error: {e}")
    st.markdown('---')
    st.caption("Офлайн тест: въведи Athlete ID")
    aid_manual = st.text_input("Athlete ID", value=str(st.session_state.athlete_id or ""))
    try:
        if aid_manual:
            st.session_state.athlete_id = int(aid_manual)
    except:
        pass

tabs = st.tabs(["Strava анализ", "ACWR / Индекси"])

with tabs[0]:
    st.subheader("Активности от Strava")
    if not st.session_state.tokens:
        st.info("Авторизирай се в Strava отляво.")
    else:
        access_token = st.session_state.tokens["access_token"]
        try:
            athlete = get_athlete(access_token)
            st.success(f"Athlete: {athlete.get('username','?')} (id {athlete.get('id')})")
            st.session_state.athlete_id = athlete.get("id")
        except Exception as e:
            st.warning(f"Не успях да прочета athlete: {e}")
            athlete = None

        act_id = None
        act_df = pd.DataFrame()
        try:
            acts = list_activities(access_token, per_page=20)
            act_df = pd.DataFrame([{"id":a["id"], "start_date":a["start_date"], "name":a["name"], "moving_time":a["moving_time"]} for a in acts])
            st.dataframe(act_df)
            if not act_df.empty:
                act_id = st.selectbox("Избери активност", act_df["id"])
        except Exception as e:
            st.error(f"Грешка при четене на активности: {e}")

        if act_id and st.button("Обработи активността"):
            try:
                streams = get_streams(access_token, int(act_id))
                keys = list(streams.keys())
                length = max(len(streams[k]["data"]) for k in keys)
                def data_or_none(k):
                    return streams.get(k, {}).get("data", [None]*length)
                df = pd.DataFrame({
                    "time": data_or_none("time"),
                    "distance": data_or_none("distance"),
                    "altitude": data_or_none("altitude"),
                    "heartrate": data_or_none("heartrate"),
                })
                start_iso = act_df.loc[act_df["id"]==act_id, "start_date"].iloc[0]
                start_ts = pd.to_datetime(start_iso, utc=True)
                df["timestamp"] = start_ts + pd.to_timedelta(df["time"], unit="s")

                binned = compute_v_flat(df, k=6.0)
                st.write("30s точки:", binned.head())

                execute(
                    \"\"\"
                    insert into workouts(athlete_id, activity_id, start_time, duration_s, avg_hr, avg_speed_flat, raw_payload)
                    values (:aid,:act,:start,:dur,:avg_hr,:avg_v,:raw::jsonb)
                    on conflict (activity_id) do nothing
                    \"\"\",
                    {
                        "aid": int(st.session_state.athlete_id or 0),
                        "act": int(act_id),
                        "start": start_iso,
                        "dur": int(df["time"].max() or 0),
                        "avg_hr": float(np.nanmean(binned["hr"])) if len(binned)>0 else None,
                        "avg_v": float(np.nanmean(binned["v_flat"])) if len(binned)>0 else None,
                        "raw": json.dumps({"name": str(act_id)})
                    }
                )

                if not binned.empty:
                    rows = []
                    for _, r in binned.iterrows():
                        rows.append((
                            int(st.session_state.athlete_id or 0),
                            int(act_id),
                            pd.to_datetime(r["timestamp"]).isoformat(),
                            None if pd.isna(r["hr"]) else float(r["hr"]),
                            None if pd.isna(r["v_flat"]) else float(r["v_flat"]),
                        ))
                    values_sql = ",".join([
                        f"({a},{b},'{t}',{ 'null' if hr is None else hr },{ 'null' if v is None else v })"
                        for (a,b,t,hr,v) in rows
                    ])
                    execute(f\"\"\"
                        insert into hr_speed_points(athlete_id, activity_id, point_time, hr, speed_flat)
                        values {values_sql}
                        on conflict do nothing
                    \"\"\", {})

                # Simple message: in this minimal build we skip per-activity zone persistence for brevity.

                pts = fetch_all(\"\"\"
                    select point_time, hr, speed_flat from hr_speed_points where athlete_id=:aid
                \"\"\", {"aid": int(st.session_state.athlete_id or 0)})
                pts_df = pd.DataFrame(pts)
                a,b,n = weighted_linreg_v_hr(pts_df, half_life_days=14.0)
                st.info(f\"HR = {a:.2f} * V + {b:.2f}  (n={n} точки)\")

                avg_hr = float(np.nanmean(binned["hr"])) if len(binned)>0 else np.nan
                avg_v = float(np.nanmean(binned["v_flat"])) if len(binned)>0 else np.nan
                fi = fatigue_index_for_workout(avg_hr, avg_v, a, b) if n>0 else np.nan
                st.metric("Fatigue Index (тренировка)", f"{fi:.3f} m/s")

            except Exception as e:
                st.error(f"Обработка неуспешна: {e}")

with tabs[1]:
    st.subheader("ACWR по зони (по дистанция) + Индекси")

    aid = int(st.session_state.athlete_id or 0)
    if aid == 0:
        st.info("Няма зададен Athlete ID.")
    else:
        # Тук бихме използвали zone_stats (не е попълнен в този минимален билд). Показваме структурата.
        st.write("Този билд е минимален preview за UI на индекси; за пълната версия използвай предишния пакет onflows_app_full.zip.")
        # Демо DataFrame с фиктивни данни (визуален преглед)
        dates = pd.date_range(pd.Timestamp.utcnow().date() - pd.Timedelta(days=60), periods=61, freq="D")
        zones = ["Z1","Z2","Z3","Z4","Z5"]
        rng = np.random.default_rng(42)
        demo = []
        for d in dates:
            for z in zones:
                workload = float(rng.normal(6 if z=='Z1' else 3, 1).clip(0, None))  # km per day
                demo.append({"date": d.date(), "zone": z, "workload": workload})
        daily = pd.DataFrame(demo)
        acwr_df = compute_acwr(daily)
        st.dataframe(acwr_df.head())

        # Total ACWR
        total = acwr_df.dropna(subset=["acwr"]).groupby("date", as_index=False)["acwr"].mean().rename(columns={"acwr":"total_acwr"})
        st.metric("Total ACWR (демо)", f"{float(total.tail(1)['total_acwr']) if not total.empty else np.nan:.2f}")
        ch = alt.Chart(total).mark_line().encode(x="date:T", y="total_acwr:Q").properties(height=200)
        st.altair_chart(ch, use_container_width=True)

        # Weekly Optimum Index (demo with ideal VTS)
        st.markdown("---")
        st.subheader("Седмичен 'Оптимум по зона' (демо)")
        k = st.slider("Коефициент k", 0.80, 1.50, 1.00, 0.05)
        wk = daily.copy()
        wk["week_start"] = pd.to_datetime(wk["date"]).dt.to_period("W").apply(lambda r: r.start_time.date())
        agg = wk.groupby(["week_start","zone"], as_index=False).agg(dist_km=("workload","sum"))
        # създаваме фиктивни 'минутите' като dist / speed; взимаме средна скорост от 12-14 km/h с шум
        agg["v_avg_kmh"] = 12 + (agg["zone"].map({"Z1":-2,"Z2":0,"Z3":1.5,"Z4":3,"Z5":4}).fillna(0)) + rng.normal(0,0.4,len(agg))
        agg["minutes"] = (agg["dist_km"] / agg["v_avg_kmh"]) * 60.0

        ideal_file = os.path.join(os.path.dirname(__file__), "ideal_distance_time_speed.csv")
        curve = VTSCurve.from_csv(ideal_file)
        def t_opt_from_v(v_kmh: float) -> float:
            if v_kmh is None or np.isnan(v_kmh) or v_kmh <= 0:
                return np.nan
            s_grid = np.linspace(max(curve.dist_km.min(), 0.2), curve.dist_km.max(), 4000)
            t_grid = curve.t_id(s_grid)
            v_grid = 60.0 * s_grid / np.maximum(t_grid,1e-9)
            i = int(np.argmin(np.abs(v_grid - v_kmh)))
            return float(t_grid[i])
        agg["T_opt_min"] = agg["v_avg_kmh"].apply(t_opt_from_v)
        agg["T_target_min"] = agg["T_opt_min"] * float(k)
        agg["T_real_min"] = agg["minutes"]
        agg["Index_pct"] = (agg["T_real_min"] / agg["T_target_min"]) - 1.0
        st.dataframe(agg[["week_start","zone","v_avg_kmh","T_opt_min","T_target_min","T_real_min","Index_pct"]])

        total_idx = agg.groupby("week_start", as_index=False)["Index_pct"].mean().rename(columns={"Index_pct":"TotalIndex"})
        st.metric("Общ седмичен индекс (демо)", f"{float(total_idx.tail(1)['TotalIndex']*100.0) if not total_idx.empty else np.nan:.1f}%")
        ch2 = alt.Chart(total_idx).mark_line().encode(x="week_start:T", y="TotalIndex:Q").properties(height=200)
        st.altair_chart(ch2, use_container_width=True)
