"""Rank-robustness sweep: is the leaderboard an artifact of the Phase A
model assumptions?

The eval's job is ORDERING candidates, not predicting absolute Wh/km. This
sweep re-flies the top archived candidates under perturbed versions of the
least-trustworthy model knobs (handbook drag coefficients, the rotor-wash
interference term, rotor CT/CP table error, the empirical rain penalties)
and measures how much the ranking moves: rank correlation against the
baseline ordering, top-5 overlap, champion identity.

If the ordering survives every perturbation, Phase A is doing its job and a
CFD upgrade (Phase B) would mostly relabel the y-axis. If a knob reshuffles
the ranking, that knob is exactly where higher-fidelity physics should be
spent first. Geometry is rebuilt from the archived genomes; projected areas
are rasterized once per candidate and re-priced per knob set (see
aero.AreaTable), so the sweep cost is dominated by the flight sims.
"""
from __future__ import annotations

import dataclasses
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .aero import CD_ARM, CD_BODY
from .config import Config
from .rotor_model import RotorModel

# Each knob set is one hypothesis "the true value differs from the handbook
# value by this much". Spans are deliberately generous: handbook Cd for a
# plate arm is good to maybe +-30 %, the wash/interference term to a factor
# of ~2, the UIUC tables stretched to edgewise flight and 3 blades to
# ~+-10 %, and the rain knobs are literature-inspired guesses.
KNOB_SETS: tuple[dict[str, Any], ...] = (
    {"name": "baseline"},
    {"name": "cd_arm-30%", "cd_arm": 0.7},
    {"name": "cd_arm+30%", "cd_arm": 1.3},
    {"name": "cd_body-30%", "cd_body": 0.7},
    {"name": "cd_body+30%", "cd_body": 1.3},
    {"name": "wash-50%", "wash": 0.5},
    {"name": "wash+100%", "wash": 2.0},
    {"name": "rotor_ct-10%", "ct": 0.9},
    {"name": "rotor_ct+10%", "ct": 1.1},
    {"name": "rotor_cp-10%", "cp": 0.9},
    {"name": "rotor_cp+10%", "cp": 1.1},
    {"name": "rain_mild", "rain_penalty": 0.08, "film": 0.5},
    {"name": "rain_harsh", "rain_penalty": 0.25, "film": 2.0},
)


def perturbed_rotor(rotor: RotorModel, ct_scale: float,
                    cp_scale: float) -> RotorModel:
    if ct_scale == 1.0 and cp_scale == 1.0:
        return rotor
    return dataclasses.replace(
        rotor,
        ct_grid=rotor.ct_grid * ct_scale, cp_grid=rotor.cp_grid * cp_scale,
        ct_static=rotor.ct_static * ct_scale,
        cp_static=rotor.cp_static * cp_scale)


def apply_knobs(cfg: Config, rotor: RotorModel,
                knobs: dict[str, Any]) -> tuple[float, float, float,
                                                RotorModel, Any]:
    """(cd_arm, cd_body, wash_scale, rotor, rain_model) under one knob set."""
    cd_arm = CD_ARM * float(knobs.get("cd_arm", 1.0))
    cd_body = CD_BODY * float(knobs.get("cd_body", 1.0))
    wash = float(knobs.get("wash", 1.0))
    rot = perturbed_rotor(rotor, float(knobs.get("ct", 1.0)),
                          float(knobs.get("cp", 1.0)))
    rain = cfg.rain
    if "rain_penalty" in knobs or "film" in knobs:
        rain = dataclasses.replace(
            cfg.rain,
            thrust_efficiency_penalty=float(
                knobs.get("rain_penalty", cfg.rain.thrust_efficiency_penalty)),
            film_mass_kg_m2=cfg.rain.film_mass_kg_m2 * float(knobs.get("film", 1.0)))
    return cd_arm, cd_body, wash, rot, rain


# ------------------------------------------------------------------ stats --
def _ranks(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):  # average ranks over ties
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        r = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = r
        i = j + 1
    return ranks


