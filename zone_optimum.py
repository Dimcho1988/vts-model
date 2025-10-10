from __future__ import annotations
from typing import Dict, List, Tuple
import pandas as pd
import numpy as np

from acwr import weekly_aggregates_with_vflat

def weekly_zone_optimum(workouts: List[Dict], cs: float, personal_curve: pd.DataFrame,
                        mean_vflat_map: Dict[int, float] | None = None,
                        k: float = 1.20) -> Tuple[pd.DataFrame, pd.DataFrame]:
    if personal_curve is None or personal_curve.empty:
        return (pd.DataFrame(columns=["week","zone","vbar_mps","topt_min","ttarget_min","treal_min","IZ"]),
                pd.DataFrame(columns=["week","I_total"]))

    agg = weekly_aggregates_with_vflat(workouts, cs, mean_vflat_map)
    if agg.empty:
        return (pd.DataFrame(columns=["week","zone","vbar_mps","topt_min","ttarget_min","treal_min","IZ"]),
                pd.DataFrame(columns=["week","I_total"]))

    agg = agg.copy()
    agg["vbar_mps"] = np.where(agg["time_min"]>0, (agg["distance_km"]*1000.0)/(agg["time_min"]*60.0), np.nan)

    sp = personal_curve["speed_mps_personal"].values.astype(float)
    ts = personal_curve["time_s"].values.astype(float)
    order = np.argsort(sp)
    sp_sorted = sp[order]; ts_sorted = ts[order]
    def t_opt_from_speed(v: float) -> float:
        if np.isnan(v):
            return np.nan
        v = float(v)
        if v <= sp_sorted[0]:
            return float(ts_sorted[0])
        if v >= sp_sorted[-1]:
            return float(ts_sorted[-1])
        return float(np.interp(v, sp_sorted, ts_sorted))

    agg["topt_min"] = agg["vbar_mps"].apply(lambda v: t_opt_from_speed(v)/60.0)
    agg["ttarget_min"] = k * agg["topt_min"]
    agg["treal_min"] = agg["time_min"]
    agg["IZ"] = np.where(agg["ttarget_min"]>0, agg["treal_min"]/agg["ttarget_min"] - 1.0, np.nan)

    detail = agg[["week","zone","vbar_mps","topt_min","ttarget_min","treal_min","IZ"]].sort_values(["week","zone"]).reset_index(drop=True)
    summ = (detail.groupby("week", as_index=False)["IZ"]
                  .mean(numeric_only=True)
                  .rename(columns={"IZ":"I_total"}))
    return detail, summ