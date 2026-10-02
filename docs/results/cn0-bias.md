# Bias of the C/N0 estimate

This page measures how far the C/N0 estimate of `acquire` lies from the true C/N0 of the
simulated satellite, one cause at a time, and what three-point parabolic interpolation
(`acquire(..., refine=True)`) does to the code-phase and frequency estimates (GitHub issue #4).
All numbers are simulated; none is a measurement of hardware.

## Terms

- **C/N0 estimate**: `cn0_dbhz_est` of `AcqResult`, computed as 10·log10((metric − 1) / T),
  where `metric` is the largest cell power divided by the mean power of the other cells (the
  noise-floor estimate) and T is the coherent integration time of one block.
- **Bias**: the C/N0 estimate minus the true C/N0, in dB, averaged over trials. A negative
  bias means the estimate reads low.
- **Frequency step**: spacing of the frequency bins, 1 / (2T): 125 Hz for the ideal condition,
  2441 Hz for the ESP32-C3 condition.
- **Standard error**: standard deviation of the per-trial bias divided by the square root of
  the number of trials.
- **Block**: with `n_blocks` = B the snapshot is cut into B parts that are correlated
  separately and added in power.

## Conditions

| | `navic_s_ideal` | `navic_s_esp32c3` |
|---|---|---|
| Sample rate | 8.184 MSa/s | 80 MSa/s |
| Snapshot | 32 736 samples (4 ms) | 16 384 samples (about 0.2 ms) |
| True C/N0 | 45 dB-Hz | 58 dB-Hz |
| Blocks B | 1 and 4 | 1 |
| Frequency search | ±2 kHz (±16 steps) | ±9.8 kHz (±4 steps) |
| True code phase | 0 chips (a whole sample) | 918.25 chips (a whole sample) |
| Quantisation in the baseline | none | none |

- NavIC S-band SPS, PRN 10, `pfa` = 1e-3, clock error 0 ppm, carrier phase 0.
- Each row is the mean of **200 trials** with noise seeds 1000 to 1199. The same seeds are used
  in every row, so differences between rows are not caused by different noise.
- The plan for this issue named 50 trials per row. The whole set ran in about 24 minutes with
  200 trials, so 200 were used to reduce the standard error.
- The frequency grid is symmetric around 0 Hz, so a true frequency of 0 Hz is a bin centre.
  The C3 grid step (2441 Hz) is not a round number, because the step is 1 / (2T) with
  T = 16 384 / 80 MHz.

## How each cause is switched on

The baseline has none of the four causes: true frequency on a bin centre, true code phase on
a whole sample, no data-bit sign change and no quantisation (floating point). Each row enables
one cause, and the last row enables all of them.

| Cause | Setting |
|---|---|
| Frequency-bin offset | true Doppler of 0.25 or 0.5 frequency step |
| Code-phase sampling | true code phase 0.25 or 0.5 sample away from a whole sample |
| Data-bit sign change | the samples after a code-period edge in the middle of the snapshot are multiplied by −1 (a navigation symbol edge falls on a code-period edge) |
| Quantisation | 10 bit, AGC with 12 dB backoff (`sim.impairments.quantize`) |

The simulator draws random navigation symbols and does not report them. To control the sign
change, the test file generates the satellite without data and flips the sign itself. No
simulator code was changed. The code is in `tests/test_cn0_bias.py`.

## Results: bias by cause

"Change" is the bias of the row minus the bias of the baseline row of the same condition.
Bias values are mean ± standard error over 200 trials. Detection probability was 1.0 in every
row.

### Ideal condition, 4 ms, 45 dB-Hz, one block (B = 1)

| Cause | Setting | Bias (dB) | Change (dB) |
|---|---|---|---|
| Baseline | none | −0.10 ± 0.04 | 0 |
| Frequency-bin offset | 0.25 step | −0.33 ± 0.04 | −0.23 |
| Frequency-bin offset | 0.5 step | −0.86 ± 0.04 | −0.76 |
| Code-phase sampling | 0.25 sample | −0.09 ± 0.04 | +0.01 |
| Code-phase sampling | 0.5 sample | −0.09 ± 0.04 | +0.01 |
| Data-bit sign change | one flip in the middle | −3.36 ± 0.04 | −3.26 |
| Quantisation | 10 bit | −0.10 ± 0.04 | 0.00 |
| All together | 0.5 step, 0.5 sample, flip, 10 bit | −2.51 ± 0.04 | −2.41 |

### Ideal condition, 4 ms, 45 dB-Hz, four blocks of 1 ms (B = 4)

| Cause | Setting | Bias (dB) | Change (dB) |
|---|---|---|---|
| Baseline | none | −0.09 ± 0.04 | 0 |
| Frequency-bin offset | 0.25 step | −0.38 ± 0.04 | −0.29 |
| Frequency-bin offset | 0.5 step | −0.81 ± 0.04 | −0.72 |
| Code-phase sampling | 0.25 sample | −0.08 ± 0.04 | +0.01 |
| Code-phase sampling | 0.5 sample | −0.08 ± 0.04 | +0.01 |
| Data-bit sign change | one flip in the middle (at 2 ms, a block boundary) | −0.15 ± 0.04 | −0.06 |
| Data-bit sign change | one flip inside a block (at 1.5 ms) | −1.44 ± 0.04 | −1.35 |
| Quantisation | 10 bit | −0.09 ± 0.04 | 0.00 |
| All together | 0.5 step, 0.5 sample, flip, 10 bit | −0.89 ± 0.04 | −0.80 |

### ESP32-C3 condition, 0.2 ms, 58 dB-Hz, one block

| Cause | Setting | Bias (dB) | Change (dB) |
|---|---|---|---|
| Baseline | none | −1.55 ± 0.03 | 0 |
| Frequency-bin offset | 0.25 step | −1.77 ± 0.03 | −0.22 |
| Frequency-bin offset | 0.5 step | −2.24 ± 0.03 | −0.69 |
| Code-phase sampling | 0.25 sample | −1.55 ± 0.03 | 0.00 |
| Code-phase sampling | 0.5 sample | −1.54 ± 0.03 | +0.01 |
| Data-bit sign change | one flip in the middle | −4.81 ± 0.04 | −3.26 |
| Quantisation | 10 bit | −1.55 ± 0.03 | 0.00 |
| All together | 0.5 step, 0.5 sample, flip, 10 bit | −4.02 ± 0.04 | −2.47 |

Data file (all rows, with and without interpolation): [cn0_bias.csv](cn0_bias.csv).

### Findings

- **A sign change inside a single block is the largest cause**, about −3.3 dB at both
  conditions. With the ideal condition cut into four 1 ms blocks, a flip in the middle of the
  snapshot falls at 2 ms, exactly on a block boundary. No block contains the edge, so every
  block is coherent and the cost is only −0.06 dB. A flip at 1.5 ms lies inside the second
  block: that block loses part of its peak (not measured separately), the other three do not, and the cost is −1.35 dB
  (this case is not at a code-period edge, so it checks the mechanism and is not a navigation
  data case). Cutting into blocks therefore limits the loss to the block that holds the edge;
  it removes the loss only when the edge falls on a boundary. The
  4 dB bias of the initial skeleton at 45 dB-Hz (41.0 dB-Hz estimated) is of the size of the
  sign-change case with one block (−3.4 dB). This explanation was not tested on the original
  skeleton run.
- **A frequency offset of half a step costs about −0.7 to −0.8 dB.** For a rough check, the
  coherent integration response is sinc², and a half-step offset is a quarter of 1 / T away
  from the bin, where sinc²(0.25) = 0.81, that is −0.9 dB. The measured changes (−0.76 and
  −0.72 dB at 4 ms, −0.69 dB at 0.2 ms) are close to this estimate.
- **Quantisation to 10 bit has no measurable effect** (changes of 0.00 dB, standard error
  0.04 dB).
- **Code-phase sampling has no measurable effect in this simulator**, and the reason is a
  limit of the simulator, not a property of receivers. The simulator forms the code at each
  sample as the chip that contains the sample time (no pulse shaping, no band limit before
  sampling). At 8 samples per chip, shifting the code phase by half a sample changes no
  sample value, so the snapshot is identical to the one without the shift. The acquisition
  then reports the code phase of the unshifted snapshot, which differs from the stated truth
  by the shift (0.0625 chip at the 0.5-sample row). The straddling loss of a real,
  band-limited receiver is therefore **not** measured here. It would need a simulator that
  delays a band-limited signal by a fraction of a sample; this is proposed as a new issue
  (see the end of the page).
- **For one block the causes do not add up.** The sums of the individual changes for the
  settings of the "all together" row are −4.0 dB (ideal, B = 1) and −3.9 dB (C3), against
  measured −2.41 and −2.47 dB. For B = 4 the sum, −0.77 dB, matches the measured −0.80 dB.
  A likely reason (not tested) is that a sign change in the middle of a block moves the peak
  to a neighbouring frequency bin (the mean frequency error is about 190 Hz at the ideal
  condition, 1.5 steps), where the extra offset of the true frequency costs less.
- **The ESP32-C3 baseline reads 1.5 dB low with none of the four causes present.** This is a
  fifth cause, outside the list in the issue. The next section describes it.

## The baseline bias grows with C/N0

The noise-floor estimate is the mean power of all cells except those next to the peak. The
snapshot also contains the satellite signal. At code phases and frequencies away from the
peak, the signal still correlates with the replica a little (the cross-correlation of the code
over a snapshot of N_chips chips). That adds to the "noise" floor in proportion to the signal
power. A rough estimate treats the leakage as random with relative power 1 / N_chips per cell,
and gives a bias of about −10·log10(1 + SNR / N_chips), where SNR is the post-correlation
signal-to-noise ratio of the peak (C/N0 · T). This estimate is not derived rigorously. The
table compares it with the measured baseline bias for one block.

| Condition | True C/N0 | N_chips | SNR (C/N0 · T) | Estimate (dB) | Measured baseline bias (dB) |
|---|---|---|---|---|---|
| ideal | 40 dB-Hz | 4092 | 40 | −0.04 | −0.16 ± 0.10 |
| ideal | 45 dB-Hz | 4092 | 126 | −0.13 | −0.15 ± 0.05 |
| ideal | 50 dB-Hz | 4092 | 400 | −0.41 | −0.34 ± 0.03 |
| ideal | 55 dB-Hz | 4092 | 1265 | −1.17 | −0.94 ± 0.01 |
| C3 | 54 dB-Hz | 209.5 | 51 | −0.96 | −0.76 ± 0.08 |
| C3 | 58 dB-Hz | 209.5 | 129 | −2.09 | −1.57 ± 0.04 |
| C3 | 62 dB-Hz | 209.5 | 325 | −4.07 | −3.11 ± 0.02 |
| C3 | 66 dB-Hz | 209.5 | 814 | −6.88 | −5.54 ± 0.01 |

Each measured value is the mean of 100 trials (noise seeds 1000 to 1099) with the baseline
settings; file [cn0_bias_baseline_vs_cn0.csv](cn0_bias_baseline_vs_cn0.csv) also lists the
standard errors. The estimate has the right shape and size, and overestimates the loss by
about 20 to 25 % in dB at the high C/N0 values. The measured values near the detection limit
(ideal at 35 dB-Hz and C3 at 50 dB-Hz, detection probability 0.17 and 0.49) are not in the
table, because the peak is then often a noise cell and the bias is not a property of the
signal. The remainder of the loss is not explained, and this is the only evidence for the
cause: no run switched the leakage off. The consequence is that at high C/N0 the estimate
saturates: for the C3 condition the bias is already −3 dB at 62 dB-Hz.

## Effect of interpolation

`acquire(..., refine=True)` fits a parabola through the power of the peak cell and its two
neighbours along code phase (neighbouring lags, wrapping at the code period) and along
frequency (neighbouring bins; not done when the peak is on the edge of the searched range).
It changes only `code_phase_chips` and `freq_offset_hz`. `metric`, `threshold`, `detected`,
`cn0_dbhz_est` and `n_cells` are those of the peak cell, so the C/N0 bias in the tables above
is the same with and without interpolation (the CSV file lists both). The default is
`refine=False`, and `tests/test_cn0_bias.py::test_refine_default_is_unchanged` checks that
`AcqResult` is unchanged.

Mean absolute error of the frequency estimate (Hz), without → with interpolation, 200 trials:

| True frequency from bin centre | Ideal, B = 1 | Ideal, B = 4 | C3, B = 1 |
|---|---|---|---|
| 0 step | 0.0 → 5.3 | 0.0 → 19.5 | 0.0 → 96.8 |
| 0.25 step | 31.2 → 9.7 | 125.0 → 38.7 | 610.4 → 194.6 |
| 0.5 step | 62.5 → 11.1 | 250.0 → 44.6 | 1220.7 → 243.6 |
| Quarter of the frequency step | 31.3 | 125 | 610 |

For B = 4 the coherent time T is 1 ms and the frequency step is 500 Hz.

- Away from a bin centre the error falls to between a third (0.25 step) and a fifth (0.5 step)
  of the grid error, and stays under a quarter of the step in every row.
- On a bin centre interpolation adds a small error (5 Hz, 19 Hz, 97 Hz at the three
  conditions) because noise tilts the parabola. At 60 dB-Hz the error is below a quarter of the
  step in all cases tested (`test_refine_accuracy`).
- **Code phase:** the error is below 0.1 chip with or without interpolation, because the grid
  already has a spacing of 1 / 8 chip (ideal) or 1 / 78 chip (C3). Because the simulator does not
  shift the signal by fractions of a sample (see Findings), the benefit of code-phase
  interpolation cannot be shown with it. It is implemented and tested on the parabola
  (`test_parabolic_offset_*`) and on the acceptance test, but its effect on real data is not
  verified.
- With a sign change in the snapshot the peak is not at the true frequency (190 Hz mean error at
  the ideal condition, 3.6 kHz at C3), and interpolation does not help (the CSV has the numbers).

## Not verified and proposals

- The effect of the causes on real hardware snapshots is not measured.
- Straddling loss in code phase with a band-limited signal: proposed as a new issue, to add a
  fractional-sample delay and pulse shaping to the simulator.
- The 4 dB of the initial skeleton is attributed to a sign change inside one block, but the
  original run was not repeated.
- A correction of the noise floor for signal leakage (and of the peak power for the frequency
  offset) could reduce the C/N0 bias. This page does not implement one, because it changes the
  value of `cn0_dbhz_est`, which is a public output of `AcqResult`. It is proposed as a new
  issue for the maintainer to decide.

## How to regenerate

About 24 minutes for the main table and about 2.5 minutes for the C/N0 table on one CPU core:

```bash
uv sync
uv run python tests/test_cn0_bias.py 200               # docs/results/cn0_bias.csv
uv run python tests/test_cn0_bias.py baseline_versus_cn0   # docs/results/cn0_bias_baseline_vs_cn0.csv
```
