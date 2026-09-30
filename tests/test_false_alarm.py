"""False-alarm rate of acquisition on noise-only snapshots versus the configured ``pfa``.

``detection_threshold`` assumes independent search cells, each Gamma(B, 1/B) under noise
alone (B = n_blocks). These trials count how often noise alone crosses the threshold.

Run this file directly to reproduce the table in docs/results/false-alarm.md::

    python tests/test_false_alarm.py
"""

from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from scipy import stats

from snappnt.rx import acquire
from snappnt.rx.acquisition import detection_threshold
from snappnt.signals import load_signal
from snappnt.sim import generate, load_scenario

SCENARIOS = Path(__file__).resolve().parents[1] / "scenarios"

# (scenario file, frequency search range in Hz), the same ranges as tests/test_loopback.py.
CONDITIONS = {
    "navic_s_ideal": ("navic_s_ideal.yaml", (-2e3, 2e3)),
    "navic_s_esp32c3": ("navic_s_esp32c3.yaml", (-40e3, 40e3)),
}


def noise_only_metrics(
    name: str, n_blocks: int, n_trials: int, seed0: int
) -> tuple[np.ndarray, int]:
    """Acquisition metric of ``n_trials`` noise-only snapshots (seeds seed0, seed0 + 1, ...).

    Returns (metrics, n_cells). The metric does not depend on ``pfa``, so one run serves
    every ``pfa`` via ``detection_threshold(n_cells, n_blocks, pfa)``.
    """
    path, freq_range_hz = CONDITIONS[name]
    scn = load_scenario(SCENARIOS / path)
    spec = load_signal(scn.signal)
    prn = scn.satellites[0].prn
    metrics = np.empty(n_trials)
    n_cells = 0
    for i in range(n_trials):
        x, _ = generate(replace(scn, satellites=(), seed=seed0 + i))
        res = acquire(
            x,
            scn.receiver.sample_rate_hz,
            spec,
            prn,
            center_offset_hz=scn.receiver.baseband_offset_hz,
            freq_range_hz=freq_range_hz,
            n_blocks=n_blocks,
        )
        metrics[i] = res.metric
        n_cells = res.n_cells
    return metrics, n_cells


def count_false_alarms(metrics: np.ndarray, n_cells: int, n_blocks: int, pfa: float) -> int:
    return int(np.sum(metrics > detection_threshold(n_cells, n_blocks, pfa)))


@pytest.mark.slow
def test_false_alarm_rate_ideal_4_blocks():
    n_trials, pfa, n_blocks = 300, 0.1, 4
    metrics, n_cells = noise_only_metrics("navic_s_ideal", n_blocks, n_trials, seed0=100_000)
    k = count_false_alarms(metrics, n_cells, n_blocks, pfa)
    lo, hi = stats.binom.interval(0.99, n_trials, pfa)
    assert lo <= k <= hi, f"{k} false alarms in {n_trials}, 99 % interval [{lo:.0f}, {hi:.0f}]"


def main(n_trials: int = 1000, seed0: int = 0) -> None:
    print(
        "| Scenario | n_blocks | Cells | pfa | Trials | False alarms | Rate "
        "| 99 % CI of rate | 99 % interval of count under pfa |"
    )
    print("|---|---|---|---|---|---|---|---|---|")
    for name in CONDITIONS:
        for n_blocks in (1, 4):
            metrics, n_cells = noise_only_metrics(name, n_blocks, n_trials, seed0)
            for pfa in (0.1, 0.01):
                k = count_false_alarms(metrics, n_cells, n_blocks, pfa)
                ci = stats.binomtest(k, n_trials).proportion_ci(0.99, method="exact")
                lo, hi = stats.binom.interval(0.99, n_trials, pfa)
                print(
                    f"| `{name}` | {n_blocks} | {n_cells} | {pfa} | {n_trials} | {k} "
                    f"| {k / n_trials:.3f} | {ci.low:.3f} – {ci.high:.3f} "
                    f"| {lo:.0f} – {hi:.0f} |",
                    flush=True,
                )


if __name__ == "__main__":
    main()
