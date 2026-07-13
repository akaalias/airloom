# Source One V6 — 7 in DC plate drawings (provenance)

`So1-V6-7inDC-2025-JUL-07.dxf` is the official TBS Source One V6 7-inch
DeadCat frame drawing, copied unmodified from the upstream open-source
repository (GPLv3):

    https://github.com/tbs-trappy/source_one

It is cached here because this drawing is framevo's **genome substrate**:
`src/framevo/realgeo.py` parses the plate outlines straight from the DXF —
arcs, cutouts and every bolt hole — and the genes morph those outlines
(`frame_gen.py`). The generation-0 baseline genome is **measured from this
file** (see `src/framevo/genome.py`):

| measured from the DXF | value |
|---|---|
| bottom/main plate footprint | 106.6 × 48.5 mm |
| plate thickness (drawing callout) | 2 mm |
| arm plate thickness (drawing callout) | 6 mm |
| arm overall length | 160.7 mm |
| arm width: root tongue / waist / motor end | ~21.8 / ~12.5 / ~21.6 mm |
| deck standoffs (BOM) | M3 × 30 mm × 4 |

Every scale gene at ×1.00 reproduces the real V6 part exactly; the baseline
frame mass comes out at 144 g against the real frame's ~145 g. The front
arm anchors are exact bolt-pattern registrations from this drawing (stock
sweep 31.4°); the rear anchor is a best-fit clamp registration (stock
36.0°). The DC arms keep their true left/right mirrored chirality.
