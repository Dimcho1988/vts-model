import streamlit as st
import numpy as np
import pandas as pd
import plotly.graph_objects as go

from model_utils import (
    load_ideal, RealPoint, compute_r_samples, r_of_s_interpolator,
    PersonalizedModel, cs_w_from_two_times, modulate_r_by_wprime
)

st.set_page_config(page_title="VTS Model", layout="wide")
st.title("vts-model • Velocity–Time–Distance модел")

st.sidebar.header("Настройки")

# -------------------------
# Helpers for pretty time & pace
# -------------------------
def fmt_hmm_from_minutes(mins: float) -> str:
    if mins is None or mins <= 0:
        return "-"
    h = int(mins // 60)
    m = int(round(mins - 60*h))
    if h > 0:
        return f"{h}:{m:02d}"   # 2:15
    # за кратки времена можеш да смениш на mm:ss логика при нужда
    return f"{m} мин"

def fmt_hhmm_text(mins: float) -> str:
    if mins is None or mins <= 0:
        return "-"
    h = int(mins // 60)
    m = int(round(mins - 60*h))
    if h > 0:
        return f"{h} ч {m} мин"
    return f"{m} мин"

def pace_str_from_speed(speed_kmh: float) -> str:
    # speed km/h -> pace min/km
    if speed_kmh is None or speed_kmh <= 0:
        return "-"
    pace_min = 60.0 / speed_kmh
    mm = int(pace_min)
    ss = int(round((pace_min - mm) * 60))
    if ss == 60:
        mm += 1
        ss = 0
    return f"{mm}:{ss:02d}/км"

# =========================
# Зареждане на идеалните данни
# =========================
default_csv = "ideal_distance_time_speed.csv"
csv_file = st.sidebar.file_uploader("Идеални данни (CSV)", type=["csv"], help="Колони: distance_km, time_min")
if csv_file is not None:
    ideal_df = pd.read_csv(csv_file)
    csv_path = csv_file
else:
    ideal_df = pd.read_csv(default_csv)
    csv_path = default_csv

# =========================
# Реални точки (гъвкаво въвеждане)
# =========================
st.sidebar.subheader("Реални точки (въведи две от трите полета)")
st.sidebar.caption("За всеки ред попълни поне ДВЕ полета: дистанция (km), време (min), скорост (km/h).")

pts_df = st.sidebar.data_editor(
    pd.DataFrame({
        "distance_km": [1.0, 5.0],
        "time_min":    [3.5, 20.0],
        "speed_kmh":   [np.nan, np.nan],
    }),
    num_rows="dynamic",
    use_container_width=True,
    key="points_editor_v2"
)

points = []
for _, row in pts_df.iterrows():
    d = row.get("distance_km")
    t = row.get("time_min")
    v = row.get("speed_kmh")
    have_d = pd.notna(d)
    have_t = pd.notna(t)
    have_v = pd.notna(v)
    try:
        if have_d and have_t:
            # VT: distance, time
            points.append(RealPoint(kind="VT", a=float(d), b=float(t)))
        elif have_t and have_v:
            # SV: speed, time
            points.append(RealPoint(kind="SV", a=float(v), b=float(t)))
        elif have_d and have_v:
            # DS: distance, speed
            points.append(RealPoint(kind="DS", a=float(d), b=float(v)))
        else:
            # по-малко от две полета – игнорирай
            pass
    except Exception:
        pass

# =========================
# Модел идеал + r(s) от входните точки
# =========================
ideal = load_ideal(csv_path)
s_pts, r_pts = compute_r_samples(ideal, points)
r_func = r_of_s_interpolator(s_pts, r_pts, ideal)
personal = PersonalizedModel(ideal=ideal, r_func=r_func)

# =========================
# CS / W' от 3' и 12' (само ИДЕАЛ + ЛИЧЕН БЕЗ МОД.)
# =========================
t1, t2 = 3.0, 12.0
CS_id_kmh, Dp_id_km, _, _ = cs_w_from_two_times(
    PersonalizedModel(ideal, lambda s: np.ones_like(np.asarray(s, float))), t1, t2
)
CS_p_kmh, Dp_p_km, _, _ = cs_w_from_two_times(personal, t1, t2)

# =========================
# Модулация по W' — влияе САМО на прогнозните криви/таблици
# =========================
st.sidebar.subheader("Модулация от W' (D')")
mod_strength = st.sidebar.slider("Сила на модулацията", 0.0, 1.0, 0.5, 0.05)
use_mod = st.sidebar.toggle("Включи модулация спрямо ΔW' (идеал → личен)", value=True)

if use_mod:
    r_func_mod = modulate_r_by_wprime(ideal, r_func, Dp_p_km, Dp_id_km, strength=mod_strength)
else:
    r_func_mod = r_func
personal_mod = PersonalizedModel(ideal=ideal, r_func=r_func_mod)

# =========================
# ОБОГАТЕНА ТАБЛИЦА: Идеал + лични (без мод.) + модул.
# =========================
_df = ideal_df.copy().reset_index(drop=True)
s_col, t_col = None, None
for c in _df.columns:
    cl = c.lower()
    if cl in {"distance_km","distance","dist_km","s_km","s"}:
        s_col = c
    if cl in {"time_min","time","t_min","t"}:
        t_col = c

st.subheader("Идеални данни + лични и модулирани прогнози")
if s_col is None or t_col is None:
    st.error("CSV трябва да има колони за дистанция (distance_km) и време (time_min).")
else:
    s_vals = _df[s_col].astype(float).values
    t_id_vals = _df[t_col].astype(float).values
    v_id_vals = s_vals / (t_id_vals/60.0 + 1e-9)

    # Лични (без мод.) стойности върху идеалните дистанции
    v_p_vals = personal.v_of_s()(s_vals)
    t_p_vals = 60.0 * s_vals / (v_p_vals + 1e-9)

    # Модулирани стойности
    v_pm_vals = personal_mod.v_of_s()(s_vals)
    t_pm_vals = 60.0 * s_vals / (v_pm_vals + 1e-9)

    # Отклонения (% по скорост) спрямо идеала
    dev_no_mod = (v_p_vals/(v_id_vals + 1e-9) - 1.0) * 100.0
    dev_mod    = (v_pm_vals/(v_id_vals + 1e-9) - 1.0) * 100.0

    # Форматирани времена и темпо
    ideal_time_hmm = [fmt_hmm_from_minutes(x) for x in t_id_vals]
    ideal_time_text = [fmt_hhmm_text(x) for x in t_id_vals]
    personal_time_hmm = [fmt_hmm_from_minutes(x) for x in t_p_vals]
    personal_time_text = [fmt_hhmm_text(x) for x in t_p_vals]
    mod_time_hmm = [fmt_hmm_from_minutes(x) for x in t_pm_vals]
    mod_time_text = [fmt_hhmm_text(x) for x in t_pm_vals]

    ideal_pace = [pace_str_from_speed(x) for x in v_id_vals]
    personal_pace = [pace_str_from_speed(x) for x in v_p_vals]
    mod_pace = [pace_str_from_speed(x) for x in v_pm_vals]

    enriched = pd.DataFrame({
        "distance_km": s_vals,

        "ideal_time_min": t_id_vals,
        "ideal_time": ideal_time_hmm,                 # 2:15
        "ideal_time_text": ideal_time_text,           # 2 ч 15 мин
        "ideal_speed_kmh": v_id_vals,
        "ideal_pace": ideal_pace,                     # мин/км

        "r_no_mod": np.maximum(1e-6, v_p_vals/(v_id_vals + 1e-9)),
        "personal_time_min": t_p_vals,
        "personal_time": personal_time_hmm,
        "personal_time_text": personal_time_text,
        "personal_speed_kmh": v_p_vals,
        "personal_pace": personal_pace,
        "deviation_no_mod_%": dev_no_mod,

        "r_mod": np.maximum(1e-6, v_pm_vals/(v_id_vals + 1e-9)),
        "mod_time_min": t_pm_vals,
        "mod_time": mod_time_hmm,
        "mod_time_text": mod_time_text,
        "mod_speed_kmh": v_pm_vals,
        "mod_pace": mod_pace,
        "deviation_mod_%": dev_mod,
    }).sort_values("distance_km")

    st.dataframe(enriched, use_container_width=True)
    st.download_button(
        "Свали таблицата (CSV)",
        enriched.to_csv(index=False).encode("utf-8"),
        file_name="ideal_plus_predictions.csv",
        mime="text/csv"
    )

# =========================
# Криви за графики (идеал/личен/мод.)
# =========================
s_grid = np.linspace(float(ideal.s_km[0]), float(ideal.s_km[-1]), 600)
v_id = ideal.v_of_s()(s_grid)
t_id = ideal.t_of_s()(s_grid)
v_p  = personal.v_of_s()(s_grid)
t_p  = personal.t_of_s()(s_grid)
v_pm = personal_mod.v_of_s()(s_grid)
t_pm = personal_mod.t_of_s()(s_grid)

r_grid     = np.maximum(1e-6, v_p/(v_id + 1e-9))
r_grid_mod = np.maximum(1e-6, v_pm/(v_id + 1e-9))

tab1, tab2, tab3 = st.tabs(["Скорост–дистанция", "Време–дистанция", "Отклонение (%)"])

with tab1:
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=s_grid, y=v_id, mode="lines", name="Идеална v(s)"))
    fig.add_trace(go.Scatter(x=s_grid, y=v_p,  mode="lines", name="Лична v(s)"))
    if use_mod:
        fig.add_trace(go.Scatter(x=s_grid, y=v_pm, mode="lines", name="Лична v(s) – модул."))
    fig.update_layout(xaxis_title="Дистанция (km)", yaxis_title="Скорост (km/h)", height=520, legend_orientation="h")
    st.plotly_chart(fig, use_container_width=True)

