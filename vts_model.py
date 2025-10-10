from __future__ import annotations
from typing import Tuple
import pandas as pd
import numpy as np

def compute_cs_wprime(d1_m: float, t1_s: float, d2_m: float, t2_s: float) -> Tuple[float, float]:
    if t1_s == t2_s:
        raise ValueError("t1 and t2 must differ")
    cs = (d2_m - d1_m) / (t2_s - t1_s)
    w_prime = d1_m - cs * t1_s
    return cs, w_prime

def zones_from_cs(cs_mps: float) -> pd.DataFrame:
    bounds = {
        "Z1": (0.70 * cs_mps, 0.85 * cs_mps),
        "Z2": (0.85 * cs_mps, 1.00 * cs_mps),
        "Z3": (1.00 * cs_mps, 1.10 * cs_mps),
        "Z4": (1.10 * cs_mps, 1.25 * cs_mps),
        "Z5": (1.25 * cs_mps, np.inf),
    }
    rows = []
    for z, (lo, hi) in bounds.items():
        rows.append({
            "zone": z,
            "min_speed_mps": lo,
            "max_speed_mps": hi if np.isfinite(hi) else None,
            "min_pace_s_per_km": (1000.0/hi) if np.isfinite(hi) and hi>0 else None,
            "max_pace_s_per_km": (1000.0/lo) if lo>0 else None,
        })
    return pd.DataFrame(rows)

def personal_curve_from_ideal(ideal_df: pd.DataFrame, cs_mps: float) -> pd.DataFrame:
    df = ideal_df.copy()
    last_speed = float(df["speed_mps"].iloc[-1])
    s = cs_mps / last_speed if last_speed > 0 else 1.0
    df["speed_mps_personal"] = df["speed_mps"] * s
    return df[["time_s", "speed_mps", "speed_mps_personal"]]

def optimal_time_for_speed(speed_mps: float, personal_curve: pd.DataFrame) -> float:
    sp = personal_curve["speed_mps_personal"].values.astype(float)
    ts = personal_curve["time_s"].values.astype(float)
    order = np.argsort(sp)
    sp_sorted = sp[order]; ts_sorted = ts[order]
    v = float(speed_mps)
    if v <= sp_sorted[0]:
        return float(ts_sorted[0])
    if v >= sp_sorted[-1]:
        return float(ts_sorted[-1])
    return float(np.interp(v, sp_sorted, ts_sorted))