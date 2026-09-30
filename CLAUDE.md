# CLAUDE.md

Instructions for Claude Code working in this repository. People can read it too.

**Before starting any task, read:**

- [docs/development/orchestration.md](docs/development/orchestration.md) — roles, status labels, when to stop and escalate
- [docs/development/workflow.md](docs/development/workflow.md) — issue steps and writing style
- [docs/development/public-safety.md](docs/development/public-safety.md) — what must never be recorded

## Project

snappnt receives satellite navigation signals with low-cost radios (ESP32 via ESP-SDR, HackRF,
USRP) by capturing short snapshots and processing them afterwards. The simulator and the
receiver processing live in one repository so that results can be compared with the
simulator's truth automatically.

- First target: NavIC S-band SPS (2492.028 MHz, BPSK(1), public ICD).
- Later targets: C-band LEO-PNT (5010–5030 MHz, down-converted to 2.4 GHz with an external
  mixer) and others.

## Commands

```bash
pip install -e ".[dev,docs]"     # add ",hw" to talk to hardware
pytest -q                        # all tests
pytest -m icd -q                 # spreading codes against values printed in ICDs
pytest -m loopback -q            # simulate -> acquire -> compare with truth
ruff check . && ruff format .    # lint and format
mkdocs build --strict            # documentation site
python tools/check_public_safety.py
snappnt info
snappnt sim scenarios/navic_s_esp32c3.yaml -o out/c3
snappnt acquire out/c3 --prn 10 --freq-span 40000
snappnt sweep scenarios/navic_s_esp32c3.yaml --cn0 48:60:2 --trials 20 -o out/pd.csv
```

Before finishing any change, all of these must pass: `ruff check .`, `ruff format --check .`,
`pytest -q`, `mkdocs build --strict`, `python tools/check_public_safety.py`.

## Layout (details in docs/design/architecture.md)

| Path | Contents |
|---|---|
| `src/snappnt/signals/` | What is received: `catalog/*.yaml` parameters, `codes/` spreading-code generators |
| `src/snappnt/frontend/` | How it is received: `devices/*.yaml` hardware limits, `freqplan.py` mixer frequency plans |
| `src/snappnt/io/` | Data between layers: SigMF, ESP-SDR 32-bit words, generator command builders |
| `src/snappnt/sim/` | Snapshots with known truth: scenarios, impairments, playback files |
| `src/snappnt/rx/` | Acquisition, including snapshots shorter than one code period |
| `src/snappnt/eval/` | Detection probability versus C/N0, comparison with truth |
| `scenarios/` | Scenario YAML files |
| `docs/` | MkDocs site: design, guides, results, project records, development rules |
| `tools/` | Helper scripts (public-safety check, benchmarks, plotting) |

## Conventions

1. **Units in names.** `_hz`, `_s`, `_sps`, `_dbhz`, `_chips`, `_ppm`. SI units.
2. **Codes are ±1 int8.** Bit 0 → +1, bit 1 → −1 (the GNSS convention).
3. **Complex baseband is complex64.** Noise has unit variance per sample, so N0 = 1/fs (see the
   docstring of `sim/generate.py`).
4. **Code phase** is the chip position at the first sample of the snapshot. **Frequency offset**
   is measured from the centre set by the frequency plan (`baseband_offset_hz`). The simulator's
   truth and the acquisition output use these same definitions.
5. **Every new signal gets an ICD check test.** Type values printed in the ICD (for example the
   first chips in octal) into the test, independently of the generator. Never derive expected
   values from the generator. For signals without a public ICD, use a `random:` code family and
   say so in the YAML `source` field.
6. **Never transmit.** Do not run `hackrf_transfer`, `tx_samples_from_file` or similar
   (denied in `.claude/settings.json`). snappnt writes playback files and command strings only.
   A person transmits, after checking the path is closed with cables and attenuators
   (docs/guides/conducted-test.md).
7. **No large data in git.** `out/` and `data/` are ignored. Tests generate small scenarios on
   the fly.

## Records

- **Everything committed or posted to GitHub is in English**: code comments, docstrings,
  documentation, commit messages, issues, pull requests, review replies. Chat replies to the
  maintainer may follow the language the maintainer uses.
- Every comment, review reply and pull request description you post starts with an author tag
  on its own line: `**[worker]**` when working on an issue, `**[orchestrator]**` when acting as
  the orchestrator (docs/development/orchestration.md, "Author tag").
- Follow the writing style in docs/development/workflow.md: established terms only, no invented
  terms, no compressed back-references, each page stands on its own, facts separated from
  assumptions.
- Design decisions go into `docs/project/decisions.md`. Results go into `docs/results/`, and
  each new page is added to the `nav` in `mkdocs.yml`.
- Nothing personal, location-specific or machine-specific is ever recorded
  (docs/development/public-safety.md).

## Open questions (update when settled)

- ESP-SDR firmware licence (before any fork) — issue #7
- Maximum samples per capture on ESP32-C3 (`frontend/devices/esp32c3.yaml` assumes 16384) — issue #11
- Exact ESP-SDR tuning and capture commands and host transfer format (`io/espsdr_client.py`) — issue #6
- Whether low sample rates on ESP32-C61 are clock division only, without band limiting — issues #3 and #13
- Reference receiver specifications (`frontend/devices/b206mini_i.yaml`)