with tab2:
    fig2 = go.Figure()
    fig2.add_trace(go.Scatter(x=s_grid, y=t_id, mode="lines", name="Идеална t(s)"))
    fig2.add_trace(go.Scatter(x=s_grid, y=t_p,  mode="lines", name="Лична t(s)"))
    if use_mod:
        fig2.add_trace(go.Scatter(x=s_grid, y=t_pm, mode="lines", name="Лична t(s) – модул."))
    fig2.update_layout(xaxis_title="Дистанция (km)", yaxis_title="Време (min)", height=520, legend_orientation="h")
    st.plotly_chart(fig2, use_container_width=True)

with tab3:
    fig3 = go.Figure()
    fig3.add_trace(go.Scatter(x=s_grid, y=(r_grid-1.0)*100.0, mode="lines", name="% отклонение (без мод.)"))
    if use_mod:
        fig3.add_trace(go.Scatter(x=s_grid, y=(r_grid_mod-1.0)*100.0, mode="lines", name="% отклонение (модул.)"))
    fig3.add_trace(go.Scatter(x=s_pts, y=(r_pts-1.0)*100.0, mode="markers", name="Входни точки"))
    fig3.update_layout(xaxis_title="Дистанция (km)", yaxis_title="Отклонение по скорост (%)", height=520, legend_orientation="h")
    st.plotly_chart(fig3, use_container_width=True)

