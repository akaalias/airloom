# framevo — evolving quadcopter frames for Wh/km

A fully automated, headless research loop that evolves quadcopter **frame
geometry** to minimize **energy per distance (Wh/km)** flown through a
portfolio of adverse-weather scenarios. Everything except the frame — battery,
motors, propellers, flight controller — is fixed. Runs unattended, is
resumable after a crash, and produces a ranked, visual archive of every frame
it ever evaluated.

```
make demo        # 3 generations x population 8, ~2-4 min on 8 cores
make test        # pytest suite
.venv/bin/framevo run --generations 40             # a real run
.venv/bin/framevo run --run-id myrun --resume      # continue after a crash
.venv/bin/framevo lineage <genome_hash>            # ancestor chain w/ fitness
.venv/bin/framevo gallery                          # rebuild artifacts from db
```

Local-first: plain `pip install -e .` on macOS (Apple Silicon) or Linux x86,
CPU-only, no Docker/GPU/EGL. Thumbnails render through headless matplotlib.
Worker count auto-scales to the core count.

## What it produces (in `results/`)

- `gallery.html` — static, self-refreshing (30 s meta-refresh), no JavaScript,
  open with `file://`. One row per generation, thumbnails sorted by fitness,
  aggregate + per-scenario Wh/km under each, best candidate highlighted,
  invalid candidates greyed with the failure reason. Every thumbnail links to
  a detail block showing its **parents' thumbnails** — you can see which two
  frames were crossed to produce a child.
- `leaderboard.md` — top 10 with all metrics and per-scenario columns.
- `lineage.svg` + `lineage.dot` — the full family tree: nodes shaded by
  fitness (dark = better), hollow nodes = invalid, edges colored by operator,
  elite carry-overs as dotted vertical pass-throughs.
- `convergence.png` — fitness vs. generation.
- `frames/gen_XXXX/<hash>.stl` + `.png` — **every** candidate, including
  invalid ones (`_INVALID` suffix; the failures are instructive).
- `gen_XXXX_best.stl` — the generation's champion.
- `run.db` — SQLite: genomes, lineage (self-referencing, `WITH RECURSIVE`
  ancestry), per-scenario metrics, populations, config snapshot, git hash.

## The genome (13 continuous genes)

arm length / width / height / sweep / dihedral / taper, a cross-section shape
blend (rectangle → ellipse → faired teardrop), body length / width / height /
corner fillet / pitch, and a material-thickness scale. Hard geometric
constraints (fitness = ∞, no simulation): the 138×47×38 mm battery must fit
inside the body shell, a 36 mm flat must exist for the 30.5 mm FC pattern,
and rotors need ≥ 5 mm clearance from each other and the body.

## Scenario portfolio

Six scenarios (config/scenarios.yaml): `calm_warm`, `cold_headwind`, `storm`
(25 mm/h rain), `crosswind`, `gusty_light` (severe Dryden gusts),
`hot_thin` (1500 m density altitude). Every candidate flies **all** of them
over the identical mission: 2 km north + 2 km south at 12 m/s, 30 m AGL.
Each scenario has a fixed turbulence seed, so all candidates fly identical
gust histories — fitness differences are frame differences, never gust luck.

Fitness = mean Wh/km + λ·worst Wh/km (λ = 0.5), or pure worst-case with
`aggregation: minimax`. Any scenario failure (rotor saturation, mission not
completed, structural) ⇒ invalid. An optional early-reject screen
(`early_reject.enabled`) flies `calm_warm` first and gives clearly-losing
candidates a finite penalized fitness without flying the other five.

## Physics (Phase A — deliberately boring and verifiable)

