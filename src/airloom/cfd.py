"""Phase B milestone 1: OpenFOAM drag-calibration harness.

The robustness sweep showed that only the ARM drag coefficient reorders
the leaderboard, so before any per-candidate CFD pipeline we calibrate
the component buildup's global knobs against a handful of RANS cases:

  arms_baseline   -> measures the arm-class CdA        (calibrates CD_ARM)
  body_baseline   -> measures the deck/kit-class CdA   (calibrates CD_BODY)
  full_baseline   -> ground truth for the whole frame; the residual
                     full - (arms + body) IS the interference drag the
                     buildup currently assumes to be zero
  full_contrast   -> the same assembly for a contrasting genome; if its
                     interference fraction differs from the baseline's,
                     interference varies with the genes and can reorder
                     candidates (else it is an absolute-only error)

Each geometry is meshed once (blockMesh + snappyHexMesh) and solved at
three tilt angles (0/20/40 deg at cruise speed) by varying the freestream
velocity vector -- far-field patches use freestream BCs so no re-meshing
per angle. simpleFoam, k-omega SST, wall functions; a forces function
object writes force.dat, and CdA = 2 F.d_hat / (rho U^2).

Everything except the actual solve works without Docker: `airloom
cfd-calibrate` writes cases + manifest.json under cfd/, `--solve` runs
them through opencfd/openfoam-default, `--report` parses the forces and
writes cfd/calibration.md next to the analytical predictions. Local-first
rule: Docker is strictly optional; case generation and the report are
plain Python.
"""
from __future__ import annotations

import json
import math
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np

from .aero import CD_ARM, CD_BODY, AreaTable, measure_areas
from .config import Config
from .genome import BASELINE, Genome

RHO = 1.225                    # calibration is an ISA sea-level exercise
NU = 1.48e-05
TILTS_DEG = (0.0, 20.0, 40.0)
DOCKER_IMAGE = "opencfd/openfoam-default"

# A deliberately different point in gene space: long thin-waisted arms,
# open deck gap, tilted battery -- the geometry features that could
# plausibly change how much the components interfere. (Sweep genes are
# pinned by the bolt-registration constraint and cannot move far.) Must
# build VALID (asserted on export).
CONTRAST_GENES: dict[str, float] = dict(
    BASELINE, arm_length_scale=1.30, arm_waist_scale=0.70,
    deck_gap=0.042, battery_wedge_deg=10.0)


@dataclass(frozen=True)
class CaseSpec:
    """One (geometry, tilt) solve."""
    name: str            # e.g. full_baseline_t20
    geometry: str        # arms_baseline | body_baseline | full_* ...
    tilt_deg: float
    u_ms: float
    predicted_cda_m2: float | None   # component buildup's number, None for
                                     # geometries the buildup has no claim on


# ----------------------------------------------------------- geometry -----
def _frame_for(genes: dict[str, float], cfg: Config):
    from .frame_gen import build_frame
    frame = build_frame(Genome.from_dict(genes), cfg.platform)
    if not frame.valid:
        raise SystemExit(f"calibration genome does not build: "
                         f"{frame.failure_reason}")
    return frame


def _interp_tilt(grid_tilt: np.ndarray, values: np.ndarray,
                 tilt: float) -> float:
    return float(np.interp(tilt, grid_tilt, values))


def predicted_cda(areas: AreaTable, geometry: str, tilt: float) -> float:
    """The component buildup's prediction for flow along body x at `tilt`
    (the same direction the CFD cases use)."""
    arm = _interp_tilt(areas.tilt_deg, areas.arm_x, tilt) * CD_ARM
    body = _interp_tilt(areas.tilt_deg, areas.body_x, tilt) * CD_BODY
    if geometry.startswith("arms"):
        return arm
    if geometry.startswith("body"):
        return body
    return arm + body   # full assembly: the buildup just sums (that gap is
                        # exactly what full_* cases measure)


def export_geometries(cfg: Config, out_dir: Path) -> dict[str, dict[str, Any]]:
    """Write one watertight-ish STL per geometry; return geometry metadata
    (STL path, bbox, analytical areas) keyed by geometry name."""
    import trimesh

    out_dir.mkdir(parents=True, exist_ok=True)
    base = _frame_for(BASELINE, cfg)
    contrast = _frame_for(CONTRAST_GENES, cfg)
    geoms = {
        "arms_baseline": (base.arms_mesh, measure_areas(base, cfg.platform)),
        "body_baseline": (base.body_mesh, measure_areas(base, cfg.platform)),
        "full_baseline": (trimesh.util.concatenate(
            [base.arms_mesh, base.body_mesh]),
            measure_areas(base, cfg.platform)),
        "full_contrast": (trimesh.util.concatenate(
            [contrast.arms_mesh, contrast.body_mesh]),
            measure_areas(contrast, cfg.platform)),
    }
    meta: dict[str, dict[str, Any]] = {}
    for name, (mesh, areas) in geoms.items():
        stl = out_dir / f"{name}.stl"
        mesh.export(stl)
        meta[name] = {
            "stl": str(stl),
            "bounds": [list(map(float, b)) for b in mesh.bounds],
            "areas": {k: (list(map(float, v)) if isinstance(v, np.ndarray)
                          else float(v))
                      for k, v in asdict(areas).items()},
        }
    return meta


