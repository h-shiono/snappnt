# LEO Doppler rate and the Doppler-rate search

This page states how fast the Doppler shift of a low-Earth-orbit (LEO) satellite changes, how
much coherent integration loses when that change is ignored, and from which coherent
integration time a Doppler-rate search is needed (GitHub issue #16). All numbers come from a
simple pass model and from simulated snapshots; none is a measurement of hardware.

## Terms

- **Doppler rate**: time derivative of the carrier Doppler shift, in Hz/s.
- **Coherent time T**: length of one coherent integration in `acquire`, in seconds (the
  snapshot length divided by `n_blocks`).
- **Rate error e**: true Doppler rate minus the rate hypothesis used by the receiver, in Hz/s.
- **Rate-mismatch loss**: power of the correlation peak with a rate error, relative to the peak
  with the true rate, in dB (positive means a loss). The frequency bin is the best one.
- **Closest approach**: the moment of the shortest distance between satellite and receiver
  during a pass. Pass time is zero there and negative before it.

## Pass model

`snappnt.sim.leo.leo_pass_doppler(carrier_hz, altitude_m, max_elevation_deg, time_s)`:

- circular orbit of radius R + h with R = 6371 km, orbital angular rate sqrt(μ / (R + h)³),
  μ = 3.986004418·10¹⁴ m³/s²;
- spherical, non-rotating Earth, no atmosphere, receiver on the surface;
- the maximum elevation fixes how far the receiver is from the orbital plane;
- Doppler = −f · dρ/dt / c and Doppler rate = d(Doppler)/dt, with slant range ρ.

A scenario uses it with `pass: {altitude_m, max_elevation_deg, time_s}` in a satellite entry
(see `scenarios/cband_leo_overhead.yaml`). Giving `pass` together with `doppler_hz` or
`doppler_rate_hzps` is an error.

Model output at the carrier of the C-band placeholder signal (5020 MHz), overhead pass
(maximum elevation 90°):

| Altitude | Largest Doppler (at the horizon-side end of ±200 s) | Largest Doppler rate (closest approach) |
|---|---|---|
| 300 km | 123 kHz | 3185 Hz/s |
| 550 km | 113 kHz | 1614 Hz/s |
| 1200 km | 82 kHz | 618 Hz/s |

The rate at 550 km is 1.6 kHz/s, not the rounded 1.7 kHz/s quoted in the issue; the test
accepts 1.7 kHz/s within 10 %. For a pass with a maximum elevation of 30° the largest rate is
887 Hz/s: the closer the pass is to overhead, the faster the Doppler changes.

## Rate-mismatch loss

With frequency matched at the middle of the integration, a rate error e leaves the phase
π·e·t² for t from −T/2 to T/2. The normalised coherent sum is (C(x)² + S(x)²) / x², where C and
S are the Fresnel integrals and x = (T/2)·sqrt(2·|e|). The loss is the negative of its value in
dB (`rate_mismatch_loss_db`).

Loss in dB for a rate error equal to the whole rate (that is, a receiver that assumes zero
rate). The table is in [leo_doppler_rate.csv](leo_doppler_rate.csv).

| T (ms) | e = 100 Hz/s | 200 Hz/s | 500 Hz/s | 1000 Hz/s | 1614 Hz/s |
|---|---|---|---|---|---|
| 1 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| 2 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| 4 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| 8 | 0.000 | 0.000 | 0.000 | 0.001 | 0.003 |
| 16 | 0.000 | 0.001 | 0.004 | 0.016 | 0.041 |
| 32 | 0.002 | 0.010 | 0.062 | 0.251 | 0.657 |
| 64 | 0.040 | 0.160 | 1.015 | 4.243 | 10.347 |
| 128 | 0.646 | 2.663 | 10.311 | 12.758 | 13.300 |

Coherent time at which the loss reaches 1 dB, and 3 dB:

| Rate error (Hz/s) | 1 dB at T = | 3 dB at T = |
|---|---|---|
| 100 | 143 ms | 186 ms |
| 200 | 101 ms | 132 ms |
| 500 | 64 ms | 83 ms |
| 1000 | 45 ms | 59 ms |
| 1614 | 35 ms | 46 ms |

Check against simulated snapshots (`tests/test_leo_doppler.py`): at T = 40 ms, true rate
−1572 Hz/s (the 550 km overhead pass 10 s before closest approach), C/N0 50 dB-Hz and a
frequency step of 1/(8T), the peak power with the true rate is 1.62 dB above that with rate zero.
The formula gives 1.54 dB. The test accepts a difference of 0.3 dB; the remaining difference is
partly the noise-floor estimate in the metric.

## Doppler-rate search

`acquire(..., rate_range_hzps=(low, high), rate_step_hzps=step)` computes the complete
frequency–lag power grid for each rate hypothesis and takes the largest cell. Without
`rate_range_hzps` there is one hypothesis, `doppler_rate_hzps`, as before, and the results are
unchanged. `n_cells` counts the rate hypotheses, so the false-alarm probability over the whole
search stays `pfa`; the threshold rises accordingly. `AcqResult.doppler_rate_hzps` is the rate
of the peak cell and `rate_step_hzps` the step used (0 for a single hypothesis). The cost grows
in proportion to the number of rate hypotheses.

The hypotheses lie inside the range, both ends included, and are evenly spaced with a spacing
of at most the requested step. A reversed range or a step that is not positive raises
`ValueError`. The default step is 1 / (4·T²) for one block. With `n_blocks` > 1 all blocks
share one frequency bin, and a rate error also moves the carrier by up to half of
(error × snapshot length) either side of the middle of the snapshot; the default step is then
the smaller of 1 / (4·T²) and 1 / (2·T·T_snapshot), which keeps that movement below a quarter
of a bin width at the edge of a step. For one block only the first term applies. At a rate error of half that step the formula gives a loss of
0.004 dB for every T, so the default is finer than needed; a step of 1 / T² would still
leave a loss of only about 0.06 dB at the edge of a step (from the formula, not simulated).

Example (`tests/test_leo_doppler.py`): 80 ms snapshot, C/N0 34 dB-Hz, true rate −1572 Hz/s,
frequency range ±80 Hz around the Doppler. With rate zero the peak metric is 40 against a
threshold of 18.5. With a rate search over −1900 to −1300 Hz/s (spacing 37.5 Hz/s) the metric is 136
(5.3 dB higher), and the peak rate is −1637.5 Hz/s. The peak is flat near the true rate, so the
test accepts a rate within two steps of the truth.

## From which coherent time a rate search is needed

Criterion: a loss above 1 dB when the rate is ignored. For the 550 km overhead pass, where the
rate is at most 1.6 kHz/s, this is T above about **35 ms**. At 16 ms the loss is 0.04 dB and at
8 ms it is below 0.01 dB, so for the snapshots of a few milliseconds used so far (ESP32:
0.2 ms to a few ms) a rate search is not needed. For lower rates the limit is later (45 ms at
1 kHz/s, 64 ms at 500 Hz/s). Above 64 ms a search is needed for every pass in the table.

## Decisions and assumptions

- **Spherical, non-rotating Earth, no atmosphere.** The rotation of the Earth changes the
  speed of the receiver relative to the orbit by at most about 0.46 km/s of about 7.6 km/s, a
  change of up to about 6 % in speed and up to about 12 % in rate (the rate is proportional to
  the speed squared; estimate, not computed). The 1 dB limit moves by about half that
  fraction, so it stays at a few tens of milliseconds and the conclusion above does not change. The
  atmosphere (refraction) is negligible for the geometry of the Doppler at 5 GHz (assumption,
  not checked).
- **Rate step 1 / (4·T²)** is a conservative estimate chosen so that the loss at a step edge
  is negligible; it is an estimate, not an optimum.
- **1 dB criterion** for "a rate search is needed" is a choice; the table gives the times for
  3 dB too.
- **Coherent sum only.** The loss is for one coherent block. With `n_blocks` > 1 each block has
  its own T, and the rate error then also shifts the frequency from block to block; the blocks
  are combined in power, and this case is not evaluated here.
- **Placeholder signal.** The C-band signal has no public ICD; its parameters are placeholders.

## Reproduce

```bash
pytest tests/test_leo_doppler.py -q
python - <<'PY'
from snappnt.sim.leo import rate_mismatch_loss_db
for t_ms in (1, 2, 4, 8, 16, 32, 64, 128):
    print(t_ms, [round(rate_mismatch_loss_db(t_ms * 1e-3, e), 3) for e in (100, 200, 500, 1000, 1614)])
PY
```
