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
# Helpers: time & pace formatting
# -------------------------
def fmt_time_hms_from_minutes(mins: float) -> str:
    """Форматира минути -> h:mm:ss / m:ss / m:ss.t (за много къси)."""
    if mins is None or mins <= 0:
        return "-"
    total_seconds = mins * 60.0
    if total_seconds < 5 * 60:  # под 5 мин → m:ss.t
        m = int(total_seconds // 60)
        s = total_seconds - m * 60
        return f"{m}:{s:04.1f}"
    elif total_seconds < 60 * 60:  # под 60 мин → m:ss
        m = int(total_seconds // 60)
        s = int(round(total_seconds - m * 60))
        if s == 60:
            m += 1
            s = 0
        return f"{m}:{s:02d}"
    else:  # над 60 мин → h:mm:ss
        h = int(total_seconds // 3600)
        rem = total_seconds - h * 3600
        m = int(rem // 60)
        s = int(round(rem - m * 60))
        if s == 60:
            m += 1
            s = 0
        if m == 60:
            h += 1
            m = 0
        return f"{h}:{m:02d}:{s:02d}"

def pace_str_from_speed(speed_kmh: float) -> str:
    """speed km/h -> pace min/km (mm:ss/км)."""
    if speed_kmh is None or speed_kmh <= 0:
        return "-"
    pace_min = 60.0 / speed_kmh
    mm = int(pace_min)
    ss = int(round((pace_min - mm) * 60))
    if ss == 60:
        mm += 1
        ss = 0
    return f"{mm}:{ss:02d}/км"

def pretty_time_with_pace(minutes: float, speed_kmh: float) -> str:
    """Комбинира време (динамичен формат) + темпо в една колона."""
    return f"{fmt_time_hms_from_minutes(minutes)} ({pace_str_from_speed(speed_kmh)})"

# -------------------------
# Parse time inputs like "1:02:30", "4:26", "26.5"
# -------------------------
def parse_time_to_minutes(val) -> float | None:
    """Приема ч:мм:сс, м:сс, м:сс.д или десетични минути и връща минути."""
    if val is None:
        return None
    s = str(val).strip()
    if not s:
        return None
    # ако вече е десетично число (в минути)
    try:
        return float(s)
    except:
        pass
    parts = s.split(":")
    try:
        if len(parts) == 3:
            h = float(parts[0]); m = float(parts[1]); sec = float(parts[2])
            return h * 60 + m + sec / 60.0
        elif len(parts) == 2:
            m = float(parts[0]); sec = float(parts[1])
            return m + sec / 60.0
        elif len(parts) == 1:
            return float(parts[0])
    except:
        return None
    return None

# =========================
# Зареждане на идеалните данни
# =========================
default_csv = "ideal_distance_time_speed.csv"
csv_file = st.sidebar.file_uploader("Идеални данни (CSV)", type=["csv"])
if csv_file is not None:
    ideal_df = pd.read_csv(csv_file)
    csv_path = csv_file
else:
    ideal_df = pd.read_csv(default_csv)
    csv_path = default_csv

# =========================
# Реални точки (въвеждаш ДВЕ от ТРИТЕ: distance_km / time / speed_kmh)
# =========================
st.sidebar.subheader("Реални точки (въведи две от трите полета)")
st.sidebar.caption("Попълни за всеки ред поне ДВЕ полета: дистанция (km), време (ч:мм:сс или м:сс или м:сс.д), скорост (km/h).")

pts_df = st.sidebar.data_editor(
    pd.DataFrame({
        "distance_km": [2.0, 10.0],
        "time": ["4:26", "26:28"],      # време като текст: h:mm:ss / m:ss / m:ss.t
        "speed_kmh": [np.nan, np.nan],  # по избор
    }),
    num_rows="dynamic",
    use_container_width=True,
    key="points_editor_v3"
)

# Конвертираме входните редове в RealPoint (VT/SV/DS) според наличните две полета
points = []
for _, row in pts_df.iterrows():
    d = row.get("distance_km")
    t_str = row.get("time")
    v = row.get("speed_kmh")

    t_min = parse_time_to_minutes(t_str) if pd.notna(t_str) and str(t_str).strip() != "" else None
    have_d = pd.notna(d)
    have_t = t_min is not None
    have_v = pd.notna(v)

    try:
        if have_d and have_t:
            points.append(RealPoint(kind="VT", a=float(d), b=float(t_min)))
        elif have_t and have_v:
            points.append(RealPoint(kind="SV", a=float(v), b=float(t_min)))
        elif have_d and have_v:
            points.append(RealPoint(kind="DS", a=float(d), b=float(v)))
    except Exception:
        pass

# =========================
# Модел идеал + r(s)
# =========================
ideal = load_ideal(csv_path)
s_pts, r_pts = compute_r_samples(ideal, points)
r_func = r_of_s_interpolator(s_pts, r_pts, ideal)
personal = PersonalizedModel(ideal=ideal, r_func=r_func)

# =========================
# CS / W' (само идеал + личен без мод.)
# =========================
t1, t2 = 3.0, 12.0
CS_id_kmh, Dp_id_km, _, _ = cs_w_from_two_times(
    PersonalizedModel(ideal, lambda s: np.ones_like(np.asarray(s, float))), t1, t2
)
CS_p_kmh, Dp_p_km, _, _ = cs_w_from_two_times(personal, t1, t2)

# =========================
# Модулация (само прогнозните криви/таблици)
# =========================
st.sidebar.subheader("Модулация от W'")
mod_strength = st.sidebar.slider("Сила на модулацията", 0.0, 1.0, 0.5, 0.05)
use_mod = st.sidebar.toggle("Включи модулация спрямо ΔW'", value=True)

if use_mod:
    r_func_mod = modulate_r_by_wprime(ideal, r_func, Dp_p_km, Dp_id_km, strength=mod_strength)
else:
    r_func_mod = r_func
personal_mod = PersonalizedModel(ideal=ideal, r_func=r_func_mod)

# =========================
# Таблица: идеални + лични + модул. (компактен вид)
# =========================
_df = ideal_df.copy().reset_index(drop=True)
s_col, t_col = None, None
for c in _df.columns:
    cl = c.lower()
    if cl in {"distance_km","distance","s"}: s_col = c
    if cl in {"time_min","time"}: t_col = c

st.subheader("Идеални данни + лични и модулирани прогнози")
if s_col is None or t_col is None:
    st.error("CSV трябва да има колони distance_km и time_min.")
else:
    s_vals = _df[s_col].astype(float).values
    t_id_vals = _df[t_col].astype(float).values
    v_id_vals = s_vals / (t_id_vals/60.0 + 1e-9)

    v_p_vals  = personal.v_of_s()(s_vals)
    t_p_vals  = 60.0 * s_vals / (v_p_vals + 1e-9)

    v_pm_vals = personal_mod.v_of_s()(s_vals)
    t_pm_vals = 60.0 * s_vals / (v_pm_vals + 1e-9)

    dev_no_mod = (v_p_vals/(v_id_vals+1e-9)-1)*100
    dev_mod    = (v_pm_vals/(v_id_vals+1e-9)-1)*100

    table = pd.DataFrame({
        "distance_km": s_vals,
        "ideal (time + pace)":    [pretty_time_with_pace(t, v) for t, v in zip(t_id_vals, v_id_vals)],
        "personal (time + pace)": [pretty_time_with_pace(t, v) for t, v in zip(t_p_vals,  v_p_vals)],
        "modulated (time + pace)":[pretty_time_with_pace(t, v) for t, v in zip(t_pm_vals, v_pm_vals)],
        "deviation_no_mod_%": dev_no_mod,
        "deviation_mod_%": dev_mod,
    }).sort_values("distance_km")

    st.dataframe(table, use_container_width=True)

# =========================
# Криви за графики (същите три таба)
# =========================
# Грид за рисуване
s_grid = np.linspace(float(ideal.s_km[0]), float(ideal.s_km[-1]), 600)

# Идеални криви
v_id = ideal.v_of_s()(s_grid)
t_id = ideal.t_of_s()(s_grid)

# Лични (без мод.)
v_p  = personal.v_of_s()(s_grid)
t_p  = personal.t_of_s()(s_grid)

# Лични (модулирани)
v_pm = personal_mod.v_of_s()(s_grid)
t_pm = personal_mod.t_of_s()(s_grid)

# Отклонение r(s)
r_grid     = np.maximum(1e-6, v_p  / (v_id + 1e-9))
r_grid_mod = np.maximum(1e-6, v_pm / (v_id + 1e-9))

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
    if len(s_pts) > 0:
        fig3.add_trace(go.Scatter(x=s_pts, y=(r_pts-1.0)*100.0, mode="markers", name="Входни точки"))
    fig3.update_layout(xaxis_title="Дистанция (km)", yaxis_title="Отклонение по скорост (%)", height=520, legend_orientation="h")
    st.plotly_chart(fig3, use_container_width=True)

# =========================
# Резултати CS / W' (модулацията не влияе)
# =========================
st.subheader("Критична скорост и W'")
cols = st.columns(2)
with cols[0]:
    st.metric("CS идеал (km/h)", f"{CS_id_kmh:.2f}")
    st.metric("W' идеал (m)", f"{Dp_id_km*1000:.0f}")
with cols[1]:
    st.metric("CS реален (km/h)", f"{CS_p_kmh:.2f}")
    st.metric("W' реален (m)", f"{Dp_p_km*1000:.0f}")



