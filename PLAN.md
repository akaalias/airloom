# PLAN — Quadcopter Frame Auto-Research Loop (Phase A)

Living architecture document, updated after the real-geometry rebuild
(the original 13-gene parametric-primitive plan this file used to describe
was completed, checkpointed at `fe7b85e`, and replaced by morphs of the real
Source One V6 drawings). `README.md` is the user-facing companion.

Goal: a headless, resumable evolutionary loop that optimizes quadcopter
**frame geometry** for minimum **Wh/km** across a portfolio of six
adverse-weather scenarios. Everything except the frame is fixed. Local-first:
`pip install -e .`, CPU-only, no Docker/GPU/EGL.

## Package layout

```
pyproject.toml            # package `framevo`, console script `framevo`
Makefile                  # install / test / demo
config/platform.yaml      # fixed platform (battery, motors, prop, FC, material library)
config/scenarios.yaml     # mission + 6 scenarios (seeded turbulence, rain),
                          # aggregation + gallery benchmark lines, early-reject
config/evolution.yaml     # GA + patience, designer, narrator, execution
data/uiuc/                # cached UIUC Master Airscrew GF 7x4 prop data (static + 4 RPM sweeps)
data/source_one/          # official SO V6 7in DC plate DXF, provenance README
scripts/fetch_uiuc.py     # re-download the cached dataset
docs/glossary.html        # EA + domain glossary, copied into results/
src/framevo/
  config.py               # typed dataclasses + YAML loaders
  genome.py               # 12-gene real-morph genome, bounds, hashing, V6 baseline
  realgeo.py              # parses the official DXF outlines (arcs, cutouts, holes)
  frame_gen.py            # genome -> morphed real plates -> watertight STL,
                          # mass/CG, validity checks, printable-parts export
  components.py           # dimension-accurate fixed-kit meshes (pack, stack,
                          # motors, props, camera, VTX, antennas, GPS, XT60, wires)
  meshutil.py             # dependency-light watertight primitives
  rotor_model.py          # UIUC CT(J)/CP(J) interpolation + rotor-speed solver
  aero.py                 # STL rasterization -> per-class projected areas -> drag table
  dryden.py               # MIL-F-8785C Dryden turbulence, fixed seed per scenario
  simulator.py            # 100 Hz point-mass 3-DOF sim, quasi-static attitude,
                          # P velocity loop, energy integral
  structures.py           # Euler-Bernoulli arm checks + resonance constraint
  evaluate.py             # subprocess entry points: build_task, scenario_task,
                          # aggregation, structural check
  parallel.py             # process-per-task pool, hard timeout, graceful stop
  dbstore.py              # SQLite persistence, recursive ancestry, schema
                          # versioning (old dbs archived, never deleted)
  evolution.py            # GA with full lineage, patience/pivot machinery,
                          # minimal CMA-ES (flag-gated)
  designer.py             # headless-Claude design rounds (operator `designer`)
  narrator.py             # lab-notebook notes: hypothesis / method / result
                          # per candidate; async enrichment, rule-based fallback
  loop.py                 # the resumable generation loop, artifact regeneration
  lineage.py              # ancestor-chain CLI, DOT export, lineage.html family tree
  render.py               # headless matplotlib stills (incl. from-below view)
  gallery.py              # gallery.html (progress chart, 3D overlay, notes),
                          # leaderboard.md, convergence.png
  cli.py                  # `framevo run|lineage|gallery` (run resumes by default)
tests/                    # pytest suite (see below)
results/                  # run outputs (db, frames/gen_XXXX/*.stl+png, gallery, ...)
```

## Genome (12 genes — morphs of the REAL parts)

Genes deform the official Source One V6 7in DC plate drawings
(`data/source_one/`, parsed by `realgeo.py`) under zone constraints: arm
tongues and the 16×19 mm motor-mount end stay rigid, the 30.5 mm stack
pattern stays pinned, plates stretch around their functional regions. Scale
genes at 1.0 reproduce the real V6 exactly (gen-0 seed; 144 g frame mass vs.
~145 g real).

