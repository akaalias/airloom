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

- `gallery.html` — static, self-refreshing (30 s meta-refresh), no frameworks,
  no server, open with `file://`. Tufte-styled (cream paper, ink, one rust
  accent, hairlines). At the top: a **progress chart** of every candidate in
  evaluation order — gray dots, a best-so-far step line with labeled
  improvements, invalid candidates as rust ×, generation ticks — so you can
  see what moved the needle and where the search plateaued. Below: one row
  per generation sorted by fitness, then **detail blocks with an interactive
  3D model at half width** (a small depth-buffered WebGL viewer fed by
  embedded mesh data: drag to rotate, scroll to zoom, double-click to reset) beside the metrics
  and the parents' thumbnails. Parts are colored by role: rust arms and
  near-black deck plates are the **evolved** geometry; the blue Li-Ion pack,
  gray motor cans and pale translucent prop disks are the **fixed** kit.
- `leaderboard.md` — top 10 with all metrics and per-scenario columns.
- `lineage.html` (+ raw `lineage.svg`, `lineage.dot`) — a dedicated family
  tree page: nodes shaded by fitness (dark = better), hollow nodes = invalid,
  edges colored by operator, elite carry-overs as dotted pass-throughs.
- `convergence.png` — fitness vs. generation.
- `frames/gen_XXXX/<hash>.stl` + `.png` — **every** candidate, including
  invalid ones (`_INVALID` suffix; the failures are instructive).
- `gen_XXXX_best.stl` — the generation's champion (fused), plus
  `gen_XXXX_best_parts/` — the same frame as separate flat, printable pieces.
- `run.db` — SQLite: genomes, lineage (self-referencing, `WITH RECURSIVE`
  ancestry), per-scenario metrics, populations, config snapshot, git hash.
- `glossary.html` (copied from `docs/glossary.html`, linked from the gallery)
  — definitions of both the evolutionary-algorithm terms and the domain terms
  (genes, Wh/km, constraints, physics vocabulary).

## The fixed platform (never evolved)

