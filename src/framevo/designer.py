"""Headless-Claude designer rounds.

Every K generations the loop hands the current state of the search -- elite
genomes with their per-scenario results, the failure histogram, the gene
specification -- to a headless `claude -p` invocation and asks it to DESIGN
new candidates: reason about why the elites win, where they are weak, and
propose genome vectors the GA's local operators would be unlikely to reach.
Proposals come back as JSON, are validated/clipped onto the gene bounds,
pre-screened against the geometric hard constraints (a mesh-free
`build_frame` -- proposals that would die on the launch pad get ONE repair
round with the concrete failure reasons), and enter the population as
operator `designer` (no parents; rationales -- including pre-flight
rejections -- are appended to results/designer_log.md).

Fail-soft: if the CLI is missing, times out, or returns unparseable output,
the round is skipped and ordinary GA breeding proceeds.
"""
from __future__ import annotations

import json
import math
import re
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

BEST-PER-GENERATION TRAJECTORY (Wh/km-agg): {history}

CURRENT ELITES (best first):
{elites}

YOUR EARLIER PROPOSALS AND HOW THEY FARED:
{past_designs}

RECENT INVALID-DESIGN REASONS (histogram): {failures}
{inspiration}

SCENARIO NOTES: storm (8 m/s wind, severe gusts, rain) dominates worst-case; \
cold_headwind rewards low frontal drag; hot_thin (thin air) rewards low mass; \
crosswind rewards a small side profile.

{ask}

