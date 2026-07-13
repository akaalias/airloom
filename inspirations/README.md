# Inspirations

Idea files for the Claude designer. Feed one into a run with:

    framevo run --fresh --inspiration inspirations/zen.md

The file's content is stored with the run (`runs.inspiration_text`),
shown in the gallery header, and injected into every designer brief —
generation 0 and each periodic design round. Passing `--inspiration`
while resuming replaces the stored text and steers the remaining
rounds.

| file | designer | angle |
| --- | --- | --- |
| `frogs.md` | biomimicry | squat-vs-leap postures, area over mass, compliance |
| `rem-koolhaas.md` | Rem Koolhaas | program over form, bigness, celebrate the generic |
| `picasso.md` | Picasso | abstraction by subtraction, deliberate distortion |
| `zen.md` | Zen Buddhism | negative space, sufficiency, the middle way |
| `von-neumann.md` | John von Neumann | minimax, corner solutions, shadow prices |
| `freakonomics.md` | Levitt & Dubner | incentive loopholes, one-gene natural experiments |
| `buckminster-fuller.md` | Buckminster Fuller | ephemeralization, strength from geometry |
| `gaudi.md` | Antoni Gaudí | load-path-shaped structure, fore-aft asymmetry |

Writing your own: anything goes, but the designer works best when the
metaphors gesture at something translatable into the genome (arm
length/width/waist, thickness, sweeps, plate scales, deck gap, battery
wedge, material) or the scenarios (storm worst-case, thin air,
crosswind, headwind). Files are truncated at 6,000 characters in the
prompt.
