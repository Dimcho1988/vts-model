from typing import List, Dict, Tuple
import numpy as np
import pandas as pd


# ---------- I/O ----------
def load_ideal_csv(path: str) -> pd.DataFrame:
    """
    Expect columns: speed_kmh, time_min (optionally distance_km).
    If speed_kmh is missing but (distance_km,time_min) exist, compute it.
    """
    df = pd.read_csv(path)
    if "speed_kmh" not in df.columns and {"distance_km", "time_min"}.issubset(df.columns):
        df["speed_kmh"] = 60.0 * df["distance_km"] / df["time_min"]
    # keep only positive/monotonic speeds
    df = df.sort_values("speed_kmh").reset_index(drop=True)
    return df[["speed_kmh", "time_min"]]


# ---------- CS / W′ ----------
def estimate_cs_wprime(points: List[Tuple[float, float]]) -> Tuple[float, float]:
    """
    points: list of (T_sec, v_kmh) steady bests. Returns (CS_kmh, Wprime_m).
    Uses linear fit in D = CS*T + W' (meters).
    """
    if len(points) < 3:
        raise ValueError("Need at least 3 points for stable CS/W′")
    T = np.array([p[0] for p in points], dtype=float)
    v_kmh = np.array([p[1] for p in points], dtype=float)
    v = v_kmh / 3.6
    D = v * T
    A = np.vstack([T, np.ones_like(T)]).T
    cs_mps, wprime_m = np.linalg.lstsq(A, D, rcond=None)[0]
    return float(3.6 * cs_mps), float(max(wprime_m, 0.0))


# ---------- VTS Baseline + Models ----------
def baseline_vts(cs_kmh: float, wprime_m: float, v_min_kmh: float = 8.0,
                 v_max_kmh: float = 20.0, n: int = 160) -> pd.DataFrame:
    """
    Build baseline t(v) with an asymptote around CS and sensible caps to avoid exploding values.

    t(v) = W' / (v - CS)  for v > CS
    t(v) = t_cap_low      for v <= CS   (durability cap)

    Returns DataFrame with columns: v_kmh, t_sec
    """
    v = np.linspace(v_min_kmh, v_max_kmh, n)
    v_mps = v / 3.6
    cs = cs_kmh / 3.6

    # above CS – asymptote; add small epsilon to avoid divide-by-zero jitter
    eps = 1e-4
    t_high = wprime_m / np.maximum(v_mps - cs, eps)

    # below CS – cap to long but finite duration (e.g., 2h)
    t_low = np.full_like(t_high, 2 * 3600.0)

    t_sec = np.where(v_mps > cs, t_high, t_low)

    # FINAL GUARDS: keep within [0, 6000 s] (~100 min) for plotting stability
    t_sec = np.clip(t_sec, 0.0, 6000.0)

    return pd.DataFrame({"v_kmh": v, "t_sec": t_sec})


def modeled_vts_volume(t0: pd.DataFrame, delta_Tz: Dict[str, float]) -> pd.DataFrame:
    """
    Simple "volume warp": small global change based on Z1..Z5 deltas.
    Keeps change within ±25% vs baseline to prevent unrealistic results.
    """
    # Combine zone effects (knobs easy to tune later)
    D = 0.6 * (delta_Tz.get("Z1", 0) + delta_Tz.get("Z2", 0)) \
        + 0.2 * (delta_Tz.get("Z3", 0)) \
        - 0.9 * (delta_Tz.get("Z4", 0) + delta_Tz.get("Z5", 0))
    gain = 1.0 + 0.18 * D

    out = t0.copy()
    out["t_sec"] = np.clip(out["t_sec"] * gain, 0.75 * t0["t_sec"], 1.25 * t0["t_sec"])
    return out


def apply_hrv_gain(t: pd.DataFrame, delta_Iglob: float) -> pd.DataFrame:
    """
    Global HR↔V gain; positive = more durable, negative = less.
    Also clipped within ±25% from the incoming curve.
    """
    c = 0.5
    gain = 1.0 + c * float(delta_Iglob)
    base = t["t_sec"].to_numpy()
    out = t.copy()
    out["t_sec"] = np.clip(base * gain, 0.75 * base, 1.25 * base)
    return out