| gene | bounds | notes |
|---|---|---|
| arm_length_scale | 0.75–1.35 | shaft stretch (wheelbase) |
| arm_width_scale | 0.75–1.40 | shaft width at the zone borders |
| arm_waist_scale | 0.55–1.30 | extra mid-shaft narrowing |
| arm_thickness | 4–9 mm | real: 6 mm plate |
| front_sweep_deg | 30–52° | about the exact bolt-pattern anchor (stock 31.4°) |
| rear_sweep_deg | 34–62° | rear anchor is a best-fit clamp registration (stock 36.0°) |
| plate_length_scale | 0.85–1.30 | main/mid/top plates, cutouts and holes included |
| plate_width_scale | 0.85–1.25 | |
| deck_gap | 20–45 mm | standoff length; real: M3×30 |
| battery_wedge_deg | 0–15° | pack tilt on the top plate |
| plate_thickness_scale | 0.7–1.6 | × 2 mm real plates |
| material | 0–1 | carbon plate / PA12-CF / PET-CF / PLA+ / PETG / ASA |

ID = first 12 hex of SHA-1 over genes rounded to 1e-6 (stable across runs).

## Frame generation & validity

- Real outlines morphed per the genes; every candidate assembles the full
  kit (`components.py`): 6×21700 pack, FC/ESC stack between the plates
  (a bluff body for drag), 2806 motors, 3-blade prop disks, camera, VTX +
  ELRS antennas, GPS, XT60 and routed wire looms. The battery wedge hinges
  on its front bottom edge so it never sinks into the plate.
- Union via trimesh + manifold3d → watertight STL. Mass/CG analytic.
- Validity (fail ⇒ fitness = ∞, no simulation): FC/ESC stack fits the deck
  gap; placed arm outlines must not overlap (tongue interlock is not
  redesigned); each tongue's bolt pair lands on main-plate material; rotor
  disks ≥ 5 mm from each other; prop disks checked against deck/battery in
  3D; mesh watertight.
- The generation champion is also exported as separate flat printable/
  cuttable pieces (`gen_XXXX_best_parts/`: bottom_plate, top_plate, arm ×4).

## Physics (Phase A, boring on purpose)

- **Rotor**: UIUC Master Airscrew GF 7×4 tables (static + 4 RPM sweeps) →
  monotone-J CT(J), CP(J) interpolants. Newton solve for rotor speed given
  thrust and axial inflow. Electrical power = ρn³D⁵CP(J) / 0.85 (motor+ESC).
  Hard caps: max RPM, max per-motor power → saturation.
- **Drag**: per-class projected areas (arms vs body) by rasterizing the STL
  from the flow direction at tilt 0–60°, body-x/body-y azimuths blended
  cos²/sin². Cd per class: arms 1.9/1.1/0.6 by section blend, body ~1.05.
  Rotor-wash download on arm planform under the disks.
- **Turbulence**: Dryden MIL-F-8785C low-altitude forms, per-scenario fixed
  seed → identical gust history for every candidate.
- **Rain** (empirical, NASA TP-2671 cited): water-film added mass, momentum
  drag via equivalent suspended-water density, 15 % CT penalty.
- **Sim**: 100 Hz point-mass 3-DOF, quasi-static attitude, P velocity loop
  with accel limits, mission = 2 km north + 2 km south at 12 m/s GS, 30 m
  AGL. Integrate electrical energy; log peak per-rotor thrust.
- **Structures** (constraint): cantilever arm, worst-case per-rotor thrust
  across ALL scenarios × 1.5; stress ≤ the genome-selected material's
  strength, tip deflection ≤ 5 % L; first bending mode outside ±15 % of
  hover 1P.

