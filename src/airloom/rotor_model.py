"""Rotor thrust/power from cached UIUC measured coefficient tables.

Ground truth: UIUC Propeller Database (M. Selig et al.), GWS Direct Drive
5x4.3 -- one static file (CT, CP vs RPM) and four dynamic sweeps (CT, CP vs
advance ratio J at ~4k/6k/8k RPM). We merge the sweeps with the high-RPM end
of the static data as the J=0 anchor, fit smooth CT(J)/CP(J) polynomials, and
sample them onto a dense grid for fast lookup inside the 100 Hz simulator.

Conventions: T = rho n^2 D^4 CT(J), P_shaft = rho n^3 D^5 CP(J), J = V/(nD),
n in rev/s. Electrical power = shaft / (motor+ESC efficiency).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .config import Propulsion

_GRID_N = 512


def _read_table(path: Path) -> np.ndarray:
    rows = []
    for line in path.read_text().splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 3:
            try:
                rows.append([float(x) for x in parts[:3]])
            except ValueError:
                continue
    return np.array(rows)


@dataclass
class RotorModel:
    diameter: float
    efficiency: float
    max_rps: float
    max_motor_power_w: float
    j_grid: np.ndarray
    ct_grid: np.ndarray
    cp_grid: np.ndarray
    ct_static: float
    cp_static: float
    # merged raw measurement points (for tests / provenance)
    raw_j: np.ndarray
    raw_ct: np.ndarray
    raw_cp: np.ndarray

    @staticmethod
    def from_platform(prop: Propulsion) -> "RotorModel":
        ddir = prop.uiuc_data_dir
        static = _read_table(ddir / prop.uiuc_static_file)  # RPM, CT, CP
        # take the high-RPM half of the static sweep: closest Reynolds number
        # to our 12k-20k RPM operating band
        upper = static[static[:, 0] >= np.median(static[:, 0])]
        ct0, cp0 = float(upper[:, 1].mean()), float(upper[:, 2].mean())

        js, cts, cps = [0.0], [ct0], [cp0]
        for name in prop.uiuc_dynamic_files:
            tab = _read_table(ddir / name)  # J, CT, CP
            js.extend(tab[:, 0]); cts.extend(tab[:, 1]); cps.extend(tab[:, 2])
        raw_j, raw_ct, raw_cp = (np.array(js), np.array(cts), np.array(cps))

        # weight the single static anchor as strongly as one full sweep
        w = np.ones_like(raw_j)
        w[0] = 20.0
        ct_fit = np.polynomial.Polynomial.fit(raw_j, raw_ct, deg=3, w=w)
        cp_fit = np.polynomial.Polynomial.fit(raw_j, raw_cp, deg=3, w=w)

        j_grid = np.linspace(0.0, 1.0, _GRID_N + 1)
        ct_grid = np.maximum(ct_fit(j_grid), 1e-4)
        cp_grid = np.maximum(cp_fit(j_grid), 1e-4)
        # beyond the measured range the cubic is extrapolation; freeze the
        # slope direction so it stays monotone-decreasing (conservative)
        jmax = float(raw_j.max())
        mask = j_grid > jmax
        ct_grid[mask] = np.minimum.accumulate(ct_grid)[mask]
        cp_grid[mask] = np.minimum.accumulate(cp_grid)[mask]

        return RotorModel(
            diameter=prop.prop_diameter_m, efficiency=prop.motor_esc_efficiency,
            max_rps=prop.max_rps, max_motor_power_w=prop.max_motor_power_w,
            j_grid=j_grid, ct_grid=ct_grid, cp_grid=cp_grid,
            ct_static=ct0, cp_static=cp0,
            raw_j=raw_j, raw_ct=raw_ct, raw_cp=raw_cp,
        )

    # -- fast scalar lookups (used ~10^5 times per scenario) ---------------
    def ct(self, j: float) -> float:
        if j <= 0.0:
            return float(self.ct_grid[0])
        x = j * _GRID_N
        if x >= _GRID_N:
            return float(self.ct_grid[-1])
        i = int(x)
        f = x - i
        return float(self.ct_grid[i] * (1.0 - f) + self.ct_grid[i + 1] * f)

    def cp(self, j: float) -> float:
        if j <= 0.0:
            return float(self.cp_grid[0])
        x = j * _GRID_N
        if x >= _GRID_N:
            return float(self.cp_grid[-1])
        i = int(x)
        f = x - i
        return float(self.cp_grid[i] * (1.0 - f) + self.cp_grid[i + 1] * f)

    def solve_n(self, thrust: float, v_axial: float, rho: float,
                ct_scale: float = 1.0, n_guess: float | None = None) -> float:
        """Rotor speed (rev/s) so that rho n^2 D^4 CT(v_ax/(nD)) * ct_scale
        equals the requested thrust. Newton with a numeric derivative."""
        d4 = self.diameter ** 4
        k = rho * d4 * ct_scale
        n = n_guess if n_guess and n_guess > 1.0 else \
            math.sqrt(max(thrust, 1e-6) / (k * self.ct_grid[0]))
        for _ in range(4):
            j = v_axial / (n * self.diameter)
            f = k * n * n * self.ct(j) - thrust
            dn = max(n * 1e-4, 1e-6)
            j2 = v_axial / ((n + dn) * self.diameter)
            df = (k * (n + dn) ** 2 * self.ct(j2) - thrust - f) / dn
            if abs(df) < 1e-12:
                break
            step = f / df
            n = min(max(n - step, 5.0), self.max_rps * 2.0)
        return n

    def electrical_power(self, n: float, v_axial: float, rho: float) -> float:
        j = v_axial / (n * self.diameter)
        return rho * n ** 3 * self.diameter ** 5 * self.cp(j) / self.efficiency

    def hover(self, total_mass: float, rho: float, g: float = 9.80665,
              ct_scale: float = 1.0) -> tuple[float, float]:
        """(rotor speed rev/s, total electrical power W) at static hover."""
        t_per = total_mass * g / 4.0
        n = self.solve_n(t_per, 0.0, rho, ct_scale=ct_scale)
        return n, 4.0 * self.electrical_power(n, 0.0, rho)
