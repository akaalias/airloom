"""Patience: plateau detection and pivot breeding."""
import math

import numpy as np
import pytest

from framevo.evolution import (gens_since_significant_improvement, pivot_rank,
                               propose_next, select_far_parents)
from framevo.genome import Genome


def test_gens_since_significant_improvement():
    f = gens_since_significant_improvement
    assert f([7.0], 0.005) == 0
    assert f([7.0, 6.5, 6.4], 0.005) == 0          # improving every gen
    assert f([7.0, 6.5, 6.5, 6.5, 6.5], 0.005) == 3
    # sub-threshold jitter must NOT reset the clock
    assert f([7.0, 6.5, 6.499, 6.498, 6.497], 0.005) == 3
    # infinities (all-invalid generations) are skipped
    assert f([math.inf, math.inf, 7.0, 7.0], 0.005) == 1


def test_pivot_rank_grows_with_the_plateau(cfg):
    ga = cfg.evolution.ga
    n = ga.patience.generations
    flat = [7.0] + [7.0] * (n - 1)
    assert pivot_rank([7.0, 6.5], ga) == 0
    assert pivot_rank([6.5] + flat, ga) >= 1
    assert pivot_rank([6.5] + flat * 2, ga) >= 2


def test_far_parents_are_distant_but_decent():
    rng = np.random.default_rng(5)
    best = Genome.baseline()
    history = [(g.hash, g, 6.0 + i * 0.05)
               for i, g in enumerate(Genome.random(rng) for _ in range(30))]
    history.append((best.hash, best, 6.0))
    far = select_far_parents(history, best, 6.0, decent_factor=1.2)
    assert far and all(h != best.hash for h, _ in far)
    fits = {h: f for h, _, f in history}
    assert all(fits[h] <= 6.0 * 1.2 for h, _ in far)
    # they must actually be far away in gene space
    for _, g in far:
        assert np.linalg.norm(g.normalized - best.normalized) > 0.5


def test_pivot_generation_breeds_far_parents(cfg):
    rng = np.random.default_rng(9)
    prev = [(g.hash, g, 6.0 + i * 0.1)
            for i, g in enumerate(Genome.random(rng) for _ in range(10))]
    far = [(g.hash, g) for g in (Genome.random(rng) for _ in range(4))]
    props = propose_next(prev, 10, cfg.evolution.ga, rng, pivot=1,
                         far_parents=far)
    ops = [p.operator for p in props]
    n_pivot = ops.count("pivot")
    assert n_pivot == round(cfg.evolution.ga.patience.pivot_fraction
                            * (len(prev) - cfg.evolution.ga.elitism))
    far_hashes = {h for h, _ in far}
    assert all(p.parent_b in far_hashes for p in props if p.operator == "pivot")
    # escalated pivots use random genomes (no recorded second parent)
    props2 = propose_next(prev, 10, cfg.evolution.ga, rng, pivot=2,
                          far_parents=far)
    assert all(p.parent_b is None for p in props2 if p.operator == "pivot")


def test_no_pivot_without_flag(cfg):
    rng = np.random.default_rng(11)
    prev = [(g.hash, g, 6.0 + i * 0.1)
            for i, g in enumerate(Genome.random(rng) for _ in range(10))]
    props = propose_next(prev, 5, cfg.evolution.ga, rng)
    assert all(p.operator != "pivot" for p in props)