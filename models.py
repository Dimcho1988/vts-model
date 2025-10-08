# models.py
from dataclasses import dataclass
from typing import Optional, Tuple
import numpy as np
import pandas as pd
from sqlalchemy import text
from datetime import datetime, timezone

@dataclass
class HRSpeedModelState:
    a: float = 2.0   # HR per (m/s)
    b: float = 60.0  # baseline HR
    r2: float = 0.0
    updated_at: Optional[datetime] = None

@dataclass
class HRSpeedModelConfig:
    half_life_days: float = 14.0  # колко силно тежим скорошните точки (по желание)
    min_points: int = 60          # минимум 30-сек точки за фит

def _weights_from_time(ts: pd.Series, half_life_days: float) -> np.ndarray:
    now = pd.Timestamp.utcnow().tz_localize("UTC")
    age = (now - ts).dt.total_seconds() / (3600*24)
    lam = np.log(2.0) / max(half_life_days, 0.1)
    w = np.exp(-lam * age)
    return w.values

def update_model(engine, athlete_id: int, cfg: HRSpeedModelConfig) -> Optional[HRSpeedModelState]:
    q = text("""
        select point_time, hr, speed_flat
          from hr_speed_points
         where athlete_id=:aid
           and hr is not null and speed_flat is not null
    """)
    with engine.begin() as conn:
        df = pd.read_sql(q, conn, params={"aid": athlete_id})
    if df.empty or df.shape[0] < cfg.min_points:
        return None

    df["point_time"] = pd.to_datetime(df["point_time"], utc=True)
    df = df.dropna(subset=["hr","speed_flat"])
    w = _weights_from_time(df["point_time"], cfg.half_life_days)

    x = df["speed_flat"].values.astype(float)   # m/s
    y = df["hr"].values.astype(float)

    # претеглени най-малки квадрати за y = a*x + b
    W = np.diag(w)
    X = np.vstack([x, np.ones_like(x)]).T
    beta = np.linalg.pinv(X.T @ W @ X) @ (X.T @ W @ y)
    a, b = float(beta[0]), float(beta[1])

    # r^2
    y_pred = a*x + b
    ss_res = np.sum(w*(y - y_pred)**2)
    ss_tot = np.sum(w*(y - np.average(y, weights=w))**2)
    r2 = 1.0 - ss_res/ss_tot if ss_tot > 0 else 0.0

    return HRSpeedModelState(a=a, b=b, r2=float(r2), updated_at=datetime.now(timezone.utc))

def predict_hr(state: HRSpeedModelState, v_ms: float) -> float:
    return state.a * v_ms + state.b

def predict_speed_from_hr(state: HRSpeedModelState, hr: float) -> float:
    if abs(state.a) < 1e-6:
        return np.nan
    return (hr - state.b) / state.a

def fatigue_index_for_workout(state: HRSpeedModelState, avg_hr: float, avg_vflat_ms: float) -> float:
    """ v_real - v_pred (m/s). Отрицателно → умора. """
    v_pred = predict_speed_from_hr(state, avg_hr)
    return float(avg_vflat_ms - v_pred)