Matched to the **official DroneAid Collective (drone-aid.de) workshop kit**,
a 7-inch long-range build in the most popular open-source plate-frame
archetype — the [TBS Source One](https://github.com/tbs-trappy/source_one)
family (GPLv3: 2 mm deck plates, M3 standoffs, sandwiched plate arms).
Kit components as modeled: 4× 2806-class ~1300KV motors with 7×4-class
3-blade props (ground truth: UIUC Master Airscrew GF 7×4 measurements),
a self-built 6S1P 21700 Li-Ion pack (4.2 Ah, 470 g, strapped on top of the
deck), 30.5 mm Betaflight FC + 4-in-1 ESC stack between the plates, micro
FPV camera, VTX + antenna, ELRS receiver. Fixed non-frame mass: 0.78 kg;
baseline AUW ≈ 1.0 kg.

The generation-0 baseline genome is **measured from the official Source One
V6 7in DC plate drawing** (cached with provenance notes in
`data/source_one/`): 106.6×48.5 mm bottom plate, 2 mm plates, 6 mm arms,
M3×30 standoffs, ~160 mm arms. Assembly is modeled the way the real frame
bolts together: arm root tongues rest on the bottom plate inside the
sandwich (tongues may not collide — hard constraint), the FC/ESC boards sit
in the gap (and count as a bluff body for drag), the battery wedge hinges on
its front bottom edge so it never sinks into the plate, and the XT60/lead
are modeled visually. The best candidate of each generation is also exported
as individual print/cut-ready pieces in `gen_XXXX_best_parts/`
(bottom_plate, top_plate, arm ×4).

## The genome (14 continuous genes)

arm length / width / height / sweep / dihedral / taper, a cross-section shape
blend (rectangle → ellipse → faired teardrop), deck plate length / width /
standoff gap / corner fillet, a battery wedge angle (`body_pitch_deg`), a
plate-thickness scale — and a **print material** gene that selects the frame
material from a config library: CNC carbon plate, carbon-fiber nylon
(PA12-CF), PET-CF, PLA+, PETG or ASA, each with its own density, tensile
strength and stiffness. Soft materials save mass but fail the structural
constraints on slender arms — the optimizer gets to negotiate that trade.

Hard geometric constraints (fitness = ∞, no simulation): the deck gap must
fit the 20 mm FC/ESC stack, a 36 mm flat must exist for the 30.5 mm mount
pattern, the top plate must support the battery footprint, and rotors need
≥ 5 mm clearance from each other and from the deck/battery.

## Scenario portfolio

Six scenarios (config/scenarios.yaml): `calm_warm`, `cold_headwind`, `storm`
(25 mm/h rain), `crosswind`, `gusty_light` (severe Dryden gusts),
`hot_thin` (1500 m density altitude). Every candidate flies **all** of them
over the identical mission: 2 km north + 2 km south at 12 m/s, 30 m AGL.
Each scenario has a fixed turbulence seed, so all candidates fly identical
gust histories — fitness differences are frame differences, never gust luck.

**Patience:** if the best-so-far stalls for 6 generations (no ≥0.5 %
improvement), the loop pivots — it crosses tournament winners with *far
parents* (the most genetically distant still-decent candidates in the run's
history) under boosted mutation, escalating to random parents if the plateau
persists. Derived from persisted history, so it survives `--resume`;
configured under `ga.patience` in `config/evolution.yaml`.

Fitness = mean Wh/km + λ·worst Wh/km (λ = 0.5), or pure worst-case with
`aggregation: minimax`. Any scenario failure (rotor saturation, mission not
completed, structural) ⇒ invalid. An optional early-reject screen
(`early_reject.enabled`) flies `calm_warm` first and gives clearly-losing
candidates a finite penalized fitness without flying the other five.

## Physics (Phase A — deliberately boring and verifiable)

| piece | model | source / check |
|---|---|---|
| rotor | CT(J), CP(J) interpolated from measured tables; `T = ρn²D⁴CT`, `P = ρn³D⁵CP / 0.85` (motor+ESC) | UIUC Propeller DB, Master Airscrew GF 7×4 (static + 4 RPM sweeps), cached in `data/uiuc/`; unit-tested against tabulated points |
| frame drag | component buildup: projected areas from rasterizing the STL along the flow at 0–60° tilt; Cd per class (arm 1.9→1.1→0.6 by section blend, body 1.05); rotor-wash download on arm planform under the disks | classic flat-plate/cylinder/fairing Cd values |
| turbulence | Dryden, MIL-F-8785C low-altitude forms, spectral synthesis, fixed seeds | variance unit-tested against σ² spec |
| rain | (a) water-film added mass ∝ top area, (b) momentum drag via equivalent suspended-water density + vertical impact force, (c) 15 % thrust-coefficient penalty | empirical knobs, see NASA TP-2671 (Dunham et al.) heavy-rain research; all in config |
| flight | 100 Hz point-mass 3-DOF sim; quasi-static attitude (the quad tilts into the relative wind), P velocity loop with accel limits; rotor speeds solved each step from the CT tables; electrical energy integrated | zero-wind mission unit-tested against a quasi-static analytic power balance (±6 %) |
| structure | Euler–Bernoulli cantilever arm: worst-case per-rotor thrust across all scenarios × 1.5 safety factor; stress ≤ material strength, tip deflection ≤ 5 % L, first bending mode outside ±15 % of hover 1P — all with the genome-selected material's properties | stress/deflection unit-tested against hand calculations |

Sanity anchors (unit-tested): the original spec anchor — a 5-inch quad at
1.1 kg AUW hovers at ~195 W (180–280 W band), checked against the cached
GWS 5×4.3 dataset — plus the shipped platform: the baseline 7-inch deck
(~0.34 m wheelbase, ~1.0 kg AUW) hovers in a plausible 90–230 W band on
the MA GF 7×4 data.

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
- **UIUC data was measured at 2.5k–7k RPM and on a 2-blade prop**; the kit
  flies 3-blade 7×4s and hovers near 9k RPM. CT/CP are treated as
  Re-independent and blade-count effects are absorbed into the tables.
- **Print-material properties are XY/datasheet values.** FDM parts are
  weaker across layer lines (often 40–60 % in Z); the 1.5 safety factor is
  the only allowance for anisotropy, print quality, or temperature.
- Structural model checks the arms only (root stress, tip deflection,
  resonance); the deck is assumed rigid and the standoffs ideal.
- **Printability is enforced by geometry constraints, not full DFM.** Parts
  are flat plates with non-colliding bolt-clamped tongues and exported as
  separate pieces, but bolt holes, interlock notches, tolerances and
  print-orientation strength are not modeled.
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
