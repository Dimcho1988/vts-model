import numpy as np
import pandas as pd
from dataclasses import dataclass

@dataclass
class CSResult:
    cs: float     # m/s
    w_prime: float  # m

def load_ideal(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    if "speed_mps" not in df.columns:
        df["speed_mps"] = df["distance_m"] / df["time_s"]
    if "time_s" not in df.columns and "distance_m" in df.columns and "speed_mps" in df.columns:
        df["time_s"] = df["distance_m"] / df["speed_mps"]
    return df.sort_values("time_s").reset_index(drop=True)

def fit_cs_wprime(two_points):
    t = np.array([p[0] for p in two_points], dtype=float)
    d = np.array([p[1] for p in two_points], dtype=float)
    A = np.vstack([t, np.ones_like(t)]).T
    cs, wprime = np.linalg.lstsq(A, d, rcond=None)[0]
    return CSResult(cs=cs, w_prime=wprime)

def personalized_from_ideal(ideal_df: pd.DataFrame, percent_offsets: dict) -> pd.DataFrame:
    base = ideal_df.copy()
    base["r"] = 1.0
    anchors = sorted([(int(k), float(v)) for k,v in percent_offsets.items()], key=lambda x:x[0]) if percent_offsets else []
    if not anchors:
        base["v_personal"] = base["speed_mps"]
        base["d_personal"] = base["v_personal"] * base["time_s"]
        return base
    t_anchor = np.array([a[0] for a in anchors], dtype=float)
    r_anchor = 1.0 + np.array([a[1] for a in anchors], dtype=float)
    r_interp = np.interp(base["time_s"].values, t_anchor, r_anchor, left=r_anchor[0], right=r_anchor[-1])
    base["v_personal"] = base["speed_mps"] * r_interp
    base["d_personal"] = base["v_personal"] * base["time_s"]
    return base

def zones_from_cs(cs: float) -> dict:
    return {
        1: (0.60*cs, 0.80*cs),
        2: (0.80*cs, 0.90*cs),
        3: (0.90*cs, 1.00*cs),
        4: (1.00*cs, 1.05*cs),
        5: (1.05*cs, 1.20*cs),
    }
