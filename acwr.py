import pandas as pd
import numpy as np

def weekly_acwr(df):
    if df.empty:
        return pd.DataFrame()
    df["week_start"] = pd.to_datetime(df["date"]).dt.to_period("W").apply(lambda r: r.start_time)
    gp = df.groupby(["week_start", "zone"]).agg(
        time_min=("time_min", "sum"),
        distance_km=("distance_km", "sum")
    ).reset_index()
    total = gp.groupby("week_start")[["time_min","distance_km"]].sum().reset_index()
    total["zone"] = 0
    gp = pd.concat([gp, total], ignore_index=True).sort_values("week_start")
    # compute ACWR (acute: last week; chronic: avg of last 4 weeks)
    out_rows = []
    for z in sorted(gp["zone"].unique()):
        zdf = gp[gp["zone"]==z].copy()
        zdf = zdf.set_index("week_start").asfreq("W-MON").fillna(0).reset_index()
        zdf["acute"] = zdf["distance_km"].rolling(window=1).sum()
        zdf["chronic"] = zdf["distance_km"].rolling(window=4, min_periods=1).mean()
        zdf["acwr"] = zdf["acute"] / zdf["chronic"].replace({0: np.nan})
        zdf["zone"] = z
        out_rows.append(zdf[["week_start","zone","time_min","distance_km","acwr"]])
    out = pd.concat(out_rows, ignore_index=True)
    return out.sort_values(["week_start","zone"])
