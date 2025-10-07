
import json
import numpy as np
import pandas as pd
from dataclasses import dataclass
from typing import Dict, Any, Tuple

@dataclass
class HRSpeedModelConfig:
    ew_alpha: float = 0.2  # smoothing for coeffs
    init_slope: float = 0.02
    init_intercept: float = 0.0

@dataclass
class HRSpeedModelState:
    slope: float
    intercept: float

    def to_json(self):
        return json.dumps({"slope": self.slope, "intercept": self.intercept})

    @staticmethod
    def from_json(s: str):
        d = json.loads(s)
        return HRSpeedModelState(slope=d.get("slope", 0.02), intercept=d.get("intercept", 0.0))

def fit_linear(hr: np.ndarray, vflat: np.ndarray) -> Tuple[float,float]:
    # Simple linear fit v = a*HR + b
    X = np.vstack([hr, np.ones_like(hr)]).T
    a,b = np.linalg.lstsq(X, vflat, rcond=None)[0]
    return float(a), float(b)

def update_model(prev: HRSpeedModelState, hr_vals: np.ndarray, vflat_vals: np.ndarray, cfg: HRSpeedModelConfig):
    if len(hr_vals) < 3:
        return prev
    a,b = fit_linear(hr_vals, vflat_vals)
    # EW update
    slope = cfg.ew_alpha * a + (1-cfg.ew_alpha) * prev.slope
    intercept = cfg.ew_alpha * b + (1-cfg.ew_alpha) * prev.intercept
    return HRSpeedModelState(slope=slope, intercept=intercept)

def predict_speed(state: HRSpeedModelState, hr: float) -> float:
    return state.slope * hr + state.intercept

def fatigue_index_for_workout(state: HRSpeedModelState, avg_hr: float, avg_vflat: float) -> float:
    v_pred = predict_speed(state, avg_hr)
    return float(avg_vflat - v_pred)  # negative => slower than expected (fatigue)

def merge_with_cs(cs_value: float, fatigue_index: float, alpha: float = 1.0) -> float:
    return float(cs_value + alpha * fatigue_index)
