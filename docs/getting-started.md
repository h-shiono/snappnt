# Getting started

## Install

```bash
git clone https://github.com/h-shiono/snappnt
cd snappnt
pip install -e ".[dev]"        # add ",hw" to talk to hardware, ",docs" to build this site
```

## Look at what is available

```bash
snappnt info                                # registered signals and devices
snappnt codes --signal navic_s_sps --prn 1-3
```

`snappnt codes` prints the first 10 chips of each code in octal, the same form the NavIC
ICD uses in its code table, so you can compare them by eye.

## Simulate a snapshot and acquire it

```bash
snappnt sim scenarios/navic_s_esp32c3.yaml -o out/c3
snappnt acquire out/c3 --prn 10 --freq-span 40000
```

The scenario models a Seeed XIAO ESP32C3: 80 MSa/s, 16384 samples (about 0.2 ms),
a 10-bit ADC and a receiver crystal error of 12 ppm (about −30 kHz at 2492 MHz).

`sim` writes a [SigMF](https://sigmf.org) recording: `out/c3.sigmf-data` holds the samples and
`out/c3.sigmf-meta` holds the metadata, including a `truth` annotation with the values the
simulator used. `acquire` reads the truth when it is present and marks each result `OK` when
the detected code phase and frequency match it.

## Detection probability versus C/N0

```bash
snappnt sweep scenarios/navic_s_esp32c3.yaml --cn0 48:60:2 --trials 20 -o out/pd.csv
```

For each C/N0 value the simulator generates `--trials` snapshots with random code phase and
carrier phase, and counts how often the acquisition finds the right peak.

## Run the checks

```bash
ruff check .
ruff format --check .
pytest -q
mkdocs build --strict           # needs the "docs" extra
```
