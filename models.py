from __future__ import annotations
from typing import Tuple, Dict
import numpy as np
import pandas as pd

def fit_hr_v_linear(points: pd.DataFrame) -> Tuple[float, float]:
    df = points.dropna(subset=["mean_vflat", "mean_hr"]).copy()
    if len(df) < 2:
        raise ValueError("Need at least 2 points for regression.")
    a, b = np.polyfit(df["mean_vflat"].values, df["mean_hr"].values, 1)
    return float(a), float(b)

def compute_fi(points: pd.DataFrame, a: float, b: float) -> pd.DataFrame:
    df = points.copy()
    df["hr_pred"] = a * df["mean_vflat"] + b
    df["fi"] = np.where(df["hr_pred"] > 0, (df["mean_hr"] - df["hr_pred"]) / df["hr_pred"], np.nan)
    return df

def fi_summary(fi_df: pd.DataFrame) -> Dict[str, float]:
    return {
        "n": int(fi_df["fi"].notna().sum()),
        "fi_mean": float(fi_df["fi"].mean(skipna=True)) if "fi" in fi_df else float("nan"),
        "fi_median": float(fi_df["fi"].median(skipna=True)) if "fi" in fi_df else float("nan"),
    }