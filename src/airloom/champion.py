"""Champion-only structural verification: off the loop's critical path.

The in-loop constraint (structures.py) is now the same station-by-station,
Kt-aware, taper-aware beam model this module used to be the only place
running (promoted 2026-07-24 -- see structures.py's docstring for why a
root-only check stopped being safe once the genome could taper thickness
or pierce the shaft with lightening holes). The in-loop gate checks stress
against plain DATASHEET strength; what this module still uniquely adds:

  1. the material's as-built strength knockdown (platform.yaml
     `as_built_strength_frac`) -- printed strength well below datasheet
     (perimeter seams, layer adhesion, moisture) -- as the margin this
     report verdicts on,
  2. a physical print-and-test protocol with predicted hold/failure loads.

It is deliberately NOT full FEM -- it is a hand-checkable refinement, and
the per-station geometry it exports is also the natural input for a
CalculiX/shell pass later.

Output: results/champion_check.md + a returned summary dict.
CLI: `airloom verify-champions [--top N] [--run-id ID]`.
"""
from __future__ import annotations

import json
from typing import Any

from .config import Config
from .structures import ArmVerdict, analyze_arm

G = 9.80665


# ---------------------------------------------------------------- report --
def verify_champions(cfg: Config, run_id: str | None = None,
                     top: int = 5) -> dict[str, Any]:
    from .dbstore import Store
    from .frame_gen import build_arm_front

    results_dir = cfg.evolution.results_dir
    store = Store(results_dir / "run.db")
    run_id = run_id or store.latest_run_id(with_data=True)
    if run_id is None:
        raise SystemExit("no runs with data found in run.db")

    rows = [r for r in store.candidates_for_run(run_id)
            if r["valid"] and r["fitness"] is not None]
    rows.sort(key=lambda r: r["fitness"])
    rows = rows[:top]
    if not rows:
        raise SystemExit(f"run {run_id}: no valid candidates")

    sf = cfg.platform.safety_factor
    champions = []
    for rank, r in enumerate(rows, 1):
        peaks = [s["peak_rotor_thrust_n"]
                 for s in store.scenario_results_for(run_id, r["hash"])
                 if s["peak_rotor_thrust_n"] is not None]
        if not peaks:
            continue
        genome = json.loads(r["genome_json"])
        arm, t_m, tip_scale, material = build_arm_front(genome, cfg.platform)
        v = analyze_arm(arm, t_m, material, max(peaks) * sf,
                        cfg.platform.max_tip_deflection_frac,
                        tip_thickness_scale=tip_scale)
        champions.append({
            "rank": rank, "hash": r["hash"], "fitness": r["fitness"],
            "material": material.name, "thickness_mm": t_m * 1e3,
            "peak_thrust_n": max(peaks), "verdict": v,
        })

    out_path = results_dir / "champion_check.md"
    out_path.write_text(_report_md(run_id, cfg, champions))
    n_bad = sum(1 for c in champions if c["verdict"].margin < 1.0)
    n_marginal = sum(1 for c in champions if 1.0 <= c["verdict"].margin < 1.2)
    print(f"champion check: {len(champions)} frames -- "
          f"{n_bad} overstressed, {n_marginal} marginal under the refined "
          f"model (report: {out_path})")
    return {"run_id": run_id, "champions": champions, "report": str(out_path),
            "n_overstressed": n_bad, "n_marginal": n_marginal}


def _verdict_word(margin: float) -> str:
    if margin < 1.0:
        return "**OVERSTRESSED**"
    if margin < 1.2:
        return "**MARGINAL**"
    return "OK"


def _report_md(run_id: str, cfg: Config, champions: list[dict]) -> str:
    from datetime import datetime, timezone
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    sf = cfg.platform.safety_factor
    lines = [
        "# Champion structural verification",
        "",
        f"Run `{run_id}`, top {len(champions)} frames ({ts}). "
        "The in-loop constraint already runs this same station-by-station "
        "bending model along the real morphed arm outline, with net-section "
        "stress concentration (Peterson Kt = 2 + (1 − d/w)³) and the taper "
        "gene included, gated on plain datasheet strength. This report's "
        "own addition is the as-built strength knockdown (print quality: "
        "perimeter seams, layer adhesion, moisture) — the one optimism the "
        "fast in-loop gate deliberately doesn't apply — plus a bench "
        f"print-and-test protocol. Load = worst per-rotor thrust across "
        f"all flown scenarios × {sf:g} safety factor, applied at the motor "
        "axis, arm cantilevered at the deck clamp. Not FEM; a "
        "hand-checkable refinement (and the geometry export a CalculiX "
        "pass would start from).",
        "",
        "| rank | frame | material | as-built verdict | margin (as-built) "
        "| margin (root-only view) | critical station | Kt | deflection |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for c in champions:
        v: ArmVerdict = c["verdict"]
        defl = (f"{v.tip_deflection_m * 1e3:.1f} mm"
                f"{' ⚠' if v.tip_deflection_m > v.deflection_limit_m else ''}")
        lines.append(
            f"| {c['rank']} | `{c['hash']}` | {c['material']} "
            f"{c['thickness_mm']:.1f} mm | {_verdict_word(v.margin)} "
            f"| {v.margin:.2f} | {v.margin_naive:.2f} "
            f"| x={v.x_crit_mm:.0f} mm ({v.feature_crit}) "
            f"| {v.kt_crit:.2f} | {defl} |")
    lines += [
        "",
        "*margin (as-built)* uses the full station-by-station stress "
        "against the material's as-built (print-derated) strength — the "
        "number this report verdicts on. *margin (root-only view)* checks "
        "only the root station, no Kt, against plain datasheet strength — "
        "roughly what a much simpler check would have seen; a frame whose "
        "full-shaft margin drops well below its root-only margin usually "
        "means the critical point is mid-shaft (a taper or a lightening "
        "hole), not the root.",
        "",
        "## Print-and-test protocol (per arm)",
        "",
        "Simulation ends where a bench vise begins. For each frame above:",
        "",
        "1. Print/cut ONE arm flat (the gallery's `gen_XXXX_best_parts/` "
        "pieces are already in print orientation).",
        "2. Clamp the tongue (root to the tongue-end line) between two "
        "rigid plates in a vise — replicating the deck sandwich.",
        "3. Load at the motor-mount holes, perpendicular to the plate, "
        "via a luggage scale pulled slowly (5 s ramp).",
    ]
    for c in champions:
        v = c["verdict"]
        hold = v.p_tip_n
        fail = v.predicted_failure_load_n
        lines.append(
            f"   - `{c['hash']}` ({c['material']}): must hold "
            f"**{hold:.1f} N** ({hold / G * 1000:.0f} gf) without cracking; "
            f"predicted failure ≈ {fail:.1f} N ({fail / G * 1000:.0f} gf). "
            f"Failure below the hold load falsifies the eval's structural "
            f"constraint for this geometry — feed that back before Phase B.")
    lines.append("")
    return "\n".join(lines)
