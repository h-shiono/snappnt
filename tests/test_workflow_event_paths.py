"""Check every `github.event.<...>` path in the workflow files against an allow list.

actionlint (run by the `actionlint` job in `.github/workflows/ci.yml`) types `github.event` as
an object with any properties, so a misspelled webhook payload property such as
`github.event.comment.user.logn` passes it and evaluates to empty on GitHub. A start condition
of an agent workflow that compares such a property then silently never holds, or silently
stops excluding someone. This test closes that gap: each path used in `.github/workflows/*.yml`
must be in `ALLOWED_PATHS`, and each entry there was checked by hand against GitHub's
documentation.

Adding an entry: open the section of the event in "Webhook events and payloads" and follow the
property down to the last name. Where the webhook documentation does not list the properties
of an object (`comment`, `sender`, `repository`), it links to the REST API schema of that
object; check the property there and link that page too.
"""

import re
from pathlib import Path
from typing import NamedTuple

WORKFLOWS_DIR = Path(__file__).resolve().parents[1] / ".github" / "workflows"

WEBHOOKS = "https://docs.github.com/en/webhooks/webhook-events-and-payloads"
REST_ISSUE_COMMENT = "https://docs.github.com/en/rest/issues/comments#get-an-issue-comment"
REST_REVIEW_COMMENT = (
    "https://docs.github.com/en/rest/pulls/comments#get-a-review-comment-for-a-pull-request"
)
REST_REPOSITORY = "https://docs.github.com/en/rest/repos/repos#get-a-repository"


class Entry(NamedTuple):
    events: tuple[str, ...]  # events whose payload has the property
    docs: tuple[str, ...]  # pages where the property was checked


# Checked against the documentation on 2026-10-04.
ALLOWED_PATHS: dict[str, Entry] = {
    "github.event.action": Entry(
        ("issue_comment",), (f"{WEBHOOKS}#common-payload-parameters", f"{WEBHOOKS}#issue_comment")
    ),
    "github.event.comment.body": Entry(
        ("issue_comment", "pull_request_review_comment"),
        (
            f"{WEBHOOKS}#issue_comment",
            REST_ISSUE_COMMENT,
            f"{WEBHOOKS}#pull_request_review_comment",
            REST_REVIEW_COMMENT,
        ),
    ),
    "github.event.comment.user.login": Entry(
        ("issue_comment", "pull_request_review_comment"),
        (
            f"{WEBHOOKS}#issue_comment",
            REST_ISSUE_COMMENT,
            f"{WEBHOOKS}#pull_request_review_comment",
            REST_REVIEW_COMMENT,
        ),
    ),
    "github.event.issue.number": Entry(
        ("issues", "issue_comment"), (f"{WEBHOOKS}#issues", f"{WEBHOOKS}#issue_comment")
    ),
    "github.event.issue.pull_request": Entry(("issue_comment",), (f"{WEBHOOKS}#issue_comment",)),
    "github.event.label.name": Entry(("issues",), (f"{WEBHOOKS}#issues",)),
    "github.event.pull_request.head.ref": Entry(
        ("pull_request_review", "pull_request_review_comment"),
        (f"{WEBHOOKS}#pull_request_review", f"{WEBHOOKS}#pull_request_review_comment"),
    ),
    "github.event.pull_request.head.repo.full_name": Entry(
        ("pull_request_review", "pull_request_review_comment"),
        (f"{WEBHOOKS}#pull_request_review", f"{WEBHOOKS}#pull_request_review_comment"),
    ),
    "github.event.pull_request.number": Entry(
        ("pull_request_review", "pull_request_review_comment"),
        (f"{WEBHOOKS}#pull_request_review", f"{WEBHOOKS}#pull_request_review_comment"),
    ),
    # `repository` is a common payload parameter; its properties are in the REST schema.
    "github.event.repository.private": Entry(
        ("workflow_dispatch",),
        (f"{WEBHOOKS}#common-payload-parameters", f"{WEBHOOKS}#workflow_dispatch", REST_REPOSITORY),
    ),
    # `sender` is a common payload parameter ("A GitHub user", the Simple User schema, whose
    # `login` is shown in the `user` property of the issue comment schema).
    "github.event.sender.login": Entry(
        ("issues",),
        (f"{WEBHOOKS}#common-payload-parameters", f"{WEBHOOKS}#issues", REST_ISSUE_COMMENT),
    ),
    "github.event.review.user.login": Entry(
        ("pull_request_review",), (f"{WEBHOOKS}#pull_request_review",)
    ),
    "github.event.workflow_run.event": Entry(("workflow_run",), (f"{WEBHOOKS}#workflow_run",)),
    "github.event.workflow_run.head_repository.full_name": Entry(
        ("workflow_run",), (f"{WEBHOOKS}#workflow_run",)
    ),
}

