# Prompt for Claude Code: Quadcopter Frame Auto-Research Loop

> **Historical document** — the original brief, kept verbatim for
> provenance. The implementation has since evolved past it in places: the
> genome now morphs the real Source One V6 plate drawings instead of
> parametric primitives, the platform is the DroneAid 7-inch kit (6S Li-Ion,
> 2806 motors, 7×4 props) rather than the 5-inch 4S example below, and
> headless-Claude designer rounds and a lab-notebook narrator were added.
> `README.md` and `PLAN.md` describe the current state.

Build a fully automated, headless research loop that evolves quadcopter **frame geometry** to minimize **energy per distance (watt-hours per kilometer, Wh/km)** flown through a specified adverse environment. Everything except the frame is fixed. The system must run unattended on a Linux server, be resumable, and produce a ranked archive of all evaluated frames.

---

## 1. Fixed platform (identical for every candidate — never vary these)

Define these once in `config/platform.yaml`:

- **Battery:** 4S lithium-polymer, 5000 mAh, nominal 14.8 V, mass 520 g, rigid rectangular block 138 × 47 × 38 mm. The frame must physically accommodate this block (hard geometric constraint).
- **Rotors + motors:** 4× fixed combination, e.g. 2306-size brushless motors with 5-inch (127 mm) diameter, 4.3-inch pitch propellers. Motor mass 32 g each. Use one published propeller performance dataset (e.g. APC 5x4.3 from the UIUC Propeller Database — download and cache it) as ground truth for thrust and power coefficients.
- **Flight controller / microcontroller:** fixed 30.5 × 30.5 mm mount pattern, mass 15 g, plus 10 g for receiver and wiring. Frame must provide this mount.
- **Payload:** none. Total non-frame mass is therefore constant; only frame mass varies.

## 2. The variable: parametric frame geometry

Represent each frame candidate as a small genome (10–16 continuous parameters), for example:

