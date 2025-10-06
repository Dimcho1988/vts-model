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
# Зареждане на идеалните данни
# -------------------------
default_csv = "ideal_distance_time_speed.csv"
csv_file = st.sidebar.file_uploader("Идеални данни (CSV)", type=["csv"], help="Колони: distance_km, time_min")
if csv_file is not None:
    ideal_df = pd.read_csv(csv_file)
    csv_path = csv_file
else:
    ideal_df = pd.read_csv(default_csv)
    csv_path = default_csv

ideal_df = ideal_df.sort_values(ideal_df.columns[0])
st.subheader("Идеални данни (преглед)")
st.dataframe(ideal_df.head(20), use_container_width=True)

ideal = load_ideal(csv_path)

# -------------------------
# Реални точки (едитируеми)
# -------------------------
st.sidebar.subheader("Реални точки (една или повече)")
st.sidebar.markdown("Видове: **DS** (distance, speed), **VT** (distance, time), **SV** (speed, time)")

pts_df = st.sidebar.data_editor(
    pd.DataFrame({
        "kind": ["DS", "VT"],
        "a":    [1.0, 5.0],
        "b":    [16.0, 20.0],  # speed km/h ИЛИ time min (според вида)
    }),
    num_rows="dynamic",
    use_container_width=True,
    key="points_editor"
)

points = []
for _, row in pts_df.dropna().iterrows():
    try:
        points.append(RealPoint(kind=str(row["kind"]), a=float(row["a"]), b=float(row["b"])))
    except Exception:
        pass

s_pts, r_pts = compute_r_samples(ideal, points)
r_func = r_of_s_interpolator(s_pts, r_pts, ideal)

# -------------------------
# Личен модел (без модулация)
# -------------------------
personal = PersonalizedModel(ideal=ideal, r_func=r_func)

# -------------------------
# 3' и 12' – CS и W' (само ИДЕАЛ + ЛИЧЕН БЕЗ МОД.)
# -------------------------
t1, t2 = 3.0, 12.0
CS_id_kmh, Dp_id_km, d1_id, d2_id = cs_w_from_two_times(
    PersonalizedModel(ideal, lambda s: np.ones_like(np.asarray(s, float))), t1, t2
)
CS_p_kmh, Dp_p_km, d1_p, d2_p = cs_w_from_two_times(personal, t1, t2)

# -------------------------
# Модулация по W' (за ПРОГНОЗИ/КРИВИ, не за CS/W')
# -------------------------
st.sidebar.subheader("Модулация от W' (D')")
mod_strength = st.sidebar.slider("Сила на модулацията", 0.0, 1.0, 0.5, 0.05)
use_mod = st.sidebar.toggle("Включи модулация спрямо ΔW' (идеал → личен)", value=True)

if use_mod:
    r_func_mod = modulate_r_by_wprime(ideal, r_func, Dp_p_km, Dp_id_km, strength=mod_strength)
else:
    r_func_mod = r_func

personal_mod = PersonalizedModel(ideal=ideal, r_func=r_func_mod)

# -------------------------
# Подготовка на криви за графики
# -------------------------
s_grid = np.linspace(float(ideal.s_km[0]), float(ideal.s_km[-1]), 600)
v_id = ideal.v_of_s()(s_grid)
t_id = ideal.t_of_s()(s_grid)

v_p = personal.v_of_s()(s_grid)
t_p = personal.t_of_s()(s_grid)

v_pm = personal_mod.v_of_s()(s_grid)
t_pm = personal_mod.t_of_s()(s_grid)

r_grid = np.maximum(1e-6, v_p / (v_id + 1e-9))
r_grid_mod = np.maximum(1e-6, v_pm / (v_id + 1e-9))

# -------------------------
# Графики
# -------------------------
tab1, tab2, tab3 = st.tabs(["Скорост–дистанция", "Време–дистанция", "Отклонение (%)"])

with tab1:
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=s_grid, y=v_id, mode="lines", name="Идеална v(s)"))
    fig.add_trace(go.Scatter(x=s_grid, y=v_p, mode="lines", name="Лична v(s)"))
    if use_mod:
        fig.add_trace(go.Scatter(x=s_grid, y=v_pm, mode="lines", name="Лична v(s) – модул."))
    fig.update_layout(xaxis_title="Дистанция (km)", yaxis_title="Скорост (km/h)", height=520, legend_orientation="h")
    st.plotly_chart(fig, use_container_width=True)

with tab2:
    fig2 = go.Figure()
    fig2.add_trace(go.Scatter(x=s_grid, y=t_id, mode="lines", name="Идеална t(s)"))
    fig2.add_trace(go.Scatter(x=s_grid, y=t_p, mode="lines", name="Лична t(s)"))
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

