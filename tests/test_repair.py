"""Constraint repair: cheap geometry pre-screen + bisection back toward a
known-feasible parent, plus resampled (not blind) immigrants."""
import numpy as np

from airloom.evolution import (_is_feasible, _propose_immigrant, _repair,
                               propose_gen0, propose_next)
from airloom.genome import LOWER, RANGE, Genome


def _find_infeasible(rng: np.random.Generator, platform):
    for _ in range(500):
        g = Genome.random(rng)
        if not _is_feasible(g.array, platform):
            return g.array
    raise AssertionError("expected at least one infeasible random draw")


def test_baseline_is_feasible(cfg):
    assert _is_feasible(Genome.baseline().array, cfg.platform)


def test_repair_converts_infeasible_child_to_feasible(cfg):
    rng = np.random.default_rng(7)
    bad = _find_infeasible(rng, cfg.platform)
    assert not _is_feasible(bad, cfg.platform)
    repaired = _repair(bad, Genome.baseline().array, cfg.platform, max_steps=6)
    assert _is_feasible(repaired, cfg.platform)


def test_repair_is_a_noop_when_child_already_feasible(cfg):
    base = Genome.baseline().array
    out = _repair(base, base, cfg.platform, max_steps=6)
    assert np.array_equal(out, base)


def test_repair_is_a_noop_without_a_platform():
    rng = np.random.default_rng(3)
    child = Genome.random(rng).array
    assert _repair(child, Genome.baseline().array, None, max_steps=6) is child


def test_propose_immigrant_is_always_feasible_with_repair(cfg):
    rng = np.random.default_rng(11)
    for _ in range(50):
        p = _propose_immigrant(rng, cfg.platform, cfg.evolution.ga.repair)
        assert _is_feasible(p.genome.array, cfg.platform)
        assert p.operator == "immigrant"


def test_propose_immigrant_falls_back_to_a_baseline_perturbation(cfg):
    # zero resamples forces the fallback path on every call
    repair = cfg.evolution.ga.repair.__class__(
        enabled=True, max_bisect_steps=6, immigrant_max_resamples=0)
    rng = np.random.default_rng(11)
    p = _propose_immigrant(rng, cfg.platform, repair)
    assert _is_feasible(p.genome.array, cfg.platform)


def test_propose_immigrant_without_repair_is_a_blind_draw(cfg):
    rng_a = np.random.default_rng(42)
    rng_b = np.random.default_rng(42)
    p = _propose_immigrant(rng_a, None, None)
    assert np.array_equal(p.genome.array, Genome.random(rng_b).array)


def test_propose_gen0_with_platform_is_fully_feasible(cfg):
    rng = np.random.default_rng(21)
    props = propose_gen0(16, rng, platform=cfg.platform,
                         repair=cfg.evolution.ga.repair)
    assert len(props) == 16
    assert props[0].genome.hash == Genome.baseline().hash  # explicit seed kept
    assert all(_is_feasible(p.genome.array, cfg.platform) for p in props)


def test_propose_gen0_without_platform_matches_old_blind_behavior(cfg):
    rng = np.random.default_rng(21)
    props = propose_gen0(16, rng)
    assert len(props) == 16
    assert all(p.operator == "seed" for p in props)


def test_propose_next_with_platform_lifts_validity_of_bred_children(cfg):
    rng = np.random.default_rng(5)
    prev = []
    while len(prev) < 16:
        g = Genome.random(rng)
        if _is_feasible(g.array, cfg.platform):
            prev.append((g.hash, g, 6.0 + len(prev) * 0.05))
    props = propose_next(prev, 5, cfg.evolution.ga, rng, platform=cfg.platform)
    assert len(props) == 16
    non_elite = [p for p in props if p.operator != "elite"]
    assert non_elite  # sanity: the test actually exercises bred operators
    feasible = sum(_is_feasible(p.genome.array, cfg.platform) for p in non_elite)
    # repair does not GUARANTEE feasibility (bisection can exhaust its
    # budget against a parent sitting right at the constraint boundary),
    # but it should be the overwhelming majority -- nowhere near the
    # 37-90% invalid rates measured for the unrepaired operators.
    assert feasible / len(non_elite) >= 0.85


def test_propose_next_pivot_children_stay_within_the_gene_box(cfg):
    rng = np.random.default_rng(9)
    prev = []
    while len(prev) < 16:
        g = Genome.random(rng)
        if _is_feasible(g.array, cfg.platform):
            prev.append((g.hash, g, 6.0 + len(prev) * 0.05))
    far = [(h, g) for h, g, _ in prev[:5]]
    props = propose_next(prev, 15, cfg.evolution.ga, rng, pivot=1,
                         far_parents=far, platform=cfg.platform)
    for p in props:
        assert np.all(p.genome.array >= LOWER - 1e-9)
        assert np.all(p.genome.array <= LOWER + RANGE + 1e-9)
