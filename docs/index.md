# snappnt

snappnt is a toolkit for receiving satellite navigation signals with very low-cost radios by
**capturing a short burst of samples (a snapshot) and processing it afterwards**.

It pairs a signal simulator with an acquisition engine. The simulator records the true
parameters it used (code phase, frequency offset, C/N0), so every processing step can be
checked automatically against known truth.

!!! note "Status"
    Pre-alpha. Not affiliated with ESPARGOS or Espressif.

## Why snapshots

Some ESP32 chips contain an undocumented debug path that writes raw I/Q samples from the
Wi-Fi radio into internal memory ([ESPARGOS ESP-SDR](https://espargos.net/espsdr/)).
The chip samples at up to 80 MSa/s but can only move a small part of those samples to a host
computer. A continuous receiver is therefore not possible; a receiver that works on isolated
snapshots is.

At 80 MSa/s one 64 KiB memory bank holds about 0.2 ms of samples. That is one fifth of a
NavIC code period (1 ms), so the acquisition in snappnt is written to work with snapshots
shorter than one code period.

## Targets

| Signal | Carrier | Front end | Status |
|---|---|---|---|
| NavIC S-band SPS | 2492.028 MHz | ESP32 (2.4 GHz radio, no mixer) | simulator and acquisition |
| NavIC L5 SPS | 1176.45 MHz | reference only | spreading codes |
| GPS L1 C/A | 1575.42 MHz | reference only | spreading codes (used to validate shared code) |
| C-band LEO-PNT (hypothetical BPSK) | 5010–5030 MHz | ESP32 with an external mixer | placeholder |

## Where to read next

- [Getting started](getting-started.md): install, simulate a snapshot, acquire it.
- [Architecture](design/architecture.md): how the code is organised and why.
- [Conducted test](guides/conducted-test.md): feeding a generated signal into an ESP32 through cables.
- [Milestones](project/milestones.md) and [decision log](project/decisions.md).
