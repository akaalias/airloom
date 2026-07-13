"""Candidate evaluation pipeline: the functions executed inside worker
subprocesses, plus fitness aggregation.

Stage 1 (`build_task`): genome -> frame mesh, validity, STL + PNG artifacts,
drag table. Heavier imports (trimesh, matplotlib) happen only here.

Stage 2 (`scenario_task`): one (candidate, scenario) flight simulation.
Scenarios are embarrassingly parallel and are distributed as individual tasks.

Aggregation (`aggregate_fitness`): mean + lambda * worst across the scenario
portfolio (or pure minimax), infinity if any scenario failed.
"""
from __future__ import annotations

import dataclasses
import math
from pathlib import Path
from typing import Any

from .aero import DragTable
from .config import Config, load_config
from .genome import Genome
from .rotor_model import RotorModel
from .simulator import ScenarioResult, simulate_scenario

_CACHE: dict[str, tuple[Config, RotorModel]] = {}


def _write_mesh_blob(parts: dict[str, Any], path: Path) -> None:
    """Compact viewer payload for the gallery's interactive 3D canvases:
    base64 float32 vertices, uint16/32 face indices, and a per-face palette
    index so evolved vs fixed parts stay distinguishable. file:// pages
    cannot fetch local STLs (CORS), so the gallery inlines these blobs."""
    import base64
    import json

    import numpy as np

    from .render import DRAW_ORDER, PART_COLORS

    # per-part decimation budget; the physics/STL meshes stay full
    # resolution. The evolved parts (deck, arms) get generous budgets --
    # aggressive decimation warped their thin truss webs into false spikes
    # on screen -- while the fixed kit stays cheap. Bigger blobs simply
    # count against the gallery's total embed budget.
    budget = {"deck": 12000, "arms": 7000, "wiring": 1400, "motors": 1400,
              "props": 1600, "battery": 900, "stack": 900, "antennas": 700,
              "camera": 300}
    try:
        import fast_simplification
    except ImportError:
        fast_simplification = None

    verts_list, faces_list, fc_list, palette, part_names = [], [], [], [], []
    offset = 0
    for name in DRAW_ORDER:
        mesh = parts.get(name)
        if mesh is None:
            continue
        color, alpha = PART_COLORS.get(name, ("#8a97a8", 1.0))
        pi = len(palette)
        palette.append([int(color[1:3], 16), int(color[3:5], 16),
                        int(color[5:7], 16), round(alpha, 2)])
        part_names.append(name)
        v = np.asarray(mesh.vertices, dtype=np.float32)
        f = np.asarray(mesh.faces, dtype=np.int64)
        cap = budget.get(name, 1500)
        if fast_simplification is not None and len(f) > cap:
            v2, f2 = fast_simplification.simplify(
                np.asarray(mesh.vertices, dtype=np.float64), f,
                target_reduction=1.0 - cap / len(f))
            v = np.asarray(v2, dtype=np.float32)
            f = np.asarray(f2, dtype=np.int64)
        f = f + offset
        verts_list.append(v)
        faces_list.append(f)
        fc_list.append(np.full(len(f), pi, dtype=np.uint8))
        offset += len(v)
    if not verts_list:
        return
    verts = np.vstack(verts_list)
    faces = np.vstack(faces_list)
    fc = np.concatenate(fc_list)
    idx_dtype = np.uint16 if len(verts) < 65535 else np.uint32
    blob = {
        "v": base64.b64encode(verts.tobytes()).decode(),
        "f": base64.b64encode(faces.astype(idx_dtype).tobytes()).decode(),
        "i": "u16" if idx_dtype is np.uint16 else "u32",
        "fc": base64.b64encode(fc.tobytes()).decode(),
        "p": palette,
        "pn": part_names,
        "c": [float(x) for x in verts.mean(axis=0)],
        "r": float(np.linalg.norm(verts - verts.mean(axis=0), axis=1).max()),
    }
    path.write_text(json.dumps(blob))


