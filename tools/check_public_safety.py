#!/usr/bin/env python3
"""Scan tracked text files for information that must not be published.

Generic patterns only (see docs/development/public-safety.md):
  * email addresses, except an allow list of project and placeholder addresses
  * absolute paths into a personal home directory
  * coordinate-like keys (lat, lon, latitude, longitude, alt) with precise values
  * the SigMF key core:geolocation

Optional: SNAPPNT_PRIVATE_TERMS=<file outside the repository> adds case-insensitive terms,
one per line. That file must never be committed.

A line containing the marker "public-safety: ignore" is skipped; use it only where a pattern is
named on purpose (for example in the rules page). Test fixtures for this checker are excluded.

Exit status 1 when anything is found. Findings print as file:line: reason.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

ALLOWED_EMAILS = {
    "noreply@anthropic.com",
    "you@example.com",
}
ALLOWED_EMAIL_SUFFIXES = ("@users.noreply.github.com", "@example.com", "@example.org")

EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
HOME_PATH = re.compile(
    r"(/Users/[^/\s<>\"'`]+/|/home/(?!runner/|<)[^/\s<>\"'`]+/|[A-Za-z]:\\Users\\[^\\\s<>]+\\)"
)
COORD = re.compile(
    r"\b(lat|lon|lng|latitude|longitude|alt|altitude)(_deg|_m)?\b[\"']?\s*[:=]\s*-?\d+\.\d{3,}",
    re.IGNORECASE,
)
GEOLOCATION = re.compile(r"core:geolocation")

SKIP_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".pdf", ".zip", ".sigmf-data", ".i8", ".sc16"}
SKIP_FILES = {"tools/check_public_safety.py", "tests/test_public_safety.py"}
IGNORE_MARKER = "public-safety: ignore"


def tracked_files(root: Path) -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "-z"], cwd=root, capture_output=True, check=True
    ).stdout.decode()
    return [root / p for p in out.split("\0") if p]


def load_private_terms() -> list[str]:
    path = os.environ.get("SNAPPNT_PRIVATE_TERMS")
    if not path:
        return []
    p = Path(path).expanduser()
    return [t.strip() for t in p.read_text(encoding="utf-8").splitlines() if t.strip()]


def scan_line(line: str, terms: list[str]) -> list[str]:
    reasons = []
    for m in EMAIL.finditer(line):
        addr = m.group(0).lower()
        if addr not in ALLOWED_EMAILS and not addr.endswith(ALLOWED_EMAIL_SUFFIXES):
            reasons.append(f"email address {m.group(0)!r}")
    if HOME_PATH.search(line):
        reasons.append("absolute path into a home directory")
    if COORD.search(line):
        reasons.append("precise coordinate value")
    if GEOLOCATION.search(line):
        reasons.append("SigMF core:geolocation key")
    low = line.lower()
    for t in terms:
        if t.lower() in low:
            reasons.append("private term from SNAPPNT_PRIVATE_TERMS")
    return reasons


def main() -> int:
    root = Path(
        subprocess.run(
            ["git", "rev-parse", "--show-toplevel"], capture_output=True, check=True, text=True
        ).stdout.strip()
    )
    terms = load_private_terms()
    findings = 0
    for path in tracked_files(root):
        rel = path.relative_to(root).as_posix()
        if rel in SKIP_FILES or path.suffix.lower() in SKIP_SUFFIXES or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for n, line in enumerate(text.splitlines(), start=1):
            if IGNORE_MARKER in line:
                continue
            for reason in scan_line(line, terms):
                findings += 1
                print(f"{rel}:{n}: {reason}")
    if findings:
        print(f"\n{findings} finding(s). See docs/development/public-safety.md.")
        return 1
    print("public-safety check: no findings")
    return 0


if __name__ == "__main__":
    sys.exit(main())
