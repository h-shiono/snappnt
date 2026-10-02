# Decision log

Design decisions, newest at the bottom. Each entry records what was decided, why, and which
alternatives were considered. Entries are not edited after the fact; a later entry supersedes
an earlier one and says so.

## D-001 Simulator and receiver processing live in one repository (2026-09-30)

- **Decision:** The host-side code (simulator, acquisition, evaluation) lives in one
  repository, `snappnt`. ESP32 firmware, if it ever needs changes, goes into a separate fork of
  ESP-SDR.
- **Why:** The simulator and the receiver share the signal definitions (spreading codes,
  carrier, chip rate). One repository lets CI run the "generate, acquire, compare with truth"
  loop in one place. For now one person changes both sides at the same time.
- **Alternatives:** A separate `snappnt-sim` package. To be reconsidered if the simulator needs
  to be distributed on its own, or once the signal definitions are stable enough to become a
  library.

## D-002 License: BSD-2-Clause (2026-09-30)

- **Decision:** BSD-2-Clause.
- **Why:** Wide adoption comes first. It matches RTKLIB and its derivatives, so code can move
  between those projects without licence questions.
- **Alternatives:** Apache-2.0, which adds an explicit patent grant from contributors. To be
  reconsidered if companies start contributing. Until then the Developer Certificate of Origin
  (sign-off on each commit, see CONTRIBUTING.md) is the minimum safeguard.

## D-003 Pure Python; no dependency on MATLAB (2026-09-30)

- **Decision:** Runtime dependencies are numpy, scipy and pyyaml only. MATLAB waveform
  generators may be used for cross-checks but are never required.
- **Why:** Anyone can run the project without a toolbox licence.

## D-004 Minimal in-house SigMF reader and writer (2026-09-30)

- **Decision:** `io/sigmf_io.py` implements the small subset needed; the `sigmf` package is not
  a dependency.
- **Why:** The needed features (cf32/ci16/ci8, a truth annotation) are small. Fewer
  dependencies also means fewer licences to review.
- **Alternatives:** The official `sigmf` package, if schema validation becomes necessary.

## D-005 Spreading codes are checked against values printed in the ICD (2026-09-30)

- **Decision:** Every code generator has a test that compares its output with values printed
  in the ICD (for example the first 10 chips in octal), typed into the test independently of
  the generator.
- **Why:** Expected values derived from the generator itself would turn any generator bug into
  "truth".
- **Status:** All 28 NavIC L5/S SPS codes match Table 7 of the IRNSS SIS ICD for SPS v1.1. The
  G2 initial-state table also matches the one in PocketSDR (BSD-2-Clause). GPS L1 C/A PRN 1–10
  match IS-GPS-200.

## D-006 README in English, design notes in Japanese (2026-09-30)

- **Superseded by D-007.**

## D-007 All project records in English; documentation site with MkDocs (2026-10-01)

- **Decision:** Everything committed to the repository or posted on GitHub (code comments,
  documentation, commit messages, issues, pull requests, review replies) is written in English.
  Documentation is built with MkDocs and the Material theme. CI builds the site with
  `--strict` on every pull request. The site is deployed to GitHub Pages by hand, and only
  once the repository is public.
- **Why:** The project is intended as open source. A browsable site makes the reasoning behind
  the code easier to follow later. GitHub Pages sites are public even when the repository is
  private, so deploying before publication would leak unpublished material.
- **Alternatives:** Zensical, the successor to Material for MkDocs from the same team; it reads
  `mkdocs.yml`, so switching later should be cheap. Material for MkDocs is in maintenance mode
  (security and critical fixes only), which is acceptable for a documentation site. MkDocs is
  pinned below 2.0 because 2.0 is a separate rewrite.

## D-008 Agent orchestration with a separate orchestrator (2026-10-01)

- **Decision:** Work is done by Claude Code sessions on the maintainer's machine (workers). A
  separate Claude session (the orchestrator) approves plans, handles reviews and merges pull
  requests for issues labelled `auto`, following
  [Agent orchestration](../development/orchestration.md). Greptile reviews every pull request.
  The maintainer handles everything the rules escalate.
- **Why:** Keeps work moving without waiting on the maintainer for routine approvals, while
  keeping the approving context separate from the context that wrote the change.
- **Alternatives:** The maintainer merges every pull request (slower). The orchestrator only
  recommends merges for a trial period (considered, not chosen).

## D-009 Public-safety rules and a CI check (2026-10-01)

- **Decision:** Personal information about the maintainer and site-specific details must never
  enter the repository or GitHub records. The rules are in
  [Public-safety rules](../development/public-safety.md). CI runs a generic pattern check;
  any list of specific private terms is kept outside the repository.
- **Why:** The repository will be published. A deny list of private terms committed to the
  repository would itself publish those terms.

## D-010 Agents run on GitHub Actions (2026-10-01)

