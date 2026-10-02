# Removing the DC offset before acquisition

This page records how a receiver DC offset changes the probability of detecting a NavIC S-band
SPS signal, and how much of it `snappnt acquire --remove-dc` gives back (GitHub issue #43).
Everything here is simulated. No real capture was used.

## Background

A noise-only capture from one XIAO ESP32C3 board showed a mean of about −270 counts on I, about
−0.5 of the 512-count full scale ([ESP32-C3 bench checks](esp32c3-bench-no-rf.md)). A constant
offset is a carrier at 0 Hz. After correlation with the spreading code it makes a peak at a
fixed code phase that does not depend on the satellite, and that peak is higher than the
signal's own peak at the C/N0 values of interest.

`acquire` has the keyword `remove_dc` (and the command-line option `--remove-dc` on
`snappnt acquire` and `snappnt sweep`):

| Value | What is subtracted from the snapshot before correlation |
|---|---|
| `none` (default) | Nothing. |
| `mean` | The complex mean of the snapshot. |
| `linear` | A straight line fitted by least squares to I and Q separately against the sample index. It also removes a steady drift of the offset. |

## Method

`snappnt sweep` as described in [Detection probability versus C/N0](pd-curves.md): PRN 10,
200 trials per C/N0 value, C/N0 from 46 to 60 dB-Hz in 1 dB steps, `--freq-span 40000`,
`--blocks 1`, `--pfa 0.001`, `--seed 0`. Five cases:

| Case | Scenario | `--remove-dc` |
|---|---|---|
| A | `navic_s_esp32c3.yaml` (no DC offset) | `none` |
| B | `navic_s_esp32c3_dc.yaml` | `none` |
| C | `navic_s_esp32c3_dc.yaml` | `mean` |
| D | `navic_s_esp32c3.yaml` | `mean` |
| E | `navic_s_esp32c3_dc.yaml` | `linear` |

`navic_s_esp32c3_dc.yaml` has a DC offset of −0.5 of full scale on I, 0 on Q, constant over the
snapshot, and the fixed spur measured on the same board (−12 dB, at −12 MHz). The spur is
part of cases B, C and E, so the loss of C and E against A includes any effect of the spur.
The drift of the offset within a capture (about 25 counts in 0.2 ms) is not in the simulator.

## Results

The 50 % and 90 % points are linear interpolations between adjacent grid points, as on the
pd-curves page. With 200 trials they are uncertain by roughly ±0.2 dB each. The runs share the
seed, but each case draws its noise differently once the scenario differs, so differences
below about 0.2 dB are not significant.

| Case | 50 % point [dB-Hz] | 90 % point [dB-Hz] | Loss against A at 50 % [dB] | Loss against A at 90 % [dB] |
|---|---|---|---|---|
| A: no offset, `none` | 50.29 | 52.19 | 0 | 0 |
| B: offset, `none` | not reached | not reached | not defined | not defined |
| C: offset, `mean` | 50.38 | 52.31 | 0.09 | 0.12 |
| D: no offset, `mean` | 50.37 | 52.29 | 0.08 | 0.10 |
| E: offset, `linear` | 50.40 | 52.31 | 0.11 | 0.12 |

- **Case B never detects.** `p_detect` is 0 at every C/N0 up to 60 dB-Hz, and so is `p_wrong`:
  the detection metric stays at about 8.6 to 8.8 (the offset's own peak) and never exceeds the
  threshold, so the offset hides the signal without producing a false detection. With removal
  (case C) the mean metric rises from 8.6 to 14.1 at 46 dB-Hz.
- **Mean removal costs about 0.1 dB.** Case D, which has no offset to remove, loses 0.08 dB at
  the 50 % point and 0.10 dB at the 90 % point. This is the price of switching removal on
  when the receiver has no offset. It is within the statistical uncertainty of the points.
- **`linear` is not different from `mean` here** (0.02 dB at the 50 % point), as expected,
  because the simulated offset is constant. The benefit of `linear` is checked only with a
  synthetic ramp in `tests/test_dc_removal.py`.
- The noise-only test in the same file shows the effect on the largest cell: without removal
  it is at about 179 chips of code phase in 11 of 12 seeds; with `mean` the 12 seeds give 12
  different values.

Data files (columns `cn0_dbhz`, `trials`, `p_detect`, `p_wrong`, `mean_metric`):

- [A](dc_removal_a_clean_none.csv), [B](dc_removal_b_dc_none.csv),
  [C](dc_removal_c_dc_mean.csv), [D](dc_removal_d_clean_mean.csv),
  [E](dc_removal_e_dc_linear.csv)

Commands (here for case C; the others change the scenario and `--remove-dc`):

```bash
snappnt sweep scenarios/navic_s_esp32c3_dc.yaml --cn0 46:60:1 --trials 200 \
    --freq-span 40000 --blocks 1 --pfa 0.001 --seed 0 --remove-dc mean \
    -o docs/results/dc_removal_c_dc_mean.csv
```

## Not verified

- Real captures. The check that the largest cell of a real noise-only or weak-signal capture
  is no longer at a fixed place needs the maintainer's captures:
  `snappnt acquire <capture> --prn 10 --center 28000 --freq-span 40000 --remove-dc mean`.
- Drift of the offset within a capture, and the offset at other gain settings or boards.
- Other sample rates and snapshot lengths. The 0.2 ms snapshot at 80 MSa/s is the only one
  measured; the loss of mean removal grows when the snapshot is so short that it holds few
  cycles of the lowest signal frequencies, so longer snapshots are expected to lose less
  (estimate, not measured).
