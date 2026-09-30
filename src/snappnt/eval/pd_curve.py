"""Detection probability versus C/N0 (Monte Carlo over the simulator).

A trial counts as a correct detection when the detector fires AND the peak is at the true
code phase (within ``code_tol_chips``) and frequency (within one search bin). A detection
at the wrong place counts as a false alarm, not a success.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np

from snappnt.rx import acquire
from snappnt.signals import load_signal
from snappnt.sim import SatelliteTruth, Scenario, generate


@dataclass(frozen=True)
class SweepPoint:
    cn0_dbhz: float
    trials: int
    p_detect: float
    p_wrong: float
    mean_metric: float


def is_correct(res, truth_sat: dict, code_length: int, code_tol_chips: float) -> bool:
    d_code = abs(res.code_phase_chips - truth_sat["code_phase_chips"])
    d_code = min(d_code, code_length - d_code)
    d_freq = abs(res.freq_offset_hz - truth_sat["expected_freq_offset_hz"])
    return d_code <= code_tol_chips and d_freq <= res.freq_step_hz


def sweep(
    base: Scenario,
    cn0_list: list[float],
    trials: int,
    *,
    freq_range_hz: tuple[float, float] = (-50e3, 50e3),
    n_blocks: int = 1,
    pfa: float = 1e-3,
    code_tol_chips: float = 0.5,
    seed: int = 0,
) -> list[SweepPoint]:
    """Vary C/N0 of the scenario's first satellite; code phase and Doppler are randomised."""
    spec = load_signal(base.signal)
    if not base.satellites:
        raise ValueError("scenario needs at least one satellite")
    sat0 = base.satellites[0]
    rng = np.random.default_rng(seed)
    out = []
    for cn0 in cn0_list:
        hits = wrong = 0
        metrics = []
        for _ in range(trials):
            sat = SatelliteTruth(
                prn=sat0.prn,
                cn0_dbhz=cn0,
                doppler_hz=sat0.doppler_hz,
                code_phase_chips=float(rng.uniform(0, spec.code_length)),
                carrier_phase_rad=float(rng.uniform(0, 2 * np.pi)),
            )
            scn = replace(base, satellites=(sat,), seed=int(rng.integers(2**31)))
            x, truth = generate(scn)
            res = acquire(
                x,
                scn.receiver.sample_rate_hz,
                spec,
                sat.prn,
                center_offset_hz=scn.receiver.baseband_offset_hz,
                freq_range_hz=freq_range_hz,
                n_blocks=n_blocks,
                pfa=pfa,
            )
            metrics.append(res.metric)
            if res.detected:
                if is_correct(res, truth["satellites"][0], spec.code_length, code_tol_chips):
                    hits += 1
                else:
                    wrong += 1
        out.append(SweepPoint(cn0, trials, hits / trials, wrong / trials, float(np.mean(metrics))))
    return out


def write_csv(points: list[SweepPoint], path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["cn0_dbhz", "trials", "p_detect", "p_wrong", "mean_metric"])
        for p in points:
            w.writerow([p.cn0_dbhz, p.trials, p.p_detect, p.p_wrong, f"{p.mean_metric:.3f}"])
    return path
