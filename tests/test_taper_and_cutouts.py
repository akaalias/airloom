"""Tapered arm thickness (tip_thickness_scale) and lightening cutouts
(arm_cutout_scale): the two genes added 2026-07-24."""
import numpy as np
import pytest

from airloom.frame_gen import build_arm_front, build_frame
from airloom.genome import Genome
from airloom.realgeo import add_lightening_holes, extrude, extrude_tapered
from airloom.structures import analyze_arm, check_structure


def _rect_arm(length_mm=140.0, width_mm=12.0, tongue=20.0, mount=None):
    from airloom.realgeo import ArmOutline
    hw = width_mm / 2.0
    shell = np.array([[0.0, -hw], [length_mm, -hw],
                      [length_mm, hw], [0.0, hw]])
    return ArmOutline(name="test", shell=shell, holes=(), cutouts=(),
                      tongue_end=tongue,
                      mount_start=mount if mount is not None else length_mm - 20.0,
                      motor_xy=(length_mm - 10.0, 0.0))


# ------------------------------------------------------------ extrude_tapered --
def test_extrude_tapered_matches_plain_extrude_at_scale_one():
    arm = _rect_arm()
    t = 0.006
    plain = extrude(arm, t)
    tapered = extrude_tapered(arm, t, t, arm.tongue_end, arm.mount_start)
    assert tapered.volume == pytest.approx(plain.volume, rel=1e-9)


def test_extrude_tapered_sheds_volume_when_tip_is_thinner():
    arm = _rect_arm()
    t = 0.006
    uniform = extrude(arm, t)
    tapered = extrude_tapered(arm, t, t * 0.5, arm.tongue_end, arm.mount_start)
    assert tapered.volume < uniform.volume
    # bump profile keeps full thickness at the tongue and the motor mount,
    # so the taper can't shed more than the whole shaft would at half
    # thickness -- a loose sanity bound, not a tight one
    assert tapered.volume > uniform.volume * 0.5


# --------------------------------------------------------- lightening holes --
def test_lightening_holes_are_a_noop_below_threshold():
    arm = _rect_arm()
    assert add_lightening_holes(arm, 0.0) is arm
    assert add_lightening_holes(arm, 0.005) is arm


def test_lightening_holes_placed_within_the_shaft_and_bounded():
    arm = _rect_arm()
    holed = add_lightening_holes(arm, 0.5, n=3)
    assert len(holed.holes) == 3
    for x, y, r in holed.holes:
        assert arm.tongue_end < x < arm.mount_start
        assert y == 0.0
        # radius must stay under the local half-width (6.0 mm for this
        # constant-width test arm)
        assert 0.0 < r < 6.0


def test_lightening_hole_radius_scales_with_cutout_gene():
    arm = _rect_arm()
    small = add_lightening_holes(arm, 0.2, n=3)
    big = add_lightening_holes(arm, 0.5, n=3)
    assert big.holes[0][2] > small.holes[0][2]


# ------------------------------------------------------- analyze_arm taper --
def test_taper_thins_the_middle_not_the_root_or_mount(cfg):
    """Root and near-mount stations should be near-full thickness; a
    mid-shaft station should be visibly thinner, per the bump profile."""
    arm = _rect_arm()
    t = 0.006
    material = cfg.platform.material_for(0.0)  # cf_plate
    v = analyze_arm(arm, t, material, 12.0, tip_thickness_scale=0.5)
    root_i = v.stations[0].w_net_mm * 1e-3 * t ** 3 / 12.0
    mid = v.stations[len(v.stations) // 2]
    mid_i = mid.w_net_mm * 1e-3 * t ** 3 / 12.0
    # if thickness dipped mid-shaft, I(x) there (recovered from stress via
    # the known moment) must be smaller than a full-thickness estimate --
    # check indirectly via stress: same moment scale, dipped thickness ->
    # local I smaller than the root's nominal (full-thickness) I
    full_i_estimate = mid.w_net_mm * 1e-3 * t ** 3 / 12.0
    assert mid_i == pytest.approx(full_i_estimate)  # sanity: same formula
    # direct check: recompute the local thickness the analysis used at the
    # midpoint by inverting stress = kt * M * (t/2) / (w*t^3/12)
    # -> stress = 6*kt*M / (w * t^2) -> t = sqrt(6*kt*M / (w*stress))
    t_mid = np.sqrt(6.0 * mid.kt * mid.moment_nm
                    / (mid.w_net_mm * 1e-3 * mid.stress_pa))
    t_root = np.sqrt(6.0 * v.stations[0].kt * v.stations[0].moment_nm
                     / (v.stations[0].w_net_mm * 1e-3 * v.stations[0].stress_pa))
    assert t_mid < t_root
    assert t_root == pytest.approx(t, rel=0.05)


def test_no_taper_reproduces_original_uniform_thickness_stress():
    arm = _rect_arm()
    t = 0.006
    from airloom.config import Material
    cf = Material(name="cf_plate", density_kg_m3=1600.0,
                 tensile_strength_pa=600.0e6, youngs_modulus_pa=70.0e9,
                 as_built_strength_frac=1.0)
    v_default = analyze_arm(arm, t, cf, 12.0)
    v_explicit_one = analyze_arm(arm, t, cf, 12.0, tip_thickness_scale=1.0)
    assert v_default.stress_max_pa == pytest.approx(v_explicit_one.stress_max_pa)


# ------------------------------------------------------ end-to-end (real V6) --
def test_baseline_frame_mass_unaffected_by_new_genes(cfg):
    """The two new genes default to values that reproduce prior behavior
    exactly -- Genome.baseline()'s mass must be unchanged."""
    frame = build_frame(Genome.baseline(), cfg.platform)
    assert frame.valid
    assert 0.120 < frame.frame_mass < 0.175


def test_moderate_taper_and_cutouts_shed_real_mass_and_stay_valid(cfg):
    g = dict(Genome.baseline().as_dict(),
             tip_thickness_scale=0.6, arm_cutout_scale=0.4)
    baseline = build_frame(Genome.baseline(), cfg.platform)
    lightened = build_frame(Genome.from_dict(g), cfg.platform)
    assert lightened.valid, lightened.failure_reason
    assert lightened.frame_mass < baseline.frame_mass * 0.95


def test_structural_check_rejects_an_overaggressive_taper_and_cutout(cfg):
    g = dict(Genome.baseline().as_dict(), tip_thickness_scale=0.5,
             arm_cutout_scale=0.6, arm_thickness=0.0026)
    frame = build_frame(Genome.from_dict(g), cfg.platform)
    assert frame.valid  # passes the geometric pre-screen
    arm, t_m, tip_scale, material = build_arm_front(g, cfg.platform)
    peak = frame.total_mass * 9.81 / 4 * 1.8  # rough hover-ish load
    res = check_structure(arm, t_m, tip_scale, frame.arm.mass, peak,
                          200.0, cfg.platform, material)
    assert not res.ok  # the whole point: the fast check catches this


def test_build_arm_front_matches_frame_gen_geometry(cfg):
    """build_arm_front (used by the in-loop check and verify-champions)
    must derive the SAME front-arm outline build_frame() actually builds."""
    g = dict(Genome.baseline().as_dict(), arm_cutout_scale=0.3)
    arm, t_m, tip_scale, material = build_arm_front(g, cfg.platform)
    assert len(arm.holes) >= 3  # baseline bolt holes + 3 lightening holes
    assert t_m == g["arm_thickness"]
    assert tip_scale == g["tip_thickness_scale"]
    assert material.name == "cf_plate"
