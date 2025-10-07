
import pandas as pd
import numpy as np
from typing import Dict, Any, Tuple

# ---- Grade to flat-equivalent speed adjustment ----
def grade_to_flat_speed(speed_mps: np.ndarray, grade: np.ndarray) -> np.ndarray:
    # grade is in decimal (e.g., +0.05 for +5%)
    g = np.clip(grade, -0.2, 0.2)
    k_up = 0.035   # uphill penalty
    k_down = 0.018 # downhill benefit (smaller magnitude)
    k = np.where(g >= 0, k_up, k_down)
    denom = (1.0 + k * g)
    denom = np.where(denom == 0, 1e-6, denom)
    return speed_mps / denom

def to_30s_bins(streams: Dict[str, Any], start_time: pd.Timestamp) -> pd.DataFrame:
    # Build dataframe from streams
    t = streams.get("time", {}).get("data")
    hr = streams.get("heartrate", {}).get("data")
    v = streams.get("velocity_smooth", {}).get("data")
    grade = streams.get("grade_smooth", {}).get("data")
    dist = streams.get("distance", {}).get("data")

    # Some streams may be missing velocity; derive from distance if needed.
    if v is None and dist is not None and t is not None:
        dist = pd.Series(dist, dtype="float64")
        t = pd.Series(t, dtype="float64")
        v = dist.diff().fillna(0) / t.diff().replace(0, np.nan)
        v = v.fillna(0).to_numpy()
    elif v is None:
        raise ValueError("No velocity_smooth and cannot derive from distance.")

    df = pd.DataFrame({
        "t": t,
        "hr": hr if hr is not None else [np.nan]*len(v),
        "v": v,
        "grade": (np.array(grade)/100.0 if grade is not None else np.zeros(len(v)))
    })

    # Convert relative time to absolute timestamps
    df["time"] = pd.to_datetime(start_time) + pd.to_timedelta(df["t"], unit="s")
    df.set_index("time", inplace=True)

    # Compute flat-equivalent speed (m/s)
    df["v_flat"] = grade_to_flat_speed(df["v"].values, df["grade"].values)

    # Resample to 30s bins
    bin_df = df.resample("30S").agg({
        "hr": "mean",
        "v": "mean",
        "v_flat": "mean"
    }).dropna(how="all")

    # Ensure numeric
    bin_df = bin_df.astype({"hr":"float64","v":"float64","v_flat":"float64"})
    return bin_df

def per_activity_summary(bin_df: pd.DataFrame) -> Tuple[float, float, int]:
    avg_hr = float(bin_df["hr"].mean(skipna=True)) if "hr" in bin_df else np.nan
    avg_vflat = float(bin_df["v_flat"].mean(skipna=True))
    duration_s = int((len(bin_df) * 30))
    return avg_hr, avg_vflat, duration_s
