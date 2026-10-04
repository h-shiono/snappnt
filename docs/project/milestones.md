# Milestones

Publication plan: the repository is made public after milestone M3 (conducted test), once the
publication checklist (issue #12) is done.

Each milestone has a matching GitHub milestone; the issues listed there are the source of
truth for open work. This page records what each milestone is for and what has been reached.

## M1 Signal definitions and data format — done in the initial skeleton

- [x] NavIC S and L5 SPS code generators, checked against ICD Table 7
- [x] GPS L1 C/A codes, used to check the shared shift-register code
- [x] SigMF read and write, with a truth annotation
- [x] CI: ICD checks, simulate-acquire-compare loop, command-line smoke test

## M2 Software-only loop

Goal: quantify detection probability, false-alarm rate and loss sources using the simulator
alone.

- [x] Simulator: C/N0, Doppler, crystal error, 10-bit quantisation, capture length
- [x] Acquisition that works on snapshots shorter than one code period
- [x] Detection probability versus C/N0 (`snappnt sweep`)
- [x] Recorded curves for each condition (issue #2). XIAO ESP32C3 condition: 50 % detection
      at 50.2 dB-Hz, 90 % at 52.0 dB-Hz ([Detection probability](../results/pd-curves.md)).
- [x] Measured false-alarm rate (issue #1, [False-alarm rate](../results/false-alarm.md))
- [x] Noise-folding loss at low sample rates (issue #3,
      [Noise-folding loss](../results/aliasing-loss.md)). Whether the ESP32-C61 band-limits at
      low sample rates is still open; see M4.
- [x] C/N0 estimate bias (issue #4, [C/N0 estimate bias](../results/cn0-bias.md))
- [x] Faster acquisition (issue #5)

## M3 Conducted test — condition for going public

Goal: capture with a real XIAO ESP32C3 fed from a generator through cables, and compare with
the M2 curves.

- [x] ESP-SDR tuning and capture in the host client (issue #6)
- [x] `snappnt capture` (issue #8), level calculation and log template (issue #9),
      conversion of reference-receiver recordings (issue #10)
- [x] The test itself (issue #11). With the DC offset removed, the measured curve has the
      simulated slope and lies 0.7 dB to the right of it: 50 % detection at 50.9 dB-Hz, 90 % at
      52.7 dB-Hz
      ([Conducted test (M3)](../results/conducted-m3.md)).
- [ ] Publication checklist (issue #12)

## M4 Longer captures with ESP32-C61

- [ ] How low sample rates and ring-buffer capture work on the C61 (issue #13).
      Early simulation estimate at 4 MSa/s with four 1 ms blocks added non-coherently,
      assuming ideal band limiting: 50 % detection at about 37–38 dB-Hz.

## M5 Acquire NVS-01 from the sky

- [ ] Visibility, link budget and receive chain (issue #14)

## M6 C-band

- [ ] External mixer in the simulated frequency plan (issue #15)
- [ ] LEO Doppler and Doppler rate (issue #16)
