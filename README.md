# snappnt

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.23163934.svg)](https://doi.org/10.5281/zenodo.23163934)

Snapshot PNT receiver toolkit for low-cost front ends.

snappnt pairs a signal simulator with a snapshot acquisition engine, so that short captures
from cheap radios — ESP32 chips running [ESPARGOS ESP-SDR](https://espargos.net/espsdr/),
HackRF, USRP — can be processed and checked against known truth. The first target is the
NavIC S-band Standard Positioning Service signal at 2492.028 MHz, which an ESP32's own 2.4 GHz
radio can receive without a mixer.

> **Status:** research software, early stage. The receive chain has been verified in a
> conducted test (cables and attenuators, nothing radiated). **NavIC S-band SPS has been
> received from the sky with a B210-class SDR**
> ([first sky acquisition](docs/results/sky-first-acquisition.md)). In a preliminary experiment
> with equipment at hand, an ESP32-C5 acquired NavIC S-band PRN 10 from the sky behind a 45 cm
> dish in single 4.1 ms snapshots
> ([preliminary ESP32-C5 result](docs/results/sky-esp32c5-preliminary.md)); a measurement with
> a dedicated feed is being prepared. Not affiliated with ESPARGOS or Espressif.

## What has been shown so far

**Simulation (milestone M2).** Detection probability versus C/N0 for a XIAO ESP32C3-like
receiver (80 MSa/s, a snapshot of about 0.2 ms, 10-bit ADC, 12 ppm crystal): 50 % detection
at 50.2 dB-Hz and 90 % at 52.0 dB-Hz. With the longer captures that the ESP32-C61 allows
(4 MSa/s, about 4 ms), the 50 % point moves to 37.8 dB-Hz with one 4 ms coherent block, or
38.7 dB-Hz with four 1 ms blocks added non-coherently, assuming the chip band-limits at low
sample rates (not yet confirmed). See
[Detection probability versus C/N0](docs/results/pd-curves.md).

**Conducted test (milestone M3).** A B210-class generator played NavIC S-band signals with
noise added in software, through 60 dB of attenuation, into a Seeed XIAO ESP32C3 running the
ESP-SDR firmware; 200 captures were taken at each C/N0. With the DC offset removed before
acquisition, the measured curve has the simulated slope and lies 0.7 dB to the right of it
(50 % at 50.9 dB-Hz, 90 % at 52.7 dB-Hz), and the results page accounts for most of that
difference. See
[Conducted test](docs/results/conducted-m3.md).

![Detection probability of the XIAO ESP32C3 in the conducted test, with and without DC offset removal, over the simulated curve](docs/results/conducted-m3.png)

**First reception from the sky (milestone M5).** A B210-class SDR recorded 32 s through a
battery-powered low-noise amplifier and a small 2.4 GHz whip antenna. `snappnt acquire`, with
1 s of non-coherent integration and code-Doppler compensation, acquired NavIC S-band PRN 10 and
PRN 7 in each of 17 windows of 1 s spread over the recording; PRN 10 was also acquired with
0.2 s. The estimated C/N0 of PRN 10 was 32 to 35 dB-Hz, below the link-budget estimate for that
chain. On this
recording, narrow interference lines made the computed detection threshold invalid; a third
satellite, PRN 5, was acquired only after removing them, a step that snappnt does not have
yet ([issue #80](https://github.com/h-shiono/snappnt/issues/80)). See
[First NavIC S-band acquisition from the sky](docs/results/sky-first-acquisition.md).

**What this means for the sky.** At the minimum received power stated in the NavIC ICD
(−162.3 dBW), a single 0.2 ms capture of the ESP32-C3 is not expected to detect the signal,
even with a low-noise amplifier; a longer coherent snapshot is what the ESP32-C3 lacks. The
ESP32-C61 with a 4 ms snapshot has a few dB of margin with a low-noise amplifier, but only if
it band-limits at low sample rates. A HackRF or USRP with the same antenna and amplifier can
record many milliseconds without gaps; such a receiver made the first reception above. Its
estimated C/N0 of 32 to 35 dB-Hz is below the 50 % point of every simulated ESP32 condition
(37.8 dB-Hz and above), so an ESP32 behind the same antenna and amplifier is not expected to
detect the signal. These are estimates; they and the sky test plan are in
[Sky test plan](docs/guides/sky-test-plan.md).

A preliminary experiment then put a 45 cm dish in front of the amplifier. Behind it, an
ESP32-C5 with 4.1 ms snapshots at 4 MSa/s acquired PRN 10 in single captures; without a
reflector, the C/N0 at its input was about 40.8 to 42.5 dB-Hz
([preliminary ESP32-C5 result](docs/results/sky-esp32c5-preliminary.md)). This does not apply
to the ESP32-C3: a single 0.2 ms capture needs about 50 dB-Hz for 50 % detection, and the
ESP32-C3 has not been shown from the sky.

## Targets

| Signal | Carrier | Front end | Status |
|---|---|---|---|
| NavIC S-band SPS | 2492.028 MHz | ESP32 (2.4 GHz, no mixer) | simulator, acquisition, conducted test; from the sky with a B210-class SDR |
| NavIC L5 SPS | 1176.45 MHz | reference only | codes |
| GPS L1 C/A | 1575.42 MHz | reference only | codes (validation) |
| C-band LEO-PNT (hypothetical BPSK) | 5010–5030 MHz | ESP32 + external mixer | placeholder |

The C-band entry is a generic placeholder. LEO PNT in the 5010–5030 MHz RNSS allocation has
been announced publicly: TrustPoint describes the constellation of navigation microsatellites
that it is deploying in that allocation in
[The Case for LEO GNSS at C-Band](https://insidegnss.com/the-case-for-leo-gnss-at-c-band/)
(Inside GNSS, February 2025, written by TrustPoint staff). No
C-band signal specification is public, so snappnt uses a made-up BPSK signal with random codes
only to exercise the frequency plan (external mixer) and LEO Doppler; it does not model any
real system.

## Quick start

```bash
uv sync
uv run snappnt info
uv run snappnt codes --signal navic_s_sps --prn 1-14
uv run snappnt sim scenarios/navic_s_esp32c3.yaml -o out/c3
uv run snappnt acquire out/c3 --prn 10 --freq-span 40000
uv run snappnt sweep scenarios/navic_s_esp32c3.yaml --cn0 48:60:2 --trials 20 -o out/pd.csv
uv run pytest -q
```

The ESP32-C3 scenario models a XIAO ESP32C3: 80 MSa/s, a snapshot of about 0.2 ms (a fifth
of a NavIC code period), a 10-bit ADC and a 12 ppm crystal error.

Hardware use (capturing from an ESP32 board, the conducted test) is described in
[Conducted test](docs/guides/conducted-test.md).

## Layout

```
src/snappnt/
  signals/   catalog/*.yaml (signal parameters) + codes/ (spreading-code generators)
  frontend/  devices/*.yaml (hardware limits) + freqplan.py (mixer frequency plans)
  io/        SigMF read/write, ESP-SDR client and word decoding, generator command builders
  sim/       scenarios, impairments, playback files for HackRF / UHD
  rx/        snapshot acquisition (works for snapshots shorter than one code period)
  eval/      detection probability vs C/N0, link budget, truth comparison
scenarios/   example scenarios
tools/       helper scripts (public-safety check, benchmarks, plotting, conducted test,
             visibility, sky link budget)
docs/        MkDocs site (uv run mkdocs serve to browse locally)
```

## Spreading-code verification

Every code generator is tested against values printed in its ICD, typed into the tests
independently of the generator:

- NavIC L5/S SPS PRN 1–14: IRNSS SIS ICD for SPS v1.1, Table 7 (first 10 chips, octal)
- GPS L1 C/A PRN 1–10: IS-GPS-200, Table 3-Ia

## How this project is developed

Most of the code and documentation was written by AI agents (Claude Code) working from
GitHub issues, and pull requests are also reviewed by Greptile. The maintainer sets the
direction, approves plans, makes the design decisions recorded in
[the decision log](docs/project/decisions.md), and runs all hardware tests. The process is
described in [Agent orchestration](docs/development/orchestration.md). Commits written by
agents carry a `Co-Authored-By` line, and contributions are signed off under the
[Developer Certificate of Origin](https://developercertificate.org/) (`CONTRIBUTING.md`).

This is a research tool maintained in spare time. Issues and pull requests are welcome, but
responses may be slow. `CONTRIBUTING.md` lists the sign-off and the checks to run before a
pull request.

## Safety

- snappnt never transmits. It writes playback files and builds command lines for a person to
  review and run.
- Conducted tests use cables and attenuators only. Never connect an antenna to a generator.
- The emission of the conducted-test bench (leakage from cables, attenuators and the
  generator) has **not** been measured against any regulatory limit (issue #57). Whoever runs a
  transmitter, even into a closed cable path, is responsible for complying with the radio
  regulations where they are.
- See [Conducted test](docs/guides/conducted-test.md) for the procedure and its safety rules.

## Related software

The ESP-SDR firmware that runs on the ESP32 boards is a separate project under GPL-3.0 and is
not part of this repository; snappnt only talks to it over a USB serial link, and no
firmware code is copied into snappnt (decision D-015 in
[the decision log](docs/project/decisions.md)).

## Citing

If you use snappnt in published work, please cite it with the DOI
[10.5281/zenodo.23163934](https://doi.org/10.5281/zenodo.23163934) (Zenodo). This DOI always
resolves to the latest version. Each version also has its own DOI, listed on the Zenodo page;
use that one to cite an exact version.

## License

BSD-2-Clause. See `LICENSE`.
