# Architecture

## Data flow

```
                 ┌──────────── signals (what is transmitted) ─────────────┐
                 │ catalog/*.yaml  +  codes/ (spreading-code generators)   │
                 └───────────────┬─────────────────────────────────────────┘
                                 │
 scenarios/*.yaml ──▶ sim ──▶ SigMF (samples + truth annotation) ──▶ rx (acquisition) ──▶ eval (compare with truth)
                       │                                               ▲
                       └─▶ playback file (int8 / sc16)                 │
                              │                                        │
                              ▼ (a person transmits, cables only)      │
                         generator ─▶ attenuators ─▶ ESP32 ──▶ SigMF (no truth)
                                                   frontend (device limits, frequency plan)
```

The acquisition code (`rx`) does not know whether a SigMF file came from the simulator or from
an ESP32. Both arrive in the same format. Files from the simulator also carry a `truth`
annotation, which `eval` uses for automatic checks.

## Three layers kept apart

The layers are separated so that adding a new signal or a C-band front end changes one place
only.

### 1. Signal definition (`signals`)

A YAML file per signal lists the carrier frequency, chip rate, code length, modulation, data
symbol rate and whether there is a pilot component. The spreading code is produced by the
generator registered under the file's `code_family` name.

Adding a signal takes one YAML file, one generator and one test that compares the generator
with values printed in the ICD (see `.claude/commands/add-signal.md`).

### 2. Front end and frequency plan (`frontend`)

Device files record hardware limits: sample rates, ADC bits, and the largest number of samples
one capture can hold. `freqplan.py` converts between the frequency at the antenna and the
frequency the receiver is tuned to, including an optional external mixer.

If the mixer's local oscillator (LO) is above the signal frequency, the spectrum is mirrored at
the intermediate frequency and a positive Doppler shift at the antenna appears as a negative
shift in the samples. `FrequencyPlan.doppler_sign` expresses this.

A scenario can carry a frequency plan (`frequency_plan` in the scenario YAML). The simulator
then mirrors the Doppler shift for a high-side LO, applies the external LO error
(`lo_offset_ppm`) separately from the receiver crystal error, and takes `baseband_offset_hz`
from the plan, so acquisition needs no other input. See decision D-013.

### Receiver impairments in the simulator

Optional keys under `receiver` in a scenario YAML; without them the output of a scenario is
unchanged (a test compares the samples of every scenario in `scenarios/` with stored hashes).

| Key | Meaning |
|---|---|
| `dc_offset: {i, q}` | Constant offset of each component as a fraction of ADC full scale (−0.5 on I with 10 bits is −256 counts). Each value must be in [−1, 1). Needs `quantization_bits`. |
| `spurs: [{offset_hz, power_db}]` | Fixed tones. `offset_hz` is the offset from the tuned frequency in the samples, and must be inside ±half of the rate at which samples are generated. `power_db` is the tone power divided by the total noise power per sample at the generation rate (noise has unit variance); it is not the height above the noise floor in a spectrum, where a tone of power ratio 1 stands `10·log10(N)` dB above the floor of one bin in an N-point spectrum. |

Processing order: signal and noise at the generation rate, then spurs, analog low-pass,
output-band low-pass (decimation method `ideal`), decimation, and the ADC. With a generation rate
(`generate_rate_hz`), a spur outside the analog bandwidth is removed; without one, the analog
bandwidth has no effect and the spur stays. A spur outside the output band folds to an aliased frequency when
the decimation method is `none`. The DC offset is added in the ADC after the gain of the
automatic gain control (AGC) is set from the signal alone, so the offset is not part of the
level the AGC holds. The offset is constant over a snapshot; the drift of about 25 counts
within one 205 µs capture seen on an ESP32-C3 is not modelled. Spur phases come from a random
generator separate from the one for noise and data symbols. See decision D-016.

### 3. Data format (`io`)

Recordings use SigMF: a raw sample file plus a JSON metadata file. The simulator's truth is
stored in an annotation whose `core:label` is `truth`, under the key `snappnt:truth`.

## Acquisition (`rx/acquisition.py`)

- An ESP32 at 80 MSa/s captures about 0.2 ms, shorter than one NavIC code period (1 ms).
  The snapshot is therefore correlated against a local code replica that is one code period
  plus one snapshot long. The correlation lag tells where in the code period the snapshot
  started. All lags are computed at once with FFTs.
- The carrier frequency is searched by repeating the correlation over a grid of frequency
  offsets. The default grid step is 1 / (2 × coherent integration time).
- With `n_blocks` greater than 1, the snapshot is split into blocks that are correlated
  separately and added in power (non-coherent integration). This tolerates data-bit sign
  changes and a coarse frequency grid, at some cost in sensitivity.
- The detection threshold is set so that, with noise only, the probability of a false peak
  anywhere in the search grid equals `pfa`. It assumes independent search cells; issue #1
  checks this assumption by measurement.
- The C/N0 estimate ignores losses and therefore reads low. Issue #4 measures the bias.
- Code Doppler (option `code_doppler`, command-line `--code-doppler`). By default one code
  replica at the nominal chip rate serves every frequency bin. In direct reception, one crystal
  drives both the LO and the ADC, so a carrier offset Δf (from satellite Doppler and from the
  receiver clock error together) comes with a change of the code rate, relative to the sample
  clock, of Δf / f_c, where f_c is the carrier frequency. Over a snapshot of length T the code
  drifts by Δf / f_c × R_c × T chips, where R_c is the nominal chip rate. For NavIC S-band at
  Δf = 25 kHz and T = 0.2 s this is about 2 chips, which spreads the correlation peak over
  several lags. With the option on, the frequency bins are split into groups of neighbouring
  bins, and each group uses a replica with chip rate R_c × (1 + f_g / f_c), where f_g is the
  middle of the group measured from the centre frequency of the search. A group is at most
  2 × 0.1 × f_c / (R_c × T) wide, so the code drift left over within a group stays below
  0.1 chip. For a snapshot of a few milliseconds all bins fall into one group. The groups are
  processed one at a time (with a Doppler-rate search, all rate hypotheses inside each group),
  so only one group's replica spectra are in memory. The code phase is converted from the lag
  with the chip rate of the group that holds the peak. The decision and the alternatives are
  in D-023 of the [decision log](../project/decisions.md).
- The option assumes direct reception. With an external mixer the offset at the receiver also
  contains the error of the external LO, which shifts the IF without changing the code rate.
  `snappnt acquire` and `snappnt sweep` therefore stop with an error when the truth annotation
  or the scenario has a frequency plan with `lo_hz`. A recording without a truth annotation
  carries no frequency plan, so the check cannot be made, and the option is applied as for
  direct reception.

## Terms used in this project

| Term | Meaning |
|---|---|
| Snapshot (capture) | One block of I/Q samples that a device writes to memory in one go. Not a continuous stream. |
| Code phase | The chip position in the spreading code at the first sample of the snapshot, in chips. |
| Frequency offset | How far the carrier is from the centre frequency set by the frequency plan (`baseband_offset_hz`). It is the sum of the Doppler shift and the receiver's crystal error. |
| Truth | The parameter values the simulator used to generate a snapshot, stored for comparison. |
| Conducted test | A test in which the generator is connected to the receiver through cables and attenuators, so no signal is radiated. |
