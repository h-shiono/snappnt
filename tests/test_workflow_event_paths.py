"""Check every `github.event.<...>` path in the workflow files against an allow list.

actionlint (run by the `actionlint` job in `.github/workflows/ci.yml`) types `github.event` as
an object with any properties, so a misspelled webhook payload property such as
`github.event.comment.user.logn` passes it and evaluates to empty on GitHub. A start condition
of an agent workflow that compares such a property then silently never holds, or silently
stops excluding someone. This test closes that gap: each path used in an expression in
`.github/workflows/*.yml` must be in `ALLOWED_PATHS`, and each entry there was checked by hand
against GitHub's documentation.

Adding an entry: open the section of the event in "Webhook events and payloads" and follow the
property down to the last name. Where the webhook documentation does not list the properties
of an object (`comment`, `sender`, `repository`), it links to the REST API schema of that
object; check the property there and link that page too.
"""

import re
from pathlib import Path
from typing import NamedTuple

import yaml

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
# GitHub resolves context and property names without regard to case (`GitHub.Event.Comment`
# works), so matching ignores case and paths are compared in lower case.
_PATH = re.compile(r"\bgithub\.event((?:\.[A-Za-z_][A-Za-z0-9_-]*)+)", re.IGNORECASE)
# Index (`github['event']`, `github.event['x']`) and object filter (`.*`) syntax would let a
# path past the allow list, so the workflows must not use them on `github.event`.
_OTHER_SYNTAX = re.compile(
    r"\bgithub\s*\[|\bgithub\.event(?:\.[A-Za-z0-9_-]+)*\s*(?:\[|\.\*)", re.IGNORECASE
)
# A string literal in an expression; GitHub writes a quote inside one as ''.
_STRING_LITERAL = re.compile(r"'(?:[^']|'')*'")
_EMBEDDED = re.compile(r"\$\{\{(.*?)\}\}", re.DOTALL)


def scan(expression: str) -> tuple[list[str], list[str]]:
    """Return the event paths and the unsupported syntax in one expression.

    String literals are blanked first, so text such as `'github.event.x'` is not a path.
    """
    code = _STRING_LITERAL.sub("''", expression)
    paths = ["github.event" + m.group(1).lower() for m in _PATH.finditer(code)]
    return paths, [m.group(0) for m in _OTHER_SYNTAX.finditer(code)]


def expressions(node, where: str = "") -> list[tuple[str, str]]:
    """Return (location, expression) for each expression in a parsed workflow file.

    An `if:` value is an expression as a whole, with or without `${{ }}`; elsewhere only the
    text inside `${{ }}` is. YAML comments are dropped by the parser and plain text is skipped,
    so only what GitHub evaluates is checked.
    """
    found: list[tuple[str, str]] = []
    if isinstance(node, dict):
        for key, value in node.items():
            here = f"{where}.{key}" if where else str(key)
            if key == "if" and isinstance(value, str) and "${{" not in value:
                found.append((here, value))
            else:
                found += expressions(value, here)
    elif isinstance(node, list):
        for i, value in enumerate(node):
            found += expressions(value, f"{where}[{i}]")
    elif isinstance(node, str):
        found += [(where, m.group(1)) for m in _EMBEDDED.finditer(node)]
    return found


def _workflow_expressions() -> list[tuple[str, str]]:
    files = sorted(WORKFLOWS_DIR.glob("*.yml")) + sorted(WORKFLOWS_DIR.glob("*.yaml"))
    assert files, f"no workflow files found in {WORKFLOWS_DIR}"
    found = []
    for f in files:
        doc = yaml.safe_load(f.read_text(encoding="utf-8"))
        found += [(f"{f.name}: {where}", expr) for where, expr in expressions(doc)]
    return found


def _used_paths() -> dict[str, list[str]]:
    used: dict[str, list[str]] = {}
    for where, expr in _workflow_expressions():
        for path in scan(expr)[0]:
            if where not in used.setdefault(path, []):
                used[path].append(where)
    return used


def test_every_event_path_is_in_the_allow_list():
    unknown = {p: where for p, where in _used_paths().items() if p not in ALLOWED_PATHS}
    assert not unknown, (
        "github.event paths not in ALLOWED_PATHS (misspelled, or not yet checked against the "
        f"webhook payload documentation): {unknown}"
    )


def test_no_index_or_filter_syntax_on_github_event():
    found = [(where, text) for where, expr in _workflow_expressions() for text in scan(expr)[1]]
    assert not found, f"use dot syntax for github.event paths: {found}"


def test_every_allow_list_entry_is_used():
    stale = sorted(set(ALLOWED_PATHS) - set(_used_paths()))
    assert not stale, f"ALLOWED_PATHS entries used by no workflow; remove them: {stale}"


def test_allow_list_entries_name_events_and_documentation():
    for path, entry in ALLOWED_PATHS.items():
        assert path == path.lower(), path
        assert entry.events, path
        assert entry.docs and all(d.startswith("https://docs.github.com/") for d in entry.docs)


def test_scan_finds_paths_and_ignores_other_context_properties_and_literals():
    expr = (
        "github.event_name == 'github.event.not.a.path' && GitHub.Event.Issue.Pull_Request &&\n"
        "  startsWith(github.event.comment.body, '**[it''s]') || github.repository_owner\n"
    )
    assert scan(expr) == (["github.event.issue.pull_request", "github.event.comment.body"], [])


def test_scan_reports_index_and_filter_syntax():
    for expr in ("github.event['comment']", "github['event']", "GITHUB.event.labels.*.name"):
        assert scan(expr)[1], expr


def test_expressions_reads_if_conditions_and_embedded_expressions_only():
    doc = yaml.safe_load(
        "# github.event.in.a.comment\n"
        "jobs:\n"
        "  a:\n"
        "    if: github.event.label.name == 'x'\n"
        "    steps:\n"
        "      - if: ${{ github.event.action == 'created' }}\n"
        "        run: echo github.event.plain.text ${{ github.event.issue.number }}\n"
    )
    paths = [p for _, expr in expressions(doc) for p in scan(expr)[0]]
    assert paths == ["github.event.label.name", "github.event.action", "github.event.issue.number"]
