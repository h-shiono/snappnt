---
description: Steps for adding a new signal (system and band)
argument-hint: <signal name, e.g. navic_l1_sps>
---

Add the signal `$ARGUMENTS`. Follow these steps and report what each step was based on.

1. **Find the source document.** Identify the ICD: title, version, and the table numbers that
   define the signal and its codes. Show them to the maintainer. If no public ICD exists, say
   so and ask whether to continue with a placeholder code (`random:` code family).
2. **Write the catalog entry** `src/snappnt/signals/catalog/$ARGUMENTS.yaml`: carrier frequency,
   chip rate, code length, modulation, data symbol rate, pilot or not, PRN range, and `source`.
   Write numbers with a decimal point (for example `2492028000.0`).
3. **Write the code generator** in `src/snappnt/signals/codes/` and register it in `_REGISTRY` in
   `codes/__init__.py` under its `code_family` name. Shift-register codes follow the conventions
   in `codes/lfsr.py` (initial state written in output order).
4. **Write the ICD check test** `tests/test_codes_<system>.py`: type in values printed in the ICD
   (for example the first chips in octal) and compare. Never derive expected values from the
   generator. Mark the test `@pytest.mark.icd`.
5. **Add a loopback test** if useful: a scenario in `scenarios/` and a test in
   `tests/test_loopback.py` that acquires it and compares with truth.
6. **Record decisions** and placeholder values in `docs/project/decisions.md`.
7. Run `/check`.