- **Decision:** The worker and the orchestrator run as GitHub Actions workflows
  (`anthropics/claude-code-action@v1` in automation mode), started by events and hourly as a
  fallback. They authenticate to Claude with the maintainer's plan (`CLAUDE_CODE_OAUTH_TOKEN`)
  and to GitHub with a fine-grained personal access token limited to this repository. A
  repository variable, `AGENTS_ENABLED`, switches both on and off. This supersedes the worker
  location in D-008 (the maintainer's machine) for everything except hardware work.
- **Why:** Work continues without the maintainer's computer being on, and each hand-off happens
  when the triggering event arrives instead of at the next hourly check.
- **Merge evidence:** the orchestrator no longer re-runs the tests itself (as D-008 described).
  Its session holds a write-capable token, so it never checks out or runs pull request code;
  it merges only when the token-less `ci` workflow and a Greptile review have both completed on
  the exact head commit, and only for branches of this repository named after the issue.
- **Alternatives:** A scheduled job on the maintainer's machine running `claude -p` (depends on
  the machine being awake; hourly hand-offs). A scheduled cloud task (hourly hand-offs; package
  installation was not available in that environment). The Claude GitHub App instead of a
  personal access token: avoids a personal token, but its broad permission set and bot identity
  need `allowed_bots` for every hand-off; the token keeps start conditions simple.

## D-011 One SigMF recording per ESP-SDR capture (2026-10-01)

- **Decision:** `snappnt capture --count N` writes N separate SigMF recordings,
  `<output>_0000`, `<output>_0001`, ..., and the plain `<output>` when N is 1. Each recording
  carries its own host time (`snappnt:host_time_utc`, `core:datetime`) and gain.
- **Why:** `snappnt acquire` and `read_sigmf` treat a data file as one contiguous snapshot. The
  firmware takes one burst per capture command, so separate captures are not contiguous in
  time. Joining them in one file would make acquisition correlate across the gaps and give a
  wrong code phase and Doppler frequency.
- **Alternatives:** One file with several SigMF `captures` segments. It is valid SigMF, but
  `read_sigmf` and `acquire` would have to be changed to treat each segment separately, which
  is outside this issue.

## D-012 Link budget calculator defaults (2026-10-01)

- **Decision:** `snappnt link-budget` computes the receiver noise density at a reference
  temperature of 290 K (−174 dBm/Hz plus the noise figure). Its check for software-added noise
  requires the injected noise density to be at least 10 dB above the receiver's own; the margin
  can be changed with `--margin-db`. The generator power, the losses and the noise figures have
  no defaults.
- **Why:** 290 K is the convention in which noise figures are specified. At 10 dB the receiver's
  own noise raises the total noise density by 0.41 dB, so the C/N0 error stays below
  0.5 dB; 10 dB is this project's choice, not a value from a source.
- **Alternatives:** Reading noise figures from the device YAML files: no verified value exists
  there yet. A smaller margin such as 6 dB: the C/N0 error would be about 1 dB.

## D-013 Frequency plans in the simulator (2026-10-01)

- **Decision:** A scenario may set `frequency_plan: {lo_hz, lo_side, tuned_hz}`; the RF
  frequency is the signal's `carrier_hz`. `baseband_offset_hz` is then the plan's value, and
  giving it in the receiver section as well is an error. With a plan, the carrier offset in the
  samples is `doppler_sign * doppler_hz`, where `doppler_sign` is −1 for a high-side LO. The
  receiver crystal error (`clock_offset_ppm`) is applied to `tuned_hz`, because the crystal
  drives the receiver's own LO. The external LO error (`lo_offset_ppm`, valid only with a plan)
  is applied to `lo_hz` and shifts the IF by −δ for a low-side LO and +δ for a high-side LO
  (δ = `lo_offset_ppm` · 1e-6 · `lo_hz`). The carrier Doppler rate is mirrored the same way (`doppler_sign * doppler_rate_hzps`; the
  truth keeps the RF value in `doppler_rate_hzps` and gives the value in the samples as
  `expected_doppler_rate_hzps`). Code Doppler keeps the RF sign, and the simulator holds the chip rate constant over a snapshot (the Doppler rate acts on the carrier phase only). `lo_side` must be
  `low` or `high`; anything else raises `ValueError`. `snappnt sim` writes
  `tuned_hz` as the SigMF centre frequency when a plan is present.
- **Why:** IF = RF − LO (low side) or LO − RF (high side), so a shift of the LO moves the IF in
  the opposite or the same direction. The mixer does not change the chip rate, so the code
  rate follows the RF Doppler. Without a plan, nothing changes (the crystal error still
  scales with `carrier_hz`).
- **Alternatives:** Applying the crystal error to `carrier_hz` with a plan too: it would
  describe a receiver tuned to the RF, which is not the case behind a mixer. `tuned_hz` equal
  to the IF in the C-band scenarios is an assumption until a real receiver setup is chosen.

## D-014 SigMF pair replacement uses backup and restore (2026-10-01)