# =========================
# Метрики CS/W' – модулацията НЕ влияе
# =========================
st.subheader("Резултати за 3' и 12' + критична скорост (CS) и W' (D')")
cols = st.columns(2)
with cols[0]:
    st.markdown("**Идеал**")
    st.metric("CS (km/h)", f"{CS_id_kmh:.2f}")
    st.metric("W' / D' (m)", f"{Dp_id_km*1000:.0f}")
with cols[1]:
    st.markdown("**Личен (без модулация)**")
    st.metric("CS (km/h)", f"{CS_p_kmh:.2f}")
    st.metric("W' / D' (m)", f"{Dp_p_km*1000:.0f}")

# =========================
# Допълнителна ПРОГНОЗА (по избор): по дистанция / по време
# =========================
st.header("Прогноза (скорост–време–път)")
mode = st.radio("Режим на прогноза",
                ["По дистанция (въвеждам km)", "По време (въвеждам min)"],
                horizontal=True)

default_dists = "1, 3, 5, 10, 21.097, 42.195"
default_times = "1, 3, 5, 12, 30, 60"

if mode.startswith("По дистанция"):
    dists_str = st.text_input("Дистанции (km), разделени със запетая", value=default_dists)
    try:
        dists = [float(x.strip()) for x in dists_str.split(",") if x.strip()]
    except:
        dists = []
    if dists:
        v_id_f = ideal.v_of_s(); t_id_f = ideal.t_of_s()
        v_p_f  = personal.v_of_s(); t_p_f = personal.t_of_s()
        v_pm_f = personal_mod.v_of_s(); t_pm_f = personal_mod.t_of_s()
        rows = []
        for s in dists:
            vi, ti = float(v_id_f(s)), float(t_id_f(s))
            vp, tp = float(v_p_f(s)),  float(t_p_f(s))
            vpm, tpm = float(v_pm_f(s)), float(t_pm_f(s))
            rows.append({
                "distance_km": s,
                "ideal_time_min": ti, "ideal_time": fmt_hmm_from_minutes(ti),
                "ideal_speed_kmh": vi, "ideal_pace": pace_str_from_speed(vi),
                "personal_time_min": tp, "personal_time": fmt_hmm_from_minutes(tp),
                "personal_speed_kmh": vp, "personal_pace": pace_str_from_speed(vp),
                "mod_time_min": tpm, "mod_time": fmt_hmm_from_minutes(tpm),
                "mod_speed_kmh": vpm, "mod_pace": pace_str_from_speed(vpm),
                "deviation_no_mod_%": (vp/max(vi,1e-9)-1.0)*100.0,
                "deviation_mod_%": (vpm/max(vi,1e-9)-1.0)*100.0,
            })
        pred_df = pd.DataFrame(rows).sort_values("distance_km")
        st.dataframe(pred_df, use_container_width=True)
        st.download_button("Свали прогноза (по дистанция) CSV",
                           pred_df.to_csv(index=False).encode("utf-8"),
                           file_name="forecast_by_distance.csv", mime="text/csv")
