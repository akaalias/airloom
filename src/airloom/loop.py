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
import secrets
import shutil
import statistics
import time
from dataclasses import asdict
from pathlib import Path

from . import gallery as gallery_mod
from . import lineage as lineage_mod
from .config import Config
from .dbstore import CandidateRow, Store
from .evolution import (CmaEs, Proposal, generation_rng,
                        gens_since_significant_improvement, pivot_rank,
                        propose_gen0, propose_next, select_far_parents)
from .genome import Genome
from .parallel import RunAborted, run_tasks

SCENARIO_ORDER_KEY = "calm_warm"  # flown first when early-reject is enabled


def _log(msg: str) -> None:
    print(f"[airloom] {msg}", flush=True)


class EvolutionLoop:
    _stop = None

    def __init__(self, cfg: Config, run_id: str, resume: bool = False,
                 inspiration: tuple[str, str] | None = None):
        self.cfg = cfg
        self.run_id = run_id
        self.results = cfg.evolution.results_dir
        self.results.mkdir(parents=True, exist_ok=True)
        self.store = Store(self.results / "run.db")
        self.root = str(cfg.root)
        ev = cfg.evolution

        existing = self.store.get_run(run_id)
        if existing is None:
            # config seed None -> every new run gets its own random seed
            # (persisted in run.db, so resume replays the exact same streams)
            self.seed = ev.seed if ev.seed is not None \
                else secrets.randbelow(2 ** 31)
            if ev.seed is None:
                _log(f"drew random seed {self.seed} for this run"
                     " (set evolution.seed or --seed to reproduce)")
            snapshot = json.dumps({
                "population": ev.population, "generations": ev.generations,
                "optimizer": ev.optimizer, "seed": self.seed,
                "aggregation": asdict(cfg.aggregation),
                "early_reject": asdict(cfg.early_reject),
                "mission": asdict(cfg.mission),
                "scenarios": [s.name for s in cfg.scenarios],
            })
            self.store.create_run(run_id, self.seed, ev.optimizer, ev.population,
                                  ev.generations, snapshot, cfg.root)
            if inspiration is not None:
                self.store.set_inspiration(run_id, *inspiration)
                _log(f"inspiration recorded from {inspiration[0]}")
            self.start_gen = 0
        elif resume:
            self.seed = int(existing["seed"])  # the run's own seed, not config's
            if inspiration is not None:  # steer the remaining designer rounds
                self.store.set_inspiration(run_id, *inspiration)
                _log(f"inspiration updated from {inspiration[0]}")
            done = self.store.generations_with_population(run_id)
            self.start_gen = (max(done) + 1) if done else 0
            self.store.update_generations_target(run_id, ev.generations)
            _log(f"resuming run '{run_id}' at generation {self.start_gen}"
                 f" (target {ev.generations})")
        else:
            raise SystemExit(
                f"run '{run_id}' already exists in {self.results / 'run.db'};"
                " use --resume to continue it or pick another --run-id")

    # ------------------------------------------------------------------ run --
    def run(self, stop_event=None) -> None:
        self._stop = stop_event
        ev = self.cfg.evolution
        cmaes = self._restore_cmaes() if ev.optimizer == "cmaes" else None

        try:
            self._run_generations(ev, cmaes)
        except RunAborted:
            self._join_narrators(timeout=5.0)
            self.store.finish_run(self.run_id, status="stopped")
            _log("run stopped -- everything up to the last completed "
                 "generation is saved; continue any time with "
                 "`airloom run --generations N`")
            return
        self._join_narrators()  # let pending note-enrichments land
        self._write_artifacts(ev.generations - 1)
        self.store.finish_run(self.run_id)
        gallery_path = self.results / "index.html"
        _log(f"done. gallery: file://{gallery_path}")

    def _run_generations(self, ev, cmaes) -> None:
        for gen in range(self.start_gen, ev.generations):
            t0 = time.time()
            rng = generation_rng(self.seed, gen)

            if cmaes is not None:
                xs = cmaes.ask(rng)
                proposals = [Proposal(Genome.from_normalized(x), None, None,
                                      "cmaes", cmaes.sigma) for x in xs]
            elif gen == 0:
                proposals = propose_gen0(ev.population, rng)
                proposals = self._designer_round(gen, proposals)
            else:
                prev = self._load_population(gen - 1)
                pivot, far = self._patience_state(gen)
                proposals = propose_next(prev, gen, ev.ga, rng,
                                         pivot=pivot, far_parents=far)
                proposals = self._designer_round(gen, proposals, pivot=pivot)

            new_hashes = [p.genome.hash for p in proposals
                          if self.store.get_candidate(self.run_id,
                                                      p.genome.hash) is None]
            entries = self._evaluate_generation(gen, proposals)
            if self.cfg.evolution.narrator.enabled and new_hashes:
                self._narrate_async(gen, new_hashes)

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
            if self._stop is not None and self._stop.is_set():
                raise RunAborted("stop requested")

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
        builds = run_tasks("build_task", build_args, ev.workers,
                           ev.task_timeout_s, stop_event=self._stop)

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
            outs = run_tasks("scenario_task", args, ev.workers,
                             ev.task_timeout_s, stop_event=self._stop)
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

    # ------------------------------------------------------------ narrator --
    def _narrate_async(self, gen: int, new_hashes: list[str]) -> None:
        """Rule-based notes are written immediately; the headless-Claude
        enrichment runs on a background thread so it never blocks the next
        generation."""
        import threading

        from .narrator import enrich_notes, prepare_candidates, \
            write_fallback_notes
        try:
            cands, best_before = prepare_candidates(self.store, self.run_id,
                                                    new_hashes)
            write_fallback_notes(self.store, self.run_id, cands)
        except Exception as exc:
            _log(f"narrator skipped: {type(exc).__name__}: {exc}")
            return
        nr = self.cfg.evolution.narrator
        t = threading.Thread(
            target=enrich_notes,
            args=(str(self.store.path), self.run_id, gen, cands, best_before,
                  nr.model, nr.timeout_s),
            daemon=True, name=f"narrator-g{gen}")
        t.start()
        self._narrator_threads = getattr(self, "_narrator_threads", [])
        self._narrator_threads.append(t)

    def _join_narrators(self, timeout: float = 330.0) -> None:
        for t in getattr(self, "_narrator_threads", []):
            t.join(timeout=timeout)

    # ------------------------------------------------------------ designer --
    def _designer_round(self, gen: int, proposals: list[Proposal],
                        pivot: int = 0) -> list[Proposal]:
        """Fires at gen 0 (opening hypotheses), on the periodic cadence, and
        whenever patience declares a pivot (a step-back ask with the full
        plateau context)."""
        dz = self.cfg.evolution.designer
        n = dz.gen0_candidates if gen == 0 else dz.candidates
        due = gen == 0 or pivot > 0 or gen % dz.every_generations == 0
        if not dz.enabled or n <= 0 or not due:
            return proposals
        kind = "opening" if gen == 0 else ("pivot" if pivot else "periodic")
        from .designer import design_round
        designed = design_round(self.store, self.run_id, self.cfg, gen,
                                n, dz.model, dz.timeout_s,
                                self.results, kind=kind)
        if not designed:
            return proposals
        _log(f"designer round ({kind}): injecting {len(designed)} candidates")
        seen = {p.genome.hash for p in proposals}
        designed = [d for d in designed if d.genome.hash not in seen]
        keep = len(proposals) - len(designed)
        return proposals[:keep] + designed

    # ------------------------------------------------------------ patience --
    def _patience_state(self, gen: int) -> tuple[int, list | None]:
        """(pivot rank, far-parent pool) for the generation about to be bred.
        Derived entirely from persisted history, so it survives --resume."""
        pt = self.cfg.evolution.ga.patience
        if not pt.enabled:
            return 0, None
        best_per_gen = []
        for g in range(gen):
            fits = [r["fitness"] for r in self.store.population(self.run_id, g)
                    if r["fitness"] is not None]
            best_per_gen.append(min(fits) if fits else math.inf)
        rank = pivot_rank(best_per_gen, self.cfg.evolution.ga)
        if rank == 0:
            return 0, None
        stall = gens_since_significant_improvement(best_per_gen,
                                                   pt.min_rel_improvement)
        history, best = [], (None, math.inf)
        for r in self.store.candidates_for_run(self.run_id):
            f = self.store.fitness_of(r)
            if not math.isfinite(f):
                continue
            g = Genome.from_dict(json.loads(r["genome_json"]))
            history.append((r["hash"], g, f))
            if f < best[1]:
                best = (g, f)
        far = select_far_parents(history, best[0], best[1], pt.decent_factor) \
            if best[0] is not None else []
        _log(f"patience exhausted ({stall} gens without >="
             f"{pt.min_rel_improvement:.1%} improvement) -- pivot rank {rank}"
             + (f", {len(far)} far parents" if rank == 1 else " (escalated)"))
        return rank, far or None

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
        # pick up gallery/lineage code changes made while a long run is
        # alive: artifacts always render with the newest module versions
        import importlib
        try:
            importlib.reload(gallery_mod)
            importlib.reload(lineage_mod)
        except Exception:
            pass
        glossary = self.cfg.root / "docs" / "glossary.html"
        if glossary.exists():  # keep the gallery's glossary link file://-local
            shutil.copyfile(glossary, self.results / "glossary.html")
        gallery_mod.write_gallery(self.store, self.run_id, self.results,
                                  self.cfg.aggregation.target_whkm,
                                  self.cfg.aggregation.record_whkm,
                                  self.cfg.evolution, cfg=self.cfg)
        gallery_mod.write_leaderboard(self.store, self.run_id, self.results,
                                      [s.name for s in self.cfg.scenarios])
        gallery_mod.write_convergence(self.store, self.run_id, self.results)
        if self.cfg.evolution.optimizer != "cmaes":
            lineage_mod.write_dot(self.store, self.run_id, self.results)
            lineage_mod.write_svg(self.store, self.run_id, self.results)
            lineage_mod.write_lineage_page(self.store, self.run_id, self.results)
        # docs/ is the standing publish target (the GitHub Pages root):
        # every artifact refresh mirrors the report there
        gallery_mod.publish_docs(self.results, self.cfg.root / "docs")
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
        # the champion as individual printable/cuttable pieces
        from .frame_gen import export_printable_parts
        genome = Genome.from_dict(json.loads(best["genome_json"]))
        export_printable_parts(genome, self.cfg.platform,
                               self.results / f"gen_{gen:04d}_best_parts")
