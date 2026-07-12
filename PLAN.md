# PLAN — Quadcopter Frame Auto-Research Loop (Phase A)

Goal: a headless, resumable evolutionary loop that optimizes parametric quadcopter
**frame geometry** for minimum **Wh/km** across a portfolio of six adverse-weather
scenarios. Everything except the frame is fixed. Local-first: `pip install -e .`,
CPU-only, no Docker/GPU/EGL.

## Package layout

```
pyproject.toml            # package `framevo`, console script `framevo`
Makefile                  # install / test / demo
config/platform.yaml      # fixed platform (battery, motors, prop, FC, material)
config/scenarios.yaml     # mission + 6 scenarios (seeded turbulence, rain)
config/evolution.yaml     # GA hyper-parameters, aggregation, parallelism
data/uiuc/                # cached UIUC GWS DD 5x4.3 prop data (static + 4 RPM sweeps)
scripts/fetch_uiuc.py     # re-download the cached dataset
src/framevo/
  config.py               # typed dataclasses + YAML loaders
  genome.py               # 13-gene continuous genome, bounds, hashing, baseline
  meshutil.py             # dependency-light watertight primitives (extrusions, sweeps)
  frame_gen.py            # genome -> watertight STL mesh, mass/CG, validity checks
  rotor_model.py          # UIUC CT(J)/CP(J) interpolation + rotor-speed solver
  aero.py                 # STL rasterization -> per-class projected areas -> drag table
  dryden.py               # MIL-F-8785C Dryden turbulence, fixed seed per scenario
  simulator.py            # 100 Hz point-mass 3-DOF sim, cascaded PI(D), energy integral
  structures.py           # Euler-Bernoulli arm checks + resonance constraint
  evaluate.py             # per-candidate pipeline: build -> scenarios -> aggregate
  parallel.py             # process-per-task pool with hard timeout (terminate)
  dbstore.py              # SQLite persistence, recursive ancestry queries
  evolution.py            # GA with full lineage (+ minimal CMA-ES, flag-gated)
  lineage.py              # ancestor-chain CLI, Graphviz DOT export, pure-SVG family tree
  render.py               # headless matplotlib thumbnails, fixed 3/4 camera
  gallery.py              # gallery.html, leaderboard.md, convergence.png
  cli.py                  # `framevo run|resume|lineage|gallery`
tests/                    # pytest suite (see below)
results/                  # run outputs (db, frames/gen_XXXX/*.stl+png, gallery, ...)
```

## Genome (13 continuous genes)

| gene | bounds | notes |
|---|---|---|
| arm_length | 0.07–0.18 m | rotor center offset from body attach point |
| arm_width | 0.008–0.028 m | root cross-section chord |
| arm_height | 0.005–0.016 m | root cross-section thickness |
| arm_sweep_deg | 25–65° | plan angle from forward axis (45 = pure X) |
| arm_dihedral_deg | −8–8° | |
| section_blend | 0–1 | 0 rect (Cd 1.9) → 0.5 ellipse (1.1) → 1 faired (0.6) |
| arm_taper | 0.5–1.0 | tip/root width ratio |
| body_length | 0.150–0.240 m | must swallow 138 mm battery + walls |
| body_width | 0.048–0.100 m | battery is 47 mm wide |
| body_height | 0.040–0.085 m | battery is 38 mm tall |
| body_fillet | 0–0.012 m | plan-view corner radius |
| body_pitch_deg | 0–15° | whole-body nose-down pitch (forward-flight drag) |
| thickness_scale | 0.6–1.6 | scales 2 mm body shell wall; arms are solid CF |

ID = first 12 hex of SHA-1 over genes rounded to 1e-6 (stable across runs).

## Frame generator

- Body: convex rounded-rectangle plan polygon extruded to height, pitched by
  `body_pitch_deg`; hollow shell for mass (wall = 2 mm × thickness_scale), outer
  solid for aerodynamics. Battery/FC live inside.
- Arms: superellipse cross-section (exponent 8→2 by blend; faired = elongated
  ellipse with tapered tail), swept root→tip with taper and dihedral; solid CF.
- Motor pads: short cylinders at arm tips; rotor center above pad.
- Union via trimesh + manifold3d → single watertight STL. Mass/CG analytic
  (shell body + solid arms + fixed component masses).
- Validity (fail ⇒ fitness = ∞, no simulation): battery box fits interior with
  1 mm clearance; ≥36 mm square flat top for the 30.5 mm FC pattern; adjacent
  rotor centers ≥ D + 5 mm apart; rotor disk ≥ 5 mm from body footprint;
  mesh watertight.

## Physics (Phase A, boring on purpose)

