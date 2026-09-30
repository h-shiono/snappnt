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

## Terms used in this project

| Term | Meaning |
|---|---|
| Snapshot (capture) | One block of I/Q samples that a device writes to memory in one go. Not a continuous stream. |
| Code phase | The chip position in the spreading code at the first sample of the snapshot, in chips. |
| Frequency offset | How far the carrier is from the centre frequency set by the frequency plan (`baseband_offset_hz`). It is the sum of the Doppler shift and the receiver's crystal error. |
| Truth | The parameter values the simulator used to generate a snapshot, stored for comparison. |
| Conducted test | A test in which the generator is connected to the receiver through cables and attenuators, so no signal is radiated. |