def _context(root: str) -> tuple[Config, RotorModel]:
    """Per-process config + rotor tables (loaded once, reused across tasks)."""
    if root not in _CACHE:
        cfg = load_config(root)
        _CACHE[root] = (cfg, RotorModel.from_platform(cfg.platform.propulsion))
    return _CACHE[root]


def build_task(root: str, genome_values: tuple[float, ...], generation: int,
               results_dir: str) -> dict[str, Any]:
    """Build one candidate's geometry and artifacts. Returns a compact,
    picklable summary; the mesh itself stays in the STL file."""
    from .frame_gen import build_frame
    from .aero import build_drag_table
    from .render import render_bottom_view, render_parts, render_placeholder

    cfg, rotor = _context(root)
    genome = Genome(genome_values)
    frame = build_frame(genome, cfg.platform)

    gen_dir = Path(results_dir) / "frames" / f"gen_{generation:04d}"
    gen_dir.mkdir(parents=True, exist_ok=True)
    suffix = "" if frame.valid else "_INVALID"
    stl_path = gen_dir / f"{genome.hash}{suffix}.stl"
    png_path = gen_dir / f"{genome.hash}.png"

    mesh_json_path = gen_dir / f"{genome.hash}.mesh.json"
    if frame.mesh is not None:
        frame.mesh.export(stl_path)
        render_parts(frame.parts, png_path, valid=frame.valid)
        render_bottom_view(frame.parts,
                           png_path.with_name(png_path.stem + "_bottom.png"),
                           valid=frame.valid)
        _write_mesh_blob(frame.parts, mesh_json_path)
    else:
        render_placeholder(png_path, frame.failure_reason or "no mesh")

    out: dict[str, Any] = {
        "hash": genome.hash,
        "valid": frame.valid,
        "failure_reason": frame.failure_reason,
        "frame_mass": frame.frame_mass,
        "total_mass": frame.total_mass,
        "cg": [float(x) for x in frame.cg],
        "material": frame.material.name,
        "material_gene": genome["material"],
        "stl_path": str(stl_path),
        "png_path": str(png_path),
        "drag": None,
        "arm": None,
    }
    if frame.valid:
        drag = build_drag_table(frame, cfg.platform)
        out["drag"] = {f.name: getattr(drag, f.name) for f in dataclasses.fields(DragTable)}
        out["arm"] = dataclasses.asdict(frame.arm)
    return out


def scenario_task(root: str, total_mass: float, drag_fields: dict[str, Any],
                  scenario_name: str) -> dict[str, Any]:
    """Fly one scenario. Fixed per-scenario seeds make gust histories
    identical across candidates."""
    cfg, rotor = _context(root)
    drag = DragTable(**drag_fields)
    result = simulate_scenario(total_mass, drag, rotor, cfg.scenario(scenario_name),
                               cfg.mission, cfg.rain)
    return dataclasses.asdict(result)


def structural_check(root: str, arm_fields: dict[str, Any], total_mass: float,
                     peak_rotor_thrust: float,
                     material_gene: float) -> tuple[bool, str | None, float]:
    """Worst-case-across-scenarios structural constraint (runs in-parent:
    it is a closed-form beam calculation)."""
    from .frame_gen import ArmProperties
    from .structures import check_structure

    cfg, rotor = _context(root)
    # hover rotor frequency (1P) for the resonance band, ISA sea level
    hover_n, _ = rotor.hover(total_mass, 1.225)
    res = check_structure(ArmProperties(**arm_fields), peak_rotor_thrust,
                          hover_n, cfg.platform,
                          cfg.platform.material_for(material_gene))
    return res.ok, res.reason, res.f1_hz


def aggregate_fitness(results: list[ScenarioResult | None], mode: str,
                      lambda_worst: float) -> tuple[float, float, float]:
    """(fitness, mean_whkm, worst_whkm). Any failed/missing scenario -> inf."""
    if any(r is None or not r.valid for r in results) or not results:
        return math.inf, math.inf, math.inf
    values = [r.wh_per_km for r in results]  # type: ignore[union-attr]
    mean = sum(values) / len(values)
    worst = max(values)
    if mode == "minimax":
        return worst, mean, worst
    return mean + lambda_worst * worst, mean, worst