- **Rotor**: merged UIUC GWS DD 5x4.3 tables (static CT/CP at J=0 taken at the
  high-RPM end + 4 dynamic sweeps) → monotone-J CT(J), CP(J) interpolants on a
  dense grid. Newton solve for rotor speed n given required thrust and axial
  inflow. Electrical power = ρn³D⁵CP(J) / 0.85 (motor+ESC). Hard caps: max RPM,
  max per-motor electrical power → saturation.
- **Drag**: per-class projected areas (arms vs body) by rasterizing the STL
  onto a ~1.5 mm grid from the flow direction at tilt angles 0–60°, for body-x
  and body-y flow azimuths; arbitrary azimuth via cos²/sin² ellipse blend.
  Cd per class: arms interpolated 1.9/1.1/0.6 by section blend, body ~ box 1.05
  reduced by fillet. Rotor-wash download: 0.5ρv_i²·Cd·A(arm under disk).
- **Turbulence**: Dryden MIL-F-8785C low-altitude forms, discretized shaping
  filters, per-scenario fixed seed → identical gust history for every candidate.
- **Rain** (config-parameterized, empirical — NASA TP-2671 cited in code):
  water-film added mass ∝ top area, rain momentum drag via equivalent rain
  density ρ_rain = flux/v_terminal, 15 % CT penalty.
- **Sim**: 100 Hz point-mass 3-DOF translation, quasi-static attitude (thrust
  vector = required force; tilt feeds drag lookup), cascaded P-velocity /
  PI-acceleration-free controller with accel limits, mission = 2 km north +
  2 km south at 12 m/s GS, 30 m AGL, vehicle yaws to travel direction.
  Integrate electrical energy; log peak per-rotor thrust for structures.
  Saturated rotors (sustained) or failure to finish ⇒ invalid in that scenario.
- **Structures** (constraint): cantilever arm, tip load = worst-case per-rotor
  thrust across ALL scenarios × 1.5; Euler-Bernoulli σ ≤ 600 MPa, tip deflection
  ≤ 5 % L; first bending mode (tip mass = motor + 0.243·arm mass) outside
  ±15 % of hover rotor frequency (1P).

## Fitness

Per scenario: Wh over 4 km ÷ 4. Any scenario invalid ⇒ candidate invalid (∞).
Aggregate = mean(Wh/km) + λ·worst(Wh/km), λ = 0.5; `aggregation: minimax`
supported. Optional early-reject (config, default off): fly calm_warm first,
candidates worse than the generation median by a margin skip the rest and get a
finite penalized fitness.

## Evolution

GA, population 16: tournament(k=3) selection, SBX crossover, Gaussian mutation
with generation-decaying sigma, elitism top-2 (recorded as `elite` pass-through),
occasional random immigrants. Every candidate records parent_a, parent_b,
operator, generation_born, mutation magnitude. CMA-ES behind `--optimizer cmaes`
(distribution-level provenance: mean/σ per generation, no family tree).
Per-generation RNG seed = base_seed + 1000·gen → deterministic resume.

Parallelism: stage 1 builds frames/aero/thumbnails per candidate in parallel;
stage 2 runs (candidate × scenario) tasks in parallel. Each task is its own
spawned process with a hard timeout (terminate ⇒ invalid). Worker count =
`os.cpu_count()` capped by config.

## Persistence & artifacts

SQLite `results/run.db`: runs (config json, seed, git hash), candidates
(self-referencing lineage), scenario_results, populations (resume anchor).
Per generation: every STL (`_INVALID` suffix when applicable) + PNG thumbnail
under `results/frames/gen_XXXX/`, `results/gallery.html` (static, meta-refresh
30 s, relative-path images, no JS), `results/leaderboard.md`,
`results/gen_XXXX_best.stl`, `results/convergence.png`, `results/lineage.svg`
(pure-Python SVG layout) + `results/lineage.dot`.

## Tests (pytest)

1. frame generator: baseline genome valid + watertight; battery-too-small and
   rotor-overlap genomes rejected with the right reason.
2. rotor model reproduces 3 tabulated UIUC points; hover solver round-trips.
3. beam stress/deflection vs hand-calculated cantilever numbers.
4. Dryden series variance matches σ² (long sample, tolerance).
5. zero-wind energy integration vs quasi-static analytic power.
6. sanity anchor: hover electrical power at 1.1 kg AUW ∈ [180, 280] W.

## Milestones

1. Scaffold + configs + UIUC cache (done: data downloaded).
2. genome → frame_gen → render (visual check).
3. rotor + dryden + aero + simulator + structures, with tests green.
4. evaluate + parallel pool + dbstore.
5. evolution loop + lineage + gallery/leaderboard/convergence.
6. `make demo` (3 gens × pop 8) end-to-end under ~10 min; README.

Phase B (OpenFOAM) is out of scope for this pass; the drag-table interface
(`CdA(tilt, azimuth)`) is the seam where CFD results would slot in.
