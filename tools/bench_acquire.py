"""Time ``acquire`` for the ESP32-C3 and ESP32-C61 (4 MSa/s) conditions.

    python tools/bench_acquire.py [--repeats 5] [--reference]

``--reference`` also times the per-bin FFT loop that the batched code replaced
(tests/acquire_reference.py). Times depend on the machine, so the output states the CPU
count and the library versions.
"""

from __future__ import annotations

import argparse
import os
import platform
import sys
import time
from functools import partial
from pathlib import Path

import numpy as np
import scipy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from snappnt.rx import acquire  # noqa: E402
from snappnt.signals import load_signal  # noqa: E402
from snappnt.sim import generate, load_scenario  # noqa: E402

CASES = [
    ("navic_s_esp32c3", "navic_s_esp32c3.yaml", 1, (-40e3, 40e3)),
    ("navic_s_esp32c61_4msps", "navic_s_esp32c61_4msps.yaml", 4, (-40e3, 40e3)),
]


def best_of(fn, repeats: int) -> float:
    fn()  # warm-up
    times = []
    for _ in range(repeats):
        t0 = time.perf_counter()
        fn()
        times.append(time.perf_counter() - t0)
    return min(times)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repeats", type=int, default=5)
    ap.add_argument("--reference", action="store_true", help="also time the per-bin loop")
    a = ap.parse_args()

    print(
        f"cpus={os.cpu_count()} python={platform.python_version()} "
        f"numpy={np.__version__} scipy={scipy.__version__}"
    )
    funcs = [("batched", acquire)]
    if a.reference:
        from tests.acquire_reference import acquire_reference

        funcs.insert(0, ("reference", acquire_reference))

    for name, yaml_name, n_blocks, rng in CASES:
        scn = load_scenario(ROOT / "scenarios" / yaml_name)
        spec = load_signal(scn.signal)
        x, truth = generate(scn)
        prn = truth["satellites"][0]["prn"]
        fs = scn.receiver.sample_rate_hz
        for label, fn in funcs:
            kw = dict(
                center_offset_hz=scn.receiver.baseband_offset_hz,
                freq_range_hz=rng,
                n_blocks=n_blocks,
            )
            t = best_of(partial(fn, x, fs, spec, prn, **kw), a.repeats)
            print(f"{name:26s} n_blocks={n_blocks} {label:9s} {t * 1e3:9.1f} ms")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
