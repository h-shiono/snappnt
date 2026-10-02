# snappnt

Snapshot PNT receiver toolkit for low-cost front ends.

snappnt pairs a signal simulator with a snapshot acquisition engine so that captures from
cheap radios — ESP32 chips via [ESPARGOS ESP-SDR](https://espargos.net/espsdr/), HackRF,
USRP — can be processed and checked against known truth.

> **Status:** pre-alpha, private. Not affiliated with ESPARGOS or Espressif.

## Targets

| Signal | Carrier | Front end | Status |
|---|---|---|---|
| NavIC S-band SPS | 2492.028 MHz | ESP32 (2.4 GHz, no mixer) | simulator + acquisition |
| NavIC L5 SPS | 1176.45 MHz | reference only | codes |
| GPS L1 C/A | 1575.42 MHz | reference only | codes (validation) |
| C-band LEO-PNT (hypothetical BPSK) | 5010–5030 MHz | ESP32 + external mixer | placeholder |

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

The ESP32-C3 scenario models a XIAO ESP32C3: 80 MSa/s, a ~0.2 ms snapshot (a fifth of a
NavIC code period), a 10-bit ADC and a 12 ppm crystal error.

## Layout

```
src/snappnt/
  signals/   catalog/*.yaml (signal parameters) + codes/ (spreading-code generators)
  frontend/  devices/*.yaml (hardware limits) + freqplan.py (mixer frequency plans)
  io/        SigMF read/write, ESP-SDR word decoding, generator command builders
  sim/       scenarios, impairments, playback files for HackRF / UHD
  rx/        snapshot acquisition (works for snapshots shorter than one code period)
  eval/      detection probability vs C/N0, truth comparison
scenarios/   example scenarios
docs/        MkDocs site (mkdocs serve to browse locally)
```

## Spreading-code verification

Every code generator is tested against values printed in its ICD, typed into the tests
independently of the generator:

- NavIC L5/S SPS PRN 1–14: IRNSS SIS ICD for SPS v1.1, Table 7 (first 10 chips, octal)
- GPS L1 C/A PRN 1–10: IS-GPS-200, Table 3-Ia

## Documentation

The `docs/` directory is an MkDocs site. Install it with `uv sync` and build it with
`uv run mkdocs serve`. It will be published on GitHub Pages when the repository becomes public.

## Safety

snappnt never transmits. It writes playback files and builds command lines for a person to
review. Conducted tests must use cables and attenuators only — no antennas on generators.
See `docs/guides/conducted-test.md`.

## License

BSD-2-Clause. See `LICENSE`.
