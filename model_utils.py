
from __future__ import annotations
import numpy as np
import pandas as pd
from dataclasses import dataclass
from typing import Callable, List, Tuple

EPS = 1e-9

def _build_interpolator_xy(x: np.ndarray, y: np.ndarray) -> Callable[[np.ndarray], np.ndarray]:
    """Piecewise-linear with edge extension."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    idx = np.argsort(x)
    x = x[idx]; y = y[idx]
    def f(xq: np.ndarray | float) -> np.ndarray:
        xq = np.asarray(xq, dtype=float)
        out = np.empty_like(xq, dtype=float)
        # left
        left_mask = xq <= x[0]
        if np.any(left_mask):
            m = (y[1] - y[0]) / (x[1] - x[0] + EPS)
            out[left_mask] = y[0] + m*(xq[left_mask] - x[0])
        # right
        right_mask = xq >= x[-1]
        if np.any(right_mask):
            m = (y[-1] - y[-2]) / (x[-1] - x[-2] + EPS)
            out[right_mask] = y[-1] + m*(xq[right_mask] - x[-1])
        # mid
        mid_mask = ~(left_mask | right_mask)
        if np.any(mid_mask):
            xm = xq[mid_mask]
            # find intervals
            idxs = np.searchsorted(x, xm, side="right") - 1
            idxs = np.clip(idxs, 0, len(x)-2)
            x0 = x[idxs]; x1 = x[idxs+1]
            y0 = y[idxs]; y1 = y[idxs+1]
            w = (xm - x0) / (x1 - x0 + EPS)
            out[mid_mask] = y0 + w*(y1 - y0)
        return out
    return f

@dataclass
class IdealModel:
    s_km: np.ndarray   # distances (km)
    t_min: np.ndarray  # times (min)

    @property
    def v_kmh(self) -> np.ndarray:
        return self.s_km / (self.t_min/60.0 + EPS)

    def v_of_s(self) -> Callable[[np.ndarray], np.ndarray]:
        return _build_interpolator_xy(self.s_km, self.v_kmh)

    def t_of_s(self) -> Callable[[np.ndarray], np.ndarray]:
        return _build_interpolator_xy(self.s_km, self.t_min)

    def s_of_t(self) -> Callable[[np.ndarray], np.ndarray]:
        # invert by building (t -> s) PWL
        return _build_interpolator_xy(self.t_min, self.s_km)

def load_ideal(csv_path: str) -> IdealModel:
    df = pd.read_csv(csv_path)
    # Expect columns named like distance_km, time_min OR flexible matching
    def pick(col_opts):
        for c in df.columns:
            if c.lower() in col_opts: return c
        raise ValueError(f"Missing required column among: {col_opts}")
    s_col = pick({"distance_km", "distance", "dist_km", "s_km", "s"})
    t_col = pick({"time_min", "time", "t_min", "t"})
    s = df[s_col].astype(float).values
    t = df[t_col].astype(float).values
    # ensure unique & sorted
    idx = np.argsort(s)
    s = s[idx]; t = t[idx]
    # drop dup distances keeping first
    uniq_s, uniq_idx = np.unique(s, return_index=True)
    return IdealModel(s_km=uniq_s, t_min=t[uniq_idx])

@dataclass
class RealPoint:
    kind: str  # 'DS' (distance, speed), 'VT' (distance, time), 'SV' (speed, time)
    a: float
    b: float

def compute_r_samples(ideal: IdealModel, points: List[RealPoint]) -> tuple[np.ndarray, np.ndarray]:
    """Return (s_samples, r_values) for piecewise-linear r(s); edge-extended later."""
    if not points:
        s_mid = np.median(ideal.s_km)
        return np.array([ideal.s_km[0], s_mid, ideal.s_km[-1]]), np.array([1.0, 1.0, 1.0])

    v_of_s = ideal.v_of_s()
    t_of_s = ideal.t_of_s()
    s_of_t = ideal.s_of_t()

    s_list, r_list = [], []
    for p in points:
        k = p.kind.upper().strip()
        if k == "DS":
            s = float(p.a)
            v_real = float(p.b)
            v_id = float(v_of_s(s))
            r = (v_real + EPS) / (v_id + EPS)
            s_list.append(s); r_list.append(r)
        elif k == "VT":
            s = float(p.a)      # distance
            t_real = float(p.b) # min
            t_id = float(t_of_s(s))
            r = (t_id + EPS) / (t_real + EPS)  # since t_personal = t_id / r
            s_list.append(s); r_list.append(r)
        elif k == "SV":
            v_real = float(p.a)       # km/h
            t_given = float(p.b)      # min
            s_at_t_id = float(s_of_t(t_given))
            v_id = float(v_of_s(s_at_t_id))
            r = (v_real + EPS) / (v_id + EPS)
            s_list.append(s_at_t_id); r_list.append(r)
        else:
            continue
    s = np.array(s_list, dtype=float); r = np.array(r_list, dtype=float)
    if len(s) == 0:
        s_mid = np.median(ideal.s_km)
        return np.array([ideal.s_km[0], s_mid, ideal.s_km[-1]]), np.array([1.0, 1.0, 1.0])
    idx = np.argsort(s)
    return s[idx], r[idx]

def r_of_s_interpolator(s_pts: np.ndarray, r_pts: np.ndarray, ideal: IdealModel) -> Callable[[np.ndarray], np.ndarray]:
    """Piecewise-linear r(s) with flat extension outside data range."""
    f = _build_interpolator_xy(s_pts, r_pts)
    s_min = float(np.min(s_pts)); s_max = float(np.max(s_pts))
    def g(sq: np.ndarray | float) -> np.ndarray:
        sq = np.asarray(sq, dtype=float)
        r = f(sq)
        r = np.where(sq < s_min, r_pts[0], r)
        r = np.where(sq > s_max, r_pts[-1], r)
        return np.clip(r, 0.2, 2.5)
    return g

@dataclass
class PersonalizedModel:
    ideal: IdealModel
    r_func: Callable[[np.ndarray], np.ndarray]

    def v_of_s(self) -> Callable[[np.ndarray], np.ndarray]:
        v_id = self.ideal.v_of_s()
        def v(sq):
            return self.r_func(sq) * v_id(sq)
        return v

    def t_of_s(self) -> Callable[[np.ndarray], np.ndarray]:
        v = self.v_of_s()
        def t(sq):
            return 60.0*sq / (v(sq) + EPS)
        return t

    def s_of_t(self) -> Callable[[np.ndarray], np.ndarray]:
        s_grid = np.linspace(self.ideal.s_km[0], self.ideal.s_km[-1], 2000)
        t_vals = self.t_of_s()(s_grid)
        return _build_interpolator_xy(t_vals, s_grid)

def cs_w_from_two_times(model: PersonalizedModel, t1_min: float, t2_min: float) -> tuple[float, float, float, float]:
    """Return (CS_kmh, Dprime_km, d1_km, d2_km) using two time trials (min)."""
    s_of_t = model.s_of_t()
    d1 = float(s_of_t(t1_min))
    d2 = float(s_of_t(t2_min))
    T1 = float(t1_min); T2 = float(t2_min)
    CS_km_per_min = (d2 - d1) / max(T2 - T1, EPS)
    CS_kmh = CS_km_per_min * 60.0
    Dprime_km = d1 - CS_km_per_min * T1
    return CS_kmh, Dprime_km, d1, d2

def modulate_r_by_wprime(ideal: IdealModel, r_func: Callable[[np.ndarray], np.ndarray],
                         Dprime_personal_km: float, Dprime_ideal_km: float,
                         strength: float = 0.5) -> Callable[[np.ndarray], np.ndarray]:
    """
    Tilt r(s) depending on ΔD' relative to ideal.
    Negative delta -> reduce r at short distances (high speeds) and increase at long distances.
    strength in [0,1].
    """
    smin, smax = float(ideal.s_km[0]), float(ideal.s_km[-1])
    span = max(smax - smin, EPS)
    delta = (Dprime_personal_km - Dprime_ideal_km) / (abs(Dprime_ideal_km) + EPS)
    def r_mod(sq):
        sq = np.asarray(sq, dtype=float)
        w = 1.0 - (sq - smin)/span            # w≈1 short, w≈0 long
        tilt = (2*w - 1.0)                    # +1 short .. -1 long
        adj = 1.0 + strength * delta * tilt   # delta<0: adj<1 at short, >1 at long
        return np.clip(r_func(sq) * adj, 0.2, 2.5)
    return r_mod