## Fitness

Per scenario: Wh over 4 km ÷ 4. Any scenario invalid ⇒ candidate invalid (∞).
Aggregate = mean(Wh/km) + λ·worst(Wh/km), λ = 0.5; `aggregation: minimax`
supported. Optional early-reject (config, default off): fly calm_warm first,
candidates worse than the generation median by a margin skip the rest and
get a finite penalized fitness. Gallery benchmark lines: 5.0 Wh/km aggregate
(current 7-inch long-range practice), 4.0 (record-class stretch).

## Evolution

GA, population 16: tournament(k=3), SBX crossover, Gaussian mutation with
generation-decaying sigma, elitism top-2, random immigrants. Every candidate
records parent_a, parent_b, operator, generation_born, mutation magnitude.

- **Patience/pivot**: after 6 generations without ≥0.5 % improvement, breed
  half the non-elite slots from (tournament winner) × (far parent — the most
  genetically distant still-decent candidate in run history) under boosted
  sigma; escalate to random far-parents if the plateau persists. Derived
  from persisted history → survives resume.
- **Designer rounds**: every 6 generations, headless `claude -p` receives
  elites + per-scenario results + failure histogram + constraint couplings
  and proposes genome vectors (operator `designer`, no parents; rationales
  → `results/designer_log.md`). Fail-soft.
- **Narrator**: after each generation, one headless-Claude call writes
  hypothesis / method / result notes per new candidate; instant rule-based
  fallback, async enrichment off the critical path; shown in gallery detail
  blocks and family-tree hover cards.
- **CMA-ES** behind `--optimizer cmaes` (distribution-level provenance:
  mean/σ per generation, resumable state, no family tree).

Per-generation RNG seed = f(base_seed, gen) → deterministic resume.

Parallelism: stage 1 builds frames/aero/stills per candidate in parallel;
stage 2 runs (candidate × scenario) tasks in parallel. Each task is its own
spawned process with a hard timeout (terminate ⇒ invalid). A stop request
(`quit` + enter or ctrl-c) terminates in-flight workers and leaves the run
resumable. Worker count = `os.cpu_count()` capped by config.

## Persistence & artifacts

SQLite `results/run.db` (schema-versioned; old-schema files are archived,
never deleted): runs (config json, seed, git hash), candidates
(self-referencing lineage + narrator notes), scenario_results, populations
(resume anchor), cma_state. `framevo run` resumes the latest run by default
(`--fresh` for a new one; a genome-spec mismatch auto-starts fresh).

Per generation: every STL (`_INVALID` suffix when applicable) + PNG still
under `results/frames/gen_XXXX/`, `results/gallery.html` (static,
meta-refresh 30 s, progress chart with benchmark lines, 3D overlay with
synced ancestor compare, lab-notebook notes), `results/leaderboard.md`,
`results/gen_XXXX_best.stl` + `_parts/`, `results/convergence.png`,
`results/lineage.html` (+ `lineage.svg`, `lineage.dot`),
`results/designer_log.md`, `results/glossary.html`.

## Tests (pytest)

1. frame generator: the baseline genome reproduces the real V6 (mass, validity,
   watertightness); gap-too-small and tongue-collision genomes rejected with
   the right reason; random genomes always mesh.
2. kit components: dimension checks for pack, stack, motors, props, etc.
3. materials: gene→library mapping, mass effects, soft-print material fails
   where carbon passes.
4. designer: reply parsing, bound clipping, garbage rejection.
5. patience: plateau detection, pivot escalation, far-parent selection/breeding.
6. rotor model reproduces tabulated UIUC points; hover solver round-trips.
7. beam stress/deflection vs hand-calculated cantilever numbers.
8. Dryden series variance matches σ² (long sample, tolerance).
9. zero-wind energy integration vs quasi-static analytic power (±6 %).
10. sanity anchors: 5-inch spec case (180–280 W) and the shipped 7-inch
    platform (90–230 W hover band).

