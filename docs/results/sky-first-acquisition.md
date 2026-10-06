# First NavIC S-band acquisition from the sky

This page records the first reception of the NavIC S-band Standard Positioning Service (SPS)
signal from the sky (GitHub issue #74). A B210 clone recorded 32 s of samples through an
external LNA and a small 2.4 GHz whip antenna. The recording was acquired afterwards with
`snappnt` commands. PRN 10 and PRN 7 are acquired with `snappnt` alone. PRN 5 was acquired
only after narrow interference lines were removed with a step that `snappnt` does not have
yet, so it is listed here as not reproduced.

The receiver position, the place, the satellites' azimuth and elevation, and the code phases
are not recorded on this page, because together they would reveal where the receiver was
([Public-safety rules](../development/public-safety.md)). The recording itself is not
published.

A later, preliminary acquisition with an ESP32-C5 behind a 45 cm dish is on
[NavIC S-band from the sky on an ESP32-C5 (preliminary)](sky-esp32c5-preliminary.md).

Terms used on this page:

- *C/N0:* carrier-to-noise density ratio in dB-Hz.
- *Carrier offset:* the frequency of the received carrier minus 2492.028 MHz, as seen by the
  receiver. It contains the satellite's Doppler, the satellite's oscillator error and the
  receiver's clock error.
- *Block:* 4 ms of samples, correlated coherently. With 250 blocks (1 s) the block results are
  added in power (non-coherent integration).
- *Bin:* the frequency step of the search, 1/(2 × 4 ms) = 125 Hz.
- *Detection metric:* the largest correlation power of the search grid divided by the mean
  power of the other cells. *Threshold:* the metric above which a cell counts as a detection,
  set so that the probability of any false peak over the grid is `pfa` = 1e-3 when the noise is
  white (`snappnt.rx.acquire`).
- *Code-Doppler compensation* (`--code-doppler`): the replica's chip rate is scaled by
  1 + (carrier offset / 2492.028 MHz), so that the code does not slide out of alignment over a
  1 s integration (see [Architecture](../design/architecture.md)).

## Setup

The setup as stated by the maintainer; none of it was checked from the recording except
the tune frequency, the sample rate and the length. The order of the chain (whip, LaNA, cable,
B210 clone) is assumed in the link budget below.

| Item | Value |
|---|---|
| Date | 2026-10-04 |
| Antenna | Small vertical 2.4 GHz whip (linear polarisation), no filter |
| LNA | Nooelec LaNA, powered from a battery, directly after the antenna |
| Receiver | B210 clone (AD9361), recorded with GQRX's I/Q recorder |
| Receiver settings | Hardware tune frequency 2489.9995 MHz, 8 MSa/s, GQRX "Bandwidth" 8 MHz, PGA gain 40 dB |
| Connection | B210 clone connected directly to the computer by USB, without a hub |
| Recording | 255 673 405 complex samples (31.96 s), 32-bit float |

NavIC S-band SPS is at +2.0285 MHz in this recording's baseband: 2492.028 − 2489.9995 MHz.

## Commands

GQRX writes complex 32-bit floats and puts the hardware tune frequency and the sample rate in
the file name (`gqrx_<date>_<time>_<frequency>_<rate>_fc.raw`). The file was converted to
SigMF and then acquired:

```bash
uv run snappnt convert gqrx_<date>_<time>_2489999500_8000000_fc.raw -o out/sky/rec \
    --format uhd-float --rate-sps 8e6 --freq-hz 2489999500 --device "B210 clone (AD9361)"

# Search of all PRNs, 1 s starting at 1 s
uv run snappnt acquire out/sky/rec --signal navic_s_sps --prn 1-14 --center 2028500 \
    --code-doppler --freq-span 30000 --start-s 1 --duration-s 1 --blocks 250

# Noise-only reference: NavIC L5 codes, which are not transmitted at S band
uv run snappnt acquire out/sky/rec --signal navic_l5_sps --prn 5,7 --center 2028500 \
    --code-doppler --freq-span 30000 --start-s 1 --duration-s 1 --blocks 250

# PRN 10 with 0.2 s
uv run snappnt acquire out/sky/rec --signal navic_s_sps --prn 10 --center 2028500 \
    --code-doppler --freq-span 30000 --start-s <t> --duration-s 0.2 --blocks 50

# Drift and sample-drop check: 1 s windows starting at 1, 3, ..., 27, 28, 29, 30 s
uv run snappnt acquire out/sky/rec --signal navic_s_sps --prn 5,7,10 --center 2028500 \
    --code-doppler --freq-span 15000 --start-s <t> --duration-s 1 --blocks 250
```

`--center 2028500` puts the search around 2492.028 MHz. No preprocessing was applied: no
notch, no frequency shift, no decimation and no removal of narrow lines. The threshold printed by
`snappnt acquire` is 1.4 for 1 s (1.444 with ±30 kHz, read from `snappnt.rx.acquire`) and 2.1
for 0.2 s.

Options used:

- `--code-doppler` (GitHub issue #72) scales the replica's chip rate with the frequency bin, in
  groups of bins. It assumes direct reception, with one clock for the LO and the sample clock,
  as with the B210 clone here. `snappnt acquire` refuses it when the recording's frequency plan
  has an external LO, because an LO error then moves the carrier without changing the code rate.
- `--start-s` and `--duration-s` (GitHub issue #73) select a segment of the recording. The
  reported code phase refers to the first sample of that segment, not of the file. For a
  simulated recording, the truth is compared only when the segment starts at the first sample.
- Frequency refinement was off (`refine=False`, the default of `snappnt acquire`). Carrier
  offsets are therefore reported on the 125 Hz bin grid, and code phases on the sample grid.

## Results

### The threshold does not hold on this recording

With 1 s starting at 1 s, all 14 S-band PRNs give a metric above the threshold of 1.444: from
1.5 to 2.0 for the PRNs other than 10 and 7. So do the two NavIC L5 codes used as a noise-only
reference, each with a metric of 1.8. A detection decided by the threshold alone therefore
means nothing on this recording. The threshold assumes white noise.

*Inference, not checked:* the recording contains narrow interference lines. The replica
spreads a line over the search grid, and this power does not average down over the blocks,
so the largest cell of a noise-only search exceeds the threshold.

The PRN 10 and PRN 7 results below are judged against the noise-only level of 1.8 instead, and
by their consistency over the recording.

### PRN 10 and PRN 7

Seventeen 1 s windows (±15 kHz) between 1 s and 31 s:

| PRN | Carrier offset (125 Hz bin) | Metric | Estimated C/N0 | Satellite |
|---|---|---|---|---|
| 10 | +9500 Hz in every window | 6.9 to 13.8 | 31.7 to 35.1 dB-Hz | NVS-01 (secondary sources) |
| 7 | +6250 Hz in every window | 2.8 to 5.6 | 26.6 to 30.6 dB-Hz | IRNSS-1G (inferred, not verified) |

- **PRN 10 is far above the noise-only level** in every window, and with 0.2 s (50 blocks) as
  well: metric 7.8 to 11.1 against a threshold of 2.1, in windows starting at 5, 10, 15, 20
  and 25 s.
- **PRN 7 is lower but consistent.** Its metric is 1.5 to 3 times the noise-only level, its
  carrier offset stays in the same bin in all 17 windows, and its code phase follows the
  predicted drift ("Per-window results" below). A single window alone would be weak
  evidence; the 17 together are not consistent with noise.
- **Not explained:** PRN 10 with 0.2 s starting at 0.5 s gives a carrier offset of +7750 Hz,
  against +9500 Hz in every other window. A disturbance in the first second of the
  recording (receiver settling, or an earlier sample drop) is an inference, not checked.

Satellites: PRN 10 is NVS-01 according to secondary sources only
([Wikipedia](https://en.wikipedia.org/wiki/NVS-01),
[SatNow](https://www.satnow.com/gnss-constellation-details/irnss/nvs-01)). PRN 7 is IRNSS-1G by
inference from a sky-plot application and TLE positions, not verified.

### Estimated C/N0 and its bias

The C/N0 estimate is 10·log10((metric − 1) / T) with T = 4 ms
([Bias of the C/N0 estimate](cn0-bias.md)). That page measured the bias of this estimate in
simulation for 1 and 4 blocks at 45 dB-Hz, not for 250 blocks near 30 dB-Hz; the bias is not
known for this condition. Causes it lists that apply here:

- the carrier offset lies up to half a bin from a bin centre, because the search is not
  refined (up to −0.8 dB in that simulation);
- a navigation symbol edge (50 symbols/s, every 20 ms) can fall inside a 4 ms block (the
  block with the edge loses part of its peak).

Both make the estimate read low. On this recording, the noise-floor estimate is also not that of
white noise (previous section); how that moves the C/N0 estimate was not measured. The
estimates above are therefore estimates of unknown bias, not measurements.

### Code drift

With one clock for the LO and the sample clock, a carrier offset f comes with a code-rate
change of f / 2492.028 MHz relative to the sample clock. The code phase therefore drifts by
(f / 2492.028 MHz) × 1.023 Mchip/s: 3.90 chip/s for PRN 10 and 2.57 chip/s for PRN 7, using the
bin centres above.

The code phases found in the windows starting at 1 to 27 s were compared with this drift from
the first window. The largest deviation is 0.004 chip for PRN 10 and 0.12 chip for PRN 7. Both
are below one sample (0.128 chip at 8 MSa/s), which is the resolution of the reported code
phase, since `snappnt acquire` does not interpolate between samples. The smaller value for
PRN 10 is not a finer resolution: its drift over 2 s, 7.80 chips, happens to be close to a
whole number of samples (61).

### Per-window results

All windows are 1 s (250 blocks of 4 ms), searched over ±15 kHz with code-Doppler compensation.

- *Bin* is the carrier offset of the grid peak.
- *Deviation* is the code phase found minus the code phase predicted from the window starting at
  1 s and the drift above, in chips. It is relative to that first window, so it shows no
  absolute code phase.
- PRN 5 is listed for comparison: its bin is not stable from window to window.

| Window start [s] | PRN 10 bin [Hz] | PRN 10 metric | PRN 10 deviation [chip] | PRN 7 bin [Hz] | PRN 7 metric | PRN 7 deviation [chip] | PRN 5 bin [Hz] | PRN 5 metric |
|---|---|---|---|---|---|---|---|---|
| 1 | +9500 | 10.7 | +0.00 | +6250 | 3.6 | +0.00 | +11625 | 2.0 |
| 3 | +9500 | 11.1 | +0.00 | +6250 | 3.8 | −0.02 | +11625 | 1.6 |
| 5 | +9500 | 11.0 | +0.00 | +6250 | 3.3 | −0.03 | +11625 | 1.5 |
| 7 | +9500 | 12.6 | +0.00 | +6250 | 4.3 | −0.05 | +11625 | 1.6 |
| 9 | +9500 | 11.7 | +0.00 | +6250 | 4.2 | −0.07 | +11625 | 1.5 |
| 11 | +9500 | 13.6 | +0.00 | +6250 | 4.7 | −0.09 | +11625 | 1.5 |
| 13 | +9500 | 12.4 | +0.00 | +6250 | 5.2 | −0.10 | +6000 | 1.5 |
| 15 | +9500 | 10.6 | +0.00 | +6250 | 3.9 | −0.12 | +3000 | 1.4 |
| 17 | +9500 | 12.5 | +0.00 | +6250 | 4.3 | −0.00 | +3000 | 1.5 |
| 19 | +9500 | 9.9 | +0.00 | +6250 | 3.5 | −0.02 | +14000 | 1.5 |
| 21 | +9500 | 11.8 | +0.00 | +6250 | 4.5 | −0.03 | +14000 | 1.5 |
| 23 | +9500 | 8.9 | +0.00 | +6250 | 3.4 | −0.05 | +6000 | 1.4 |
| 25 | +9500 | 9.0 | +0.00 | +6250 | 3.4 | −0.07 | +3000 | 1.4 |
| 27 | +9500 | 6.9 | +0.00 | +6250 | 2.8 | −0.09 | +3000 | 1.5 |
| 28 | +9500 | 9.4 | +323.72 | +6250 | 3.0 | +323.69 | +6000 | 1.4 |
| 29 | +9500 | 11.6 | +323.78 | +6250 | 3.6 | +323.68 | +3000 | 1.4 |
| 30 | +9500 | 13.8 | +323.72 | +6250 | 5.6 | +323.68 | +11625 | 1.6 |

The PRN 7 deviation falls step by step to −0.12 chip and returns to 0 at 17 s. This sawtooth is
what one-sample resolution gives. The predicted drift over 2 s is 5.13 chips, or 40.1 samples,
while the reported code phase moves in whole samples. The deviation therefore grows by about
0.1 sample per window, until the reported code phase moves by one sample more. For PRN 10 the
drift over 2 s is 60.98 samples, close to a whole number, so its deviation stays near 0.

This check does not tell a satellite oscillator error from a receiver clock error: both change
the carrier and the code rate in the same ratio.

### Sample drop

In the windows starting at 28, 29 and 30 s, the code phase of both PRNs is ahead of the
predicted drift by the same amount, 323.68 to 323.79 chips. The window starting at 27 s is
still on the earlier track, with a lower metric than its neighbours (PRN 10: 6.9). The drop
therefore lies between 27 s and 28 s of the recording.

*Inference:* a jump shared by all PRNs is a property of the recording, not of a satellite:
samples were lost. 323.7 chips is 316.4 µs, or about 2531 samples at 8 MSa/s, plus an unknown
whole number of code periods (8000 samples each).

### PRN 5 and the noise-only reference: not reproduced with `snappnt` alone

- **With narrow-line removal before acquisition,** PRN 5 was detected in a local analysis, and
  the noise-only reference stayed below the threshold. That removal zeroes the bins of the
  power spectral density (PSD) that are more than 3 dB above a running median.
- **With `snappnt acquire` on the raw recording,** PRN 5's grid peak lies at the expected
  carrier offset and on the expected code track in several windows. Its metric of 1.4 to 2.0
  overlaps the noise-only level, so it is not claimed as a detection.
- **Which step matters:** the same 1 s segment was acquired with `snappnt.rx.acquire` after
  each preprocessing step alone.
  - Line removal (837 of 65 536 bins) brings both L5 noise-only codes to 1.38 to 1.39, below
    the threshold of 1.444.
  - A notch of 2493–2494 MHz and of ±0.2 MHz around the tune frequency does not: 1.79 to 1.82.
  - A frequency shift and decimation change only the centre and the sample rate; `--center`
    already covers the shift.
  - One residual remains: S-band PRN 2 stays slightly above the threshold with line removal at
    8 MSa/s (1.456). Whether band-limiting before decimation also matters is not settled.

The missing step, removing narrow lines or estimating the noise floor robustly, is GitHub
issue [#80](https://github.com/h-shiono/snappnt/issues/80). PRN 5 is IRNSS-1E per
[IGSMAIL-7272](https://lists.igs.org/pipermail/igsmail/2016/001106.html).

## Earlier attempts

Earlier recordings gave no detection. What was observed, and what is inferred:

- **Observed:** with the GQRX "Bandwidth" setting at 0, outside signals (Wi-Fi bursts)
  appeared only in a narrow part of the band around the tune frequency. With 8 MHz they
  filled the whole band. *Inferred, not checked* against the UHD or AD9361 documentation: with
  0, the analog low-pass filter was set to its minimum and cut off the NavIC signal, which lies
  2 MHz from the tune frequency.
- **Observed:** with the B210 clone connected through a USB hub, a comb of evenly spaced narrow
  lines appeared in the spectrum. It disappeared when the B210 clone was connected directly to
  the computer.
- **Observed:** a horizontal rod antenna gave no detection with 1 s, with or without the LNA.
  The cause is not known.

## Comparison with the link budget

The link budget of the [Sky test plan](../guides/sky-test-plan.md) was computed for this
chain with `tools/sky_link_budget.py`, using these assumptions:

- antenna gain −1 dBic: about 2 dBi for a linear whip, minus 3 dB for linear polarisation
  against the RHCP signal;
- antenna temperature 100 K;
- LNA gain 20 dB and noise figure 1.0 dB (assumed: the LaNA product page gives no gain or
  noise figure at 2.5 GHz);
- 1 dB of cable;
- receiver noise figure 5, 10 or 15 dB.

```bash
uv run python tools/sky_link_budget.py --received-power-dbw -162.3 \
    --antenna-gain-dbic -1 --antenna-temp-k 100 --stage lna:20:1.0 --stage cable:-1:1 \
    --receiver-nf-db 5 10 15
```

| Received power | Receiver NF 5 dB | 10 dB | 15 dB |
|---|---|---|---|
| −162.3 dBW (ICD minimum) | 42.7 | 42.1 | 40.7 |
| −157.3 dBW (ICD maximum) | 47.7 | 47.1 | 45.7 |

C/N0 in dB-Hz.

The estimated C/N0 of PRN 10, 31.7 to 35.1 dB-Hz, is 6 to 11 dB below the ICD-minimum row,
and that of PRN 7 is lower still. Bias of the estimate (above) explains part of this at most.
Possible causes, none checked:

- the whip's gain towards the satellite, which depends on the elevation and on the whip's
  pattern;
- the actual gain and noise figure of the LaNA at 2.5 GHz, and the B210 clone's noise figure;
- strong signals in the 2.4 GHz band reaching the receiver with no band-pass filter;
- the received power at the test site, which the ICD does not guarantee outside the coverage
  area (TODO in "The signal" of the Sky test plan).

TODO: settle with a measured antenna gain, a measured receiver noise figure, or a reference
recording through a band-pass filter.

## Not verified

- The satellite behind PRN 7 (IRNSS-1G is inferred) and behind PRN 10 (NVS-01 per secondary
  sources only).
- The bias of the C/N0 estimate for 250 blocks of 4 ms on a recording with narrow lines.
- PRN 5 with `snappnt` commands alone (pending GitHub issue #80 on narrow lines).
- The cause of the different carrier offset of PRN 10 in the 0.2 s window starting at 0.5 s.
