"""Rotor model vs known UIUC data points, and the speed solver."""
import pytest

# Three tabulated points straight out of the cached UIUC Master Airscrew
# GF 7x4 files (2912cm_4014, 2914cm_6020, 2915cm_6998):
UIUC_POINTS = [
    # (J, CT, CP)
    (0.205, 0.0591, 0.0428),
    (0.310, 0.0534, 0.0371),
    (0.386, 0.0471, 0.0340),
]


@pytest.mark.parametrize("j,ct,cp", UIUC_POINTS)
def test_matches_uiuc_points(rotor, j, ct, cp):
    # tolerance covers the scatter between the overlapping RPM sweeps
    # (different Reynolds numbers) that the model averages across
    assert rotor.ct(j) == pytest.approx(ct, abs=0.010)
    assert rotor.cp(j) == pytest.approx(cp, abs=0.008)


def test_static_anchor(rotor):
    # static CT/CP at the high-RPM end of the UIUC static sweep
    assert 0.06 < rotor.ct(0.0) < 0.13
    assert 0.02 < rotor.cp(0.0) < 0.07


def test_solver_round_trip(rotor):
    rho = 1.225
    for thrust, v_ax in [(2.5, 0.0), (4.0, 2.0), (1.5, 5.0)]:
        n = rotor.solve_n(thrust, v_ax, rho)
        j = v_ax / (n * rotor.diameter)
        back = rho * n * n * rotor.diameter ** 4 * rotor.ct(j)
        assert back == pytest.approx(thrust, rel=1e-3)


def test_power_increases_with_thrust(rotor):
    rho = 1.225
    n1 = rotor.solve_n(2.0, 0.0, rho)
    n2 = rotor.solve_n(4.0, 0.0, rho)
    assert n2 > n1
    assert rotor.electrical_power(n2, 0.0, rho) > rotor.electrical_power(n1, 0.0, rho)
