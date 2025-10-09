
import pandas as pd
import numpy as np

class VTSCurve:
    def __init__(self, dist_km, time_min):
        self.dist_km = np.array(dist_km, dtype=float)
        self._t_id = np.array(time_min, dtype=float)

    def t_id(self, s):
        s = np.asarray(s, dtype=float)
        return np.interp(s, self.dist_km, self._t_id)

    @staticmethod
    def from_csv(path):
        df = pd.read_csv(path)
        return VTSCurve(df['dist_km'], df['time_min'])
