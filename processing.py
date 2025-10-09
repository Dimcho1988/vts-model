import numpy as np
import pandas as pd

def vflat(speed_mps, grade, k=6.0):
    denom = (1.0 + k * grade)
    denom = np.where(denom == 0, 1e-6, denom)
    return speed_mps / denom

def bin_30s(df):
    df = df.sort_values("timestamp").copy()
    t0 = df["timestamp"].min()
    bins = ((df["timestamp"] - t0).dt.total_seconds() // 30).astype(int)
    df["bin"] = bins
    gp = df.groupby("bin")
    out = gp.agg(
        t_bin_start=("timestamp", "min"),
        mean_vflat=("speed_mps", lambda x: vflat(x.to_numpy(), df.loc[x.index, "grade"].to_numpy()).mean()),
        mean_hr=("hr", "mean")
    ).reset_index(drop=True)
    return out