else:
    times_str = st.text_input("Времена (min), разделени със запетая", value=default_times)
    try:
        times = [float(x.strip()) for x in times_str.split(",") if x.strip()]
    except:
        times = []
    if times:
        s_id_f = ideal.s_of_t(); s_p_f = personal.s_of_t(); s_pm_f = personal_mod.s_of_t()
        v_id_f = ideal.v_of_s(); v_p_f = personal.v_of_s(); v_pm_f = personal_mod.v_of_s()
        rows = []
        for T in times:
            si = float(s_id_f(T)); vi = float(v_id_f(si))
            sp = float(s_p_f(T));  vp = float(v_p_f(sp))
            spm = float(s_pm_f(T)); vpm = float(v_pm_f(spm))
            rows.append({
                "time_min": T,
                "ideal_distance_km": si, "ideal_speed_kmh": vi, "ideal_pace": pace_str_from_speed(vi),
                "personal_distance_km": sp, "personal_speed_kmh": vp, "personal_pace": pace_str_from_speed(vp),
                "mod_distance_km": spm, "mod_speed_kmh": vpm, "mod_pace": pace_str_from_speed(vpm),
                "deviation_no_mod_%": (vp/max(vi,1e-9)-1.0)*100.0,
                "deviation_mod_%": (vpm/max(vi,1e-9)-1.0)*100.0,
            })
        pred_df = pd.DataFrame(rows).sort_values("time_min")
        st.dataframe(pred_df, use_container_width=True)
        st.download_button("Свали прогноза (по време) CSV",
                           pred_df.to_csv(index=False).encode("utf-8"),
                           file_name="forecast_by_time.csv", mime="text/csv")

st.caption("Модулацията по W' влияе само на прогнозните криви/таблици, не и на CS/W'. Въвеждай по две от трите полета (дистанция/време/скорост) за всяка реална точка.")


