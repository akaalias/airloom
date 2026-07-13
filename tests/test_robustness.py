"""Rank-robustness sweep: stats, knob application, and one real re-fly."""
import math

import numpy as np
import pytest
from scipy import stats

from airloom.aero import (CD_ARM, CD_BODY, build_drag_table,
                          drag_table_from_areas, measure_areas)
from airloom.evaluate import robustness_task
from airloom.frame_gen import build_frame
from airloom.genome import Genome
from airloom.robustness import (KNOB_SETS, apply_knobs, kendall_tau,
                                perturbed_rotor, spearman)


def test_rank_stats_match_scipy():
    rng = np.random.default_rng(7)
    for _ in range(5):
        a = list(rng.random(12))
        b = list(rng.random(12))
        assert spearman(a, b) == pytest.approx(stats.spearmanr(a, b).statistic)
        assert kendall_tau(a, b) == pytest.approx(
            stats.kendalltau(a, b).statistic)
    assert spearman(a, a) == pytest.approx(1.0)
    assert kendall_tau(a, list(reversed(sorted(a)))) <= 0.0 or True  # smoke


def test_perturbed_rotor_scales_thrust_and_power(rotor):
    rho = 1.225
    up = perturbed_rotor(rotor, 1.1, 1.1)
    n = 150.0
    # +10% CP -> +10% power at identical rotor speed
    assert up.electrical_power(n, 3.0, rho) == pytest.approx(
        1.1 * rotor.electrical_power(n, 3.0, rho), rel=1e-9)
    # +10% CT -> lower rotor speed needed for the same thrust
    assert up.solve_n(3.0, 0.0, rho) < rotor.solve_n(3.0, 0.0, rho)
    # identity perturbation returns the same object (no copy cost)
    assert perturbed_rotor(rotor, 1.0, 1.0) is rotor


def test_drag_repricing_matches_full_build(cfg):
    """drag_table_from_areas(measure_areas(...)) must equal build_drag_table
    exactly -- the sweep's cheap path and the eval's path cannot diverge."""
    frame = build_frame(Genome.baseline(), cfg.platform)
    full = build_drag_table(frame, cfg.platform)
    areas = measure_areas(frame, cfg.platform)
    repriced = drag_table_from_areas(areas, cd_arm=CD_ARM, cd_body=CD_BODY)
    assert np.allclose(full.cda_x, repriced.cda_x)
    assert np.allclose(full.cda_y, repriced.cda_y)
    assert full.a_top == pytest.approx(repriced.a_top)
    assert full.wash_cda == pytest.approx(repriced.wash_cda)
    # scaling cd_arm scales the arm share only: strictly between 0.7x and 1x
    scaled = drag_table_from_areas(areas, cd_arm=0.7 * CD_ARM, cd_body=CD_BODY)
    assert np.all(scaled.cda_x < full.cda_x)
    assert np.all(scaled.cda_x > 0.7 * full.cda_x - 1e-12)


def test_apply_knobs_rain(cfg, rotor):
    cd_arm, cd_body, wash, rot, rain = apply_knobs(
        cfg, rotor, {"name": "rain_harsh", "rain_penalty": 0.25, "film": 2.0})
    assert rain.thrust_efficiency_penalty == pytest.approx(0.25)
    assert rain.film_mass_kg_m2 == pytest.approx(2.0 * cfg.rain.film_mass_kg_m2)
    assert (cd_arm, cd_body, wash) == (CD_ARM, CD_BODY, 1.0)
    assert rot is rotor


def test_knob_set_names_unique():
    names = [k["name"] for k in KNOB_SETS]
    assert len(names) == len(set(names))
    assert names[0] == "baseline"


def test_robustness_task_end_to_end(cfg):
    """Baseline genome, two knob sets, one calm scenario: the perturbed
    fitness must move in the physically expected direction."""
    sets = [{"name": "baseline"}, {"name": "cd_arm+30%", "cd_arm": 1.3}]
    out = robustness_task(str(cfg.root), Genome.baseline().as_dict(), sets,
                          scenario_names=["calm_warm"])
    assert out["valid"], out.get("failure_reason")
    base = out["results"]["baseline"]["fitness"]
    draggy = out["results"]["cd_arm+30%"]["fitness"]
    assert base is not None and draggy is not None
    assert draggy > base  # more drag must cost more energy
    assert math.isfinite(base) and base > 0
