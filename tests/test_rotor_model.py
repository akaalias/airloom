"""Rotor model vs known UIUC data points, and the speed solver."""
import pytest

# Three tabulated points straight out of the cached UIUC files
# (gwsdd_5x4.3_0512rd_6047.txt and gwsdd_5x4.3_0513rd_8044.txt):
UIUC_POINTS = [
    # (J, CT, CP)
    (0.094683, 0.144527, 0.077400),
    (0.377480, 0.097216, 0.065253),
    (0.478503, 0.082714, 0.061436),
]


@pytest.mark.parametrize("j,ct,cp", UIUC_POINTS)
def test_matches_uiuc_points(rotor, j, ct, cp):
    # tolerance covers the scatter between the overlapping RPM sweeps that
    # the model averages across
    assert rotor.ct(j) == pytest.approx(ct, abs=0.010)
    assert rotor.cp(j) == pytest.approx(cp, abs=0.008)


def test_static_anchor(rotor):
    # static CT/CP at the high-RPM end of the UIUC static sweep
    assert 0.10 < rotor.ct(0.0) < 0.20
    assert 0.05 < rotor.cp(0.0) < 0.11


def test_solver_round_trip(rotor):
    rho = 1.225
    for thrust, v_ax in [(2.0, 0.0), (3.5, 2.0), (1.0, 5.0)]:
        n = rotor.solve_n(thrust, v_ax, rho)
        j = v_ax / (n * rotor.diameter)
        back = rho * n * n * rotor.diameter ** 4 * rotor.ct(j)
        assert back == pytest.approx(thrust, rel=1e-3)


def test_power_increases_with_thrust(rotor):
    rho = 1.225
    n1 = rotor.solve_n(1.5, 0.0, rho)
    n2 = rotor.solve_n(3.0, 0.0, rho)
    assert n2 > n1
    assert rotor.electrical_power(n2, 0.0, rho) > rotor.electrical_power(n1, 0.0, rho)