## Status

Phase A is feature-complete; current work is fine-tuning (hyper-parameters,
gallery/narrator polish) ahead of the first "real" long run. Phase B
(OpenFOAM) remains out of scope; the per-candidate `DragTable`
(CdA vs tilt/azimuth) is the seam where CFD results would slot in
(snappyHexMesh + k-ω SST RANS, 3 angles × 2 speeds, top-N per generation,
cached by genome hash). The `DragTable` is now derived from a raw
`AreaTable`, so CFD-calibrated Cds can be re-priced without re-rasterizing.

Pre-Phase-B verification layer (built 2026-07-13):

- **Battery pack model** in the simulator: V = V0 − I·R sag, deliverable
  power ceiling (~820 W for the 6S1P), 45 A cell limit, I²R losses in the
  energy integral, RPM ceiling scaled by sagged voltage. Thrust limiting
  now CLAMPS (transients cost energy/tracking); failure = sustained
  limiting > `mission.saturation_frac_limit` (10 %) of nominal time,
  blamed on the dominant limiter. Finding: no frame — including the real
  V6 — can hold 12 m/s through `storm` on this pack without clamping;
  ~12 s of saturation and a higher Wh/km is the physical outcome.
- **`framevo robustness`**: re-flies the top archived candidates under
  perturbed model knobs; rank correlation + champion identity vs baseline
  → STABLE/MODERATE/FRAGILE verdict in `results/robustness.md`. First
  sweep: FRAGILE — ordering among the near-tied top 12 hinges on the ARM
  drag coefficient (Spearman 0.59 at cd_arm+30 %); everything else ≥0.9.
  Phase B should therefore start with arm-drag fidelity.
- **`framevo verify-champions`**: station-wise variable-section bending
  along the real morphed arm outline, Peterson net-section Kt at
  holes/cutouts, per-material as-built strength knockdowns
  (`as_built_strength_frac`), refined deflection, print-and-test protocol
  → `results/champion_check.md`. Deliberately not FEM; a CalculiX pass
  would consume the same per-station geometry.

## Phase B — milestone 1: CFD calibration (in progress)

The robustness sweep reframed Phase B: only the ARM drag coefficient
changes decisions, so before any per-candidate pipeline we calibrate the
buildup's global knobs with a handful of OpenFOAM cases (`framevo
cfd-calibrate`, cases + report under `cfd/`):

1. **Four geometries**: baseline arms alone, baseline deck/body alone
   (plates + battery + stack + motors + camera + antennas), the full
   baseline assembly, and the full assembly of a contrasting genome
   (long swept arms, wide deck gap).
2. **Three flow angles each** (0°/20°/40° tilt at 12 m/s — the sim's
   operating band), via freestream far-field BCs so each geometry is
   meshed once (snappyHexMesh) and solved three times (simpleFoam,
   k-ω SST, forces function object → measured CdA).
3. **Attribution**: arms-alone calibrates `CD_ARM`; body-alone `CD_BODY`;
   (full − arms − body) MEASURES the interference the buildup assumes to
   be zero; contrast-vs-baseline interference fraction tests whether
   interference varies with the genes (a ranking issue) or is a constant
   offset (absolute-only issue).
4. **Acceptance**: update the calibrated knobs, re-run
   `framevo robustness`. STABLE verdict ⇒ the full per-candidate CFD
   pipeline (original Phase B scope) is unnecessary; still-FRAGILE ⇒
   build it for the top-N per generation as originally planned.

Rotor–airframe interaction stays out of scope: the wash-term knob was the
most rank-stable of the whole sweep (Spearman ≥ 0.986 at −50 %/+100 %).
Solver runs in Docker (`opencfd/openfoam-default`, arm64-native), strictly
optional and flag-gated per the local-first rule; the harness generates
runnable cases + a manifest without Docker present.