# ------------------------------------------------- OpenFOAM case files ----
def _fmt_vec(v) -> str:
    return f"({v[0]:.6g} {v[1]:.6g} {v[2]:.6g})"


def _header(cls: str, obj: str) -> str:
    return ("FoamFile\n{\n    version 2.0;\n    format ascii;\n"
            f"    class {cls};\n    object {obj};\n}}\n\n")


def _block_mesh_dict(bounds, cell: float) -> str:
    (x0, y0, z0), (x1, y1, z1) = bounds
    # generous box: 4 lengths downstream, ~1.5 up/side (freestream BCs
    # tolerate closer far fields than fixed-value ones)
    lx = x1 - x0
    lo = (x0 - 1.5 * lx, y0 - 1.2 * lx, z0 - 1.2 * lx)
    hi = (x1 + 4.0 * lx, y1 + 1.2 * lx, z1 + 1.2 * lx)
    n = [max(int((h - l) / cell), 10) for l, h in zip(lo, hi)]
    vs = [(lo[0], lo[1], lo[2]), (hi[0], lo[1], lo[2]),
          (hi[0], hi[1], lo[2]), (lo[0], hi[1], lo[2]),
          (lo[0], lo[1], hi[2]), (hi[0], lo[1], hi[2]),
          (hi[0], hi[1], hi[2]), (lo[0], hi[1], hi[2])]
    verts = "\n".join(f"    {_fmt_vec(v)}" for v in vs)
    return (_header("dictionary", "blockMeshDict") +
            "scale 1;\n\nvertices\n(\n" + verts + "\n);\n\n"
            "blocks\n(\n    hex (0 1 2 3 4 5 6 7) "
            f"({n[0]} {n[1]} {n[2]}) simpleGrading (1 1 1)\n);\n\n"
            "boundary\n(\n    farfield\n    {\n        type patch;\n"
            "        faces\n        (\n"
            "            (0 3 2 1) (4 5 6 7) (0 1 5 4)\n"
            "            (2 3 7 6) (1 2 6 5) (0 4 7 3)\n"
            "        );\n    }\n);\n")


def _snappy_dict(inside_point) -> str:
    return (_header("dictionary", "snappyHexMeshDict") + f"""
castellatedMesh true;
snap            true;
addLayers       false;

geometry
{{
    frame.stl {{ type triSurfaceMesh; name frame; }}
}}

castellatedMeshControls
{{
    maxLocalCells        2000000;
    maxGlobalCells       6000000;
    minRefinementCells   10;
    nCellsBetweenLevels  3;
    features             ();
    refinementSurfaces   {{ frame {{ level (4 5); }} }}
    resolveFeatureAngle  30;
    refinementRegions    {{}};
    locationInMesh       {_fmt_vec(inside_point)};
    allowFreeStandingZoneFaces true;
}}

snapControls
{{
    nSmoothPatch            3;
    tolerance               2.0;
    nSolveIter              50;
    nRelaxIter              5;
    nFeatureSnapIter        10;
    implicitFeatureSnap     true;
    explicitFeatureSnap     false;
    multiRegionFeatureSnap  false;
}}

addLayersControls {{ relativeSizes true; layers {{}}; expansionRatio 1.2;
    finalLayerThickness 0.3; minThickness 0.1; nGrow 0; featureAngle 60;
    nRelaxIter 3; nSmoothSurfaceNormals 1; nSmoothNormals 3;
    nSmoothThickness 10; maxFaceThicknessRatio 0.5;
    maxThicknessToMedialRatio 0.3; minMedianAxisAngle 90;
    nBufferCellsNoExtrude 0; nLayerIter 50; }}

meshQualityControls
{{
    maxNonOrtho            65;
    maxBoundarySkewness    20;
    maxInternalSkewness    4;
    maxConcave             80;
    minVol                 1e-13;
    minTetQuality          1e-15;
    minArea                -1;
    minTwist               0.02;
    minDeterminant         0.001;
    minFaceWeight          0.05;
    minVolRatio            0.01;
    minTriangleTwist       -1;
    nSmoothScale           4;
    errorReduction         0.75;
}}

writeFlags ();
mergeTolerance 1e-6;
""")


def _control_dict(iters: int) -> str:
    return (_header("dictionary", "controlDict") + f"""
application     simpleFoam;
startFrom       latestTime;
startTime       0;
stopAt          endTime;
endTime         {iters};
deltaT          1;
writeControl    timeStep;
writeInterval   {iters};
purgeWrite      2;

functions
{{
    forces1
    {{
        type            forces;
        libs            (forces);
        patches         (frame);
        rho             rhoInf;
        rhoInf          {RHO};
        CofR            (0 0 0);
        writeControl    timeStep;
        writeInterval   10;
    }}
}}
""")