| piece | model | source / check |
|---|---|---|
| rotor | CT(J), CP(J) interpolated from measured tables; `T = ρn²D⁴CT`, `P = ρn³D⁵CP / 0.85` (motor+ESC) | UIUC Propeller DB, GWS Direct Drive 5×4.3 (static + 4 RPM sweeps), cached in `data/uiuc/`; unit-tested against tabulated points |
| frame drag | component buildup: projected areas from rasterizing the STL along the flow at 0–60° tilt; Cd per class (arm 1.9→1.1→0.6 by section blend, body 1.05); rotor-wash download on arm planform under the disks | classic flat-plate/cylinder/fairing Cd values |
| turbulence | Dryden, MIL-F-8785C low-altitude forms, spectral synthesis, fixed seeds | variance unit-tested against σ² spec |
| rain | (a) water-film added mass ∝ top area, (b) momentum drag via equivalent suspended-water density + vertical impact force, (c) 15 % thrust-coefficient penalty | empirical knobs, see NASA TP-2671 (Dunham et al.) heavy-rain research; all in config |
| flight | 100 Hz point-mass 3-DOF sim; quasi-static attitude (the quad tilts into the relative wind), P velocity loop with accel limits; rotor speeds solved each step from the CT tables; electrical energy integrated | zero-wind mission unit-tested against a quasi-static analytic power balance (±6 %) |
| structure | Euler–Bernoulli cantilever arm: worst-case per-rotor thrust across all scenarios × 1.5 safety factor; stress ≤ 600 MPa, tip deflection ≤ 5 % L, first bending mode outside ±15 % of hover 1P | stress/deflection unit-tested against hand calculations |

Sanity anchor (unit-tested): at 1.1 kg all-up mass the model hovers at
**~195 W**, inside the plausible 180–280 W band for a 5-inch quad of that
weight.

## Known limitations (please read before trusting numbers)

- **Phase A drag is approximate.** Component buildup with handbook Cd values
  and a cos²-blend between body-x and body-y flow azimuths; no interference
  drag beyond the rotor-wash term, no Reynolds corrections.
- **Rotor model is axial-flow data stretched to edgewise flight.** UIUC wind
  tunnel sweeps measure propellers in axial advance; a quadcopter in cruise
  sees mostly edgewise inflow. J is computed from the axial inflow component
  only, and there is **no rotor–rotor interaction**.
- **The rain model is empirical.** Film mass, momentum drag and the 15 %
  thrust penalty are literature-inspired config knobs, not physics.
- **No rotational dynamics.** Attitude is quasi-static; control effort in
  gusts appears as thrust modulation, not motor differential torques. Gust
  series are synthesized at the commanded cruise speed rather than the
  instantaneous airspeed.
- **UIUC data was measured at 4k–8k RPM**; our operating band is 12k–20k RPM
  (higher Reynolds). CT/CP are treated as Re-independent.
- Structural model checks the arms only (root stress, tip deflection,
  resonance); the body shell is assumed rigid.
- CMA-ES mode (`--optimizer cmaes`) has no discrete parents — it samples from
  an adapted Gaussian — so the family tree is skipped and distribution-level
  provenance (mean, σ per generation) is stored in `cma_state` instead.

## Phase B (CFD) — not built yet, seam prepared

The drag interface is a per-candidate `DragTable` (CdA vs tilt/azimuth).
A Phase-B OpenFOAM pipeline (snappyHexMesh + k-ω SST RANS at 3 angles ×
2 speeds, top-N candidates per generation, cached by genome hash) would
replace that table and nothing else.

## Layout

```
config/          platform.yaml (fixed hardware), scenarios.yaml, evolution.yaml
data/uiuc/       cached UIUC propeller measurements (scripts/fetch_uiuc.py refreshes)
src/framevo/     genome, frame_gen, rotor_model, aero, dryden, simulator,
                 structures, evaluate, parallel, evolution, loop, dbstore,
                 lineage, gallery, render, cli
tests/           frame validity, UIUC points, beam hand-calc, Dryden variance,
                 zero-wind energy, hover sanity anchor
results/         everything a run produces (see above)
```