- **Decision:** `write_sigmf` writes both files under `.tmp` names. If a recording with the same
  base name exists, it moves its two files to `.bak` names, renames the new files into place,
  and deletes the backups only after both renames have succeeded. If any step fails, it removes
  the files it placed, moves the backups back and removes the temporary files, so the old
  recording stays complete and readable. If moving a backup back fails too, the `.bak` files are
  kept and the raised error names them, so the old recording can be recovered by hand. This is
  the only case in which a temporary or backup file remains. SigMF keys and file formats do not
  change.
- **Details of the rollback:** Each cleanup step is tried even if an earlier one failed. If a
  placed new file cannot be removed, no backup is moved back, because a restored old file next
  to a new one would read as a pair of different recordings; all backups are kept and named in
  the error together with the new files that could not be removed (this also applies to a first
  write, where there are no backups and a partial recording stays at the final path). If only some backups cannot be moved back, the old files that were restored are
  never next to a new file, so at worst the recording is incomplete and does not read. Before
  anything is moved, `write_sigmf` refuses with `FileExistsError` when a `.bak` file already
  exists, as a file or a dangling symbolic link, so kept backups are never overwritten. If every rename succeeded and only deleting a
  backup fails, the write counts as successful and a log warning (the `logging` module, so that warnings
  turned into errors cannot make a finished write look failed) names the backup; the next write to
  the same base name refuses until that backup is deleted.
- **Known limit:** While an existing recording is replaced, its two final paths are missing
  for a short time (between moving them to `.bak` and placing the new files). A reader in
  another process can fail with `FileNotFoundError` in that window. Before this change both
  paths were always present, but a failed second rename could leave a mismatched pair. A
  single-writer tool such as snappnt does not need concurrent reads; this is accepted.
- **Why:** Two renames cannot be made atomic together. Before this change, a failure of the
  second rename left the new samples next to the old metadata, a pair that reads without error
  but describes the wrong samples.
- **Alternatives:** Renaming the metadata first leaves the old samples paired with the new
  metadata when the data rename fails, which is the same mismatch in the other direction.
  Refusing `--overwrite` when the metadata file cannot be replaced is a check made in advance,
  and it does not cover a failure between the two renames.

## D-015 ESP-SDR firmware is used unmodified; no fork for now (2026-10-02)

- **Decision:** M3 uses the ESP-SDR firmware (`ESPARGOS/esp-sdr`, GPL-3.0) as published,
  without changes. If M4 (long captures on the ESP32-C61) needs firmware changes, they are
  first proposed upstream. Only if upstream does not take them is the firmware forked, in a
  separate repository that stays under GPL-3.0, with source published alongside any binaries.
  No firmware code is copied into snappnt, and firmware functions are not translated into
  Python; snappnt implements the protocol and data formats from their description.
- **Why:** snappnt is a separate program that talks to the firmware over a serial link, so
  the GPL does not extend to it and snappnt stays BSD-2-Clause (D-002). Describing the
  protocol in our own words and citing firmware file and line, as
  [ESP-SDR protocol](../design/espsdr-protocol.md) and
  [ESP32-C61 capture](../design/esp32c61-capture.md) do, is not copying.
  Nothing in M3 needs a firmware change, and a fork would have to be maintained.
  #13 found that continuous capture on the C61 would need firmware changes, which is when
  this decision is revisited.
- **Alternatives:** Forking now (maintenance without a present need). Bringing firmware code
  into snappnt (would put snappnt under the GPL; rejected).
- **Not a legal opinion:** the licence reasoning is to be checked again before publication
  (#12).

## D-016 DC offset and fixed spurs in the simulated receiver (2026-10-02)

- **Decision:** Scenarios may set `receiver.dc_offset` (fraction of ADC full scale per
  component) and `receiver.spurs` (baseband offset in Hz and power in dB). The DC offset is
  applied by a new function `quantize_with_offset`; `quantize` is unchanged. A spur's power is
  the tone power divided by the total noise power per sample at the generation rate. The DC
  offset is constant over a snapshot. Spur phases are drawn from a second random generator
  seeded from the scenario seed.
- **Why:** Noise-only captures from one ESP32-C3 board (see
  [ESP32-C3 bench checks](../results/esp32c3-bench-no-rf.md)) show a DC offset of about half
  of full scale on I and fixed narrow lines. The offset must be added after the gain of the
  automatic gain control is set: if it is added before, the gain would include it in the RMS,
  and at the default 12 dB back-off (RMS of 0.25 of full scale per component) an offset of
  −0.5 of full scale cannot be reached. A second random generator keeps the noise and data
  symbols of existing scenarios, and of scenarios with spurs, identical.
- **Alternatives:** Adding the offset in input units before `quantize` (cannot reach the
  requested fraction). Changing the signature of `quantize` (a public function). Defining the
  spur level as height above the noise floor in a spectrum (depends on the FFT length).
- **Not modelled:** drift of the DC offset within one capture (about 25 counts in 205 µs on
  the board measured). The values in `scenarios/navic_s_esp32c3_dc.yaml` come from one board
  and one bench session.
