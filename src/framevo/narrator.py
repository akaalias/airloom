"""The lab-notebook narrator: a human-readable hypothesis / method / result
for every newly evaluated candidate.

After each generation is evaluated, ONE headless `claude -p` call receives
the generation's new candidates -- operator, parents and their fitness, the
gene deltas, and the flight outcome (or the constraint that invalidated the
design) -- and writes three short sections per candidate:

  hypothesis  the "why": what the search had observed and what this design
              bet is based on (phrased from the pre-flight viewpoint)
  method      what concretely changed relative to the parent(s)
  result      the outcome: better or worse than the parents / best-so-far,
              new-winner status, invalidity explained, learnings, and what
              could be tried next

Fail-soft: if the CLI is missing or the reply unparseable, a rule-based
fallback narrative is stored instead, so the sections always exist.
"""
from __future__ import annotations

import json
import re
import math
import subprocess

from .dbstore import Store
from .genome import GENE_FORMAT, GENOME_SPEC, describe_genome

_OPERATOR_WHY = {
    "seed": "Generation-0 seed: establish the baseline (the real Source One "
            "V6 for the first slot, random design-space probes for the rest).",
    "crossover": "Recombine two selected parents: their strengths may be "
                 "complementary.",
    "mutation": "Local perturbation of a selected parent to probe its "
                "neighborhood.",
    "immigrant": "Fresh random genome to re-inject diversity.",
    "pivot": "Plateau-breaking cross with a genetically distant parent "
             "under boosted mutation.",
    "designer": "Headless-Claude design hypothesis (see designer_log.md).",
    "elite": "Elite carry-over: preserve the current best unchanged.",
    "cmaes": "Sample from the CMA-ES search distribution.",
}


def _fmt_gene(gene: str, v: float) -> str:
    for g, label, unit in GENE_FORMAT:
        if g == gene:
            if unit == "mm":
                return f"{label} {v * 1000:.1f} mm"
            if unit == "deg":
                return f"{label} {v:.1f}°"
            if unit == "x":
                return f"{label} ×{v:.2f}"
            return f"{label} {v:.2f}"
    return f"{gene} {v:.3f}"


def _top_deltas(genes: dict, parent_genes: dict | None, n: int = 4) -> str:
    if not parent_genes:
        return ", ".join(_fmt_gene(k, v) for k, v in list(genes.items())[:n])
    scored = []
    for name, lo, hi in GENOME_SPEC:
        d = abs(genes.get(name, 0) - parent_genes.get(name, 0)) / (hi - lo)
        scored.append((d, name))
    scored.sort(reverse=True)
    return ", ".join(f"{_fmt_gene(nm, genes[nm])}"
                     f" (was {_fmt_gene(nm, parent_genes[nm]).split(' ', 99)[-1] if False else _fmt_gene(nm, parent_genes[nm])})"
                     for _, nm in scored[:n] if _ > 0.005) or "near-identical genes"


def _fallback(c: dict) -> dict[str, str]:
    hyp = _OPERATOR_WHY.get(c["operator"], "Explore a new genome.")
    if c["parents"]:
        pl = " and ".join(f"{p['hash'][:6]} ({p['fitness']:.2f})"
                          if p["fitness"] is not None else p["hash"][:6]
                          for p in c["parents"])
        hyp += f" Parents: {pl} Wh/km."
    method = f"Largest gene changes: {c['deltas']}." if c["parents"] \
        else f"Genome: {c['deltas']}."
    if c["valid"]:
        res = f"Aggregate {c['fitness']:.3f} Wh/km."
        if c["became_best"]:
            res += " NEW BEST-SO-FAR at evaluation time."
        elif c["best_before"] is not None:
            res += f" Best-so-far was {c['best_before']:.3f} -- no improvement."
        if c["worst_scenario"]:
            res += f" Weakest scenario: {c['worst_scenario']}."
    else:
        res = (f"INVALID -- {c['failure']}. The design never flew; "
               "the constraint itself is the learning.")
    return {"hypothesis": hyp, "method": method, "result": res}


def _build_brief(cands: list[dict], gen: int, best_before: float | None) -> str:
    lines = []
    for c in cands:
        lines.append(json.dumps({
            "hash": c["hash"], "operator": c["operator"],
            "parents": c["parents"], "gene_changes": c["deltas"],
            "genes": c["genes_pretty"],
            "outcome": ({"fitness_whkm": c["fitness"],
                         "per_scenario": c["scenarios"],
                         "became_best_so_far": c["became_best"]}
                        if c["valid"] else {"invalid": c["failure"]}),
        }))
    return f"""You are the lab-notebook narrator of an automated evolutionary \
study of 3D-printable quadcopter frames (real Source One V6 geometry, morphed \
by a genome; fitness = mean Wh/km over six adverse-weather scenarios + 0.5 x \
worst; LOWER IS BETTER; best-so-far before this generation: \
{best_before if best_before is not None else "none"}).

For EACH candidate of generation {gen} below, write three short sections:
- "hypothesis": 1-2 sentences, the WHY from the pre-flight viewpoint -- what \
had been observed (parent performance, weaknesses, plateau) and what design \
bet this candidate makes. High-level; no gene numbers.
- "method": 1-2 sentences, what concretely changed vs the parent(s), in \
plain language (use the gene_changes; readable units, no raw gene names).
- "result": 2-3 sentences, post-flight: outcome vs parents and vs the \
best-so-far (say explicitly if it is a NEW WINNER), why it might have won or \
lost, or -- if invalid -- which constraint killed it and what that teaches; \
end with one concrete idea worth testing next.

CANDIDATES (one JSON per line):
{chr(10).join(lines)}

Respond with ONLY a STRICT JSON object mapping each hash to its sections
(double-quoted, quotes inside text escaped, no trailing commas):
{{"<hash>": {{"hypothesis": "...", "method": "...", "result": "..."}}, ...}}
"""