# `github.event.` followed by dot-separated property names. `github.event_name` does not match.
_PATH = re.compile(r"\bgithub\.event((?:\.[A-Za-z_][A-Za-z0-9_-]*)+)")
# Index (`github['event']`, `github.event['x']`) and object filter (`.*`) syntax would let a
# path past the allow list, so the workflows must not use them on `github.event`.
_OTHER_SYNTAX = re.compile(r"\bgithub\s*\[|\bgithub\.event(?:\.[A-Za-z0-9_-]+)*\s*(?:\[|\.\*)")


def scan(text: str) -> tuple[list[tuple[int, str]], list[tuple[int, str]]]:
    """Return (line, path) for each event path and (line, text) for each unsupported syntax."""
    paths, other = [], []
    for lineno, line in enumerate(text.splitlines(), start=1):
        paths += [(lineno, "github.event" + m.group(1)) for m in _PATH.finditer(line)]
        other += [(lineno, m.group(0)) for m in _OTHER_SYNTAX.finditer(line)]
    return paths, other


def _workflow_files() -> list[Path]:
    files = sorted(WORKFLOWS_DIR.glob("*.yml")) + sorted(WORKFLOWS_DIR.glob("*.yaml"))
    assert files, f"no workflow files found in {WORKFLOWS_DIR}"
    return files


def _used_paths() -> dict[str, list[str]]:
    used: dict[str, list[str]] = {}
    for f in _workflow_files():
        for lineno, path in scan(f.read_text(encoding="utf-8"))[0]:
            used.setdefault(path, []).append(f"{f.name}:{lineno}")
    return used


def test_every_event_path_is_in_the_allow_list():
    unknown = {p: where for p, where in _used_paths().items() if p not in ALLOWED_PATHS}
    assert not unknown, (
        "github.event paths not in ALLOWED_PATHS (misspelled, or not yet checked against the "
        f"webhook payload documentation): {unknown}"
    )


def test_no_index_or_filter_syntax_on_github_event():
    found = {
        f"{f.name}:{lineno}": text
        for f in _workflow_files()
        for lineno, text in scan(f.read_text(encoding="utf-8"))[1]
    }
    assert not found, f"use dot syntax for github.event paths: {found}"


def test_every_allow_list_entry_is_used():
    stale = sorted(set(ALLOWED_PATHS) - set(_used_paths()))
    assert not stale, f"ALLOWED_PATHS entries used by no workflow; remove them: {stale}"


def test_allow_list_entries_name_events_and_documentation():
    for path, entry in ALLOWED_PATHS.items():
        assert entry.events, path
        assert entry.docs and all(d.startswith("https://docs.github.com/") for d in entry.docs)


def test_scan_finds_paths_and_ignores_other_context_properties():
    text = (
        "if: github.event_name == 'issues' && github.event.issue.pull_request &&\n"
        "  startsWith(github.event.comment.body, '**[') || github.repository_owner\n"
    )
    paths, other = scan(text)
    assert paths == [(1, "github.event.issue.pull_request"), (2, "github.event.comment.body")]
    assert other == []


def test_scan_reports_index_and_filter_syntax():
    text = (
        "a: ${{ github.event['comment'] }}\n"
        "b: ${{ github['event'] }}\n"
        "c: ${{ github.event.labels.*.name }}\n"
    )
    assert [lineno for lineno, _ in scan(text)[1]] == [1, 2, 3]