def spearman(a: list[float], b: list[float]) -> float:
    ra, rb = _ranks(a), _ranks(b)
    n = len(a)
    ma, mb = sum(ra) / n, sum(rb) / n
    cov = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    va = math.sqrt(sum((x - ma) ** 2 for x in ra))
    vb = math.sqrt(sum((y - mb) ** 2 for y in rb))
    return cov / (va * vb) if va > 0 and vb > 0 else 1.0


def kendall_tau(a: list[float], b: list[float]) -> float:
    n = len(a)
    conc = disc = 0
    for i in range(n):
        for j in range(i + 1, n):
            s = (a[i] - a[j]) * (b[i] - b[j])
            if s > 0:
                conc += 1
            elif s < 0:
                disc += 1
    total = n * (n - 1) / 2
    return (conc - disc) / total if total else 1.0


# ------------------------------------------------------------ orchestrator --
def _fitness_vector(per_cand: list[dict[str, Any]], knob_name: str,
                    penalty: float) -> list[float]:
    """Fitness per candidate under one knob set; failures get a finite
    worst-plus penalty so rank stats stay defined (a candidate that BREAKS
    under a perturbation is maximally destabilized, and that must count)."""
    vals = []
    for c in per_cand:
        r = (c.get("results") or {}).get(knob_name)
        f = r.get("fitness") if r else None
        vals.append(float(f) if f is not None else penalty)
    return vals


def run_robustness(cfg: Config, run_id: str | None = None, top: int = 20,
                   workers: int | None = None,
                   scenario_names: list[str] | None = None,
                   knob_sets: tuple[dict[str, Any], ...] = KNOB_SETS,
                   timeout_s: float = 1800.0) -> dict[str, Any]:
    from .dbstore import Store
    from .parallel import run_tasks

    results_dir = cfg.evolution.results_dir
    store = Store(results_dir / "run.db")
    run_id = run_id or store.latest_run_id(with_data=True)
    if run_id is None:
        raise SystemExit("no runs with data found in run.db")

    rows = [r for r in store.candidates_for_run(run_id)
            if r["valid"] and r["fitness"] is not None]
    rows.sort(key=lambda r: r["fitness"])
    rows = rows[:top]
    if len(rows) < 3:
        raise SystemExit(f"run {run_id}: only {len(rows)} valid candidates; "
                         "need at least 3 for rank statistics")

    hashes = [r["hash"] for r in rows]
    genomes = [json.loads(r["genome_json"]) for r in rows]
    args_list = [(str(cfg.root), genome, list(knob_sets), scenario_names)
                 for genome in genomes]
    n_workers = workers or cfg.evolution.workers
    print(f"robustness: run {run_id}, top {len(rows)} candidates x "
          f"{len(knob_sets)} knob sets x "
          f"{len(scenario_names or cfg.scenarios)} scenarios "
          f"({n_workers} workers)")
    outcomes = run_tasks("robustness_task", args_list, n_workers,
                         timeout_s, label="robustness")

    per_cand: list[dict[str, Any]] = []
    for h, o in zip(hashes, outcomes):
        if o.ok:
            per_cand.append(o.value)
        else:
            print(f"  {h}: task failed ({o.error}) -- excluded")
            per_cand.append({"hash": h, "valid": False, "results": None})

    keep = [i for i, c in enumerate(per_cand)
            if c.get("valid") and c.get("results")]
    if len(keep) < 3:
        raise SystemExit("too few candidates evaluated successfully")
    per_cand = [per_cand[i] for i in keep]
    hashes = [hashes[i] for i in keep]

    base_name = knob_sets[0]["name"]
    finite = [r["fitness"] for c in per_cand
              for r in c["results"].values() if r.get("fitness") is not None]
    penalty = 2.0 * max(finite) if finite else 1e9
    base = _fitness_vector(per_cand, base_name, penalty)
    base_order = sorted(range(len(base)), key=lambda i: base[i])
    base_top5 = {hashes[i] for i in base_order[:5]}
    base_champ = hashes[base_order[0]]

    per_knob: list[dict[str, Any]] = []
    for ks in knob_sets[1:]:
        v = _fitness_vector(per_cand, ks["name"], penalty)
        order = sorted(range(len(v)), key=lambda i: v[i])
        top5 = {hashes[i] for i in order[:5]}
        n_broken = sum(1 for c in per_cand
                       if (c["results"].get(ks["name"]) or {}).get("fitness") is None)
        per_knob.append({
            "name": ks["name"],
            "spearman": spearman(base, v),
            "kendall": kendall_tau(base, v),
            "top5_overlap": len(base_top5 & top5) / min(5, len(hashes)),
            "champion": hashes[order[0]],
            "champion_same": hashes[order[0]] == base_champ,
            "champion_base_rank": order.index(base_order[0]) + 1,
            "n_broken": n_broken,
        })

    min_rho = min(k["spearman"] for k in per_knob)
    champ_flips = [k["name"] for k in per_knob if not k["champion_same"]]
    if min_rho >= 0.85 and not champ_flips:
        verdict = "STABLE"
    elif min_rho >= 0.70 and len(champ_flips) <= 2:
        verdict = "MODERATE"
    else:
        verdict = "FRAGILE"
    worst_knob = min(per_knob, key=lambda k: k["spearman"])

    summary = {
        "run_id": run_id, "n_candidates": len(hashes),
        "baseline_champion": base_champ, "verdict": verdict,
        "min_spearman": min_rho, "worst_knob": worst_knob["name"],
        "champion_flips": champ_flips, "per_knob": per_knob,
    }
    out_path = results_dir / "robustness.md"
    out_path.write_text(_report_md(summary, knob_sets, per_cand, hashes,
                                   base, penalty))
    print(f"verdict: {verdict}  (min Spearman {min_rho:.3f} at "
          f"{worst_knob['name']}; champion flips: "
          f"{', '.join(champ_flips) or 'none'})")
    print(f"report: {out_path}")
    return summary