_FV_SCHEMES = _header("dictionary", "fvSchemes") + """
ddtSchemes      { default steadyState; }
gradSchemes     { default cellLimited Gauss linear 1; }
divSchemes
{
    default                     none;
    div(phi,U)                  bounded Gauss linearUpwind grad(U);
    div(phi,k)                  bounded Gauss upwind;
    div(phi,omega)              bounded Gauss upwind;
    div((nuEff*dev2(T(grad(U))))) Gauss linear;
}
laplacianSchemes { default Gauss linear limited 0.33; }
interpolationSchemes { default linear; }
snGradSchemes   { default limited 0.33; }
wallDist        { method meshWave; }
"""

_FV_SOLUTION = _header("dictionary", "fvSolution") + """
solvers
{
    p
    {
        solver          GAMG;
        smoother        GaussSeidel;
        tolerance       1e-7;
        relTol          0.01;
    }
    "(U|k|omega)"
    {
        solver          smoothSolver;
        smoother        symGaussSeidel;
        tolerance       1e-8;
        relTol          0.1;
    }
}

SIMPLE
{
    nNonOrthogonalCorrectors 1;
    consistent      no;
    residualControl { p 1e-4; U 1e-5; "(k|omega)" 1e-5; }
}

relaxationFactors
{
    fields    { p 0.3; }
    equations { U 0.7; k 0.7; omega 0.7; }
}
"""


def _field(cls: str, obj: str, dims: str, internal: str,
           farfield: str, frame: str) -> str:
    return (_header(cls, obj) +
            f"dimensions      {dims};\n\n"
            f"internalField   {internal};\n\n"
            "boundaryField\n{\n"
            f"    farfield\n    {{\n{farfield}\n    }}\n"
            f"    frame\n    {{\n{frame}\n    }}\n"
            "}\n")


def _write_fields(case: Path, u_vec) -> None:
    u = _fmt_vec(u_vec)
    umag = math.sqrt(sum(x * x for x in u_vec))
    k = 1.5 * (0.01 * umag) ** 2          # 1 % turbulence intensity
    omega = math.sqrt(k) / (0.09 ** 0.25 * 0.05)  # 5 cm length scale
    z = case / "0"
    z.mkdir(exist_ok=True)
    (z / "U").write_text(_field(
        "volVectorField", "U", "[0 1 -1 0 0 0 0]", f"uniform {u}",
        f"        type freestreamVelocity;\n"
        f"        freestreamValue uniform {u};\n"
        f"        value uniform {u};",
        "        type noSlip;"))
    (z / "p").write_text(_field(
        "volScalarField", "p", "[0 2 -2 0 0 0 0]", "uniform 0",
        "        type freestreamPressure;\n"
        "        freestreamValue uniform 0;\n"
        "        value uniform 0;",
        "        type zeroGradient;"))
    (z / "k").write_text(_field(
        "volScalarField", "k", "[0 2 -2 0 0 0 0]", f"uniform {k:.6g}",
        f"        type inletOutlet;\n"
        f"        inletValue uniform {k:.6g};\n"
        f"        value uniform {k:.6g};",
        "        type kqRWallFunction;\n"
        f"        value uniform {k:.6g};"))
    (z / "omega").write_text(_field(
        "volScalarField", "omega", "[0 0 -1 0 0 0 0]",
        f"uniform {omega:.6g}",
        f"        type inletOutlet;\n"
        f"        inletValue uniform {omega:.6g};\n"
        f"        value uniform {omega:.6g};",
        "        type omegaWallFunction;\n"
        f"        value uniform {omega:.6g};"))
    (z / "nut").write_text(_field(
        "volScalarField", "nut", "[0 2 -1 0 0 0 0]", "uniform 0",
        "        type calculated;\n        value uniform 0;",
        "        type nutkWallFunction;\n        value uniform 0;"))


