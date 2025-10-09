from __future__ import annotations
import pandas as pd
import numpy as np
from typing import Dict, List

def to_utc(ts: pd.Series) -> pd.Series:
    try:
        return ts.dt.tz_convert("UTC")
    except Exception:
        try:
            return ts.dt.tz_localize("UTC")
        except Exception:
            return pd.to_datetime(ts, utc=True)

def compute_v_flat(df: pd.DataFrame, k: float = 6.0) -> pd.DataFrame:
    df = df.copy()
    df["dt"] = df["time"].diff().fillna(0.0)
    df["ds"] = df["distance"].diff().fillna(0.0)
    df["v"] = df["ds"] / df["dt"].replace(0, np.nan)
    df["elev_diff"] = df["altitude"].diff().fillna(0.0)
    df["grade"] = (df["elev_diff"] / df["ds"].replace(0, np.nan)).clip(-0.08, 0.08)
    df["v_flat"] = df["v"] / (1.0 + k * df["grade"].fillna(0.0))
    df["timestamp"] = to_utc(pd.to_datetime(df["timestamp"], utc=True))
    binned = df.set_index("timestamp").resample("30S").agg({
        "heartrate":"mean",
        "v_flat":"mean"
    }).dropna()
    binned = binned.rename(columns={"heartrate":"hr"})
    return binned.reset_index()
