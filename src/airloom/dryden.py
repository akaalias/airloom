"""Dryden turbulence, MIL-F-8785C low-altitude forms.

Gust velocity time series are synthesized in the frequency domain: white
Gaussian spectral noise shaped by the exact Dryden PSDs, inverse-FFT'd to a
time-correlated series. The variance of each component equals the MIL-spec
sigma^2 (unit-tested), and a fixed per-scenario seed makes every candidate fly
the identical gust history.

Low-altitude scale lengths / intensities (h in feet, below 1000 ft):
    Lw = h,   Lu = Lv = h / (0.177 + 0.000823 h)^1.2
    sigma_w = 0.1 W20,  sigma_u = sigma_v = sigma_w / (0.177 + 0.000823 h)^0.4
where W20 is the wind speed at 20 ft (MIL-F-8785C: 15/30/45 kt for
light/moderate/severe intensity).
"""
from __future__ import annotations

import numpy as np

M_TO_FT = 3.28084


def dryden_params(altitude_m: float, w20_ms: float) -> tuple[float, float, float, float]:
    """(Lu, Lw, sigma_u, sigma_w) in meters / m/s."""
    h_ft = max(altitude_m, 3.0) * M_TO_FT
    denom = 0.177 + 0.000823 * h_ft
    lu_ft = h_ft / denom ** 1.2
    sigma_w = 0.1 * w20_ms
    sigma_u = sigma_w / denom ** 0.4
    return lu_ft / M_TO_FT, h_ft / M_TO_FT, sigma_u, sigma_w


def _spectral_series(n: int, dt: float, s_two_sided, rng: np.random.Generator) -> np.ndarray:
    """Time series whose two-sided PSD is s_two_sided(omega)."""
    freqs = np.fft.rfftfreq(n, dt)
    omega = 2.0 * np.pi * freqs
    d_omega = 2.0 * np.pi / (n * dt)
    mag = n * np.sqrt(s_two_sided(omega) * d_omega)
    phase = rng.standard_normal(len(omega)) + 1j * rng.standard_normal(len(omega))
    spec = mag * phase / np.sqrt(2.0)
    spec[0] = 0.0  # no DC component: gusts are zero-mean about the steady wind
    if n % 2 == 0:
        spec[-1] = spec[-1].real
    return np.fft.irfft(spec, n)


def dryden_gusts(n_steps: int, dt: float, airspeed: float, altitude_m: float,
                 w20_ms: float, seed: int) -> np.ndarray:
    """(3, n_steps) gust velocities [u along-wind, v cross-wind, w vertical].

    airspeed is the reference speed converting spatial to temporal spectra;
    we use the commanded cruise speed (documented simplification).
    """
    if w20_ms <= 0.0:
        return np.zeros((3, n_steps))
    v = max(airspeed, 1.0)
    lu, lw, sigma_u, sigma_w = dryden_params(altitude_m, w20_ms)
    lv, sigma_v = lu, sigma_u
    rng = np.random.default_rng(seed)

    def s_u(om: np.ndarray) -> np.ndarray:
        return sigma_u ** 2 * (lu / (np.pi * v)) / (1.0 + (lu * om / v) ** 2)

    def s_lateral(sigma: float, scale: float):
        def s(om: np.ndarray) -> np.ndarray:
            x = (scale * om / v) ** 2
            return sigma ** 2 * (scale / (2.0 * np.pi * v)) * (1.0 + 3.0 * x) / (1.0 + x) ** 2
        return s

    u = _spectral_series(n_steps, dt, s_u, rng)
    vv = _spectral_series(n_steps, dt, s_lateral(sigma_v, lv), rng)
    w = _spectral_series(n_steps, dt, s_lateral(sigma_w, lw), rng)
    return np.vstack([u, vv, w])
