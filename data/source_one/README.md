# Source One V6 — 7 in DC plate drawings (provenance)

`So1-V6-7inDC-2025-JUL-07.dxf` is the official TBS Source One V6 7-inch
DeadCat frame drawing, copied unmodified from the upstream open-source
repository (GPLv3):

    https://github.com/tbs-trappy/source_one

It is cached here because framevo's generation-0 baseline genome is
**measured from this file** (see `src/framevo/genome.py`):

| measured from the DXF | value |
|---|---|
| bottom/main plate footprint | 106.6 × 48.5 mm |
| plate thickness (drawing callout) | 2 mm |
| arm plate thickness (drawing callout) | 6 mm |
| arm overall length | 160.7 mm |
| arm width: root tongue / waist / motor end | ~21.8 / ~12.5 / ~21.6 mm |
| deck standoffs (BOM) | M3 × 30 mm × 4 |

The parametric baseline approximates this geometry (symmetric X instead of
DeadCat sweep; the flared motor end is covered by the motor pad).
