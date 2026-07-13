"""Champion-only structural verification: off the loop's critical path.

The in-loop constraint (structures.py) is a constant-section cantilever
checked at the arm ROOT with datasheet strength. The optimizer therefore
pushes winners toward that model's blind spots: stress concentrations at
bolt holes and lightening cutouts along the shaft, and as-printed strength
well below datasheet (perimeter seams, layer adhesion, moisture).

This module re-analyzes the top-N frames of a run with a refined model:

  1. station-by-station variable-section bending along the REAL morphed arm
     outline (net width = shell minus holes/cutouts crossing each station),
  2. a net-section stress-concentration factor at pierced stations
     (Peterson, Kt = 2 + (1 - d/w)^3 -- the tension form, conservative for
     plate bending),
  3. the material's as-built strength knockdown (platform.yaml
     `as_built_strength_frac`),
  4. tip deflection re-integrated over the actual I(x) distribution.

It is deliberately NOT full FEM -- it is a hand-checkable refinement that
catches the two known optimisms. The per-station geometry it exports is
also the natural input for a CalculiX/shell pass later, and the report ends
with a physical print-and-test protocol, which beats any simulation.

Output: results/champion_check.md + a returned summary dict.
CLI: `framevo verify-champions [--top N] [--run-id ID]`.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any

import numpy as np

from .config import Config, Material
from .realgeo import ArmOutline

G = 9.80665
STATION_STEP_MM = 0.5
SLAB_MM = 0.75          # half-width of the sampling slab around a station


@dataclass(frozen=True)
class Station:
    x_mm: float
    w_gross_mm: float
    w_net_mm: float
    removed_mm: float     # summed hole/cutout chord at this station
    kt: float
    moment_nm: float
    stress_pa: float      # Kt * M c / I_net


@dataclass(frozen=True)
class ArmVerdict:
    stations: tuple[Station, ...]
    p_tip_n: float                # applied load (peak thrust x SF)
    x_crit_mm: float
    stress_max_pa: float
    kt_crit: float
    feature_crit: str             # "hole/cutout" | "plain section"
    strength_as_built_pa: float
    margin: float                 # as-built strength / peak refined stress
    margin_naive: float           # datasheet strength / root beam stress
    tip_deflection_m: float
    deflection_limit_m: float
    predicted_failure_load_n: float


def _extents_at(pts: np.ndarray, x: float, slab: float = SLAB_MM) -> float:
    ys = pts[np.abs(pts[:, 0] - x) < slab][:, 1]
    return float(ys.max() - ys.min()) if len(ys) > 1 else 0.0


def _densify(poly: np.ndarray, step: float = 0.7) -> np.ndarray:
    out = []
    for a, b in zip(poly, np.roll(poly, -1, axis=0)):
        n = max(int(np.linalg.norm(b - a) / step), 1)
        out += [a + (b - a) * t for t in np.linspace(0, 1, n, endpoint=False)]
    return np.array(out)


def analyze_arm(arm: ArmOutline, thickness_m: float, material: Material,
                p_tip_n: float,
                max_tip_deflection_frac: float = 0.05) -> ArmVerdict:
    """Refined bending check of one (morphed) arm under a tip load at the
    motor axis, cantilevered at the tongue end (deck clamp edge)."""
    shell = _densify(arm.shell)
    cut_pts = [_densify(c) for c in arm.cutouts]
    x_root, x_mount = arm.tongue_end, arm.mount_start
    x_tip = arm.motor_xy[0]
    t = thickness_m
    e_mod = material.youngs_modulus_pa
    strength_built = material.tensile_strength_pa * material.as_built_strength_frac

    xs = np.arange(x_root + 0.5, x_mount - 0.25, STATION_STEP_MM)
    stations: list[Station] = []
    inv_ei = []  # 1/EI per station, for the deflection integral
    for x in xs:
        w_gross = _extents_at(shell, x)
        if w_gross <= 0.0:
            continue
        removed = 0.0
        for hx, _hy, r in arm.holes:
            if abs(x - hx) < r:
                removed += 2.0 * math.sqrt(r * r - (x - hx) ** 2)
        for cp in cut_pts:
            if cp[:, 0].min() - SLAB_MM < x < cp[:, 0].max() + SLAB_MM:
                removed += _extents_at(cp, x)
        w_net = max(w_gross - removed, 0.3)  # never a zero-width section
        d_over_w = min(removed / w_gross, 0.95)
        kt = 2.0 + (1.0 - d_over_w) ** 3 if removed > 0.2 else 1.0

        m_nm = p_tip_n * (x_tip - x) * 1e-3
        w_net_m = w_net * 1e-3
        i_net = w_net_m * t ** 3 / 12.0
        stress = kt * m_nm * (t / 2.0) / i_net
        stations.append(Station(float(x), w_gross, w_net, removed, kt,
                                m_nm, stress))
        inv_ei.append(1.0 / (e_mod * w_net_m * t ** 3 / 12.0))

    crit = max(stations, key=lambda s: s.stress_pa)
    feature = "hole/cutout" if crit.removed_mm > 0.2 else "plain section"

    # unit-load deflection integral over the flexible shaft (tongue and
    # motor-mount zones treated as rigid): delta = int M(x)^2 / (EI P) dx
    dx_m = STATION_STEP_MM * 1e-3
    defl = sum(s.moment_nm ** 2 * ie for s, ie in zip(stations, inv_ei)) \
        * dx_m / p_tip_n
    arm_len_m = (x_tip - x_root) * 1e-3

    # naive view = the in-loop model: root station, no Kt, datasheet strength
    root = stations[0]
    naive_stress = root.stress_pa / root.kt
    return ArmVerdict(
        stations=tuple(stations), p_tip_n=p_tip_n,
        x_crit_mm=crit.x_mm, stress_max_pa=crit.stress_pa, kt_crit=crit.kt,
        feature_crit=feature, strength_as_built_pa=strength_built,
        margin=strength_built / crit.stress_pa,
        margin_naive=material.tensile_strength_pa / naive_stress,
        tip_deflection_m=defl,
        deflection_limit_m=max_tip_deflection_frac * arm_len_m,
        predicted_failure_load_n=p_tip_n * strength_built / crit.stress_pa)


def morphed_front_arm(genome_dict: dict[str, float], cfg: Config) -> tuple[ArmOutline, float, Material]:
    """(morphed front-arm outline, thickness m, material) for one genome --
    exactly the geometry frame_gen builds."""
    from .realgeo import load_outlines, morph_arm
    src_dir = str(cfg.platform.propulsion.uiuc_data_dir.parent / "source_one")
    outlines = load_outlines(src_dir)
    arm = morph_arm(outlines["arm_front"], genome_dict["arm_length_scale"],
                    genome_dict["arm_width_scale"],
                    genome_dict["arm_waist_scale"])
    material = cfg.platform.material_for(genome_dict["material"])
    return arm, genome_dict["arm_thickness"], material


# ---------------------------------------------------------------- report --
def verify_champions(cfg: Config, run_id: str | None = None,
                     top: int = 5) -> dict[str, Any]:
    from .dbstore import Store

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
        arm, t_m, material = morphed_front_arm(genome, cfg)
        v = analyze_arm(arm, t_m, material, max(peaks) * sf,
                        cfg.platform.max_tip_deflection_frac)
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
        "Refined variable-section bending along the real morphed arm "
        "outline with net-section stress concentration (Peterson "
        "Kt = 2 + (1 − d/w)³) and as-built strength knockdowns — the two "
        "optimisms the in-loop beam constraint cannot see. Load = worst "
        f"per-rotor thrust across all flown scenarios × {sf:g} safety "
        "factor, applied at the motor axis, arm cantilevered at the deck "
        "clamp. Not FEM; a hand-checkable refinement (and the geometry "
        "export a CalculiX pass would start from).",
        "",
        "| rank | frame | material | refined verdict | margin (refined) "
        "| margin (in-loop view) | critical station | Kt | deflection |",
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
        "*margin (in-loop view)* = datasheet strength over plain root-"
        "section stress — what the evolutionary constraint saw. A frame "
        "whose refined margin drops below 1.0 while the in-loop margin "
        "looked fine is exactly the constraint-boundary optimism this "
        "report exists to catch.",
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
