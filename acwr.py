from __future__ import annotations
import pandas as pd

def compute_acwr(daily_df: pd.DataFrame):
    if daily_df.empty:
        return daily_df.assign(acute_7d=[], chronic_28d=[], acwr=[])
    df = daily_df.copy()
    df["date"] = pd.to_datetime(df["date"]).dt.date
    out = []
    for zone, sub in df.groupby("zone"):
        s = sub.set_index(pd.to_datetime(sub["date"])).sort_index()
        acute = s["workload"].rolling("7D").sum()
        chronic = s["workload"].rolling("28D").mean()
        acwr = acute / chronic.replace(0, pd.NA)
        tmp = s.copy()
        tmp["acute_7d"] = acute.values
        tmp["chronic_28d"] = chronic.values
        tmp["acwr"] = acwr.values
        tmp["zone"] = zone
        out.append(tmp.reset_index(drop=False).rename(columns={"index":"date"}))
    return pd.concat(out, ignore_index=True)
