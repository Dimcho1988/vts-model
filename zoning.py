
from dataclasses import dataclass
import numpy as np
import pandas as pd
from typing import Dict, List, Tuple

@dataclass
class ZoneConfig:
    hrmax: int = 200
    hr_zones: Dict[str, Tuple[float,float]] = None
    speed_thresholds: Dict[str, float] = None  # in m/s flat-equivalent

    def __post_init__(self):
        if self.hr_zones is None:
            # Default (from your prefs)
            self.hr_zones = {
                "Z1": (0.60, 0.75),
                "Z2": (0.76, 0.80),
                "Z3": (0.81, 0.88),
                "Z4": (0.89, 0.95),
                "Z5": (0.95, 10.0),
            }
        if self.speed_thresholds is None:
            # Provide reasonable defaults; adjust to your CS, etc.
            # m/s numbers roughly for running; tune in UI
            self.speed_thresholds = {
                "Z1": 0.0,
                "Z2": 2.6,
                "Z3": 3.2,
                "Z4": 3.8,
                "Z5": 4.4,
            }

def label_hr_zone(hr: float, cfg: ZoneConfig) -> str:
    if np.isnan(hr): return "NA"
    r = hr / cfg.hrmax
    for z,(lo,hi) in cfg.hr_zones.items():
        if lo <= r <= hi:
            return z
    return "NA"

def label_speed_zone(vflat: float, cfg: ZoneConfig) -> str:
    # assumes thresholds are lower bounds; highest label where v >= bound
    last_label = "Z1"
    for z, bound in cfg.speed_thresholds.items():
        if vflat >= bound:
            last_label = z
    return last_label

def zone_tables(bin_df: pd.DataFrame, cfg: ZoneConfig):
    df = bin_df.copy()
    df["hr_zone"] = df["hr"].apply(lambda x: label_hr_zone(x, cfg))
    df["spd_zone"] = df["v_flat"].apply(lambda x: label_speed_zone(x, cfg))

    # seconds per row = 30
    df["secs"] = 30

    # Aggregations per zone (HR-based)
    hr_tbl = df.groupby("hr_zone").agg(
        time_s=("secs","sum"),
        mean_hr=("hr","mean"),
        mean_speed_flat=("v_flat","mean")
    ).reset_index().rename(columns={"hr_zone":"zone_label"})
    hr_tbl["zone_type"] = "hr"

    # Aggregations per zone (Speed-based)
    spd_tbl = df.groupby("spd_zone").agg(
        time_s=("secs","sum"),
        mean_hr=("hr","mean"),
        mean_speed_flat=("v_flat","mean")
    ).reset_index().rename(columns={"spd_zone":"zone_label"})
    spd_tbl["zone_type"] = "speed"

    return hr_tbl, spd_tbl
