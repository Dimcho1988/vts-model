from __future__ import annotations
import numpy as np
import pandas as pd

# -------- Helpers --------
def _normalize_ideal(df: pd.DataFrame) -> pd.DataFrame:
    """
    Приема идеалната крива в какъвто и да е от следните формати и връща
    нормализиран DataFrame със стандартни колони:
      - distance_m
      - time_s
      - speed_mps
    Поддържани входни имена (както на твоя CSV):
      distance_km, time_min, time_h, speed_kmh
    """
    d = df.copy()

    # distance -> meters
    if "distance_m" in d.columns:
        pass
    elif "distance_km" in d.columns:
        d["distance_m"] = d["distance_km"] * 1000.0
    else:
        # ако няма дистанция, ще я сметнем от v*t по-долу
        d["distance_m"] = np.nan

    # time -> seconds
    if "time_s" in d.columns:
        pass
    else:
        if "time_min" in d.columns:
            d["time_s"] = d["time_min"] * 60.0
        elif "time_h" in d.columns:
            d["time_s"] = d["time_h"] * 3600.0
        else:
            d["time_s"] = np.nan

    # speed -> m/s
    if "speed_mps" in d.columns:
        pass
    elif "speed_kmh" in d.columns:
        d["speed_mps"] = d["speed_kmh"] / 3.6
    else:
        d["speed_mps"] = np.nan

    # изчисли липсващите к-сти, ако е възможно
    if d["speed_mps"].isna().any() and not d["distance_m"].isna().all() and not d["time_s"].isna().all():
        d["speed_mps"] = d["distance_m"] / d["time_s"]
    if d["distance_m"].isna().any() and not d["speed_mps"].isna().all() and not d["time_s"].isna().all():
        d["distance_m"] = d["speed_mps"] * d["time_s"]
    if d["time_s"].isna().any() and not d["distance_m"].isna().all() and not d["speed_mps"].isna().all():
        d["time_s"] = d["distance_m"] / d["speed_mps"]

    d = d[["distance_m", "time_s", "speed_mps"]].dropna().sort_values("time_s").reset_index(drop=True)
    return d


# -------- Core API used by app.py --------
def compute_cs(dist_3min: float, dist_12min: float, t1: float = 180.0, t2: float = 720.0) -> tuple[float, float]:
    """
    Класическа линейна регресия върху два теста:
        D = CS * t + W'
    Връща:
        cs (m/s), w_prime (m)
    """
    t = np.array([t1, t2], dtype=float)
    d = np.array([dist_3min, dist_12min], dtype=float)
    A = np.vstack([t, np.ones_like(t)]).T
    cs, w_prime = np.linalg.lstsq(A, d, rcond=None)[0]
    return float(cs), float(w_prime)


def build_personal_curve(ideal_df: pd.DataFrame, cs: float) -> pd.DataFrame:
    """
    Персонализира идеалната крива така, че асимптотично да клони към подадения CS.
    Правим проста скала на скоростите: намираме v_ideal при най-голямото време и
    умножаваме цялата крива по r = cs / v_ideal_end (за да съвпадне дългият сегмент).
    Връща DF с колони: time_s, speed_mps, speed_kmh.
    """
    base = _normalize_ideal(ideal_df)
    if base.empty:
        return pd.DataFrame(columns=["time_s", "speed_mps", "speed_kmh"])

    # скорост при най-голямото време от идеалната крива
    v_end = float(base.iloc[-1]["speed_mps"])
    if v_end <= 0 or not np.isfinite(v_end):
        v_end = float(base["speed_mps"].median())

    r = cs / v_end if v_end > 0 else 1.0
    v_personal = base["speed_mps"] * r

    out = pd.DataFrame({
        "time_s": base["time_s"].values,
        "speed_mps": v_personal.values,
    })
    out["speed_kmh"] = out["speed_mps"] * 3.6
    return out


def compute_zones(cs: float) -> pd.DataFrame:
    """
    Връща таблица със зони по скорост на база CS.
    """
    zones = {
        1: (0.60 * cs, 0.80 * cs),
        2: (0.80 * cs, 0.90 * cs),
        3: (0.90 * cs, 1.00 * cs),
        4: (1.00 * cs, 1.05 * cs),
        5: (1.05 * cs, 1.20 * cs),
    }
    zdf = pd.DataFrame([
        {"zone": z, "from_mps": a, "to_mps": b,
         "from_kmh": a * 3.6, "to_kmh": b * 3.6}
        for z, (a, b) in zones.items()
    ]).sort_values("zone")
    return zdf
