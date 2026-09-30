# Contributing

## Developer Certificate of Origin

Contributions are accepted under the [Developer Certificate of Origin 1.1](https://developercertificate.org/).
Sign off every commit to certify that you wrote the change or have the right to submit it
under the project's BSD-2-Clause license:

```bash
git commit -s -m "your message"
```

This adds a `Signed-off-by: Your Name <you@example.com>` line.

## Before opening a pull request

```bash
ruff check .
ruff format --check .
pytest -q
```

## Adding a signal

1. Add `src/snappnt/signals/catalog/<name>.yaml` with a `source` pointing to the ICD (name, version, table).
2. Add a code generator under `src/snappnt/signals/codes/` and register it.
3. Add a test that compares the generated code with values **printed in the ICD**
   (for example the first chips in octal), typed in independently of the generator.
4. If the ICD is not public, use a `random:` code family and say so in `source`.

## Hardware and RF safety

Never add code that starts a transmission. Playback files and command strings only.