def write_case(case_dir: Path, stl: Path, bounds, u_vec,
               iters: int = 600) -> None:
    """One complete, runnable OpenFOAM case directory."""
    sysd = case_dir / "system"
    const = case_dir / "constant"
    tri = const / "triSurface"
    for d in (sysd, const, tri):
        d.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(stl, tri / "frame.stl")

    lx = bounds[1][0] - bounds[0][0]
    cell = max(lx / 6.0, 0.05)   # background cell; level 5 -> lx/192 at wall
    # locationInMesh: near the upstream box corner, guaranteed outside the
    # geometry, inside the domain
    inside = (bounds[0][0] - 1.2 * lx, bounds[0][1] - 0.9 * lx,
              bounds[0][2] - 0.9 * lx)
    (sysd / "blockMeshDict").write_text(_block_mesh_dict(bounds, cell))
    (sysd / "snappyHexMeshDict").write_text(_snappy_dict(inside))
    (sysd / "controlDict").write_text(_control_dict(iters))
    (sysd / "fvSchemes").write_text(_FV_SCHEMES)
    (sysd / "fvSolution").write_text(_FV_SOLUTION)
    (const / "turbulenceProperties").write_text(
        _header("dictionary", "turbulenceProperties") +
        "simulationType RAS;\n\nRAS\n{\n    RASModel kOmegaSST;\n"
        "    turbulence on;\n    printCoeffs on;\n}\n")
    (const / "transportProperties").write_text(
        _header("dictionary", "transportProperties") +
        f"transportModel Newtonian;\n\nnu {NU};\n")
    _write_fields(case_dir, u_vec)


# ------------------------------------------------------------ manifest ----
def generate(cfg: Config, out_root: Path,
             tilts: tuple[float, ...] = TILTS_DEG) -> list[CaseSpec]:
    """Export geometries + write every case; cfd/manifest.json records the
    specs and analytical predictions the report will compare against."""
    u = cfg.mission.cruise_speed_ms
    geo_dir = out_root / "geometry"
    meta = export_geometries(cfg, geo_dir)
    specs: list[CaseSpec] = []
    for gname, g in meta.items():
        areas = AreaTable(**{k: (np.array(v) if isinstance(v, list) else v)
                             for k, v in g["areas"].items()})
        for tilt in tilts:
            t = math.radians(tilt)
            spec = CaseSpec(
                name=f"{gname}_t{int(tilt):02d}", geometry=gname,
                tilt_deg=tilt, u_ms=u,
                predicted_cda_m2=predicted_cda(areas, gname, tilt))
            case_dir = out_root / "cases" / spec.name
            # flow along body x at `tilt`: same direction aero.py rasterizes
            write_case(case_dir, Path(g["stl"]), g["bounds"],
                       (u * math.cos(t), 0.0, u * math.sin(t)))
            specs.append(spec)
    (out_root / "manifest.json").write_text(json.dumps(
        {"rho": RHO, "u_ms": u, "docker_image": DOCKER_IMAGE,
         "cases": [asdict(s) for s in specs]}, indent=2))
    return specs


# ------------------------------------------------------- solve + report ---
def solve_case(case_dir: Path, image: str = DOCKER_IMAGE,
               log_to: Path | None = None) -> None:
    """blockMesh + snappyHexMesh + simpleFoam inside the OpenFOAM container.
    Raises CalledProcessError on solver failure (log kept beside the case)."""
    cmd = ["docker", "run", "--rm", "-v", f"{case_dir.resolve()}:/case",
           "-w", "/case", "--entrypoint", "/bin/bash", image, "-lc",
           "source /openfoam/bash.rc 2>/dev/null || "
           "source /usr/lib/openfoam/openfoam*/etc/bashrc; "
           "blockMesh && snappyHexMesh -overwrite && simpleFoam"]
    log = log_to or (case_dir / "run.log")
    with open(log, "w") as f:
        subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, check=True)


def parse_forces(case_dir: Path) -> tuple[float, float, float]:
    """Total force vector [N] from the last line of the forces output.
    Handles both force.dat layouts: (total pressure viscous) and
    (pressure viscous porous)."""
    candidates = sorted(case_dir.glob("postProcessing/forces1/*/force*.dat"))
    if not candidates:
        raise FileNotFoundError(f"no force.dat under {case_dir}")
    last = ""
    for line in candidates[-1].read_text().splitlines():
        if line.strip() and not line.lstrip().startswith("#"):
            last = line
    nums = [float(x) for x in
            last.replace("(", " ").replace(")", " ").split()]
    triplets = [nums[i:i + 3] for i in range(1, min(len(nums), 10), 3)]
    if len(triplets) >= 3:
        t0, t1, t2 = triplets[0], triplets[1], triplets[2]
        if all(abs(a - (b + c)) <= 1e-6 + 1e-3 * abs(a)
               for a, b, c in zip(t0, t1, t2)):
            return tuple(t0)          # new layout: first triplet is total
    return tuple(a + b for a, b in zip(triplets[0], triplets[1]))


def measured_cda(case_dir: Path, tilt_deg: float, u: float) -> float:
    fx, fy, fz = parse_forces(case_dir)
    t = math.radians(tilt_deg)
    drag = fx * math.cos(t) + fz * math.sin(t)   # force along the freestream
    return drag / (0.5 * RHO * u * u)