Respond with a JSON object of the shape:
{{"proposals": [{{"rationale": "<one sentence>", "genes": {{{gene_names}}}}}, ...]}}
"""


def _proposals_schema() -> dict:
    """Schema for the CLI's --json-schema structured-output mode."""
    gene_props = {name: {"type": "number"} for name, _, _ in GENOME_SPEC}
    return {
        "type": "object",
        "properties": {
            "proposals": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "rationale": {"type": "string"},
                        "genes": {
                            "type": "object",
                            "properties": gene_props,
                            "required": list(gene_props),
                            "additionalProperties": False,
                        },
                    },
                    "required": ["rationale", "genes"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["proposals"],
        "additionalProperties": False,
    }

COUPLINGS = """Respect the hard constraints implied by the failure \
histogram. Known couplings: the deck gap must exceed 0.023 m for the FC \
stack; arm tongues collide when both sweeps sit at their minimums with wide \
arms; the tongue BOLTS must stay on the main plate -- sweeps far from \
stock (front 31.4, rear 36.0) need plate_length_scale/plate_width_scale to \
grow with them (rule of thumb: keep sweeps within ~6 deg of stock unless \
you also raise the plate scales by ~0.1 per extra 5 deg); the FC-stack \
holes stay PINNED while the plates scale, so plate scales below ~0.95 \
crush the material webs between holes and cutouts (min 80% of the stock \
web is enforced); and printed materials (anything but cf_plate) need \
plate_thickness_scale >= 0.8 (>= 1.6 mm plates)."""

ASK_PERIODIC = """Propose exactly {n} NEW genome vectors that are \
meaningfully DIFFERENT from the elites and from each other — design \
hypotheses, not small perturbations. Build on what the trajectory and your \
earlier proposals' outcomes show worked; avoid repeating what failed. \
""" + COUPLINGS

ASK_PIVOT = """THE SEARCH HAS PLATEAUED: the best-so-far has not improved \
significantly for {stall} generation(s). This is a PIVOT round. Take a step \
back: reason about WHY the current elite family has stopped improving — \
what shared trait is this local optimum built on, and what does the \
per-scenario data say it costs? Then propose exactly {n} PIVOTAL designs \
that abandon that trait and stake out genuinely different regions of the \
genome space. Do NOT refine the elites — a pivot that lands near them is a \
wasted round. """ + COUPLINGS


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


INSPIRATION_MAX_CHARS = 6000  # keep a runaway inspiration file from
                              # drowning out the elites and gene spec


def _inspiration_block(store: Store, run_id: str) -> str:
    run = store.get_run(run_id)
    text = (run["inspiration_text"] or "").strip() if run else ""
    if not text:
        return ""
    if len(text) > INSPIRATION_MAX_CHARS:
        text = text[:INSPIRATION_MAX_CHARS] + "\n[...truncated]"
    return ("\nUSER INSPIRATION -- the researcher asked you to draw on the "
            "ideas below when proposing designs. Translate them into the "
            "genome; do not ignore them:\n" + text + "\n")


def _history_line(store: Store, run_id: str) -> tuple[str, int]:
    """Best-per-generation trajectory text + the current stall length in
    generations (same 0.5%-relative yardstick the patience system uses)."""
    from .evolution import gens_since_significant_improvement
    best_per_gen = []
    for g in store.generations_with_population(run_id):
        fits = [r["fitness"] for r in store.population(run_id, g)
                if r["fitness"] is not None]
        best_per_gen.append(min(fits) if fits else math.inf)
    if not best_per_gen:
        return "(no generations evaluated yet)", 0
    stall = gens_since_significant_improvement(best_per_gen, 0.005)
    line = ", ".join(f"g{g} {'invalid-only' if math.isinf(f) else f'{f:.3f}'}"
                     for g, f in enumerate(best_per_gen))
    if stall:
        line += (f" — flat (no >=0.5% improvement) for the last "
                 f"{stall} generation(s)")
    return line, stall


def _past_designs_text(store: Store, run_id: str) -> str:
    """How every earlier designer proposal actually fared, so new ideas
    build on the run's learnings instead of starting from thin air."""
    rationales: dict[str, str] = {}
    for rnd in store.designer_rounds_for(run_id):
        for a in json.loads(rnd["accepted_json"]):
            rationales[a["hash"]] = a.get("rationale", "")
    rows = [r for r in store.candidates_for_run(run_id)
            if r["operator"] == "designer"]
    if not rows:
        return "(none yet)"
    rows.sort(key=lambda r: (r["generation_born"], r["hash"]))
    lines = []
    for r in rows:
        fate = (f"fitness {r['fitness']:.3f} Wh/km-agg" if r["fitness"]
                is not None else f"INVALID ({r['failure_reason']})")
        why = rationales.get(r["hash"], "")
        lines.append(f"- g{r['generation_born']} `{r['hash'][:8]}` {fate}"
                     + (f" — was: {why}" if why else ""))
    return "\n".join(lines[-20:])  # the most recent twenty keep it bounded


def _build_brief(store: Store, run_id: str, n: int,
                 kind: str = "periodic") -> str:
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
    elites_text = "\n".join(elites) or (
        "(none yet -- this is generation 0: propose diverse OPENING design "
        "hypotheses that stake out different regions of the genome space)")
    history, stall = _history_line(store, run_id)
    ask = (ASK_PIVOT.format(n=n, stall=stall) if kind == "pivot"
           else ASK_PERIODIC.format(n=n))
    return PROMPT_TEMPLATE.format(
        gene_spec=_gene_spec_text(), elites=elites_text, history=history,
        past_designs=_past_designs_text(store, run_id),
        failures=json.dumps(failures) or "{}", ask=ask,
        gene_names=gene_names,
        inspiration=_inspiration_block(store, run_id))


def _clean_items(items: list, n: int) -> list[tuple[dict, str]]:
    """Validate/clip raw proposal items onto the gene bounds."""
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


def _parse_proposals(text: str, n: int) -> list[tuple[dict, str]]:
    """Legacy text fallback: extract the JSON array from a prose reply."""
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if not match:
        return []
    return _clean_items(json.loads(match.group(0)), n)


def _ask_claude(prompt: str, n: int, model: str,
                timeout_s: float) -> tuple[list[tuple[dict, str]], str | None]:
    """Returns (proposals, exact_model_that_served_the_call)."""
    from .claude_cli import ask_structured

    data, exact_model, text = ask_structured(prompt, _proposals_schema(),
                                             model, timeout_s)
    if isinstance(data, dict) and isinstance(data.get("proposals"), list):
        return _clean_items(data["proposals"], n), exact_model
    return _parse_proposals(text, n), exact_model


def _prescreen(proposals: list[tuple[dict, str]], cfg: Config
               ) -> tuple[list[tuple[dict, str]], list[tuple[dict, str, str]]]:
    """Split proposals into (valid, rejected+reason) via the cheap
    constraint-only frame build -- no flight time wasted on designs the
    geometry would kill anyway."""
    from .frame_gen import build_frame
    ok: list[tuple[dict, str]] = []
    rejected: list[tuple[dict, str, str]] = []
    for genes, rationale in proposals:
        try:
            frame = build_frame(Genome.from_dict(genes), cfg.platform,
                                want_mesh=False)
            reason = None if frame.valid else frame.failure_reason
        except Exception as exc:
            reason = f"pre-screen error: {type(exc).__name__}"
        if reason is None:
            ok.append((genes, rationale))
        else:
            rejected.append((genes, rationale, reason))
    return ok, rejected


def _repair_brief(brief: str, rejected: list[tuple[dict, str, str]],
                  k: int) -> str:
    fails = "\n".join(f"- {json.dumps(g)} -> FAILED: {reason}"
                      for g, _, reason in rejected)
    return (brief + "\n\nPRE-SCREEN FEEDBACK: an earlier batch of proposals "
            "was checked against the frame's hard geometric constraints "
            "before flying, and these failed:\n" + fails +
            f"\n\nPropose exactly {k} NEW replacement vectors that avoid "
            "these failures (respect the couplings above; when in doubt, "
            "move sweeps toward stock or grow the plate scales). Same "
            "JSON-array format, nothing else.")


def design_round(store: Store, run_id: str, cfg: Config, generation: int,
                 n: int, model: str, timeout_s: float, log_dir: Path,
                 kind: str = "periodic") -> list[Proposal]:
    brief = _build_brief(store, run_id, n, kind=kind)
    try:
        proposals, exact_model = _ask_claude(brief, n, model, timeout_s)
    except Exception as exc:  # fail-soft: skip the round
        print(f"[framevo] designer round skipped: {type(exc).__name__}: {exc}",
              flush=True)
        return []
    ok, rejected = _prescreen(proposals, cfg)
    if rejected and len(ok) < n:  # one repair round with the failure reasons
        try:
            more, repair_model = _ask_claude(
                _repair_brief(brief, rejected, n - len(ok)),
                n - len(ok), model, timeout_s)
            if repair_model and repair_model != exact_model:
                exact_model = ", ".join(filter(None, {exact_model,
                                                      repair_model}))
            ok2, rejected2 = _prescreen(more, cfg)
            ok += ok2
            rejected += rejected2
        except Exception as exc:
            print(f"[framevo] designer repair round skipped: "
                  f"{type(exc).__name__}: {exc}", flush=True)
    if rejected:
        print(f"[framevo] designer pre-screen rejected "
              f"{len(rejected)} candidate(s)", flush=True)
    out = []
    accepted_meta = []
    log_lines = [f"\n## generation {generation} ({kind})\n"]
    if exact_model:
        print(f"[framevo] designer round served by {exact_model}", flush=True)
        log_lines.append(f"*model: {exact_model}*\n")
    for genes, rationale in ok[:n]:
        genome = Genome.from_dict(genes)
        out.append(Proposal(genome, None, None, "designer", None))
        accepted_meta.append({"hash": genome.hash, "rationale": rationale})
        log_lines.append(f"- `{genome.hash}` — {rationale}\n")
    rejected_meta = [{"rationale": rationale, "reason": reason}
                     for _, rationale, reason in rejected]
    for r in rejected_meta:
        log_lines.append(f"- ~~rejected pre-flight ({r['reason']})~~ — "
                         f"{r['rationale']}\n")
    store.record_designer_round(run_id, generation, kind, brief,
                                accepted_meta, rejected_meta,
                                model=exact_model)
    if out or rejected:
        log = log_dir / "designer_log.md"
        if not log.exists():
            log.write_text("# Designer rounds (headless Claude)\n")
        with open(log, "a") as f:
            f.writelines(log_lines)
    return out