def _report_md(s: dict[str, Any], knob_sets, per_cand, hashes, base,
               penalty) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "# Rank-robustness report",
        "",
        f"Run `{s['run_id']}` — top {s['n_candidates']} candidates re-flown "
        f"under {len(knob_sets) - 1} perturbations of the Phase A model "
        f"knobs ({ts}).",
        "",
        f"## Verdict: **{s['verdict']}**",
        "",
        f"- minimum Spearman rank correlation vs baseline: "
        f"**{s['min_spearman']:.3f}** (at `{s['worst_knob']}`)",
        f"- champion changes under: "
        f"{', '.join(f'`{n}`' for n in s['champion_flips']) or 'no perturbation'}",
        "",
        "STABLE = the ordering is a frame property, not a model artifact; "
        "Phase B CFD would refine absolute numbers, not decisions. "
        "FRAGILE = the flagged knob is where higher-fidelity physics "
        "changes decisions — spend Phase B effort there first.",
        "",
        "| perturbation | Spearman | Kendall τ | top-5 overlap | champion "
        "| baseline champ rank | broken |",
        "|---|---|---|---|---|---|---|",
    ]
    for k in s["per_knob"]:
        lines.append(
            f"| `{k['name']}` | {k['spearman']:.3f} | {k['kendall']:.3f} "
            f"| {k['top5_overlap']:.0%} | `{k['champion']}`"
            f"{' (=)' if k['champion_same'] else ' **(flip)**'} "
            f"| {k['champion_base_rank']} | {k['n_broken']} |")
    lines += [
        "",
        "*broken* = candidates whose flight fails outright under that "
        "perturbation (scored as worst-rank rather than dropped).",
        "",
        "## Baseline fitness (re-flown, current code)",
        "",
        "| rank | candidate | fitness (Wh/km agg) |",
        "|---|---|---|",
    ]
    order = sorted(range(len(base)), key=lambda i: base[i])
    for rank, i in enumerate(order, 1):
        f = base[i]
        shown = f"{f:.4f}" if f < penalty else "failed"
        lines.append(f"| {rank} | `{hashes[i]}` | {shown} |")
    lines.append("")
    return "\n".join(lines)