def write_report(out_root: Path) -> Path:
    man = json.loads((out_root / "manifest.json").read_text())
    rows, missing = [], []
    for c in man["cases"]:
        case_dir = out_root / "cases" / c["name"]
        try:
            cda = measured_cda(case_dir, c["tilt_deg"], c["u_ms"])
        except (FileNotFoundError, IndexError, ValueError):
            missing.append(c["name"])
            continue
        rows.append({**c, "measured_cda_m2": cda})

    lines = ["# CFD drag calibration", ""]
    if missing:
        lines += [f"unsolved cases ({len(missing)}): "
                  + ", ".join(f"`{m}`" for m in missing),
                  "run `airloom cfd-calibrate --solve` first.", ""]
    if rows:
        lines += ["| case | tilt | buildup CdA [m²] | CFD CdA [m²] | ratio |",
                  "|---|---|---|---|---|"]
        by_key = {}
        for r in rows:
            pred, meas = r["predicted_cda_m2"], r["measured_cda_m2"]
            ratio = meas / pred if pred else float("nan")
            by_key[(r["geometry"], r["tilt_deg"])] = meas
            lines.append(f"| `{r['name']}` | {r['tilt_deg']:.0f}° "
                         f"| {pred:.5f} | {meas:.5f} | {ratio:.2f} |")
        # interference: full - (arms + body), per tilt where all measured
        lines += ["", "## Interference (measured full − sum of parts)", ""]
        for tilt in sorted({r["tilt_deg"] for r in rows}):
            f = by_key.get(("full_baseline", tilt))
            a = by_key.get(("arms_baseline", tilt))
            b = by_key.get(("body_baseline", tilt))
            if None not in (f, a, b):
                lines.append(f"- {tilt:.0f}°: {f - a - b:+.5f} m² "
                             f"({(f - a - b) / f:+.1%} of full-assembly drag)")
        lines += ["",
                  "Update `CD_ARM`/`CD_BODY` in `aero.py` from the arms/body "
                  "ratios, add an interference term if the residual is "
                  "material, then re-run `airloom robustness` — a STABLE "
                  "verdict closes Phase B milestone 1.", ""]
    out = out_root / "calibration.md"
    out.write_text("\n".join(lines))
    return out


def run_calibration(cfg: Config, out_root: Path, solve: bool = False,
                    report: bool = False, jobs: int = 1) -> None:
    if not (out_root / "manifest.json").exists() or not solve and not report:
        specs = generate(cfg, out_root)
        print(f"wrote {len(specs)} cases under {out_root / 'cases'} "
              f"(4 geometries x {len(TILTS_DEG)} tilts)")
    if solve:
        from concurrent.futures import ThreadPoolExecutor, as_completed

        man = json.loads((out_root / "manifest.json").read_text())
        image = man.get("docker_image", DOCKER_IMAGE)
        todo = []
        for c in man["cases"]:
            case_dir = out_root / "cases" / c["name"]
            if list(case_dir.glob("postProcessing/forces1/*/force*.dat")):
                print(f"  {c['name']}: forces present (solved or in "
                      "flight), skipping")
                continue
            todo.append((c["name"], case_dir))

        def _one(name: str, d: Path) -> str:
            print(f"  solving {name} ...", flush=True)
            solve_case(d, image)
            return name

        with ThreadPoolExecutor(max_workers=max(1, jobs)) as ex:
            futs = {ex.submit(_one, n, d): n for n, d in todo}
            for f in as_completed(futs):
                try:
                    print(f"  done: {f.result()}", flush=True)
                except Exception as exc:
                    print(f"  FAILED {futs[f]}: {exc} "
                          f"(see cases/{futs[f]}/run.log)", flush=True)
    if report or solve:
        out = write_report(out_root)
        print(f"report: {out}")


# ------------------------------------------------- per-candidate flow -----
# Real streamlines for the gallery's flight views: the candidate's full
# assembly (minus the prop disks -- rotors are NOT modeled) is meshed
# once, then solved with simpleFoam at each weather scenario's MEAN
# relative wind, rotated into the body frame with the same attitude
# reconstruction the web replay uses. A streamLine function object
# seeds an upwind disc and the tracks are shipped to the gallery as
# <hash>.<scenario>.flow.js JSONP payloads (body-frame coordinates, so
# they pose WITH the model).
FLOW_ITERS = 400
FLOW_SEEDS = 180
# only DISTURBED streamlines ship: a line earns its place by bending
# (arc vs straight chord) or by carrying a real speed disturbance
# relative to the freestream -- the far field is uniform and boring
FLOW_MIN_BEND = 0.996      # chord/arc below this = visibly curved
FLOW_MIN_SPEED_DEV = 0.18  # max |speed-U|/U above this = disturbed


def _flow_assembly(cfg: Config, genome_dict: dict[str, float]):
    import trimesh
    frame = _frame_for(genome_dict, cfg)
    parts = [m for name, m in frame.parts.items()
             if name != "props" and m is not None]
    return trimesh.util.concatenate(parts)


