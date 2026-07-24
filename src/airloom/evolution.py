"""Optimizers.

Default: a genetic algorithm with explicit parentage -- full lineage tracking
is a first-class requirement. Every proposed individual records its parents,
the operator that produced it (seed / crossover / mutation / immigrant /
elite carry-over), and its mutation magnitude.

Alternative (flag-gated): a compact CMA-ES. CMA-ES samples from an adapted
Gaussian, so there are no discrete parents; distribution-level provenance
(mean and sigma per generation) is stored instead and the family tree is
skipped.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass

import numpy as np

from .config import GAParams, Platform, Repair
from .genome import LOWER, N_GENES, RANGE, Genome


@dataclass
class Proposal:
    genome: Genome
    parent_a: str | None
    parent_b: str | None
    operator: str
    mutation_mag: float | None


def generation_rng(base_seed: int, generation: int) -> np.random.Generator:
    """Deterministic per-generation RNG -> resume reproduces the same stream."""
    return np.random.default_rng(base_seed + 1000 * generation)


def propose_gen0(population: int, rng: np.random.Generator,
                 platform: Platform | None = None,
                 repair: Repair | None = None) -> list[Proposal]:
    """Seeded generation 0: the conventional X-frame baseline plus randoms.

    `platform`/`repair`: if given, random seeds are resampled against the
    cheap geometry pre-screen (see `_propose_immigrant`) instead of a
    single blind draw -- gen-0 randoms had a 73% invalid rate in practice."""
    out = [Proposal(Genome.baseline(), None, None, "seed", None)]
    while len(out) < population:
        out.append(_propose_immigrant(rng, platform, repair, operator="seed"))
    return out


def _tournament(pop: list[tuple[str, Genome, float]], k: int,
                rng: np.random.Generator) -> tuple[str, Genome, float]:
    picks = rng.integers(0, len(pop), size=k)
    return min((pop[i] for i in picks), key=lambda t: t[2])


def _sbx(a: np.ndarray, b: np.ndarray, eta: float,
         rng: np.random.Generator) -> np.ndarray:
    """Simulated binary crossover (one child)."""
    u = rng.random(N_GENES)
    beta = np.where(u <= 0.5,
                    (2.0 * u) ** (1.0 / (eta + 1.0)),
                    (1.0 / (2.0 * (1.0 - u))) ** (1.0 / (eta + 1.0)))
    child = 0.5 * ((1.0 + beta) * a + (1.0 - beta) * b)
    return np.clip(child, LOWER, LOWER + RANGE)


def _mutate(x: np.ndarray, sigma_frac: float, prob: float,
            rng: np.random.Generator) -> tuple[np.ndarray, float]:
    mask = rng.random(N_GENES) < prob
    if not mask.any():
        mask[rng.integers(0, N_GENES)] = True
    delta = rng.standard_normal(N_GENES) * sigma_frac * RANGE * mask
    mag = float(np.sqrt(np.mean((delta / RANGE) ** 2)))
    return np.clip(x + delta, LOWER, LOWER + RANGE), mag


def mutation_sigma(params: GAParams, generation: int) -> float:
    """Adaptive (decaying) mutation sigma as a fraction of each gene range."""
    return max(params.mutation_sigma0 * params.mutation_sigma_decay ** generation,
               params.mutation_sigma_min)


# ---------------------------------------------------------------------------
# Repair: hard constraints are pure geometry (no simulation, see
# frame_gen.build_frame(want_mesh=False)), so they are cheap to check BEFORE
# spending a population slot on a design they will reject anyway. This is
# the same pre-screen the Claude designer round already uses
# (designer.py:_prescreen, ~10% invalid there vs. 37-90% for the blind
# mechanical operators in run_20260714_015948) -- giving the rest of the
# operators the same trick.
# ---------------------------------------------------------------------------
def _is_feasible(values: np.ndarray, platform: Platform | None) -> bool:
    if platform is None:
        return True
    from .frame_gen import build_frame
    try:
        return build_frame(Genome.from_array(values), platform,
                           want_mesh=False).valid
    except Exception:
        return False


def _repair(child: np.ndarray, reference: np.ndarray, platform: Platform | None,
           max_steps: int) -> np.ndarray:
    """If `child` fails the cheap geometry pre-screen, bisect the segment
    back toward a known-feasible `reference` (its selected parent) until it
    passes, or give up after `max_steps` and fall all the way back to
    `reference`. A partial step toward the parent is still a novel,
    evaluable candidate -- unlike the discarded-slot status quo, no search
    budget is spent on a design geometry was always going to reject."""
    if platform is None or max_steps <= 0 or _is_feasible(child, platform):
        return child
    lo, hi = 0.0, 1.0  # blend fraction toward `reference`; hi stays feasible
    for _ in range(max_steps):
        mid = 0.5 * (lo + hi)
        blend = child + (reference - child) * mid
        if _is_feasible(blend, platform):
            hi = mid
        else:
            lo = mid
    return child + (reference - child) * hi


def _propose_immigrant(rng: np.random.Generator, platform: Platform | None,
                       repair: Repair | None, operator: str = "immigrant"
                       ) -> Proposal:
    """A uniform-random draw is ~90% infeasible in this tightly-constrained
    genome (run_20260714_015948 post-mortem). Resample within the box
    against the cheap pre-screen instead of accepting the first draw; if the
    box won't yield a feasible point in time, fall back to an exploratory
    perturbation of the known-good baseline (still novel, but not a near-
    certain waste)."""
    if platform is not None and repair is not None and repair.enabled:
        for _ in range(repair.immigrant_max_resamples):
            g = Genome.random(rng)
            if _is_feasible(g.array, platform):
                return Proposal(g, None, None, operator, None)
        base = Genome.baseline().array
        delta = rng.standard_normal(N_GENES) * 0.25 * RANGE
        perturbed = np.clip(base + delta, LOWER, LOWER + RANGE)
        # baseline is always feasible, so this is guaranteed to terminate
        # feasible (worst case: falls all the way back to baseline itself)
        repaired = _repair(perturbed, base, platform, repair.max_bisect_steps)
        return Proposal(Genome.from_array(repaired), None, None, operator, None)
    return Proposal(Genome.random(rng), None, None, operator, None)


# ---------------------------------------------------------------------------
# Patience: plateau detection + pivot breeding.
# ---------------------------------------------------------------------------
def gens_since_significant_improvement(best_per_gen: list[float],
                                       min_rel: float) -> int:
    """Generations elapsed since the best-so-far last improved by at least
    `min_rel` (relative). Derived purely from history -> resume-safe."""
    best = math.inf
    last_sig = 0
    for g, v in enumerate(best_per_gen):
        if not math.isfinite(v):
            continue
        if not math.isfinite(best) or (best - v) / best >= min_rel:
            last_sig = g
        best = min(best, v)
    return len(best_per_gen) - 1 - last_sig


def pivot_rank(best_per_gen: list[float], params: GAParams) -> int:
    """0 = no pivot; 1 = far-parent pivot; >=2 = escalated (random parents).
    Rank grows by one for each full patience window the plateau survives."""
    pt = params.patience
    if not pt.enabled or len(best_per_gen) < pt.generations:
        return 0
    stall = gens_since_significant_improvement(best_per_gen,
                                               pt.min_rel_improvement)
    return min(stall // pt.generations, 3)


def select_far_parents(history: list[tuple[str, Genome, float]],
                       best_genome: Genome, best_fitness: float,
                       decent_factor: float, k: int = 5) -> list[tuple[str, Genome]]:
    """The most genetically distant candidates in the run's history that are
    still decent (fitness within `decent_factor` of the best): the pool a
    pivot draws its replacement parent from."""
    ref = best_genome.normalized
    pool = [(h, g, float(np.linalg.norm(g.normalized - ref)))
            for h, g, f in history
            if math.isfinite(f) and f <= best_fitness * decent_factor
            and g.hash != best_genome.hash]
    pool.sort(key=lambda t: -t[2])
    return [(h, g) for h, g, _ in pool[:k]]


def propose_next(prev: list[tuple[str, Genome, float]], generation: int,
                 params: GAParams, rng: np.random.Generator,
                 pivot: int = 0,
                 far_parents: list[tuple[str, Genome]] | None = None,
                 platform: Platform | None = None
                 ) -> list[Proposal]:
    """prev: (hash, genome, fitness) of the previous generation's population.

    pivot > 0 turns this into a pivot generation: `pivot_fraction` of the
    non-elite slots are bred by crossing a tournament winner with a FAR
    parent (rank 1: a distant-but-decent candidate from `far_parents`;
    rank >= 2: a fully random genome), with mutation sigma boosted.

    `platform`: if given (and `params.repair.enabled`), every bred child is
    passed through the cheap geometry pre-screen (see `_repair`) and
    immigrants are resampled instead of drawn blind (see
    `_propose_immigrant`). Omit to reproduce the pre-repair GA exactly
    (existing tests rely on this)."""
    population = len(prev)
    ranked = sorted(prev, key=lambda t: t[2])
    sigma = mutation_sigma(params, generation)
    pt = params.patience
    rp = params.repair
    pivot_sigma = min(max(sigma * pt.sigma_boost, sigma), 0.30)
    max_steps = rp.max_bisect_steps if rp.enabled else 0

    out: list[Proposal] = []
    seen: set[str] = set()
    for h, g, _ in ranked[:params.elitism]:  # elite carry-over, unchanged
        out.append(Proposal(g, h, None, "elite", None))
        seen.add(g.hash)

    n_pivot = round(pt.pivot_fraction * (population - len(out))) if pivot else 0

    attempts = 0
    while len(out) < population:
        attempts += 1
        if n_pivot > 0:
            pa = _tournament(prev, params.tournament_k, rng)
            if pivot == 1 and far_parents:
                pb_hash, pb_genome = far_parents[int(rng.integers(0, len(far_parents)))]
            else:  # escalated (or no history to draw from): random far parent
                pb_hash, pb_genome = None, Genome.random(rng)
            child = _sbx(pa[1].array, pb_genome.array, params.sbx_eta, rng)
            child, mag = _mutate(child, pivot_sigma,
                                 params.mutation_prob_per_gene, rng)
            child = _repair(child, pa[1].array, platform, max_steps)
            prop = Proposal(Genome.from_array(child), pa[0], pb_hash, "pivot", mag)
        elif rng.random() < params.immigrant_prob:
            prop = _propose_immigrant(rng, platform, rp)
        elif rng.random() < params.crossover_prob:
            pa = _tournament(prev, params.tournament_k, rng)
            pb = _tournament(prev, params.tournament_k, rng)
            child = _sbx(pa[1].array, pb[1].array, params.sbx_eta, rng)
            child, mag = _mutate(child, sigma, params.mutation_prob_per_gene, rng)
            child = _repair(child, pa[1].array, platform, max_steps)
            prop = Proposal(Genome.from_array(child), pa[0], pb[0], "crossover", mag)
        else:
            pa = _tournament(prev, params.tournament_k, rng)
            child, mag = _mutate(pa[1].array, sigma,
                                 params.mutation_prob_per_gene, rng)
            child = _repair(child, pa[1].array, platform, max_steps)
            prop = Proposal(Genome.from_array(child), pa[0], None, "mutation", mag)
        h = prop.genome.hash
        if h in seen and attempts < 20 * population:
            continue  # duplicates waste evaluations; retry
        seen.add(h)
        out.append(prop)
        if prop.operator == "pivot":
            n_pivot -= 1
    return out


# ---------------------------------------------------------------------------
# Compact CMA-ES (Hansen's (mu/mu_w, lambda) formulation) in normalized space.
# ---------------------------------------------------------------------------
class CmaEs:
    def __init__(self, x0: np.ndarray, sigma0: float, population: int):
        self.n = len(x0)
        self.mean = x0.astype(float)
        self.sigma = sigma0
        self.lam = max(population, 4)
        self.mu = self.lam // 2
        w = np.log(self.mu + 0.5) - np.log(np.arange(1, self.mu + 1))
        self.weights = w / w.sum()
        self.mueff = 1.0 / float(np.sum(self.weights ** 2))
        n = self.n
        self.cc = (4 + self.mueff / n) / (n + 4 + 2 * self.mueff / n)
        self.cs = (self.mueff + 2) / (n + self.mueff + 5)
        self.c1 = 2 / ((n + 1.3) ** 2 + self.mueff)
        self.cmu = min(1 - self.c1,
                       2 * (self.mueff - 2 + 1 / self.mueff) / ((n + 2) ** 2 + self.mueff))
        self.damps = 1 + 2 * max(0.0, math.sqrt((self.mueff - 1) / (n + 1)) - 1) + self.cs
        self.pc = np.zeros(n)
        self.ps = np.zeros(n)
        self.cov = np.eye(n)
        self.chi_n = math.sqrt(n) * (1 - 1 / (4 * n) + 1 / (21 * n * n))
        self.counteval = 0

    def ask(self, rng: np.random.Generator) -> list[np.ndarray]:
        d, b = np.linalg.eigh(self.cov)
        d = np.sqrt(np.maximum(d, 1e-14))
        self._bd = b * d
        return [np.clip(self.mean + self.sigma * (self._bd @ rng.standard_normal(self.n)),
                        0.0, 1.0) for _ in range(self.lam)]

    def tell(self, xs: list[np.ndarray], fitnesses: list[float]) -> None:
        self.counteval += self.lam
        order = np.argsort(fitnesses)
        sel = np.array([xs[i] for i in order[:self.mu]])
        old_mean = self.mean.copy()
        self.mean = self.weights @ sel

        d, b = np.linalg.eigh(self.cov)
        d = np.sqrt(np.maximum(d, 1e-14))
        inv_sqrt = b @ np.diag(1.0 / d) @ b.T
        y = (self.mean - old_mean) / self.sigma
        self.ps = (1 - self.cs) * self.ps + \
            math.sqrt(self.cs * (2 - self.cs) * self.mueff) * (inv_sqrt @ y)
        hsig = float(np.linalg.norm(self.ps)) / \
            math.sqrt(1 - (1 - self.cs) ** (2 * self.counteval / self.lam)) / self.chi_n < \
            1.4 + 2 / (self.n + 1)
        self.pc = (1 - self.cc) * self.pc + \
            (math.sqrt(self.cc * (2 - self.cc) * self.mueff) * y if hsig else 0.0)
        artmp = (sel - old_mean) / self.sigma
        self.cov = (1 - self.c1 - self.cmu) * self.cov \
            + self.c1 * (np.outer(self.pc, self.pc)
                         + (0.0 if hsig else self.c1 * self.cc * (2 - self.cc)) * self.cov) \
            + self.cmu * artmp.T @ (self.weights[:, None] * artmp)
        self.sigma *= math.exp((self.cs / self.damps)
                               * (float(np.linalg.norm(self.ps)) / self.chi_n - 1))
        self.sigma = float(min(max(self.sigma, 1e-4), 1.0))

    def state_json(self) -> str:
        return json.dumps({
            "mean": self.mean.tolist(), "sigma": self.sigma,
            "cov": self.cov.tolist(), "pc": self.pc.tolist(),
            "ps": self.ps.tolist(), "counteval": self.counteval,
        })

    @staticmethod
    def from_state_json(s: str, population: int) -> "CmaEs":
        d = json.loads(s)
        es = CmaEs(np.array(d["mean"]), d["sigma"], population)
        es.cov = np.array(d["cov"])
        es.pc = np.array(d["pc"])
        es.ps = np.array(d["ps"])
        es.counteval = d["counteval"]
        return es
