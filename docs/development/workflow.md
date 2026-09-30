# Contributing and workflow

## Before opening a pull request

```bash
ruff check .
ruff format --check .
pytest -q
mkdocs build --strict      # pip install -e ".[docs]"
```

Commits are signed off under the Developer Certificate of Origin (`git commit -s`); see
`CONTRIBUTING.md`.

## Issues

Work is organised in GitHub issues. Each issue states:

- **Background:** why the work is needed, with sources for the facts it relies on.
- **Tasks.**
- **Acceptance criteria:** tests, documents or measurements that show the work is done.
- **Stop conditions:** situations in which the worker stops and reports instead of carrying on.
- **Allowed scope:** directories and files that may change.
- **Dependencies:** issues that must be closed first.

### Labels

| Label | Meaning |
|---|---|
| `auto` | Can be done and checked by an agent: tests decide pass or fail. |
| `research` | Mainly investigation. The result is a document page or an issue comment. |
| `needs-hardware` | Needs real hardware or a person's hands. Agents prepare code, procedures and tests with stand-ins; the hardware check is done by a person. |
| `needs-decision` | Needs a decision by the maintainer. Agents collect the facts and options but do not decide. |
| `status:*` | Progress of an issue through the agent workflow; see [Agent orchestration](orchestration.md). |

## Steps for an issue

1. **Plan first.** Post a plan as an issue comment before changing anything: files to change,
   tests to add, how each acceptance criterion will be checked, open questions. Wait for
   approval.
2. **Branch.** `issue-<number>-<short-description>`, for example `issue-5-acquire-speed`. Never
   commit to `main` directly.
3. **One issue per pull request.** If you find another problem on the way, do not fix it in the
   same pull request; describe it in a comment as a proposed new issue.
4. **Stop conditions are hard stops.** When one is hit, stop and report in the issue.
5. **Pull request description** follows `.github/pull_request_template.md`. Do not leave out
   "Why", "Alternatives considered" or "Not verified".
6. **Record decisions.** Any design decision goes into the [decision log](../project/decisions.md).
7. **Record results.** Measured or simulated results go into a page under
   [Results](../results/index.md), and the page is added to `mkdocs.yml`.

At the end of each milestone, write a summary page (for example `docs/project/summary-m2.md`)
that a reader can follow without reading anything else first.

## Writing style

All records are in English: code comments, docstrings, documentation, commit messages, issues,
pull requests and review replies.

- **Use established terms.** Acquisition, tracking, code phase, C/N0, coherent integration and
  so on. Do not invent new terms. If a concept has no established name, describe it in plain
  words where it is used.
- **Do not compress by back-reference.** Avoid phrases that only make sense to someone who
  remembers an earlier summary ("the fix from before", "the usual approach"). Say what is meant.
- **Make each page stand on its own.** Define symbols and units where they first appear on the
  page.
- **Separate facts from assumptions.** Unverified values are marked `TODO` with what would
  settle them. Estimates are labelled as estimates, with how they were obtained.
- **Units in names and text.** Variables carry units in their names (`_hz`, `_s`, `_sps`,
  `_dbhz`, `_chips`, `_ppm`). SI units throughout.
