# Agent orchestration

Most work on snappnt is done by Claude agents. This page is the rulebook they follow. It is
also written for people: it explains who decides what, and when a person is pulled in.

## Roles

| Role | Who | Runs where | Does |
|---|---|---|---|
| Worker | Claude Code, one fresh session per issue | The maintainer's machine | Posts a plan, implements it, opens a pull request, addresses review findings. |
| Orchestrator | Claude, a session separate from any worker | Scheduled runs in the cloud | Chooses the next issue, approves or returns plans, checks pull requests against the issue, merges pull requests for `auto` issues, escalates everything else. |
| Reviewer | Greptile | GitHub | Reviews every pull request independently. |
| Maintainer | A person | — | Handles escalations, decisions (`needs-decision`), hardware work (`needs-hardware`), and anything outside these rules. |

The orchestrator and the worker never share a session. The orchestrator judges from primary
sources only — the issue text, the diff, CI results, test output it runs itself — and not from
the worker's own description of its work.

## Status labels

Each issue carries at most one `status:` label.

```
(no status) ──orchestrator selects──▶ status:ready
status:ready ──worker posts plan──▶ status:plan-proposed
status:plan-proposed ──orchestrator approves──▶ status:plan-approved
status:plan-proposed ──orchestrator returns it──▶ status:ready   (comment lists what to change)
status:plan-approved ──worker opens PR──▶ status:in-review
status:in-review ──orchestrator merges──▶ issue closed by the PR
any state ──escalation──▶ status:blocked   (maintainer removes it when resolved)
```

Only one issue is in progress (`ready`, `plan-proposed`, `plan-approved` or `in-review`) at a
time. Parallel work is not used until the rules have run smoothly for a while, because
conflicts between pull requests make every judgement harder.

## Choosing the next issue (orchestrator)

1. Skip issues labelled `needs-decision`, and issues whose dependencies (listed under
   "Dependencies" or referenced as "depends on #N") are not closed.
2. Prefer the lowest-numbered open milestone, then issues labelled `auto`, then the lowest
   issue number.
3. `research` issues without `auto` may be selected; their result is a document or an issue
   comment, and they are never merged without the maintainer.
4. `needs-hardware` issues without `auto` are the maintainer's; the orchestrator does not select
   them.

## Plan approval (orchestrator)

A plan may be approved by the orchestrator only if **all** of these hold:

- The issue is labelled `auto`.
- Every file the plan will change is inside the issue's "Allowed scope".
- No new runtime dependency is added (optional extras such as `plot` or `docs` are allowed if
  the issue says so).
- No public function signature, command-line option, file format (SigMF keys, scenario keys,
  playback formats) or existing default value changes. Adding new optional parameters or keys
  is allowed.
- The plan says, for each acceptance criterion, how it will be checked.
- Nothing in the plan conflicts with `CLAUDE.md` or with
  [Public-safety rules](public-safety.md).

Otherwise the orchestrator either returns the plan with specific requested changes, or
escalates.

## Review handling

- Greptile findings are bug reports to verify, not orders. The worker either fixes a finding
  or replies with the reason it is not a problem, citing code, a test or a document.
- The orchestrator reads every finding and every worker reply. If it disagrees with the
  worker, it says why in the thread.
- If the worker and the orchestrator have exchanged two rounds on one finding without
  agreement, the orchestrator escalates.
- If a pull request has gone through three rounds of review and fixes and still has open
  blocking findings, the orchestrator escalates. Repeated findings mean a root cause is being
  missed.

## Merging (orchestrator, `auto` issues only)

The orchestrator merges a pull request when **all** of these hold:

1. The linked issue is labelled `auto`.
2. CI is green on the latest commit, and the branch has no conflict with `main`.
3. The orchestrator has checked out the pull request head itself and run
   `ruff check .`, `ruff format --check .`, `pytest -q` and `mkdocs build --strict`, all
   passing.
4. No Greptile finding is left unanswered, and none that the orchestrator judges blocking is
   left unfixed.
5. Each acceptance criterion in the issue has been checked, and the approval comment (below)
   says how.
6. The pull request description lists what is still unverified, and each unverified item that
   needs hardware is tracked in an open issue.

Merge method: squash merge, with the pull request title as the commit title.

`auto` issues that also carry `needs-hardware` may be merged when the code is complete and
tested with stand-ins (for example a fake serial port); the hardware check stays in its own
issue.

For issues without `auto`, the orchestrator posts the same approval comment and sets
`status:blocked` for the maintainer to merge.

## Escalation

The orchestrator sets `status:blocked` and posts a comment that starts with
**"Maintainer needed:"** and says what exactly needs deciding and what the options are, when:

- The worker reports that it hit a stop condition from the issue.
- A plan fails the approval rules and cannot be fixed by a simple request.
- The review limits above are reached.
- An action would touch hardware, transmit, add a runtime dependency, change a public
  interface, or change licensing.
- Anything in the repository or on GitHub looks like it breaks the
  [Public-safety rules](public-safety.md).
- The orchestrator is unsure. Unsure means escalate.

## Comment templates

### Plan approval

```markdown
**Plan approved** by the orchestrator.

- Scope: <files> — within the issue's allowed scope.
- Acceptance criteria: <criterion> → <how it will be checked>; ...
- Watch during implementation: <anything that could go wrong, or "nothing specific">.
```

### Merge

```markdown
**Merging.** Checks run on <commit sha>:

- ruff check / ruff format --check / pytest -q / mkdocs build --strict: pass
- Acceptance criteria:
  - <criterion>: <how it was verified, with numbers or test names>
- Greptile findings: <finding> → <fixed in sha / not a problem because ...>
- Not verified: <items and the issues that track them, or "none">
- Noticed but not blocking: <items, or "none">
```

These comments are the record of why each change was accepted. Keep them specific enough that
someone reading only the comment can follow the reasoning.

## Running the worker

The worker runs on the maintainer's machine with Claude Code, in a clone of this repository,
using the maintainer's git identity. A typical start:

```text
Read CLAUDE.md and docs/development/orchestration.md.
Work on the issue labelled status:ready (or status:plan-approved) following those rules.
```

Commits by the worker are signed off (`git commit -s`) because they are made under the
maintainer's identity, who takes responsibility for them under the Developer Certificate of
Origin.

## Running the orchestrator

The orchestrator is a scheduled task that starts a fresh Claude session every one to two hours.
Each run:

1. Reads this page, `CLAUDE.md` and [Public-safety rules](public-safety.md).
2. Lists open issues and pull requests with their `status:` labels, CI state and review
   threads.
3. Moves each item one step according to the rules above, or escalates it.
4. Selects the next issue if nothing is in progress.
5. Stops. It does not write code for the worker; small review fixes are also left to the
   worker, so that one session does not both change code and approve it.
