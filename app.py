
import streamlit as st
import pandas as pd
import numpy as np
import altair as alt
from database import init_schema, seed_demo_data, fetch_all
from vts_model import VTSCurve
import os

st.set_page_config(page_title="onFlows • Local Demo", layout="wide")
st.title("🏃 onFlows — Local Demo (Оптимум по зони + ACWR визуализация)")

# Init & seed
init_schema()
seed_demo_data(days_back=56)  # 8 седмици демо данни
st.success("Локалната база е готова и съдържа примерни данни.")

# Weekly aggregates per zone
rows = fetch_all(
    """
    select date_trunc('week', w.start_time) as week_start,
           zs.zone_label as zone,
           sum(zs.distance_m)/1000.0 as dist_km,
           sum(zs.time_s)/60.0 as minutes
    from zone_stats zs
    join workouts w on w.activity_id = zs.activity_id
    where zs.zone_type='speed'
    group by 1,2
    order by 1,2
    """
)
wk = pd.DataFrame(rows)
if wk.empty:
    st.stop()
wk["week_start"] = pd.to_datetime(wk["week_start"]).dt.date
wk["v_avg_kmh"] = wk.apply(lambda r: (r["dist_km"] / (r["minutes"]/60.0)) if r["minutes"]>0 else np.nan, axis=1)

# VTS curve (ideal) to invert time for a given speed
curve = VTSCurve.from_csv(os.path.join(os.path.dirname(__file__), "ideal_distance_time_speed.csv"))

def t_opt_from_v(v_kmh: float) -> float:
    if v_kmh is None or np.isnan(v_kmh) or v_kmh <= 0:
        return np.nan
    s_grid = np.linspace(max(curve.dist_km.min(), 0.5), curve.dist_km.max(), 4000)
    t_grid = curve.t_id(s_grid)  # minutes
    v_grid = 60.0 * s_grid / np.maximum(t_grid, 1e-9)
    i = int(np.argmin(np.abs(v_grid - v_kmh)))
    return float(t_grid[i])

st.subheader("Седмичен 'Оптимум по зони'")
k = st.slider("Коефициент на оптимума k", 0.80, 1.50, 1.00, 0.05)
wk["T_opt_min"] = wk["v_avg_kmh"].apply(t_opt_from_v)
wk["T_target_min"] = wk["T_opt_min"] * float(k)
wk["T_real_min"] = wk["minutes"]
wk["Delta_min"] = wk["T_real_min"] - wk["T_target_min"]
wk["Index_pct"] = (wk["T_real_min"] / wk["T_target_min"]) - 1.0

st.dataframe(wk[["week_start","zone","v_avg_kmh","T_opt_min","T_target_min","T_real_min","Delta_min","Index_pct"]])

tot_idx = wk.groupby("week_start", as_index=False)["Index_pct"].mean().rename(columns={"Index_pct":"TotalIndex"})
st.metric("Общ седмичен индекс (средна по зони)", f"{float(tot_idx.tail(1)['TotalIndex']*100.0):.1f}%")
ch_tot = alt.Chart(tot_idx).mark_line().encode(x="week_start:T", y="TotalIndex:Q").properties(height=220)
st.altair_chart(ch_tot, use_container_width=True)

st.markdown("---")
st.subheader("Зонова динамика на индекса спрямо оптимума")
ch_zone = alt.Chart(wk).mark_line().encode(x="week_start:T", y="Index_pct:Q", color="zone:N").properties(height=300)
st.altair_chart(ch_zone, use_container_width=True)

st.caption("Забележка: Това е локална демо-версия със синтетични данни.")
