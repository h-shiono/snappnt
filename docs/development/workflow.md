# Contributing and workflow

## Before opening a pull request

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest -q
uv run mkdocs build --strict
```

CI runs these checks too (the `test` and `docs` jobs of `.github/workflows/ci.yml`). It also
runs an `actionlint` job, which checks the files in `.github/workflows/` with actionlint. If a
change touches a workflow file, run actionlint locally first; see "Checking the workflow files"
in [Automation on GitHub Actions](automation.md).

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

## Releases

A release is made only by the maintainer. Agents prepare the files for a release but never
create a tag or a GitHub release.

Each GitHub release is archived by [Zenodo](https://zenodo.org/), which mints a DOI for that
version. Zenodo also keeps a concept DOI that always resolves to the latest version; the
concept DOI is the one given in `CITATION.cff` and the README. Zenodo reads the release's
metadata from `CITATION.cff`, because the repository has no `.zenodo.json` (a `.zenodo.json`
would make Zenodo ignore `CITATION.cff` entirely).

Before a release, the version number is set to the same value in `pyproject.toml`,
`src/snappnt/__init__.py` (`__version__`) and `CITATION.cff`, and `uv.lock` is regenerated
with `uv lock`. CI runs `uv sync --locked`, which fails if `uv.lock` does not match
`pyproject.toml`. The planned release date is set in `CITATION.cff` (`date-released`, in the
form `YYYY-MM-DD`) in a pull request merged just before the release, so that the
`CITATION.cff` archived by Zenodo for that version already carries its date.

Steps for a release, in order:

1. The pull requests that belong to the release are merged, including the one that sets
   `date-released`.
2. The repository is public and GitHub Pages is enabled (needed once, before the first
   release).
3. Zenodo's GitHub integration is enabled for the repository (needed once, before the first
   release).
4. The Trusted Publisher on pypi.org and the GitHub environment `pypi` are set up (needed
   once, before the first release; see "Publishing to PyPI" in
   [Automation on GitHub Actions](automation.md)).
5. The maintainer creates and publishes the GitHub release `vX.Y.Z`, where `X.Y.Z` is the
   version in `pyproject.toml`. Zenodo archives it and mints the DOI. The workflow
   `.github/workflows/publish.yml` starts on the published release: it checks that the tag is
   `v` followed by the version in `pyproject.toml` and stops otherwise, builds the sdist and
   the wheel, runs the installed wheel once, and uploads both files to PyPI. If the `pypi`
   environment has a required reviewer, the upload waits for that approval in the Actions tab.
   Check afterwards that the run passed and that <https://pypi.org/project/snappnt/> shows the
   new version. A run that failed before the upload, for example because step 4 was missed,
   can be re-run from the Actions tab once the cause is fixed. A version number can be
   uploaded to PyPI only once, so a wrong upload is corrected with a new release and a new
   version number.
6. After the first release, the concept DOI is added to `CITATION.cff` and to the "Citing"
   section of the README. The concept DOI does not change with later releases, so this step is
   needed only once.

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