# -------------------------
# Метрики CS/W' – модулацията НЕ влияе
# -------------------------
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

# -------------------------
# ПРОГНОЗА: скорост–време–път
# -------------------------
st.header("Прогноза (скорост–време–път)")

mode = st.radio(
    "Режим на прогноза",
    ["По дистанция (въвеждам km)", "По време (въвеждам min)"],
    horizontal=True
)

default_dists = "1, 3, 5, 10, 21.097, 42.195"
default_times = "1, 3, 5, 12, 30, 60"

if mode.startswith("По дистанция"):
    dists_str = st.text_input("Дистанции (km), разделени със запетая", value=default_dists)
    try:
        dists = [float(x.strip()) for x in dists_str.split(",") if x.strip()]
    except:
        dists = []

    if dists:
        v_id_f = ideal.v_of_s()
        t_id_f = ideal.t_of_s()
        v_p_f  = personal.v_of_s()
        t_p_f  = personal.t_of_s()
        v_pm_f = personal_mod.v_of_s()
        t_pm_f = personal_mod.t_of_s()

        rows = []
        for s in dists:
            vi = float(v_id_f(s)); ti = float(t_id_f(s))
            vp = float(v_p_f(s));  tp = float(t_p_f(s))
            vpm = float(v_pm_f(s)); tpm = float(t_pm_f(s))
            rows.append({
                "distance_km": s,
                "ideal_time_min": ti,
                "ideal_speed_kmh": vi,
                "personal_time_min": tp,
                "personal_speed_kmh": vp,
                "mod_time_min": tpm,
                "mod_speed_kmh": vpm,
                "deviation_no_mod_%": (vp/max(vi,1e-9)-1.0)*100.0,
                "deviation_mod_%": (vpm/max(vi,1e-9)-1.0)*100.0,
            })
        pred_df = pd.DataFrame(rows).sort_values("distance_km")
        st.dataframe(pred_df, use_container_width=True)

        st.download_button(
            "Свали прогноза (по дистанция) CSV",
            pred_df.to_csv(index=False).encode("utf-8"),
            file_name="forecast_by_distance.csv",
            mime="text/csv"
        )

else:
    times_str = st.text_input("Времена (min), разделени със запетая", value=default_times)
    try:
        times = [float(x.strip()) for x in times_str.split(",") if x.strip()]
    except:
        times = []

    if times:
        s_id_f = ideal.s_of_t()
        s_p_f  = personal.s_of_t()
        s_pm_f = personal_mod.s_of_t()
        v_id_f = ideal.v_of_s()
        v_p_f  = personal.v_of_s()
        v_pm_f = personal_mod.v_of_s()

        rows = []
        for T in times:
            si = float(s_id_f(T)); vi = float(v_id_f(si))
            sp = float(s_p_f(T));  vp = float(v_p_f(sp))
            spm = float(s_pm_f(T)); vpm = float(v_pm_f(spm))
            rows.append({
                "time_min": T,
                "ideal_distance_km": si,
                "ideal_speed_kmh": vi,
                "personal_distance_km": sp,
                "personal_speed_kmh": vp,
                "mod_distance_km": spm,
                "mod_speed_kmh": vpm,
                "deviation_no_mod_%": (vp/max(vi,1e-9)-1.0)*100.0,
                "deviation_mod_%": (vpm/max(vi,1e-9)-1.0)*100.0,
            })
        pred_df = pd.DataFrame(rows).sort_values("time_min")
        st.dataframe(pred_df, use_container_width=True)

        st.download_button(
            "Свали прогноза (по време) CSV",
            pred_df.to_csv(index=False).encode("utf-8"),
            file_name="forecast_by_time.csv",
            mime="text/csv"
        )

# -------------------------
# Експорт на криви (за справка)
# -------------------------
st.subheader("Експорт на криви (за справка)")
out_ready = pd.DataFrame({
    "distance_km": s_grid,
    "v_ideal_kmh": v_id,
    "t_ideal_min": t_id,
    "r_no_mod": r_grid,
    "v_personal_kmh": v_p,
    "t_personal_min": t_p,
    "r_mod": r_grid_mod,
    "v_personal_mod_kmh": v_pm,
    "t_personal_mod_min": t_pm,
})
st.download_button("Свали персонализирани криви (CSV)",
                   out_ready.to_csv(index=False).encode("utf-8"),
                   file_name="vts_personalized_curves.csv",
                   mime="text/csv")

st.caption("Съвет: попълнете реални тестови точки в панела отляво. Вид ‘DS’=Distance–Speed, ‘VT’=Distance–Time, ‘SV’=Speed–Time. Модулацията по W' влияе само на прогнозните криви/таблици, не и на CS/W'.")


