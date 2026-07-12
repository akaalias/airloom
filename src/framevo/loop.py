"""The unattended, resumable research loop: propose -> evaluate -> persist ->
regenerate artifacts, generation after generation.

Crash-safety model: candidate rows are written only when their evaluation is
complete; the per-generation `populations` rows are the resume anchor. On
`--resume`, the loop restarts from the first generation without a stored
population, re-using every already-evaluated candidate via the genome-hash
cache (identical genome -> identical fitness, since scenario seeds are fixed).
"""
from __future__ import annotations

import json
import math
import shutil
import statistics
import time
from dataclasses import asdict
from pathlib import Path

from . import gallery as gallery_mod
from . import lineage as lineage_mod
from .config import Config
from .dbstore import CandidateRow, Store
from .evolution import CmaEs, Proposal, generation_rng, propose_gen0, propose_next
from .genome import Genome
from .parallel import run_tasks

SCENARIO_ORDER_KEY = "calm_warm"  # flown first when early-reject is enabled


def _log(msg: str) -> None:
    print(f"[framevo] {msg}", flush=True)


class EvolutionLoop:
    def __init__(self, cfg: Config, run_id: str, resume: bool = False):
        self.cfg = cfg
        self.run_id = run_id
        self.results = cfg.evolution.results_dir
        self.results.mkdir(parents=True, exist_ok=True)
        self.store = Store(self.results / "run.db")
        self.root = str(cfg.root)
        ev = cfg.evolution

        existing = self.store.get_run(run_id)
        if existing is None:
            snapshot = json.dumps({
                "population": ev.population, "generations": ev.generations,
                "optimizer": ev.optimizer, "seed": ev.seed,
                "aggregation": asdict(cfg.aggregation),
                "early_reject": asdict(cfg.early_reject),
                "mission": asdict(cfg.mission),
                "scenarios": [s.name for s in cfg.scenarios],
            })
            self.store.create_run(run_id, ev.seed, ev.optimizer, ev.population,
                                  ev.generations, snapshot, cfg.root)
            self.start_gen = 0
        elif resume:
            done = self.store.generations_with_population(run_id)
            self.start_gen = (max(done) + 1) if done else 0
            _log(f"resuming run '{run_id}' at generation {self.start_gen}")
        else:
            raise SystemExit(
                f"run '{run_id}' already exists in {self.results / 'run.db'};"
                " use --resume to continue it or pick another --run-id")

    # ------------------------------------------------------------------ run --
    def run(self) -> None:
        ev = self.cfg.evolution
        cmaes = self._restore_cmaes() if ev.optimizer == "cmaes" else None

        for gen in range(self.start_gen, ev.generations):
            t0 = time.time()
            rng = generation_rng(ev.seed, gen)

            if cmaes is not None:
                xs = cmaes.ask(rng)
                proposals = [Proposal(Genome.from_normalized(x), None, None,
                                      "cmaes", cmaes.sigma) for x in xs]
            elif gen == 0:
                proposals = propose_gen0(ev.population, rng)
            else:
                prev = self._load_population(gen - 1)
                proposals = propose_next(prev, gen, ev.ga, rng)

            entries = self._evaluate_generation(gen, proposals)

            if cmaes is not None:
                cmaes.tell([p.genome.normalized for p in proposals],
                           [f for _, f in entries])
                self.store.save_cma_state(self.run_id, gen,
                                          cmaes.mean.tolist(), cmaes.sigma,
                                          cmaes.state_json())

            self.store.set_population(self.run_id, gen, entries)
            self.store.mark_generation_done(self.run_id, gen)
            self._write_artifacts(gen)

            finite = [f for _, f in entries if math.isfinite(f)]
            best = min(finite) if finite else math.inf
            _log(f"gen {gen:3d}  best {best:7.3f}  "
                 f"valid {len(finite)}/{len(entries)}  "
                 f"({time.time() - t0:5.1f}s)")

        self.store.finish_run(self.run_id)
        gallery_path = self.results / "gallery.html"
        _log(f"done. gallery: file://{gallery_path}")

    # ----------------------------------------------------------- evaluation --
    def _evaluate_generation(self, gen: int,
                             proposals: list[Proposal]) -> list[tuple[str, float]]:
        ev = self.cfg.evolution
        cached: dict[str, float] = {}
        todo: list[tuple[int, Proposal]] = []
        for i, p in enumerate(proposals):
            row = self.store.get_candidate(self.run_id, p.genome.hash)
            if row is not None:
                cached[p.genome.hash] = self.store.fitness_of(row)
            else:
                todo.append((i, p))

        # -- stage 1: geometry, artifacts, drag tables (parallel subprocesses)
        build_args = [(self.root, p.genome.values, gen, str(self.results))
                      for _, p in todo]
        builds = run_tasks("build_task", build_args, ev.workers, ev.task_timeout_s)

        # -- stage 2: flight scenarios per candidate (parallel subprocesses)
        scenario_names = [s.name for s in self.cfg.scenarios]
        er = self.cfg.early_reject
        sim_results: dict[str, dict[str, dict]] = {}  # hash -> scenario -> result

        buildable = [(p, b.value) for (_, p), b in zip(todo, builds)
                     if b.ok and b.value["valid"]]

        def run_scenarios(pairs: list[tuple[Proposal, dict]],
                          names: list[str]) -> None:
            args, keys = [], []
            for p, bv in pairs:
                for name in names:
                    args.append((self.root, bv["total_mass"], bv["drag"], name))
                    keys.append((p.genome.hash, name))
            outs = run_tasks("scenario_task", args, ev.workers, ev.task_timeout_s)
            for (h, name), out in zip(keys, outs):
                sim_results.setdefault(h, {})[name] = (
                    out.value if out.ok else
                    {"scenario": name, "valid": False,
                     "failure_reason": out.error, "wh_per_km": None,
                     "energy_wh": None, "avg_power_w": None,
                     "flight_time_s": None, "peak_rotor_thrust_n": 0.0,
                     "max_tilt_deg": 90.0})

        early_rejected: set[str] = set()
        if er.enabled and SCENARIO_ORDER_KEY in scenario_names:
            run_scenarios(buildable, [SCENARIO_ORDER_KEY])
            calm = {h: r[SCENARIO_ORDER_KEY] for h, r in sim_results.items()}
            ok_vals = [r["wh_per_km"] for r in calm.values()
                       if r["valid"] and r["wh_per_km"] is not None]
            if ok_vals:
                median = statistics.median(ok_vals)
                for p, bv in buildable:
                    r = calm.get(p.genome.hash)
                    if r and r["valid"] and r["wh_per_km"] is not None \
                            and r["wh_per_km"] > median * (1.0 + er.margin):
                        early_rejected.add(p.genome.hash)
            rest = [n for n in scenario_names if n != SCENARIO_ORDER_KEY]
            survivors = [(p, bv) for p, bv in buildable
                         if p.genome.hash not in early_rejected]
            run_scenarios(survivors, rest)
        else:
            run_scenarios(buildable, scenario_names)

        # -- stage 3: aggregate, structural check (worst case across
        # scenarios), persist
        from .evaluate import aggregate_fitness, structural_check
        from .simulator import ScenarioResult

        entries: list[tuple[str, float]] = []
        for (i, p), b in zip(todo, builds):
            h = p.genome.hash
            if not b.ok:
                self._persist(gen, p, None, False, f"evaluation failed: {b.error}",
                              math.inf, math.inf, math.inf, None)
                continue
            bv = b.value
            if not bv["valid"]:
                self._persist(gen, p, bv, False, bv["failure_reason"],
                              math.inf, math.inf, math.inf, None)
                continue

            per_scenario = sim_results.get(h, {})
            results = [ScenarioResult(**per_scenario[n])
                       for n in scenario_names if n in per_scenario]
            for r in per_scenario.values():
                self.store.insert_scenario_result(self.run_id, h, r)

            if h in early_rejected:
                calm_val = per_scenario[SCENARIO_ORDER_KEY]["wh_per_km"]
                fitness = calm_val * (1.0 + self.cfg.aggregation.lambda_worst) \
                    * er.penalty_factor
                self._persist(gen, p, bv, True, "early-reject (calm_warm screen)",
                              fitness, calm_val, calm_val, None)
                continue

            fitness, mean, worst = aggregate_fitness(
                results, self.cfg.aggregation.mode,
                self.cfg.aggregation.lambda_worst)

            f1_hz = None
            stl_path = None
            struct_reason = None
            valid = math.isfinite(fitness)
            reason = None if valid else self._first_failure(results)
            if valid or any(r.valid for r in results):
                peak = max((r.peak_rotor_thrust_n for r in results
                            if math.isfinite(r.peak_rotor_thrust_n)), default=0.0)
                ok, struct_reason, f1_hz = structural_check(
                    self.root, bv["arm"], bv["total_mass"], peak,
                    bv["material_gene"])
                if not ok:
                    valid = False
                    reason = struct_reason
                    fitness = mean = worst = math.inf
                    stl_path = self._mark_invalid_stl(bv["stl_path"])
            self._persist(gen, p, bv, valid, reason, fitness, mean, worst,
                          f1_hz, stl_path)

        # assemble the generation in proposal order
        for i, p in enumerate(proposals):
            h = p.genome.hash
            if h in cached:
                entries.insert(i, (h, cached[h]))
            else:
                row = self.store.get_candidate(self.run_id, h)
                entries.insert(i, (h, self.store.fitness_of(row)))
        return entries

    @staticmethod
    def _first_failure(results: list) -> str:
        for r in results:
            if not r.valid:
                return f"{r.scenario}: {r.failure_reason}"
        return "scenario failure"

    @staticmethod
    def _mark_invalid_stl(stl_path: str) -> str:
        p = Path(stl_path)
        if p.exists() and "_INVALID" not in p.name:
            newp = p.with_name(p.stem + "_INVALID.stl")
            p.rename(newp)
            return str(newp)
        return stl_path

    def _persist(self, gen: int, p: Proposal, bv: dict | None, valid: bool,
                 reason: str | None, fitness: float, mean: float, worst: float,
                 f1_hz: float | None, stl_path: str | None = None) -> None:
        self.store.insert_candidate(self.run_id, CandidateRow(
            hash=p.genome.hash, generation_born=gen,
            parent_a=p.parent_a, parent_b=p.parent_b, operator=p.operator,
            mutation_mag=p.mutation_mag, genome=p.genome.as_dict(),
            frame_mass=(bv or {}).get("frame_mass"),
            total_mass=(bv or {}).get("total_mass"),
            material=(bv or {}).get("material"),
            valid=valid, failure_reason=reason, fitness=fitness,
            mean_whkm=mean, worst_whkm=worst, f1_hz=f1_hz,
            stl_path=stl_path or (bv or {}).get("stl_path"),
            png_path=(bv or {}).get("png_path")))

    # ------------------------------------------------------------- plumbing --
    def _load_population(self, gen: int) -> list[tuple[str, Genome, float]]:
        rows = self.store.population(self.run_id, gen)
        out = []
        for r in rows:
            cand = self.store.get_candidate(self.run_id, r["hash"])
            genome = Genome.from_dict(json.loads(cand["genome_json"]))
            out.append((r["hash"], genome,
                        math.inf if r["fitness"] is None else r["fitness"]))
        return out

    def _restore_cmaes(self) -> CmaEs:
        ev = self.cfg.evolution
        if self.start_gen > 0:
            row = self.store.load_cma_state(self.run_id, self.start_gen - 1)
            if row is not None:
                return CmaEs.from_state_json(row["state_json"], ev.population)
        return CmaEs(Genome.baseline().normalized, ev.cmaes_sigma0, ev.population)

    def _write_artifacts(self, gen: int) -> None:
        glossary = self.cfg.root / "docs" / "glossary.html"
        if glossary.exists():  # keep the gallery's glossary link file://-local
            shutil.copyfile(glossary, self.results / "glossary.html")
        gallery_mod.write_gallery(self.store, self.run_id, self.results)
        gallery_mod.write_leaderboard(self.store, self.run_id, self.results,
                                      [s.name for s in self.cfg.scenarios])
        gallery_mod.write_convergence(self.store, self.run_id, self.results)
        if self.cfg.evolution.optimizer != "cmaes":
            lineage_mod.write_dot(self.store, self.run_id, self.results)
            lineage_mod.write_svg(self.store, self.run_id, self.results)
            lineage_mod.write_lineage_page(self.store, self.run_id, self.results)
        self._copy_best_stl(gen)

    def _copy_best_stl(self, gen: int) -> None:
        rows = [r for r in self.store.candidates_for_run(self.run_id)
                if r["fitness"] is not None and r["stl_path"]]
        if not rows:
            return
        best = min(rows, key=lambda r: r["fitness"])
        src = Path(best["stl_path"])
        if src.exists():
            shutil.copyfile(src, self.results / f"gen_{gen:04d}_best.stl")
