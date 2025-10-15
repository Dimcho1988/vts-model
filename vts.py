from typing import List, Dict, Tuple
import numpy as np, pandas as pd

def load_ideal_csv(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    # Expect columns distance_km, time_min, speed_kmh (any two are sufficient)
    if "speed_kmh" not in df.columns and {"distance_km","time_min"}.issubset(df.columns):
        df["speed_kmh"] = 60*df["distance_km"]/df["time_min"]
    return df

def estimate_cs_wprime(points: List[Tuple[float,float]]) -> Tuple[float,float]:
    """
    points: list of (T_sec, v_kmh) steady bests. Returns (CS_kmh, Wprime_m).
    Uses linear fit in D = CS*T + W' (meters).
    """
    if len(points) < 3:
        raise ValueError("Need at least 3 points for stable CS/W'")
    T = np.array([p[0] for p in points], dtype=float)
    v_kmh = np.array([p[1] for p in points], dtype=float)
    v = v_kmh/3.6
    D = v*T
    A = np.vstack([T, np.ones_like(T)]).T
    # robust-ish: ordinary least squares; callers should filter points
    cs_mps, wprime_m = np.linalg.lstsq(A, D, rcond=None)[0]
    return float(3.6*cs_mps), float(max(wprime_m, 0.0))

def baseline_vts(cs_kmh: float, wprime_m: float, v_grid_kmh=None) -> pd.DataFrame:
    """
    Build baseline t0(v) using asymptote W'/(v-CS) above CS and cap at 3h under CS.
    """
    if v_grid_kmh is None:
        v_grid_kmh = np.linspace(max(0.8*cs_kmh, 5.0), max(cs_kmh*1.5, cs_kmh+8.0), 80)
    cs = cs_kmh/3.6
    v = v_grid_kmh/3.6
    # time to exhaustion in seconds for v > CS
    t_high = np.where(v>cs, wprime_m/np.maximum(v-cs, 1e-6), np.inf)
    # below CS: cap at 3h, with a smooth curve
    t_low = 3*3600*np.ones_like(v)
    t0 = np.where(np.isfinite(t_high), t_high, t_low)
    return pd.DataFrame({"v_kmh": v_grid_kmh, "t_sec": t0})

def modeled_vts_volume(t0: pd.DataFrame, delta_Tz: Dict[str, float]) -> pd.DataFrame:
    """Simple local warp around zones: +/- up to 25%."""
    # Define zone windows around % of CS using the v axis in relative terms later in UI; here apply mild global factor
    beta = 0.35
    # Aggregate a simple D combining Z1..Z5
    D = 0.6*(delta_Tz.get("Z1",0)+delta_Tz.get("Z2",0)) - 0.9*(delta_Tz.get("Z4",0)+delta_Tz.get("Z5",0))
    gain = 1 + 0.15*D
    out = t0.copy()
    out["t_sec"] = np.clip(out["t_sec"]*gain, 0.8*out["t_sec"], 1.25*out["t_sec"])
    return out

def apply_hrv_gain(t: pd.DataFrame, delta_Iglob: float) -> pd.DataFrame:
    c = 0.5
    gain = 1 + c*delta_Iglob
    out = t.copy()
    out["t_sec"] = np.clip(out["t_sec"]*gain, 0.8*out["t_sec"], 1.25*out["t_sec"])
    return out
