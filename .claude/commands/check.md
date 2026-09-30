---
description: Run lint, format check, tests, docs build and the public-safety check, then report
---

Run these in order. If anything fails, report the cause and how to fix it. Do not change code
before reporting.

1. `ruff check .`
2. `ruff format --check .`
3. `pytest -m icd -q` (spreading codes against values printed in ICDs)
4. `pytest -m loopback -q` (simulate -> acquire -> compare with truth)
5. `pytest -q` (everything)
6. `mkdocs build --strict`
7. `python tools/check_public_safety.py`

For each failure, give the test or check name, the expected and actual values, and the files
involved.
