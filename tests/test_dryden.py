"""Dryden turbulence: statistical properties match the MIL-F-8785C spec."""
import numpy as np

from airloom.dryden import dryden_gusts, dryden_params


def test_variance_matches_spec():
    # long sample so the sample variance converges
    n, dt, v, alt = 400_000, 0.01, 12.0, 30.0
    w20 = 15.43  # 'moderate', 30 kt
    _, _, sigma_u, sigma_w = dryden_params(alt, w20)
    gusts = dryden_gusts(n, dt, v, alt, w20, seed=99)
    var_u = gusts[0].var()
    var_v = gusts[1].var()
    var_w = gusts[2].var()
    assert abs(var_u - sigma_u ** 2) / sigma_u ** 2 < 0.12
    assert abs(var_v - sigma_u ** 2) / sigma_u ** 2 < 0.12  # sigma_v = sigma_u
    assert abs(var_w - sigma_w ** 2) / sigma_w ** 2 < 0.12


def test_zero_mean_and_time_correlation():
    gusts = dryden_gusts(100_000, 0.01, 12.0, 30.0, 15.43, seed=5)
    u = gusts[0]
    assert abs(u.mean()) < 0.15
    # one-step autocorrelation must be high (time-correlated, not white noise)
    r1 = np.corrcoef(u[:-1], u[1:])[0, 1]
    assert r1 > 0.95


def test_fixed_seed_is_reproducible():
    a = dryden_gusts(5_000, 0.01, 12.0, 30.0, 23.15, seed=101)
    b = dryden_gusts(5_000, 0.01, 12.0, 30.0, 23.15, seed=101)
    c = dryden_gusts(5_000, 0.01, 12.0, 30.0, 23.15, seed=102)
    assert np.array_equal(a, b)
    assert not np.array_equal(a, c)


def test_no_turbulence_is_zero():
    assert not dryden_gusts(100, 0.01, 12.0, 30.0, 0.0, seed=1).any()