- arm length, arm cross-section width and height, arm sweep angle, arm dihedral
- arm cross-section shape blend (rectangular → elliptical → airfoil-like fairing, one blend parameter)
- central body length, width, height, edge fillet radius
- body pitch angle of the top plate (affects forward-flight drag since quadcopters tilt into the wind)
- material thickness scaling (carbon-fiber plate, fixed material properties: density 1600 kg/m³, tensile strength 600 MPa, Young's modulus 70 GPa)

Write a generator `frame_gen.py` that turns a genome into:
1. a watertight 3D mesh (use `trimesh` + `manifold3d` or CadQuery / build123d for parametric solids), exported as STL,
2. computed frame mass and center of gravity,
3. hard geometric validity checks: battery fits, rotors have ≥ 5 mm tip clearance from all frame parts and from each other, flight controller mount exists. Invalid genome → fitness = infinity, no simulation run.

## 3. Environment scenario portfolio (every candidate flies ALL scenarios)

To avoid overfitting the frame to one weather condition, each candidate is evaluated across an array of scenarios defined in `config/scenarios.yaml`. Ship these six defaults:

1. **calm_warm** — 25 °C, no wind, no rain. (Baseline efficiency; also the sanity-check case.)
2. **cold_headwind** — 5 °C, mean wind 8 m/s from north, Dryden turbulence, no rain.
3. **storm** — 5 °C, wind 8 m/s north, Dryden turbulence at higher intensity, heavy rain 25 mm/h.
4. **crosswind** — 15 °C, wind 10 m/s from east (pure crosswind on a north–south mission), moderate turbulence.
5. **gusty_light** — 10 °C, mean wind 4 m/s from northwest but severe-intensity Dryden gusts (tests control effort and structural loads, not steady drag).
6. **hot_thin** — 35 °C, density altitude 1500 m (low air density → rotors work harder), light wind.

Common physics for all scenarios:

- Air density computed from each scenario's temperature/pressure/altitude.
- Turbulence: Dryden gust model (standard MIL-F-8785C forms), time-correlated velocity components. **Each scenario has its own fixed random seed** so every candidate flies identical gust histories per scenario — fitness differences are frame differences, never gust luck.
- Rain, where present: (a) added mass flux on upward-facing projected area, (b) a rain drag/momentum penalty term, (c) a 15 % thrust-efficiency penalty on rotors (cite NASA heavy-rain research in code comments; make it a config parameter).
- Mission (identical in all scenarios): fly 2 km north, then 2 km south, at 12 m/s commanded ground speed, at 30 m altitude. Total 4 km.

**Aggregation into one fitness scalar (robustness-aware):**

- Compute Wh/km separately per scenario.
- A candidate that fails (structural, rotor saturation, geometric) in *any* scenario is invalid — fitness = infinity. Structural loads are checked against the worst case across all scenarios.
- Fitness = **mean Wh/km across scenarios + λ × worst-scenario Wh/km**, with λ = 0.5 by default (configurable). The mean rewards general efficiency; the worst-case term punishes designs that are great in five scenarios and terrible in one. Also support a pure worst-case mode (`aggregation: minimax`) as a config option.
- Store per-scenario results individually in the database and show them as columns in the leaderboard, so scenario-specific weaknesses are visible even for good aggregate scores.

**Cost control:** scenarios are embarrassingly parallel — evaluate them concurrently per candidate. Optionally support a cheap early-reject: run `calm_warm` first, and if a candidate is worse than the current population median by a configurable margin, skip the remaining scenarios and assign a penalized (but finite) fitness so evolution still gets gradient information.

## 4. Physics stack (staged fidelity — build Phase A first, make it work end-to-end, then add B)

### Phase A — fast analytical loop (must be fully working before anything else)
- **Rotor model:** blade element momentum theory (BEMT) or, simpler and acceptable, interpolation of the UIUC measured thrust/power coefficient tables vs. advance ratio. Wrap as `rotor_model.py` returning thrust and electrical power (include a fixed 85 % combined motor+ESC efficiency, where ESC = electronic speed controller).
- **Frame aerodynamics:** component drag buildup: compute projected areas of the frame mesh from multiple directions (rasterize the STL), assign drag coefficients per component class (flat plate ~1.9, cylinder ~1.1, faired section ~0.6 interpolated by the cross-section blend parameter), plus an interference penalty where arms sit inside rotor disks (rotor-wash drag on planform area under each disk). Output: a drag polar D(airspeed, tilt angle) table per candidate.
- **Flight simulation:** a 6-degrees-of-freedom (or simplified 3-degrees-of-freedom longitudinal) Python simulator, 100 Hz, with a cascaded PID (proportional–integral–derivative) attitude/velocity controller. The quadcopter tilts to fight the relative wind (mean wind + Dryden gusts + own airspeed); solve rotor speeds each step to satisfy force balance; integrate electrical energy. Log peak arm loads (thrust × moment arm, plus gust load factors).
- **Structural integrity (constraint, not objective):** Euler–Bernoulli beam model of each arm under peak simulated load × safety factor 1.5. If max stress > material strength or tip deflection > 5 % of arm length → candidate invalid (fitness = infinity). Also compute first bending natural frequency; reject if within ±15 % of rotor rotation frequency band at hover (resonance).
- **Fitness:** per scenario, total energy consumed (Wh) / 4 km, then aggregated across the scenario portfolio as defined in section 3. Lower is better. If the drone cannot hold the commanded speed (saturated rotors) in any scenario, it's invalid.

### Phase B — computational fluid dynamics (CFD) upgrade (optional, behind a flag)
- Add an OpenFOAM pipeline (Docker image `opencfd/openfoam-default`): snappyHexMesh around the frame STL, steady RANS (Reynolds-averaged Navier–Stokes) with k-omega SST turbulence model, 3 flow angles × 2 speeds per candidate, extract drag → replace the component-buildup drag polar. Run only on the top N candidates per generation (surrogate-assisted: the analytical model screens, CFD refines). Cache results by genome hash.

## 5. The evolution loop

- **Optimizer (default): a genetic algorithm with explicit parentage**, because full lineage tracking is a first-class requirement. Population 16. Tournament selection, blend/simulated-binary crossover on the continuous genome, Gaussian mutation with adaptive sigma, elitism (top 2 carried over unchanged). Implement directly or via DEAP/LEAP — but the implementation must expose, for every candidate: its parent(s), the operator that produced it (crossover, mutation, elite carry-over, or random immigrant), and the generation of birth.
- **Lineage tracking:**
  - Every candidate gets a stable ID (genome hash) and records: `parent_a`, `parent_b` (null for the seeded generation 0 or random immigrants), `operator`, `generation_born`, and mutation magnitude.
  - Stored in SQLite as a self-referencing table so ancestry queries are trivial (`WITH RECURSIVE` walk to any depth).
  - Provide a CLI command `lineage <genome_hash>` that prints the full ancestor chain of a candidate with fitness at each step — so you can trace how a winning frame's Wh/km improved along its ancestry.
  - Export the full family tree per run as a Graphviz DOT file and render `results/lineage.svg`: nodes colored by fitness (dark = better), invalid candidates as hollow nodes, edges labeled by operator. Elite carry-over shown as vertical pass-through edges.
  - In the gallery (section on results), each candidate's thumbnail links to a small detail block showing its parents' thumbnails — you should be able to visually see "this faired-arm child came from crossing the long-arm frame with the low-body frame."
- **Alternative optimizer (flag-gated):** keep CMA-ES (covariance matrix adaptation evolution strategy) available as `--optimizer cmaes` for pure optimization performance. Note in the README that CMA-ES has no discrete parents — for it, record distribution-level provenance instead (mean and sigma per generation) and skip the family tree.
- Every candidate evaluated in a subprocess with a timeout; parallelize across cores with `multiprocessing` or `joblib`.
- Persist everything to SQLite: genome, lineage fields, mass, validity, per-scenario metrics, aggregate fitness, random seed, git hash of the code. The loop must be resumable after a crash (`--resume`), including lineage continuity.
- **Save every candidate:** export each candidate's STL to `results/frames/gen_XXXX/<genome_hash>.stl` (including invalid ones, flagged in the filename, e.g. `_INVALID` suffix — the failures are instructive). Frame meshes are small; disk is not a concern.
- **Offscreen renders:** for every candidate, render the mesh headlessly to a PNG thumbnail (use `trimesh`'s offscreen rendering via `pyrender` with the EGL/OSMesa backend, or fall back to `matplotlib` 3D plotting of the mesh if no GPU/EGL is available — the fallback must always work on a plain CPU-only machine). Save alongside the STL. Render from a consistent three-quarter view with fixed camera and scale so frames are visually comparable across generations.
- **Live gallery:** after each generation, regenerate a static, self-contained `results/gallery.html`: one row per generation, thumbnails of all candidates sorted by fitness, each with its aggregate Wh/km and per-scenario scores underneath, best candidate highlighted, invalid candidates greyed out with the failure reason. Include `<meta http-equiv="refresh" content="30">` so a browser tab left open updates itself as the loop runs. No JavaScript frameworks, no server required — plain HTML you can open with `file://`. Keep the design restrained and typographic: neutral background, small caps labels, numbers aligned in tabular figures.
- After each generation also write `results/leaderboard.md` (top 10 with all metrics) and copy the best frame's STL to `results/gen_XXXX_best.stl`.
- Also save a plain matplotlib convergence plot (fitness vs. generation) — no interactive dashboards needed.

## 6. Engineering requirements

- **Local-first:** the entire Phase A loop must run on a normal laptop (macOS Apple Silicon and Linux x86, CPU-only) with nothing beyond `pip install -e .` — no Docker, no GPU, no EGL required for the default path. Anything with heavier dependencies (OpenFOAM, GPU rendering) is strictly optional and flag-gated. Auto-detect core count and scale the parallel evaluation accordingly. Verify all Python dependencies (especially the rendering fallback) install cleanly on macOS arm64.
- Python 3.11+, fully typed, `pyproject.toml`, no GUI dependencies, runs headless.
- Unit tests for: frame generator validity checks, rotor model against 3 known UIUC data points, beam stress against a hand-calculated case, Dryden model statistical properties (variance matches spec), and energy integration on a zero-wind sanity case.
- A `make demo` target that runs 3 generations with population 8 in under ~10 minutes on 8 cores, prints the leaderboard, and finishes by printing the `file://` path to `results/gallery.html`.
- README with the physics assumptions, their sources, and known limitations clearly listed (especially: rain model is empirical, Phase A drag is approximate, no rotor–rotor interaction).
- Sanity anchor: with a conventional X-frame genome (220 mm class), hover power should land in the plausible 180–280 W range for ~1.1 kg all-up mass; assert this in a test.

Start by writing the plan as `PLAN.md`, then implement Phase A end-to-end before any Phase B work. Prefer boring, verifiable physics over sophistication.
