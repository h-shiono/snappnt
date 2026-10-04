# Automation on GitHub Actions

The worker and the orchestrator described in [Agent orchestration](orchestration.md) run as
GitHub Actions workflows, so the project moves forward without anyone's computer being on.
This page explains how the pieces fit, how to switch the automation on and off, and what it
costs.

## Workflows

| Workflow | Role | Instructions | Started by |
|---|---|---|---|
| `.github/workflows/agent-worker.yml` | Worker | `.github/agents/worker.md` | `status:ready` or `status:plan-approved` label added by the repository owner; a comment or review-thread reply by the repository owner tagged `**[orchestrator]**`; an untagged comment or review-thread reply by the repository owner on a pull request; a Greptile review; hourly at minute 40; manual |
| `.github/workflows/agent-orchestrator.yml` | Orchestrator | `.github/agents/orchestrator.md` | A comment or review-thread reply by the repository owner tagged `**[worker]**`; an untagged comment by the repository owner; a Greptile review; the `ci` workflow finishing on a pull request from a branch of this repository; hourly at minute 10; manual |

The agents post, label and push through the repository owner's token (see "Why a personal
access token" below), so their comments and labels are authored by the owner's account. Every
start condition on a comment or label therefore requires the owner as author, tagged or not.
The one exception is the orchestrator's start on Greptile's review summary comment, which
requires `greptile-apps[bot]` as author. See "Start conditions in a public repository" under
"Security notes".

Both run `anthropics/claude-code-action` in automation mode (a `prompt` is given, so it does
not wait for an `@claude` mention), pinned to a release commit. Each run starts from a fresh
checkout of `main`, reads the rulebook and does one step. The worker also installs the project
so it can run the checks; the orchestrator does not, because it never runs pull request code
and judges test results from CI instead.

The hand-off between the two is event-driven. A typical issue:

1. The orchestrator adds `status:ready` → the worker starts and posts a plan.
2. The `**[worker]**` comment starts the orchestrator, which approves the plan and adds
   `status:plan-approved` → the worker starts and opens a pull request.
3. CI finishing and the Greptile review start the orchestrator and the worker; the worker
   answers findings, the orchestrator checks the merge conditions and merges. It merges only
   when CI and a Greptile review have both completed on the exact head commit.
4. The merge closes the issue. In the same run the orchestrator confirms the issue is closed,
   removes its `status:*` label and selects the next issue; if GitHub has not closed the issue
   yet, the next run does this.

The hourly runs are meant to catch anything an event missed, but GitHub delays or drops
scheduled runs when it is busy (on the first day only two of the hourly runs fired), so every
hand-off should have an event of its own. If work seems stuck, start the agent by hand from the
Actions tab ("Run workflow").

Two details keep the hand-offs moving without the maintainer:

- **Greptile reviews every push.** `.greptile/config.json` sets `autoReview` to
  `["open", "push"]`, so each fix the worker pushes gets a new review, and the orchestrator can
  require a review of the exact head commit before merging. If no review of the head commit
  has appeared two hours after CI finished on it, the orchestrator escalates rather than
  waiting indefinitely. When a review finds nothing new, Greptile only edits its summary
  comment and submits no pull request review, so the orchestrator also starts when that
  summary comment is created or edited.
- **Commits carry the maintainer's identity.** The action sets the git author itself
  (`claude[bot]` by default). The worker workflow passes the repository owner as `bot_name` and
  `bot_id`, so commits are authored with the owner's GitHub no-reply address and match the
  `Signed-off-by` line required by the Developer Certificate of Origin.

The token cannot read GitHub's check-runs API, so the orchestrator reads CI results from the
Actions runs of the `ci` workflow. It reads the Greptile review from the pull request's reviews
(their `commit_id`) or, when Greptile posts only a summary comment, from the "Last reviewed
commit" link in that comment.

## Why a personal access token

Events caused by the default `GITHUB_TOKEN` do not start other workflows (GitHub's rule to
prevent loops). The agents need exactly that: a label added by the orchestrator must start the
worker, and a push by the worker must start CI. The workflows therefore act through a
fine-grained personal access token limited to this repository. Its actions appear under the
maintainer's account, which is why every agent comment starts with a role tag.

Loops are prevented by the workflows' start conditions instead:

- Each agent only starts on the other agent's tag, on the maintainer's untagged comments, on
  Greptile, on CI, or on the schedule; never on its own comments. The worker ignores reviews
  and review comments on pull requests whose branch is not named `issue-...` (for example a
  maintainer's change to the workflows), because those have no issue for it to work on.
- A worker run ends only when its step is finished (pull request opened, plan posted, review
  items answered by fixes or reasoned replies), with a `Progress:` comment, or with the issue
  set to `status:blocked` and a report (a stop condition or the three-`Progress:` limit). A run that stopped after a partial push would
  leave no event to start the next run.
- Each role has its own concurrency group, so at most one worker and one orchestrator run at a
  time. Extra events wait; GitHub keeps only the newest waiting run per group, which is enough
  because every run re-reads the current state.
- Runs are capped: worker 120 turns and 120 minutes, orchestrator 40 turns and 30 minutes.
  GitHub cancels a job at its time limit and anything the worker has not pushed is lost, so the
  worker is given its start time, pushes finished parts early, times long computations (such
  as detection-probability sweeps) on a small size before running them, and leaves a
  `Progress:` comment when it cannot finish (on the issue while implementing, on the pull
  request while fixing review findings). That comment starts the orchestrator, which answers
  in the same place telling the worker to continue; the next worker run continues from the
  pushed branch. The orchestrator escalates instead after three `Progress:` comments on an
  issue without a pull request (probably too large for one run), or after three on a pull
  request with no Greptile review in between (the fixes are not producing pushes).
- The rulebook tells both agents to change nothing when nothing needs doing.

## Setup (maintainer)

1. **Claude token.** On your own machine run `claude setup-token` and store the result as the
   repository secret `CLAUDE_CODE_OAUTH_TOKEN`. Runs use your Claude plan's usage.
2. **GitHub token.** Create a fine-grained personal access token with access to this
   repository only, with an expiry date, and these repository permissions:
   Contents: read and write; Issues: read and write; Pull requests: read and write;
   Actions: read; Commit statuses: read; Metadata: read. Store it as the repository secret
   `AGENT_GH_TOKEN`.
3. **Branch protection for `main`.** Require a pull request before merging and require the
   `test` and `docs` checks to pass. This keeps any agent from pushing to `main` even if an
   instruction fails.
4. **Stop any other worker or orchestrator** (a local Claude Code session or a scheduled task
   doing the same job), so two of the same role do not act at once.
5. **Switch on.** Create the repository variable `AGENTS_ENABLED` with the value `true`.
   Optionally start one run by hand from the Actions tab ("Run workflow") to watch it.

## Switching off

Set the repository variable `AGENTS_ENABLED` to `false` (or delete it). Runs already in
progress finish; no new run starts. Nothing else needs to change.

## Costs and limits

- **GitHub Actions minutes.** Private repositories on GitHub Pro include 3,000 minutes per
  month. Most event-triggered runs that find nothing to do finish in a few minutes; runs that
  implement an issue can take up to the 120-minute limit, and an issue that needs several
  runs (see the `Progress:` comments above) uses that much per run.
- **Claude usage.** Runs consume the usage of the plan behind `CLAUDE_CODE_OAUTH_TOKEN`,
  shared with any other use of that plan.
- **Scheduled workflows** run from the default branch only.

## Publishing to PyPI

`.github/workflows/publish.yml` uploads snappnt to [PyPI](https://pypi.org/project/snappnt/)
when the maintainer publishes a GitHub release. It is not an agent workflow: no Claude session
runs in it, and agents never create releases (see "Releases" in
[Contributing and workflow](workflow.md)).

| Job | Permissions | Steps |
|---|---|---|
| `build` | `contents: read` | Checks out the release tag. Fails unless the tag is `v` followed by `project.version` in `pyproject.toml` (tag `v0.1.0` for version `0.1.0`). Builds the sdist and, from the sdist, the wheel (`uv build`). Installs the wheel into a clean virtual environment and runs `snappnt info`, `snappnt sim` and `snappnt acquire` from outside the source tree; fails unless `snappnt acquire` detects the simulated satellite and its result matches the simulator's truth. Stores the two files as a workflow artifact. |
| `publish` | `id-token: write` | Runs in the GitHub environment `pypi`. Downloads the artifact and uploads it with `pypa/gh-action-pypi-publish`. Does not check out the repository. |

The upload uses PyPI's
[Trusted Publishing](https://docs.pypi.org/trusted-publishers/): the `publish` job asks GitHub
for an OpenID Connect token that names this repository, the workflow file `publish.yml` and
the environment `pypi`, and PyPI accepts the upload only if those match the publisher
registered for the project. No PyPI API token is stored in the repository's secrets.

The same install-and-run check runs on every pull request as the `wheel` job of
`.github/workflows/ci.yml`, so a file missing from the wheel is found before a release.

### Setup (maintainer, once before the first release)

1. On pypi.org, with two-factor authentication enabled on the account, add a pending Trusted
   Publisher ("Publishing" in the account settings) for the project `snappnt`: owner
   `h-shiono`, repository `snappnt`, workflow `publish.yml`, environment `pypi`. A pending
   publisher turns into the project's publisher on the first upload, which creates the
   project.
2. In the GitHub repository settings, under "Environments", create the environment `pypi`.
   Optionally add the maintainer as a required reviewer; the `publish` job then waits for
   approval in the Actions tab before it receives the token and uploads.

Until both are done, the `publish` job of a release fails at the upload and nothing reaches
PyPI. A version once uploaded cannot be uploaded again, even after it is deleted on PyPI, so a
broken release is fixed with a new version number.

## Security notes

- The agents act with the personal access token's permissions. Keep it limited to this
  repository and give it an expiry date.
- The workflows start only on events listed in "Start conditions in a public repository"
  below. The agents still read every comment on an issue or pull request. Both are instructed
  to treat only untagged comments by the repository owner's account as instructions; comments
  from any other account are information.
- The orchestrator's checkout keeps no git credentials, it never checks out pull request code,
  and it merges only branches of this repository named after the issue. Pull request code runs
  only in CI, which has no write-capable token.
- `anthropics/claude-code-action`, `actions/checkout` and `astral-sh/setup-uv` are pinned to
  commit hashes, so a moved tag cannot change the code that receives the secrets. The actions
  used by `publish.yml` (`actions/upload-artifact`, `actions/download-artifact` and
  `pypa/gh-action-pypi-publish`) are pinned the same way. Update the hashes deliberately,
  after reading the release notes. The actionlint binary used by CI is
  pinned by version and SHA-256 checksum (see "Checking the workflow files" below).
- `publish.yml` starts only when a GitHub release is published, which needs write access to
  the repository; issues, comments and pull requests from other accounts cannot start it. Its
  top-level permissions are empty. Only the `publish` job may request an OpenID Connect token
  (`id-token: write`), and that job runs no code from the repository: it downloads the built
  files and runs the pinned upload action. The `build` job, which runs the build backend and
  snappnt itself, has read access to the repository contents only. The checkout keeps no git
  credentials, and the `uv` cache is off, so nothing restored from a cache written by an
  earlier run goes into a release. The PyPI publisher is bound to the workflow file
  `publish.yml` and the environment `pypi`, so PyPI refuses a token requested by another
  workflow or by a job outside that environment.
- The start conditions are checked statically on every pull request and push to `main`; see
  "Checking the workflow files" below.
- Transmit commands, pushes to `main`, and repository settings commands are denied through
  `--disallowedTools` in the workflows, in addition to the rules in the instructions.

### Start conditions in a public repository

Once the repository is public, anyone with a GitHub account can open issues, comment, review,
reply in review threads, and open pull requests from forks. Only accounts with triage access or
more can add labels, and only accounts with write access can edit another account's comment.
Each start condition below holds only when `AGENTS_ENABLED` is `true`, and is safe for these
reasons:

| Workflow | Event | Condition | Why an outside account cannot meet it |
|---|---|---|---|
| Both | `schedule` | Hourly | Not caused by any account. Scheduled runs use the workflow file on `main`. |
| Both | `workflow_dispatch` | Manual start | Needs write access to the repository. |
| Worker | `issues` (`labeled`) | Label `status:ready` or `status:plan-approved`, added by the repository owner (`sender`) | Outside accounts cannot add labels, and the issue template applies no labels. The owner check also covers anyone given triage access later. |
| Worker | `issue_comment` | Body starts with `**[orchestrator]**`, author is the repository owner | Author check. |
| Worker | `issue_comment` | On a pull request, untagged, author is the repository owner | Author check. |
| Worker | `pull_request_review_comment` | Branch of this repository named `issue-...`, author is the repository owner, tagged `**[orchestrator]**` or untagged | Author check and branch check. |
| Worker | `pull_request_review` | Branch of this repository named `issue-...`, reviewer is `greptile-apps[bot]` | Reviewer check and branch check. |
| Orchestrator | `issue_comment` (`created`) | Body starts with `**[worker]**` or is untagged, author is the repository owner | Author check. |
| Orchestrator | `issue_comment` (`created` or `edited`) | On a pull request, author is `greptile-apps[bot]`, body is Greptile's summary | Author check. `comment.user` is the comment's author, not whoever edited it, and only accounts with write access can edit another account's comment. |
| Orchestrator | `pull_request_review_comment` | Branch of this repository, author is the repository owner, tagged `**[worker]**` or untagged | Author check and branch check. |
| Orchestrator | `pull_request_review` | Branch of this repository, reviewer is `greptile-apps[bot]` | Reviewer check and branch check. |
| Orchestrator | `workflow_run` (`ci` completed) | The `ci` run was for a pull request from a branch of this repository (`workflow_run.head_repository`) | Only accounts with write access can push branches to this repository. Without this check a pull request from a fork would start the orchestrator: a `workflow_run` run gets the secrets even when the run that triggered it came from a fork (GitHub documentation, "Events that trigger workflows"). |

Notes on the branch checks:

- For `pull_request_review` and `pull_request_review_comment` on a pull request from a fork,
  GitHub passes no secrets to the run, so such a run could not act anyway. The branch check
  (`pull_request.head.repo.full_name` equal to this repository) makes the workflow skip it
  instead of starting a run that fails.
- An `issue_comment` event carries no branch information. It runs in the context of the
  default branch of this repository (GitHub documentation, "Events that trigger workflows"),
  not of the fork, so it gets the secrets even on a pull request from a fork. If Greptile
  reviews a pull request from a fork, its summary comment there starts the orchestrator
  (TODO: not checked whether Greptile reviews pull requests from forks; settled by opening one
  from a test fork). That run never checks out pull request code and merges only branches of
  this repository named after the issue, but it does read the pull request's text, which an
  outside account wrote. The same holds for scheduled
  runs, which read every open issue and pull request. The protection there is the rule that
  comments and text from other accounts are information, never instructions.

### Checking the workflow files

A misspelled property in a start condition does not cause an error on GitHub: it evaluates to
empty, so the condition silently never holds (a hand-off stops) or silently stops excluding
someone (a security check is lost). Two checks run in CI to catch this:

- **The `actionlint` job** in `.github/workflows/ci.yml` runs
  [actionlint](https://github.com/rhysd/actionlint) over every file in `.github/workflows/`.
  It checks the syntax and types of `${{ }}` expressions and `if:` conditions, the properties
  of contexts such as `github` (a misspelled `github.event_name` fails the job), the inputs of
  actions, and the shell scripts in `run:` steps with shellcheck. The job downloads a fixed
  release of actionlint and verifies its SHA-256 checksum against the value written in the
  workflow, taken from the release's `actionlint_<version>_checksums.txt`. To update it,
  change the version and the checksum together.
- **`tests/test_workflow_event_paths.py`**, run with the other tests. actionlint types
  `github.event` as an object with any properties, so it does **not** check the names of
  webhook payload properties: a misspelled `github.event.comment.user.login` passes it. The
  test reads every expression in `.github/workflows/*.yml` (each `if:` condition and the text
  inside each `${{ }}`; YAML comments and string literals are skipped), collects every
  `github.event.<...>` path in them, and fails on any path that is not in an allow list kept
  in the test. GitHub matches property names without regard to case, so the test compares
  paths in lower case. Each entry in the list names the events that carry the property and
  links to the GitHub documentation where it was checked. A new property in a workflow
  therefore needs a new entry, checked against the
  [webhook payload documentation](https://docs.github.com/en/webhooks/webhook-events-and-payloads),
  before the tests pass.

Neither check evaluates the conditions: they do not show that a condition holds for the events
it is meant to accept. That still rests on reading each condition against the table in "Start conditions in a
public repository".

To run actionlint locally, download the release archive for your platform from
<https://github.com/rhysd/actionlint/releases>, check it against the release's checksums file,
and run `actionlint` from the repository root. Install shellcheck as well to get the same
script checks as CI.
