
import pandas as pd
import numpy as np

# Zone load per activity = mean_speed_in_zone (m/s) * time_in_zone_hours
def zone_loads(zone_tbl: pd.DataFrame) -> pd.DataFrame:
    z = zone_tbl.copy()
    z["time_h"] = z["time_s"] / 3600.0
    z["zone_load"] = z["mean_speed_flat"].fillna(0) * z["time_h"]
    return z[["zone_type","zone_label","zone_load"]]

def compute_daily_acwr(all_zone_entries: pd.DataFrame, day_col="day", athlete_col="athlete_id"):
    # all_zone_entries columns: athlete_id, day (date), zone_type, zone_label, zone_load
    df = all_zone_entries.sort_values([athlete_col, "zone_type","zone_label", day_col]).copy()
    acutes = []
    chronics = []
    ratios = []

    for key,grp in df.groupby([athlete_col, "zone_type","zone_label"]):
        g = grp.set_index(day_col).asfreq("D", fill_value=0.0)
        # Acute = last 7 days sum, Chronic = last 28 days average
        acute = g["zone_load"].rolling(7, min_periods=1).sum()
        chronic = g["zone_load"].rolling(28, min_periods=1).mean().replace(0, np.nan)
        ratio = acute / chronic
        out = g.assign(acute_load=acute, chronic_load=chronic, ratio=ratio)
        out = out.reset_index()
        out[athlete_col] = key[0]
        out["zone_type"] = key[1]
        out["zone_label"] = key[2]
        acutes.append(out)

    res = pd.concat(acutes, ignore_index=True)
    return res[[athlete_col, day_col, "zone_type","zone_label","acute_load","chronic_load","ratio"]]
