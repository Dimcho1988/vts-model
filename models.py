from __future__ import annotations
import numpy as np
import pandas as pd
from typing import Tuple

def weighted_linreg_v_hr(df_points: pd.DataFrame, half_life_days: float = 14.0) -> Tuple[float,float,int]:
    if df_points.empty:
        return (1.0, 0.0, 0)
    df = df_points.dropna(subset=["hr","speed_flat","point_time"]).copy()
    if df.empty:
        return (1.0, 0.0, 0)
    now = pd.Timestamp.utcnow()
    age_days = (now - pd.to_datetime(df["point_time"], utc=True)).dt.total_seconds() / 86400.0
    w = np.exp(-np.log(2.0) * age_days / max(half_life_days, 1e-6))
    x = df["speed_flat"].to_numpy(dtype=float)
    y = df["hr"].to_numpy(dtype=float)
    W = np.diag(w)
    X = np.vstack([x, np.ones_like(x)]).T
    try:
        beta = np.linalg.inv(X.T @ W @ X) @ (X.T @ W @ y)
        a, b = float(beta[0]), float(beta[1])
    except Exception:
        a, b = 1.0, float(np.nanmean(y) - np.nanmean(x))
    return a, b, len(df)

def fatigue_index_for_workout(avg_hr: float, avg_v_flat_ms: float, a: float, b: float) -> float:
    if a == 0:
        return 0.0
    v_pred = (avg_hr - b) / a
    return float(avg_v_flat_ms - v_pred)
