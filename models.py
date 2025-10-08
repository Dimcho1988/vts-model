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
    half_life_days: float = 14.0
    min_points: int = 60

# ---------- utils ----------
def _weights_from_time(ts: pd.Series, half_life_days: float) -> np.ndarray:
    now = pd.Timestamp.utcnow().tz_localize("UTC")
    age_days = (now - ts).dt.total_seconds() / (3600 * 24)
    lam = np.log(2.0) / max(half_life_days, 0.1)
    return np.exp(-lam * age_days).values

def pace_from_kmh(v_kmh: float) -> str:
    if v_kmh <= 0: return "-"
    pace_min = 60.0 / v_kmh
    mm = int(pace_min)
    ss = int(round((pace_min - mm) * 60))
    if ss == 60: mm += 1; ss = 0
    return f"{mm}:{ss:02d}/км"

# ---------- core ----------
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

    # --- robust timezone normalization to UTC (handles mixed/aware/naive) ---
    # опит 1: конвертиране към UTC ако серията вече е tz-aware
    try:
        ts = pd.to_datetime(df["point_time"], errors="coerce")
        ts = ts.dt.tz_convert("UTC")
    except Exception:
        # опит 2: локализиране към UTC ако е naive
        try:
            ts = pd.to_datetime(df["point_time"], errors="coerce").dt.tz_localize("UTC")
        except Exception:
            # опит 3 (fallback): насилствено парсване директно към UTC
            ts = pd.to_datetime(df["point_time"], utc=True, errors="coerce")

    df["point_time"] = ts
    df = df.dropna(subset=["hr", "speed_flat"])

    w = _weights_from_time(df["point_time"], cfg.half_life_days)
    x = df["speed_flat"].astype(float).values   # m/s
    y = df["hr"].astype(float).values

    W = np.diag(w)
    X = np.vstack([x, np.ones_like(x)]).T
    beta = np.linalg.pinv(X.T @ W @ X) @ (X.T @ W @ y)
    a, b = float(beta[0]), float(beta[1])

    y_pred = a * x + b
    ss_res = np.sum(w * (y - y_pred) ** 2)
    mu_w = np.average(y, weights=w)
    ss_tot = np.sum(w * (y - mu_w) ** 2)
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0

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

def derive_hr_zones_from_speed(zones_df: pd.DataFrame, cs_kmh: float, state: HRSpeedModelState) -> pd.DataFrame:
    """Взима зони по %CS и връща таблица (VTS стил) със скорости, темпо и HR граници."""
    z = zones_df.copy()
    z["speed_low_kmh"]  = (z["low_%CS"].astype(float)/100.0)  * cs_kmh
    z["speed_high_kmh"] = (z["high_%CS"].astype(float)/100.0) * cs_kmh
    v_lo_ms  = (z["speed_low_kmh"]  / 3.6).values
    v_hi_ms  = (z["speed_high_kmh"] / 3.6).values
    hr_lo = np.round([predict_hr(state, v) for v in v_lo_ms]).astype(int)
    hr_hi = np.round([predict_hr(state, v) for v in v_hi_ms]).astype(int)
    out = pd.DataFrame({
        "zone": z["zone"],
        "low_%CS": z["low_%CS"],
        "high_%CS": z["high_%CS"],
        "speed_low_kmh":  z["speed_low_kmh"].round(2),
        "speed_high_kmh": z["speed_high_kmh"].round(2),
        "pace_low":  [pace_from_kmh(v) for v in z["speed_high_kmh"]],  # по-бързата граница → по-ниско темпо
        "pace_high": [pace_from_kmh(v) for v in z["speed_low_kmh"]],
        "hr_low_bpm": hr_lo,
        "hr_high_bpm": hr_hi,
        "note": z.get("note", "")
    })
    return out
