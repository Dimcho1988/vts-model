from __future__ import annotations
from typing import List, Dict, Optional
import pandas as pd
import numpy as np

def assign_zone_from_speed(speed_mps: float, cs: float) -> str:
    if np.isnan(speed_mps) or speed_mps <= 0 or cs <= 0:
        return "Z0"
    r = speed_mps / cs
    if r < 0.85:
        return "Z1-2"
    elif r < 1.10:
        return "Z3"
    elif r < 1.25:
        return "Z4"
    else:
        return "Z5"

def weekly_aggregates_with_vflat(workouts: List[Dict], cs: float,
                                 mean_vflat_map: Optional[Dict[int, float]]=None) -> pd.DataFrame:
    if not workouts:
        return pd.DataFrame(columns=["week", "zone", "time_min", "distance_km", "sessions"])
    df = pd.DataFrame(workouts).copy()
    df["start_time"] = pd.to_datetime(df["start_time"], utc=True, errors="coerce")
    df = df.dropna(subset=["start_time"])
    df["fallback_speed"] = df["avg_speed_mps"].fillna(df["distance_m"]/df["duration_s"])
    if mean_vflat_map:
        df["z_speed"] = df.apply(lambda r: mean_vflat_map.get(int(r["id"]), np.nan), axis=1)
        df["z_speed"] = df["z_speed"].fillna(df["fallback_speed"])
    else:
        df["z_speed"] = df["fallback_speed"]
    df["zone"] = df["z_speed"].apply(lambda v: assign_zone_from_speed(v, cs))
    df["time_min"] = df["duration_s"]/60.0
    df["distance_km"] = df["distance_m"]/1000.0
    df["week"] = df["start_time"].dt.isocalendar().year.astype(str) + "-W" + df["start_time"].dt.isocalendar().week.astype(str).str.zfill(2)
    agg = df.groupby(["week", "zone"], as_index=False).agg(
        time_min=("time_min", "sum"),
        distance_km=("distance_km", "sum"),
        sessions=("id", "count")
    )
    return agg.sort_values(["week","zone"]).reset_index(drop=True)

def compute_acwr(weekly_df: pd.DataFrame) -> pd.DataFrame:
    if weekly_df.empty:
        return pd.DataFrame(columns=["week", "time_min", "acute", "chronic", "acwr"])
    total = weekly_df.groupby("week", as_index=False)["time_min"].sum().sort_values("week")
    total["acute"] = total["time_min"]
    total["chronic"] = total["time_min"].shift(1).rolling(window=4, min_periods=1).mean()
    total["acwr"] = np.where(total["chronic"]>0, total["acute"]/total["chronic"], np.nan)
    return total