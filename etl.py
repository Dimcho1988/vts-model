from typing import Dict, Any, List, Tuple
import numpy as np, pandas as pd
from scipy.signal import medfilt
import datetime as dt

def resample_to_1hz(streams: Dict[str, Any]) -> pd.DataFrame:
    """Resample Strava streams to a 1 Hz dataframe with distance (m), v (m/s), altitude (m), HR (bpm)."""
    t = streams.get("time", {}).get("data", [])
    if not t:
        raise ValueError("No time stream")
    df = pd.DataFrame({"t": t})
    for key, target in [("distance","distance"),("velocity_smooth","v"),("altitude","altitude"),("heartrate","hr")]:
        if key in streams and "data" in streams[key]:
            df[target] = streams[key]["data"]
    # Fill seconds grid
    df = df.set_index("t").sort_index()
    full_index = np.arange(df.index.min(), df.index.max()+1, 1)
    df = df.reindex(full_index)
    df.index.name = "t"
    df["distance"] = df["distance"].interpolate(limit_direction="both")
    if "v" not in df or df["v"].isna().all():
        df["v"] = df["distance"].diff().fillna(0.0)
    df["altitude"] = df["altitude"].interpolate(limit_direction="both")
    df["hr"] = df["hr"].ffill()
    # sanity clips
    df["v"] = df["v"].clip(lower=0, upper=10)  # m/s
    df["hr"] = df["hr"].clip(lower=35, upper=220)
    return df.reset_index()

def compute_grade(df: pd.DataFrame) -> pd.DataFrame:
    # grade using 10 m windows
    d_dist = df["distance"].diff().rolling(10, min_periods=1).sum()
    d_elev = df["altitude"].diff().rolling(10, min_periods=1).sum()
    g = np.divide(d_elev, np.where(d_dist==0, np.nan, d_dist))
    g = np.clip(g, -0.2, 0.2)
    df["grade"] = g.fillna(0.0)
    return df

def v_flat_from_grade(v: np.ndarray, grade: np.ndarray, k: float=6.0) -> np.ndarray:
    k_down = 0.6*k
    denom = np.where(grade>=0, 1 + k*grade, 1 + k_down*grade)
    denom = np.clip(denom, 0.5, 1.5)
    return np.divide(v, denom)

def bin30(df: pd.DataFrame) -> pd.DataFrame:
    df2 = df.copy()
    df2["v_flat"] = v_flat_from_grade(df2["v"].values, df2["grade"].values)
    df2["valid_v"] = (df2["v"].between(0,10)).astype(int)
    df2["valid_hr"] = (df2["hr"].between(35,220)).astype(int)
    df2["valid_flat"] = 1
    # drop low speeds from load calc
    df2["is_move"] = (df2["v"]*3.6 >= 1.0).astype(int)
    # 30s bins
    df2["bin"] = (df2["t"] // 30).astype(int)
    agg = df2.groupby("bin").agg(
        seconds=("t","count"),
        v_kmh=("v", lambda x: 3.6*np.nanmean(x)),
        vflat_kmh=("v_flat", lambda x: 3.6*np.nanmean(x)),
        hr_bpm=("hr","mean"),
        grade=("grade","mean"),
        coverage=("valid_v","mean"),
        f_v=("valid_v","mean"),
        f_hr=("valid_hr","mean"),
        f_flat=("valid_flat","mean"),
        is_move=("is_move","mean"),
    ).reset_index()
    # quality filters
    agg["valid_bin"] = (agg["coverage"]>=0.5) & (agg["v_kmh"]>=1.0)
    return agg

def classify_zone(vflat_kmh: float, cs_kmh: float, zones: Dict[str, Tuple[float,float]]) -> str:
    if np.isnan(vflat_kmh) or cs_kmh<=0:
        return "NA"
    r = vflat_kmh / cs_kmh
    for label, (lo,hi) in zones.items():
        if lo <= r < hi:
            return label
    if r < list(zones.values())[0][0]:
        return "Z0"
    return "Z6"

def zone_table(bins: pd.DataFrame, cs_kmh: float, zones: Dict[str, Tuple[float,float]]) -> pd.DataFrame:
    df = bins[bins["valid_bin"]].copy()
    if df.empty:
        return pd.DataFrame(columns=["zone","time_s","vflat_avg_kmh","hr_avg_bpm","load_km","IF_v"])
    df["zone"] = [classify_zone(v, cs_kmh, zones) for v in df["vflat_kmh"].values]
    out = df.groupby("zone").agg(
        time_s=("seconds","sum"),
        vflat_avg_kmh=("vflat_kmh","mean"),
        hr_avg_bpm=("hr_bpm","mean")
    ).reset_index()
    out["load_km"] = out["vflat_avg_kmh"] * (out["time_s"]/3600.0)
    out["IF_v"] = out["vflat_avg_kmh"] / max(cs_kmh, 0.1)
    return out.sort_values("zone")
