# Noise-folding loss at low sample rates

This page estimates how much detection performance an ESP32-C61 loses if it obtains 4 MSa/s by
keeping every 20th sample of an 80 MSa/s stream **without** digital band limiting (GitHub issue
#3). Noise from the whole analog bandwidth then folds into the 4 MHz output band. The numbers
are simulated estimates for planning milestone M4; they are not measurements of hardware.

## Terms

- **Output rate**: the sample rate of the snapshot, 4 MSa/s.
- **Generate rate**: the higher rate at which the simulator first creates signal and noise,
  80 MSa/s (decimation factor 20). Noise has unit variance per sample at this rate, so
  N0 = 1 / generate rate, and C/N0 keeps its usual meaning.
- **B**: the analog bandwidth, the width of the passband around 0 Hz in complex baseband.
- **Method `none`**: low-pass filter to B, then keep every 20th sample.
- **Method `ideal`**: low-pass filter to B, low-pass filter to the output band (±2 MHz), then
  keep every 20th sample. This is what the earlier pages assume.
- **Peak-to-noise ratio**: the acquisition detection metric (the correlation peak divided by the
  noise level), averaged over the trials.

## Model and assumptions

Both low-pass filters are brick-wall filters applied in the frequency domain over the whole
snapshot (`sim.impairments.lowpass`): everything inside the passband is kept unchanged and
everything outside is removed. A Butterworth analog filter would give a slightly different
number; only the brick-wall model was simulated.

Assumptions, all of them:

1. Brick-wall filters, no passband ripple, no filter transient.
2. No ADC aperture or sample-and-hold effects.
3. B is the only property of the ESP32 analog path that is used. In `esp32c61.yaml`,
   `analog_bandwidth_hz` is a pair of bounds, 13 MHz (lower) and 54 MHz (upper). When a scenario
   names the device and does not set `analog_bandwidth_hz`, the **lower bound, 13 MHz,** is used,
   because it is the case with the least folding. An explicit value in the scenario
   overrides it; the 20 MHz cases do this. The 13 MHz value is itself marked in the device file
   as a lower bound, so the loss at the real bandwidth may be larger.

Under these assumptions the noise power in the output band is B / output rate times larger with
`none` than with `ideal`, while the signal power is the same. The rough theoretical estimate of
the loss is therefore 10·log10(B / output rate): 5.1 dB for B = 13 MHz and 7.0 dB for
B = 20 MHz. This is an estimate: it treats the signal as lying entirely inside the output band.

`tests/test_aliasing.py` checks that the measured noise-power ratio between the two methods is
within 10 % of B / output rate, that `lowpass` keeps an in-band tone and removes an out-of-band
tone, and that the simulate–acquire–compare loop passes for both methods.

## Conditions

All sweeps use one satellite (PRN 10), 16 384 output samples (about 4.1 ms), a clock error of
−8 ppm, no quantization, a frequency search of ±40 kHz, 4 blocks combined non-coherently
(each about 1 ms), `pfa` = 1e-3, 200 trials per C/N0 point and `--seed 0`. These are the
settings of the "ESP32-C61, 4 MSa/s, 4 blocks" curve on
[Detection probability versus C/N0](pd-curves.md), which serves as the reference (direct
generation at 4 MSa/s, no folding).

| Case | Scenario file | C/N0 grid |
|---|---|---|
| `none`, B = 13 MHz | `navic_s_esp32c61_aliasing_none.yaml` | 40–50 dB-Hz |
| `none`, B = 20 MHz | `navic_s_esp32c61_aliasing_none_b20.yaml` | 42–52 dB-Hz |
| `ideal`, B = 13 MHz | `navic_s_esp32c61_aliasing_ideal.yaml` | 34–44 dB-Hz |
| `ideal`, B = 20 MHz | `navic_s_esp32c61_aliasing_ideal_b20.yaml` | 34–44 dB-Hz |
| Reference, direct 4 MSa/s | `navic_s_esp32c61_4msps.yaml` | 30–46 dB-Hz |

The C/N0 grids differ from the reference grid (30–46 dB-Hz, 1 dB steps) because the `none` curves
lie 5 to 7 dB higher; each grid is in 1 dB steps and contains the 50 % and 90 % points of its
curve. The grids were chosen to keep the run time of the sweeps within one run of the automated worker. The number
of trials and every other setting are the same for all cases.

## Results

50 % and 90 % points are found as on the detection-probability page: linear interpolation
between the two adjacent grid points where `p_detect` first reaches the level. With 200 trials
the 50 % point is uncertain by roughly ±0.2 dB, so differences of a few tenths of a dB are not
significant.

| Case | 50 % point | 90 % point | Shift of 50 % point vs `ideal` | Theoretical estimate | Difference from estimate |
|---|---|---|---|---|---|
| Reference, direct 4 MSa/s | 38.7 dB-Hz | 40.6 dB-Hz | — | — | — |
| `ideal`, B = 13 MHz | 38.6 dB-Hz | 40.4 dB-Hz | 0 dB | 0 dB | — |
| `ideal`, B = 20 MHz | 38.6 dB-Hz | 40.4 dB-Hz | 0 dB | 0 dB | — |
| `none`, B = 13 MHz | 43.4 dB-Hz | 45.0 dB-Hz | 4.8 dB | 5.1 dB | −0.3 dB |
| `none`, B = 20 MHz | 45.5 dB-Hz | 47.3 dB-Hz | 6.9 dB | 7.0 dB | −0.1 dB |

Mean peak-to-noise ratio at equal C/N0 (the C/N0 values below lie in the grids of all
compared cases):

| C/N0 | `ideal` (both B) | `none`, B = 13 MHz | `none`, B = 20 MHz |
|---|---|---|---|
| 42 dB-Hz | 13.9 | 6.0 | 5.4 |
| 43 dB-Hz | 17.2 | 7.0 | 5.7 |
| 44 dB-Hz | 21.7 | 8.3 | 6.0 |

For reference, the metric of a noise-only trial is about 5.4 (see the first rows of the CSV
files, where `p_detect` is 0). At 44 dB-Hz the `none` cases have therefore lost most of the
margin above the noise.

Data files (columns `cn0_dbhz`, `trials`, `p_detect`, `p_wrong`, `mean_metric`):

- [aliasing_none.csv](aliasing_none.csv)
- [aliasing_none_b20.csv](aliasing_none_b20.csv)
- [aliasing_ideal.csv](aliasing_ideal.csv)
- [aliasing_ideal_b20.csv](aliasing_ideal_b20.csv)
- [pd_navic_s_esp32c61_4msps_b4.csv](pd_navic_s_esp32c61_4msps_b4.csv) (reference, from the detection-probability page)

## Discussion

- **The loss matches the estimate.** The measured shifts of the 50 % point, 4.8 dB and 6.9 dB,
  are 0.3 dB and 0.1 dB below 10·log10(B / output rate). Both differences are within the
  roughly ±0.2 dB uncertainty of a 50 % point from 200 trials, plus the 0.1 dB grid and
  interpolation effects; the 0.3 dB difference at 13 MHz is slightly larger than that and
  may be a statistical fluctuation, which was not tested further.
- **With `ideal` decimation B does not matter** as long as it is wider than the output band.
  The two `ideal` curves are identical, because the output filter removes everything outside
  ±2 MHz in both cases (this is also checked in `tests/test_aliasing.py`).
- **Ideal decimation agrees with direct generation at 4 MSa/s.** The `ideal` 50 % point,
  38.6 dB-Hz, equals the reference 38.7 dB-Hz within the uncertainty.
- **Expectation for M4.** If the ESP32-C61 produces 4 MSa/s by clock division with an analog
  bandwidth of 13 MHz or more, expect to need roughly 5 dB (13 MHz) to 7 dB (20 MHz), and more
  at wider bandwidths, extra C/N0 compared with the curves on the detection-probability page.
  For the upper bound of 54 MHz in the device file the same estimate gives
  10·log10(54 / 4) = 11.3 dB; this was **not simulated**.
- **What is not known.** Whether the ESP32-C61 applies any digital filtering before reducing
  the rate, and the true shape of its analog filter, are not known (issues #3 and #13). If
  either is needed to refine this estimate, that is outside this page.

## How to regenerate

About 31 minutes for the two `none` sweeps and about 20 minutes for the two `ideal` sweeps,
with two sweeps in parallel on two CPU cores. Every setting is given explicitly:

```bash
pip install -e ".[dev]"
S="--trials 200 --freq-span 40000 --blocks 4 --pfa 0.001 --seed 0"
snappnt sweep scenarios/navic_s_esp32c61_aliasing_none.yaml --cn0 40:50:1 $S -o docs/results/aliasing_none.csv
snappnt sweep scenarios/navic_s_esp32c61_aliasing_none_b20.yaml --cn0 42:52:1 $S -o docs/results/aliasing_none_b20.csv
snappnt sweep scenarios/navic_s_esp32c61_aliasing_ideal.yaml --cn0 34:44:1 $S -o docs/results/aliasing_ideal.csv
snappnt sweep scenarios/navic_s_esp32c61_aliasing_ideal_b20.yaml --cn0 34:44:1 $S -o docs/results/aliasing_ideal_b20.csv
```

## Proposed follow-up

The low-pass model (brick-wall filters, B taken as the lower bound of the device file) is a design
decision that belongs in `docs/project/decisions.md`. That file was outside the allowed scope of
issue #3, so a decision-log entry is proposed as a separate issue.