def _body_frame_wind(flight_js: Path) -> list[float]:
    """Mean relative wind in BODY coordinates -> the CFD freestream.
    Telemetry stores the craft's velocity through the air (world frame);
    the attitude basis (body z = thrust vector, body x follows the
    motion heading) is reconstructed exactly like the web replay, and
    the freestream is the NEGATED mean (air streaming past the craft)."""
    txt = flight_js.read_text()
    data = json.loads(txt[txt.index("{"): txt.rindex("}") + 1])
    tx, ty, tz = (np.array(data[k], float) for k in ("tx", "ty", "tz"))
    wx, wy, wz = (np.array(data[k], float) for k in ("wx", "wy", "wz"))
    x, y = np.array(data["x"], float), np.array(data["y"], float)
    hx, hy = np.gradient(x), np.gradient(y)
    acc = np.zeros(3)
    used = 0
    lhx, lhy = 1.0, 0.0
    for i in range(len(tx)):
        bz = np.array([tx[i], ty[i], tz[i]])
        bz /= np.linalg.norm(bz) or 1.0
        hm = math.hypot(hx[i], hy[i])
        if hm > 1e-4:
            lhx, lhy = hx[i] / hm, hy[i] / hm
        h = np.array([lhx, lhy, 0.0])
        bx = h - np.dot(h, bz) * bz
        nb = np.linalg.norm(bx)
        if nb < 1e-6:
            continue
        bx /= nb
        by = np.cross(bz, bx)
        w = np.array([wx[i], wy[i], wz[i]])
        acc += np.array([np.dot(w, bx), np.dot(w, by), np.dot(w, bz)])
        used += 1
    mean_body = acc / max(used, 1)
    return [-float(v) for v in mean_body]


def _flow_block_mesh_dict(bounds, cell: float) -> str:
    """A symmetric, generous box: ONE mesh must serve every scenario's
    wind direction, so no side gets a short wake."""
    (x0, y0, z0), (x1, y1, z1) = bounds
    lx = x1 - x0
    lo = (x0 - 3.0 * lx, y0 - 2.5 * lx, z0 - 2.0 * lx)
    hi = (x1 + 3.0 * lx, y1 + 2.5 * lx, z1 + 2.0 * lx)
    n = [max(int((h - l) / cell), 10) for l, h in zip(lo, hi)]
    vs = [(lo[0], lo[1], lo[2]), (hi[0], lo[1], lo[2]),
          (hi[0], hi[1], lo[2]), (lo[0], hi[1], lo[2]),
          (lo[0], lo[1], hi[2]), (hi[0], lo[1], hi[2]),
          (hi[0], hi[1], hi[2]), (lo[0], hi[1], hi[2])]
    verts = "\n".join(f"    {_fmt_vec(v)}" for v in vs)
    return (_header("dictionary", "blockMeshDict") +
            "scale 1;\n\nvertices\n(\n" + verts + "\n);\n\n"
            "blocks\n(\n    hex (0 1 2 3 4 5 6 7) "
            f"({n[0]} {n[1]} {n[2]}) simpleGrading (1 1 1)\n);\n\n"
            "boundary\n(\n    farfield\n    {\n        type patch;\n"
            "        faces\n        (\n"
            "            (0 3 2 1) (4 5 6 7) (0 1 5 4)\n"
            "            (2 3 7 6) (1 2 6 5) (0 4 7 3)\n"
            "        );\n    }\n);\n")


