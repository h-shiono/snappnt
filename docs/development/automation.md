# Automation on GitHub Actions

The worker and the orchestrator described in [Agent orchestration](orchestration.md) run as
GitHub Actions workflows, so the project moves forward without anyone's computer being on.
This page explains how the pieces fit, how to switch the automation on and off, and what it
costs.

## Workflows

| Workflow | Role | Instructions | Started by |
|---|---|---|---|
| `.github/workflows/agent-worker.yml` | Worker | `.github/agents/worker.md` | `status:ready` or `status:plan-approved` label added; a comment tagged `**[orchestrator]**`; an untagged maintainer comment on a pull request; a Greptile review; hourly at minute 40; manual |
| `.github/workflows/agent-orchestrator.yml` | Orchestrator | `.github/agents/orchestrator.md` | A comment tagged `**[worker]**`; an untagged maintainer comment; a Greptile review; the `ci` workflow finishing on a pull request; hourly at minute 10; manual |

Both run `anthropics/claude-code-action@v1` in automation mode (a `prompt` is given, so it does
not wait for an `@claude` mention). Each run starts from a fresh checkout of `main`, installs
the project, reads the rulebook and does one step.

The hand-off between the two is event-driven. A typical issue:

1. The orchestrator adds `status:ready` → the worker starts and posts a plan.
2. The `**[worker]**` comment starts the orchestrator, which approves the plan and adds
   `status:plan-approved` → the worker starts and opens a pull request.
3. CI finishing and the Greptile review start the orchestrator and the worker; the worker
   answers findings, the orchestrator checks the merge conditions and merges.
4. The merge closes the issue; the next orchestrator run selects the next issue.

The hourly runs catch anything an event missed.

## Why a personal access token

Events caused by the default `GITHUB_TOKEN` do not start other workflows (GitHub's rule to
prevent loops). The agents need exactly that: a label added by the orchestrator must start the
worker, and a push by the worker must start CI. The workflows therefore act through a
fine-grained personal access token limited to this repository. Its actions appear under the
maintainer's account, which is why every agent comment starts with a role tag.

Loops are prevented by the workflows' start conditions instead:

- Each agent only starts on the other agent's tag, on the maintainer's untagged comments, on
  Greptile, on CI, or on the schedule; never on its own comments.
- Each role has its own concurrency group, so at most one worker and one orchestrator run at a
  time. Extra events wait; GitHub keeps only the newest waiting run per group, which is enough
  because every run re-reads the current state.
- Runs are capped: worker 80 turns and 60 minutes, orchestrator 40 turns and 30 minutes.
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
  implement an issue can take up to the 60-minute limit.
- **Claude usage.** Runs consume the usage of the plan behind `CLAUDE_CODE_OAUTH_TOKEN`,
  shared with any other use of that plan.
- **Scheduled workflows** run from the default branch only.

## Security notes

- The agents act with the personal access token's permissions. Keep it limited to this
  repository and give it an expiry date.
- The workflows only start on comments from the repository owner or tagged agent comments, but
  the agents read every comment on an issue. Once the repository is public, anyone can comment;
  treat the rulebook's "untagged comments are from the maintainer" as meaning the repository
  owner's account only, and revisit these workflows before publication.
- Transmit commands, pushes to `main`, and repository settings commands are denied through
  `--disallowedTools` in the workflows, in addition to the rules in the instructions.
