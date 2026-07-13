"""Champion verification: the refined variable-section + Kt + as-built
strength analysis must agree with closed-form beam theory on plain
geometry, and get strictly more pessimistic when holes pierce the shaft."""
import math

import numpy as np
import pytest

from framevo.champion import analyze_arm, morphed_front_arm
from framevo.config import Material
from framevo.genome import Genome
from framevo.realgeo import ArmOutline

CF = Material(name="cf_plate", density_kg_m3=1600.0,
              tensile_strength_pa=600.0e6, youngs_modulus_pa=70.0e9,
              as_built_strength_frac=1.0)
PETG = Material(name="petg", density_kg_m3=1270.0,
                tensile_strength_pa=50.0e6, youngs_modulus_pa=2.1e9,
                as_built_strength_frac=0.60)


def rect_arm(length_mm=140.0, width_mm=12.0, tongue=20.0,
             holes=()) -> ArmOutline:
    """Constant-width strip: tongue [0,20], shaft [20,120], mount [120,140],
    motor axis at x=130."""
    hw = width_mm / 2.0
    shell = np.array([[0.0, -hw], [length_mm, -hw],
                      [length_mm, hw], [0.0, hw]])
    return ArmOutline(name="test", shell=shell, holes=tuple(holes),
                      cutouts=(), tongue_end=tongue,
                      mount_start=length_mm - 20.0,
                      motor_xy=(length_mm - 10.0, 0.0))


def test_plain_rectangle_matches_closed_form():
    arm = rect_arm()
    t = 0.006
    p = 12.0  # N at the motor axis
    v = analyze_arm(arm, t, CF, p)
    # critical station = root (max moment), no Kt
    assert v.kt_crit == 1.0 and v.feature_crit == "plain section"
    assert v.x_crit_mm == pytest.approx(20.5, abs=1.0)
    lever = (130.0 - 20.5) * 1e-3
    i_bend = 0.012 * t ** 3 / 12.0
    sigma = p * lever * (t / 2.0) / i_bend
    assert v.stress_max_pa == pytest.approx(sigma, rel=0.03)
    # deflection at the load point, unit-load method: flexible shaft
    # [20, 120] mm, rigid mount overhang to the motor axis at 130 mm:
    # delta = P/(3EI) * ((L+a)^3 - a^3)
    e_i = CF.youngs_modulus_pa * i_bend
    l_plus_a = (130.0 - 20.0) * 1e-3
    a = (130.0 - 120.0) * 1e-3
    delta = p * (l_plus_a ** 3 - a ** 3) / (3 * e_i)
    assert v.tip_deflection_m == pytest.approx(delta, rel=0.05)


def test_hole_concentrates_stress():
    plain = analyze_arm(rect_arm(), 0.006, CF, 12.0)
    holed = analyze_arm(rect_arm(holes=((60.0, 0.0, 2.0),)), 0.006, CF, 12.0)
    assert holed.stress_max_pa > plain.stress_max_pa
    assert holed.margin < plain.margin
    # critical station moves to the hole despite the lower moment there
    assert holed.feature_crit == "hole/cutout"
    assert abs(holed.x_crit_mm - 60.0) < 2.5
    assert 2.0 < holed.kt_crit <= 3.0


def test_as_built_knockdown_scales_margin():
    arm = rect_arm()
    cf = analyze_arm(arm, 0.006, CF, 12.0)
    petg = analyze_arm(arm, 0.006, PETG, 12.0)
    # identical geometry and load -> identical stress; margins scale with
    # the as-built strength alone
    assert petg.stress_max_pa == pytest.approx(cf.stress_max_pa)
    expected = (PETG.tensile_strength_pa * 0.60) / cf.stress_max_pa
    assert petg.margin == pytest.approx(expected, rel=1e-6)


def test_real_baseline_arm_is_sound(cfg):
    """The actual Source One V6 6 mm carbon arm at a realistic flight load
    must come out comfortably safe -- if this fails, the refined model is
    broken, not the arm (the V6 flies)."""
    arm, t_m, material = morphed_front_arm(Genome.baseline().as_dict(), cfg)
    assert material.name == "cf_plate"
    v = analyze_arm(arm, t_m, material, 8.0 * cfg.platform.safety_factor,
                    cfg.platform.max_tip_deflection_frac)
    assert v.margin > 2.0
    assert v.tip_deflection_m < v.deflection_limit_m
    assert math.isfinite(v.predicted_failure_load_n)
    assert len(v.stations) > 100
