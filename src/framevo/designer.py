"""Headless-Claude designer rounds.

Every K generations the loop hands the current state of the search -- elite
genomes with their per-scenario results, the failure histogram, the gene
specification -- to a headless `claude -p` invocation and asks it to DESIGN
new candidates: reason about why the elites win, where they are weak, and
propose genome vectors the GA's local operators would be unlikely to reach.
Proposals come back as JSON, are validated/clipped onto the gene bounds, and
enter the population as operator `designer` (no parents; the rationale is
appended to results/designer_log.md).

Fail-soft: if the CLI is missing, times out, or returns unparseable output,
the round is skipped and ordinary GA breeding proceeds.
"""
from __future__ import annotations

import json
import math
import re
import subprocess
from pathlib import Path

from .config import Config
from .dbstore import Store
from .evolution import Proposal
from .genome import GENOME_SPEC, Genome

PROMPT_TEMPLATE = """You are the designer in an automated evolutionary study \
of 3D-printable quadcopter frames. The geometry is the real TBS Source One V6 \
7-inch DeadCat, morphed by a genome; the mission is 2 km north + 2 km south \
at 12 m/s through six adverse-weather scenarios; fitness = mean Wh/km across \
scenarios + 0.5 x worst scenario (LOWER IS BETTER). The platform (battery, \
2806 motors, 7x4 props, electronics) is fixed; only the frame genome varies.

GENES (name: min..max — meaning):
{gene_spec}

CURRENT ELITES (best first):
{elites}

RECENT INVALID-DESIGN REASONS (histogram): {failures}

SCENARIO NOTES: storm (8 m/s wind, severe gusts, rain) dominates worst-case; \
cold_headwind rewards low frontal drag; hot_thin (thin air) rewards low mass; \
crosswind rewards a small side profile.

Propose exactly {n} NEW genome vectors that are meaningfully DIFFERENT from \
the elites and from each other — design hypotheses, not small perturbations. \
Respect the hard constraints implied by the failure histogram (e.g. arm \
tongues collide when both sweep genes are at their minimums with wide arms; \
the deck gap must exceed 23 mm for the FC stack).

Respond with ONLY a JSON array, no prose, in this exact shape:
[{{"rationale": "<one sentence>", "genes": {{{gene_names}}}}}, ...]
"""


def _gene_spec_text() -> str:
    notes = {
        "arm_length_scale": "arm shaft stretch (wheelbase / disk loading)",
        "arm_width_scale": "arm width at shaft ends (stiffness vs drag)",
        "arm_waist_scale": "extra mid-shaft narrowing (drag vs stiffness)",
        "arm_thickness": "arm plate thickness in meters",
        "front_sweep_deg": "front arm azimuth from nose",
        "rear_sweep_deg": "rear arm azimuth from tail",
        "plate_length_scale": "deck plate stretch along flight axis",
        "plate_width_scale": "deck plate stretch across",
        "deck_gap": "standoff length in meters (stack space, prop-deck gap)",
        "battery_wedge_deg": "battery tilt on the top plate (frontal area)",
        "plate_thickness_scale": "x2 mm deck plates (mass vs stiffness)",
        "material": "0-0.17 carbon plate, 0.17-0.33 PA12-CF, 0.33-0.5 PET-CF,"
                    " 0.5-0.67 PLA+, 0.67-0.83 PETG, 0.83-1 ASA",
    }
    return "\n".join(f"- {n}: {lo}..{hi} — {notes.get(n, '')}"
                     for n, lo, hi in GENOME_SPEC)


def _build_brief(store: Store, run_id: str, n: int) -> str:
    cands = [r for r in store.candidates_for_run(run_id)
             if r["fitness"] is not None]
    cands.sort(key=lambda r: r["fitness"])
    elites = []
    for r in cands[:5]:
        genes = json.loads(r["genome_json"])
        sc = {s["scenario"]: round(s["wh_per_km"], 2)
              for s in store.scenario_results_for(run_id, r["hash"])
              if s["wh_per_km"] is not None}
        elites.append(
            f"fitness {r['fitness']:.3f} Wh/km-agg, frame "
            f"{(r['frame_mass'] or 0) * 1e3:.0f} g, {r['material']}: "
            f"genes={json.dumps({k: round(v, 4) for k, v in genes.items()})} "
            f"scenarios={json.dumps(sc)}")
    failures: dict[str, int] = {}
    for r in store.candidates_for_run(run_id):
        if not r["valid"] and r["failure_reason"]:
            failures[r["failure_reason"]] = failures.get(r["failure_reason"], 0) + 1
    gene_names = ", ".join(f'"{name}": <float>' for name, _, _ in GENOME_SPEC)
    return PROMPT_TEMPLATE.format(
        gene_spec=_gene_spec_text(), elites="\n".join(elites) or "(none yet)",
        failures=json.dumps(failures) or "{}", n=n, gene_names=gene_names)


def _parse_proposals(text: str, n: int) -> list[tuple[dict, str]]:
    """Extract [(genes, rationale), ...] from the model's reply."""
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if not match:
        return []
    items = json.loads(match.group(0))
    out = []
    for item in items[:n]:
        genes = item.get("genes") if isinstance(item, dict) else None
        if not isinstance(genes, dict):
            continue
        clean = {}
        for name, lo, hi in GENOME_SPEC:
            v = genes.get(name)
            if v is None or not isinstance(v, (int, float)) or math.isnan(v):
                break
            clean[name] = min(max(float(v), lo), hi)
        else:
            out.append((clean, str(item.get("rationale", ""))[:400]))
    return out


def design_round(store: Store, run_id: str, cfg: Config, generation: int,
                 n: int, model: str, timeout_s: float,
                 log_dir: Path) -> list[Proposal]:
    brief = _build_brief(store, run_id, n)
    cmd = ["claude", "-p", brief, "--output-format", "json"]
    if model:
        cmd += ["--model", model]
    try:
        run = subprocess.run(cmd, capture_output=True, text=True,
                             timeout=timeout_s)
        envelope = json.loads(run.stdout)
        text = envelope.get("result", "") if isinstance(envelope, dict) else ""
        proposals = _parse_proposals(text, n)
    except Exception as exc:  # fail-soft: skip the round
        print(f"[framevo] designer round skipped: {type(exc).__name__}: {exc}",
              flush=True)
        return []
    out = []
    log_lines = [f"\n## generation {generation}\n"]
    for genes, rationale in proposals:
        genome = Genome.from_dict(genes)
        out.append(Proposal(genome, None, None, "designer", None))
        log_lines.append(f"- `{genome.hash}` — {rationale}\n")
    if out:
        log = log_dir / "designer_log.md"
        if not log.exists():
            log.write_text("# Designer rounds (headless Claude)\n")
        with open(log, "a") as f:
            f.writelines(log_lines)
    return out
