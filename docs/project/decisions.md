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