def _flow_seeds(bounds, u_vec) -> list[tuple[float, float, float]]:
    """Seed points on the upwind disc, biased toward the craft's core so
    the interesting streamlines pass close to the body (matches the
    gallery's visual language)."""
    (x0, y0, z0), (x1, y1, z1) = bounds
    c = np.array([(x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2])
    rb = max(x1 - x0, y1 - y0, z1 - z0) / 2
    u = np.array(u_vec, float)
    u /= np.linalg.norm(u) or 1.0
    e1 = np.cross(u, [0.0, 0.0, 1.0])
    if np.linalg.norm(e1) < 1e-4:
        e1 = np.cross(u, [1.0, 0.0, 0.0])
    e1 /= np.linalg.norm(e1)
    e2 = np.cross(u, e1)
    rng = np.random.default_rng(7)  # stable seeds across regenerations
    pts = []
    radii = [0.15, 0.30, 0.45, 0.62, 0.80]
    for i in range(FLOW_SEEDS):
        r = radii[i % len(radii)] * rb * (0.9 + 0.2 * rng.random())
        th = i * 2.39996 + rng.random() * 0.4
        p = (c - u * 1.6 * rb
             + e1 * r * math.cos(th) + e2 * r * math.sin(th))
        pts.append((float(p[0]), float(p[1]), float(p[2])))
    return pts


def _flow_control_dict(iters: int, seeds) -> str:
    pts = "\n".join(f"            ({p[0]:.5g} {p[1]:.5g} {p[2]:.5g})"
                    for p in seeds)
    return (_header("dictionary", "controlDict") + f"""
application     simpleFoam;
startFrom       latestTime;
startTime       0;
stopAt          endTime;
endTime         {iters};
deltaT          1;
writeControl    timeStep;
writeInterval   {iters};
purgeWrite      2;

functions
{{
    streamlines
    {{
        type            streamLine;
        libs            (fieldFunctionObjects);
        writeControl    onEnd;
        setFormat       vtk;
        U               U;
        fields          (U);
        direction       forward;
        lifeTime        4000;
        nSubCycle       5;
        cloud           particleTracks;
        seedSampleSet
        {{
            type        cloud;
            axis        xyz;
            points
            (
{pts}
            );
        }}
    }}
}}
""")


_FLOW_FV_SOLUTION = _header("dictionary", "fvSolution") + """
solvers
{
    p
    {
        solver          GAMG;
        smoother        GaussSeidel;
        tolerance       1e-7;
        relTol          0.01;
    }
    Phi
    {
        solver          GAMG;
        smoother        GaussSeidel;
        tolerance       1e-6;
        relTol          0.01;
    }
    "(U|k|omega)"
    {
        solver          smoothSolver;
        smoother        symGaussSeidel;
        tolerance       1e-8;
        relTol          0.1;
    }
}

potentialFlow
{
    nNonOrthogonalCorrectors 3;
}

SIMPLE
{
    nNonOrthogonalCorrectors 1;
    consistent      no;
    residualControl { p 1e-4; U 1e-5; "(k|omega)" 1e-5; }
}

relaxationFactors
{
    fields    { p 0.25; }
    equations { U 0.6; k 0.6; omega 0.6; }
}
"""


def flow_case_dirs(out_root: Path, h: str) -> Path:
    return out_root / "flow" / h


def generate_flow(cfg: Config, out_root: Path, store, run_id: str,
                  h: str) -> list[tuple[str, Path]]:
    """Write one case per scenario for candidate `h` (freestream from its
    flight payloads). Returns [(scenario, case_dir)] in solve order."""
    cand = store.get_candidate(run_id, h)
    if cand is None or not cand["png_path"]:
        raise SystemExit(f"no candidate/render for {h}")
    png = Path(cand["png_path"])
    flights = sorted(png.parent.glob(f"{h}.*.flight.js"))
    if not flights:
        raise SystemExit(f"no flight payloads for {h} -- flow freestreams "
                         "come from them (run `airloom gallery` first)")
    import json as _json
    assembly = _flow_assembly(cfg, _json.loads(cand["genome_json"]))
    root = flow_case_dirs(out_root, h)
    root.mkdir(parents=True, exist_ok=True)
    stl = root / "assembly.stl"
    assembly.export(stl)
    bounds = [list(map(float, b)) for b in assembly.bounds]
    cases: list[tuple[str, Path]] = []
    for fl in flights:
        scen = fl.name.split(".")[1]
        u_vec = _body_frame_wind(fl)
        case = root / scen
        write_case(case, stl, bounds, u_vec, iters=FLOW_ITERS)
        # flow-specific: symmetric box (one mesh, six wind directions)
        # and streamline extraction instead of the forces object
        (case / "system" / "blockMeshDict").write_text(
            _flow_block_mesh_dict(bounds, max(
                (bounds[1][0] - bounds[0][0]) / 6.0, 0.05)))
        (case / "system" / "controlDict").write_text(
            _flow_control_dict(FLOW_ITERS, _flow_seeds(bounds, u_vec)))
        (case / "system" / "fvSolution").write_text(_FLOW_FV_SOLUTION)
        (root / f"{scen}.freestream.json").write_text(
            _json.dumps({"u": u_vec}))
        cases.append((scen, case))
    return cases


def solve_flow(cases: list[tuple[str, Path]],
               image: str = DOCKER_IMAGE) -> None:
    """Mesh ONCE (first case), copy polyMesh into the rest, solve all."""
    first = True
    mesh_src: Path | None = None
    for scen, case in cases:
        print(f"  flow: {scen} ...", flush=True)
        if first:
            cmd = ["docker", "run", "--rm",
                   "-v", f"{case.resolve()}:/case", "-w", "/case",
                   "--entrypoint", "/bin/bash", image, "-lc",
                   "source /openfoam/bash.rc 2>/dev/null || "
                   "source /usr/lib/openfoam/openfoam*/etc/bashrc; "
                   "blockMesh && snappyHexMesh -overwrite && "
                   "potentialFoam && simpleFoam"]
            with open(case / "run.log", "w") as f:
                subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT,
                               check=True)
            mesh_src = case / "constant" / "polyMesh"
            first = False
        else:
            dst = case / "constant" / "polyMesh"
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(mesh_src, dst)
            cmd = ["docker", "run", "--rm",
                   "-v", f"{case.resolve()}:/case", "-w", "/case",
                   "--entrypoint", "/bin/bash", image, "-lc",
                   "source /openfoam/bash.rc 2>/dev/null || "
                   "source /usr/lib/openfoam/openfoam*/etc/bashrc; "
                   "potentialFoam && simpleFoam"]
            with open(case / "run.log", "w") as f:
                subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT,
                               check=True)
        print(f"  flow: {scen} done", flush=True)


