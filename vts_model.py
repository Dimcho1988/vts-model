from __future__ import annotations
from dataclasses import dataclass
import numpy as np
import pandas as pd

@dataclass
class VTSCurve:
    dist_km: np.ndarray
    time_min: np.ndarray

    @staticmethod
    def from_csv(path: str) -> "VTSCurve":
        df = pd.read_csv(path).sort_values("distance_km").dropna()
        return VTSCurve(df["distance_km"].to_numpy(), df["time_min"].to_numpy())

    def t_id(self, s_km: np.ndarray) -> np.ndarray:
        return np.interp(s_km, self.dist_km, self.time_min)

    def v_id(self, s_km: np.ndarray) -> np.ndarray:
        tmin = self.t_id(s_km)
        return 60.0 * s_km / np.maximum(tmin, 1e-9)
