import numpy as np

def fit_hr_v(v, hr):
    mask = np.isfinite(v) & np.isfinite(hr)
    if mask.sum() < 2:
        return float("nan"), float("nan")
    a, b = np.polyfit(v[mask], hr[mask], 1)
    return float(a), float(b)

def fatigue_index(v_real, hr_real, a, b):
    if not np.isfinite(a) or a == 0:
        return np.full_like(v_real, np.nan, dtype=float)
    return v_real - (hr_real - b)/a

def cs_star(cs, fi_mean):
    if not np.isfinite(fi_mean):
        return cs
    return cs + fi_mean