def _parse_tracks_vtp(path: Path) -> list[dict[str, list[float]]]:
    """OpenFOAM streamLine .vtp (XML, inline-binary base64 DataArrays
    with a UInt64 byte-count header) -> [{p:[x,y,z...], s:[speed...]}]."""
    import base64
    import re

    _DTYPE = {"Float32": np.float32, "Float64": np.float64,
              "Int32": np.int32, "Int64": np.int64,
              "UInt32": np.uint32, "UInt64": np.uint64}
    txt = path.read_text()
    arrays: dict[str, np.ndarray] = {}
    for m in re.finditer(r"<DataArray[^>]*type='(\w+)'[^>]*Name='(\w+)'"
                         r"[^>]*>([^<]*)</DataArray>", txt, re.S):
        dtype, name, body = m.group(1), m.group(2), m.group(3)
        raw = base64.b64decode("".join(body.split()))
        # inline binary: UInt64 payload length, then the payload
        arrays[name] = np.frombuffer(raw[8:], dtype=_DTYPE[dtype])
    pts = arrays["Points"].reshape(-1, 3)
    speeds = np.linalg.norm(arrays["U"].reshape(-1, 3), axis=1) \
        if "U" in arrays else np.zeros(len(pts))
    conn = arrays["connectivity"].astype(int)
    offsets = arrays["offsets"].astype(int)
    out = []
    start = 0
    for end in offsets:
        idx = conn[start:end]
        start = int(end)
        if len(idx) < 6:
            continue
        stride = max(1, len(idx) // 48)  # <=48 points per shipped line
        keep = list(idx[::stride])
        if keep[-1] != idx[-1]:
            keep.append(int(idx[-1]))
        p, s = [], []
        for k in keep:
            p += [round(float(v), 4) for v in pts[k]]
            s.append(round(float(speeds[k]), 2))
        out.append({"p": p, "s": s})
    return out


def extract_flow(out_root: Path, store, run_id: str, h: str) -> list[Path]:
    """Parse each solved case's streamlines and write the gallery JSONP
    payloads next to the candidate's renders."""
    cand = store.get_candidate(run_id, h)
    png = Path(cand["png_path"])
    root = flow_case_dirs(out_root, h)
    written = []
    for case in sorted(p for p in root.iterdir() if p.is_dir()):
        scen = case.name
        vtks = sorted(case.glob("postProcessing/**/streamlines/*/*.vtp"))
        if not vtks:
            print(f"  flow: {scen}: no streamline output, skipping")
            continue
        lines = _parse_tracks_vtp(vtks[-1])
        meta = json.loads((root / f"{scen}.freestream.json").read_text())
        umag = float(np.linalg.norm(meta["u"])) or 1.0
        kept = []
        for li in lines:
            pts = np.array(li["p"]).reshape(-1, 3)
            spd = np.array(li["s"])
            arc = float(np.sum(np.linalg.norm(np.diff(pts, axis=0),
                                              axis=1)))
            chord = float(np.linalg.norm(pts[-1] - pts[0]))
            straight = chord / arc if arc > 0 else 1.0
            sdev = float(np.max(np.abs(spd - umag)) / umag)
            if straight < FLOW_MIN_BEND or sdev > FLOW_MIN_SPEED_DEV:
                kept.append(li)
        print(f"  flow: {scen}: {len(kept)}/{len(lines)} lines "
              "interact with the body")
        lines = kept
        payload = json.dumps({"u": meta["u"], "lines": lines},
                             separators=(",", ":"))
        out = png.parent / f"{h}.{scen}.flow.js"
        out.write_text(f'airloomFlow("{h}","{scen}",{payload})\n')
        written.append(out)
        print(f"  flow: {scen}: {len(lines)} lines -> {out.name}")
    return written


def run_flow(cfg: Config, out_root: Path, h: str | None = None,
             solve: bool = False, extract: bool = False) -> None:
    from .dbstore import Store
    results = cfg.evolution.results_dir
    store = Store(results / "run.db")
    run_id = store.latest_run_id(with_data=True)
    if run_id is None:
        raise SystemExit("no runs found")
    if h is None:  # default: the run champion
        cands = store.candidates_for_run(run_id)
        fits = {c["hash"]: store.fitness_of(c) for c in cands}
        h = min((k for k, f in fits.items() if math.isfinite(f)),
                key=lambda k: fits[k], default=None)
        if h is None:
            raise SystemExit("no valid candidates")
    print(f"flow candidate: {h}")
    cases = generate_flow(cfg, out_root, store, run_id, h)
    print(f"cases: {', '.join(s for s, _ in cases)}")
    if solve:
        solve_flow(cases)
    if extract or solve:
        extract_flow(out_root, store, run_id, h)