def _parse_notes(text: str, hashes: list[str]) -> dict[str, dict]:
    """Parse the narrator's reply; if the full object is malformed (one bad
    escape used to lose the whole generation), salvage per-candidate."""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return {}
    blob = match.group(0)
    try:
        got = json.loads(blob)
        return got if isinstance(got, dict) else {}
    except json.JSONDecodeError:
        pass
    salvaged: dict[str, dict] = {}
    for h in hashes:  # sections are flat objects: match to the closing brace
        m = re.search(re.escape(h) + r'"\s*:\s*(\{[^{}]*\})', blob)
        if not m:
            continue
        try:
            salvaged[h] = json.loads(m.group(1))
        except json.JSONDecodeError:
            continue
    if salvaged:
        print(f"[framevo] narrator reply was malformed JSON -- salvaged "
              f"{len(salvaged)}/{len(hashes)} notes", flush=True)
    return salvaged


def prepare_candidates(store: Store, run_id: str,
                       new_hashes: list[str]) -> tuple[list[dict], float | None]:
    """Fast DB reads on the caller's thread: everything the narration needs."""
    if not new_hashes:
        return [], None
    all_rows = {r["hash"]: r for r in store.candidates_for_run(run_id)}
    # best-so-far before this generation's candidates were evaluated
    best_before = None
    for r in store.candidates_in_eval_order(run_id):
        if r["hash"] in new_hashes:
            break
        f = store.fitness_of(r)
        if math.isfinite(f) and (best_before is None or f < best_before):
            best_before = f

    cands, running_best = [], best_before
    for h in new_hashes:
        r = all_rows.get(h)
        if r is None:
            continue
        genes = json.loads(r["genome_json"])
        parents = []
        parent_genes = None
        for pk in ("parent_a", "parent_b"):
            ph = r[pk]
            if ph and ph in all_rows:
                pf = store.fitness_of(all_rows[ph])
                parents.append({"hash": ph,
                                "fitness": round(pf, 3) if math.isfinite(pf) else None})
                if parent_genes is None:
                    parent_genes = json.loads(all_rows[ph]["genome_json"])
        fit = store.fitness_of(r)
        valid = math.isfinite(fit)
        scenarios = {s["scenario"]: round(s["wh_per_km"], 2)
                     for s in store.scenario_results_for(run_id, h)
                     if s["wh_per_km"] is not None}
        worst_sc = max(scenarios, key=scenarios.get) if scenarios else None
        became_best = valid and (running_best is None or fit < running_best)
        if became_best:
            running_best = fit
        cands.append({
            "hash": h, "operator": r["operator"], "parents": parents,
            "deltas": _top_deltas(genes, parent_genes),
            "genes_pretty": dict(describe_genome(genes, r["material"])),
            "valid": valid, "fitness": round(fit, 3) if valid else None,
            "failure": r["failure_reason"], "scenarios": scenarios,
            "worst_scenario": worst_sc, "became_best": became_best,
            "best_before": best_before,
        })

    return cands, best_before


def narrate_generation(store: Store, run_id: str, gen: int,
                       new_hashes: list[str], model: str,
                       timeout_s: float) -> None:
    """Synchronous convenience wrapper (used by tests)."""
    cands, best_before = prepare_candidates(store, run_id, new_hashes)
    write_fallback_notes(store, run_id, cands)
    enrich_notes(str(store.path), run_id, gen, cands, best_before,
                 model, timeout_s)


def write_fallback_notes(store: Store, run_id: str, cands: list[dict]) -> None:
    """Instant rule-based notes so the sections always exist; the async
    Claude enrichment upgrades them in place afterwards."""
    for c in cands:
        sec = _fallback(c)
        store.set_narrative(run_id, c["hash"], sec["hypothesis"],
                            sec["method"], sec["result"])


def enrich_notes(db_path: str, run_id: str, gen: int, cands: list[dict],
                 best_before: float | None, model: str,
                 timeout_s: float) -> None:
    """The slow part -- ONE headless-Claude call -- designed to run on a
    background thread with its own DB connection, off the loop's critical
    path. Fail-soft: the fallback notes simply remain."""
    if not cands:
        return
    notes: dict[str, dict] = {}
    try:
        brief = _build_brief(cands, gen, best_before)
        cmd = ["claude", "-p", brief, "--output-format", "json"]
        if model:
            cmd += ["--model", model]
        run = subprocess.run(cmd, capture_output=True, text=True,
                             timeout=timeout_s)
        envelope = json.loads(run.stdout)
        text = envelope.get("result", "") if isinstance(envelope, dict) else ""
        got = _parse_notes(text, [c["hash"] for c in cands])
        wanted = {c["hash"]: _fallback(c) for c in cands}
        for h, sec in got.items():
            if h in wanted and isinstance(sec, dict):
                merged = wanted[h]
                for k in ("hypothesis", "method", "result"):
                    if isinstance(sec.get(k), str) and sec[k].strip():
                        merged[k] = sec[k].strip()[:1200]
                notes[h] = merged
    except Exception as exc:
        print(f"[framevo] narrator kept rule-based notes: "
              f"{type(exc).__name__}: {exc}", flush=True)
        return

    from pathlib import Path

    from .dbstore import Store as _Store
    own = _Store(Path(db_path))  # background thread: own connection
    try:
        for h, sec in notes.items():
            own.set_narrative(run_id, h, sec["hypothesis"], sec["method"],
                              sec["result"])
    finally:
        own.close()
