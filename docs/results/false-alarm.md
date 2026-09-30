# False-alarm rate versus the configured `pfa`

This page measures how often acquisition reports a detection when the snapshot holds noise
only, and compares that rate with the false-alarm probability `pfa` that the detection
threshold is designed for (GitHub issue #1).

## What the threshold assumes

`acquire` in `src/snappnt/rx/acquisition.py` searches a grid of code phase × carrier frequency.
Each point of the grid is a *cell*; `n_cells` is the number of cells (number of code-phase lags
× number of frequency bins). The snapshot is cut into B blocks (`n_blocks`), which are
correlated separately and added in power. The detection metric is the largest cell power
divided by the mean power of the other cells (the noise-floor estimate).

`detection_threshold(n_cells, n_blocks, pfa)` assumes that, with noise only:

- the normalised power of each cell follows a Gamma distribution with shape B and scale 1/B,
- all cells are independent,

and sets the threshold so that each cell exceeds it with probability `pfa / n_cells`. The
probability that any cell of the grid exceeds it is then close to `pfa`.

In reality neighbouring code phases and neighbouring frequency bins are correlated, and the
noise floor is estimated from the same data. The measurement below shows how far the real rate
is from `pfa`.

## Conditions

| | `navic_s_ideal` | `navic_s_esp32c3` |
|---|---|---|
| Sample rate | 8.184 MSa/s | 80 MSa/s |
| Snapshot length | 32 736 samples (4 ms) | 16 384 samples (about 0.2 ms) |
| Samples per chip (chip rate 1.023 Mcps) | 8 | about 78 |
| Quantization | none | 10 bits, 12 dB AGC backoff |
| Clock error | 0 ppm | 12 ppm (as in the scenario file) |
| Frequency search range | ±2 kHz | ±40 kHz |

- Signal: NavIC S-band SPS, PRN 10 searched. The satellite is removed from the scenario, so
  every snapshot holds noise only (complex white Gaussian noise, unit variance per sample,
  before quantization).
- `n_blocks` = 1 and 4. The frequency step is the default 1/(2T), where T is the length of one
  block: 125 Hz and 500 Hz for `navic_s_ideal`, about 2441 Hz and 9766 Hz for
  `navic_s_esp32c3`. With `n_blocks=4`, a `navic_s_esp32c3` block is about 51 µs long and the
  ±40 kHz range holds only 9 frequency bins.
- The frequency search ranges are the ones used in `tests/test_loopback.py`. ±40 kHz covers
  the −30 kHz carrier shift that a 12 ppm clock error causes at 2492 MHz. A wider range gives
  more cells and a higher threshold.
- 1000 trials per condition, with noise seeds 0 to 999. The detection metric of a trial does
  not depend on `pfa`, so the same 1000 trials are compared with the threshold for
  `pfa` = 0.1 and for `pfa` = 0.01.

## Results

Two intervals are given for each condition:

- **99 % CI of rate:** the Clopper–Pearson (exact binomial) 99 % confidence interval of the
  measured rate.
- **99 % interval of count under `pfa`:** the central 99 % range of the number of false alarms
  in 1000 trials if the true rate were exactly `pfa` (`scipy.stats.binom.interval`). A
  measured count outside this range is a significant deviation from the configured `pfa`.

| Scenario | B | `n_cells` | `pfa` | False alarms / 1000 | Rate | 99 % CI of rate | 99 % interval of count under `pfa` | Inside? |
|---|---|---|---|---|---|---|---|---|
| `navic_s_ideal` | 1 | 270 072 | 0.1 | 83 | 0.083 | 0.062 – 0.108 | 76 – 125 | yes |
| `navic_s_ideal` | 1 | 270 072 | 0.01 | 13 | 0.013 | 0.006 – 0.025 | 3 – 19 | yes |
| `navic_s_ideal` | 4 | 73 656 | 0.1 | 83 | 0.083 | 0.062 – 0.108 | 76 – 125 | yes |
| `navic_s_ideal` | 4 | 73 656 | 0.01 | 10 | 0.010 | 0.004 – 0.021 | 3 – 19 | yes |
| `navic_s_esp32c3` | 1 | 2 720 000 | 0.1 | 23 | 0.023 | 0.013 – 0.038 | 76 – 125 | no, lower |
| `navic_s_esp32c3` | 1 | 2 720 000 | 0.01 | 2 | 0.002 | 0.000 – 0.009 | 3 – 19 | no, lower |
| `navic_s_esp32c3` | 4 | 720 000 | 0.1 | 23 | 0.023 | 0.013 – 0.038 | 76 – 125 | no, lower |
| `navic_s_esp32c3` | 4 | 720 000 | 0.01 | 1 | 0.001 | 0.000 – 0.007 | 3 – 19 | no, lower |

The equal counts for B = 1 and B = 4 in the same scenario (83 and 83, 23 and 23) are a
coincidence: the trials that raise a false alarm are different. In a check of 300 trials of
`navic_s_ideal` (seeds 0 to 299, the first 300 of the 1000), 29 trials exceeded the threshold with B = 1 and 25 with B = 4, and only 5 of
those trials exceeded it in both cases.

## Discussion

**`navic_s_ideal` (8 samples per chip):** all four measured rates are inside the 99 % interval
around the configured `pfa`. At `pfa` = 0.1 the measured rate, 0.083, is on the low side, but
the difference is not significant with 1000 trials.

**`navic_s_esp32c3` (about 78 samples per chip):** all four measured rates are far below the
configured `pfa`, outside the 99 % interval. At `pfa` = 0.1 the rate is 0.023, about a quarter
of the configured value (99 % CI 0.013 – 0.038). At `pfa` = 0.01 the rate is 0.001 to 0.002.
The deviation is in the conservative direction: the threshold is higher than it needs to be
for the configured `pfa`. This does not cause wrong detections, but it costs sensitivity,
because a weaker signal would have been detected with a threshold that gave the configured
`pfa`. How much sensitivity is lost has not been measured.

**Hypothesis (not verified):** the threshold treats all `n_cells` cells as independent. When
there are many samples per chip, neighbouring code-phase lags give almost the same correlation
value: the correlation of a lag with its neighbour one sample away falls off only by about one
part in 78 at 80 MSa/s, compared with one part in 8 at 8.184 MSa/s. The number of cells that
behave independently is then smaller than `n_cells`, and a per-cell probability of
`pfa / n_cells` gives an overall false-alarm rate below `pfa`.

The size of the effect does not follow the number of samples per chip directly. For
`navic_s_esp32c3` the ratio of measured rate to configured `pfa` is about 0.23 at `pfa` = 0.1
(and 0.1 to 0.2 at `pfa` = 0.01, where the counts are small). That is consistent with a grid
behaving like one with about a quarter of `n_cells` independent cells, not with one
independent cell per chip, which would predict a ratio of about 1/78 ≈ 0.013. For
`navic_s_ideal` the ratio is 0.83 at `pfa` = 0.1 and 1.0 to 1.3 at `pfa` = 0.01; this is
consistent with a small effect or none, and would predict 1/8 ≈ 0.125 under one independent
cell per chip.

Other factors differ between the two scenarios and have not been separated: 10-bit
quantization with AGC and the 12 ppm clock error in `navic_s_esp32c3`, the number of frequency
bins (as few as 9), and the snapshot being shorter than one code period, so that the searched
lags cover a full code period while each correlation uses only about a fifth of it. TODO:
repeat `navic_s_esp32c3` without quantization, and at a lower sample rate with the same
snapshot duration, to see which factor causes the deviation.

The threshold formula in `rx/acquisition.py` was not changed. A possible follow-up is to
replace `n_cells` in the threshold with an effective number of independent cells. How that
number depends on the sample rate, the snapshot length and the number of blocks is not known
yet and would need its own measurement; the simple rule of one independent cell per chip is
ruled out by the numbers above.

## Automated check

`tests/test_false_alarm.py::test_false_alarm_rate_ideal_4_blocks` repeats a smaller version of
this measurement: `navic_s_ideal`, B = 4, `pfa` = 0.1, 300 trials with noise seeds 100 000 to
100 299, and checks that the count of false alarms lies inside
`scipy.stats.binom.interval(0.99, 300, 0.1)`, which is 17 to 44. It carries the `slow` marker
and only runs with `pytest -m slow -q` (about 12 s). This condition was chosen because it
agreed with theory above and is the fastest of the four.

## How to reproduce

```bash
pip install -e ".[dev]"
python tests/test_false_alarm.py      # prints the results table; takes several minutes
pytest -m slow -q                     # the automated check
```
