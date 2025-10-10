from __future__ import annotations
import pandas as pd
import numpy as np

def _to_datetime_utc(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, utc=True, errors="coerce")

def gap_adjustment_factor(grade_decimal: float) -> float:
    gperc = max(-10.0, min(10.0, float(grade_decimal) * 100.0))
    if gperc >= 0:
        adj = 1.0 + 0.035 * gperc + 0.0005 * (gperc ** 2)
    else:
        adj = 1.0 + 0.018 * gperc + 0.0010 * (gperc ** 2)
    return float(adj)

def compute_v_flat(v_obs_mps: float, grade_decimal: float) -> float:
    if v_obs_mps is None or np.isnan(v_obs_mps) or v_obs_mps <= 0:
        return np.nan
    return float(v_obs_mps * gap_adjustment_factor(grade_decimal))

def bin_1hz_to_30s(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["t_bin_start", "mean_hr", "mean_vflat"])
    req = {"time", "velocity_smooth", "heartrate"}
    missing = req - set(df.columns)
    if missing:
        raise ValueError(f"Missing columns: {missing}")
    data = df.copy()
    data["time"] = _to_datetime_utc(data["time"])
    data = data.dropna(subset=["time"]).sort_values("time")
    if "grade_smooth" not in data.columns:
        data["grade_smooth"] = 0.0
    data["v_flat"] = [compute_v_flat(v if pd.notna(v) else np.nan, g if pd.notna(g) else 0.0)
                      for v, g in zip(data["velocity_smooth"].values, data["grade_smooth"].values)]
    data["bin"] = (data["time"].astype("int64") // (30 * 10**9))
    agg = data.groupby("bin").agg(
        t_start=("time", "min"),
        mean_hr=("heartrate", "mean"),
        mean_vflat=("v_flat", "mean"),
    ).reset_index(drop=True)
    agg["t_bin_start"] = agg["t_start"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return agg[["t_bin_start", "mean_hr", "mean_vflat"]]