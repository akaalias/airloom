# CFD drag calibration

| case | tilt | buildup CdA [m²] | CFD CdA [m²] | ratio |
|---|---|---|---|---|
| `arms_baseline_t00` | 0° | 0.00233 | 0.00157 | 0.68 |
| `arms_baseline_t20` | 20° | 0.01094 | 0.00529 | 0.48 |
| `arms_baseline_t40` | 40° | 0.01614 | 0.00991 | 0.61 |
| `body_baseline_t00` | 0° | 0.00522 | 0.00567 | 1.09 |
| `body_baseline_t20` | 20° | 0.00978 | 0.00673 | 0.69 |
| `body_baseline_t40` | 40° | 0.01105 | 0.00908 | 0.82 |
| `full_baseline_t00` | 0° | 0.00755 | 0.00684 | 0.91 |
| `full_baseline_t20` | 20° | 0.02072 | 0.00944 | 0.46 |
| `full_baseline_t40` | 40° | 0.02719 | 0.01390 | 0.51 |
| `full_contrast_t00` | 0° | 0.00879 | 0.00761 | 0.87 |
| `full_contrast_t20` | 20° | 0.02302 | 0.01078 | 0.47 |
| `full_contrast_t40` | 40° | 0.02927 | 0.01459 | 0.50 |

## Interference (measured full − sum of parts)

- 0°: -0.00040 m² (-5.8% of full-assembly drag)
- 20°: -0.00259 m² (-27.4% of full-assembly drag)
- 40°: -0.00509 m² (-36.6% of full-assembly drag)

Update `CD_ARM`/`CD_BODY` in `aero.py` from the arms/body ratios, add an interference term if the residual is material, then re-run `framevo robustness` — a STABLE verdict closes Phase B milestone 1.
