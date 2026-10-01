"""Bias of the acquisition C/N0 estimate, one cause at a time, and parabolic interpolation.

The bias is ``cn0_dbhz_est - true C/N0`` averaged over trials with different noise seeds.
Every row starts from a baseline in which none of the four causes is present, then enables
one cause. The causes are:

- frequency-bin offset: the true carrier frequency lies between two frequency bins,
- code-phase sampling: the true code phase lies between two samples,
- data-bit sign change: a navigation symbol edge falls in the middle of the snapshot,
- quantisation: 10-bit ADC with AGC (the baseline keeps floating point).

The simulator draws random navigation symbols and does not report them. To control the
causes, this file generates the satellite signal without data and, for the sign-change case,
multiplies the samples after a code-period edge by -1 itself (symbol edges fall on code-period
edges). Quantisation is applied afterwards with ``sim.impairments.quantize``.

Run this file directly to reproduce docs/results/cn0_bias.csv::

    python tests/test_cn0_bias.py
"""

from __future__ import annotations

import csv
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from unittest import mock

import numpy as np
import pytest

from snappnt.rx import acquire
from snappnt.rx.acquisition import parabolic_offset
from snappnt.signals import load_signal
from snappnt.sim import SatelliteTruth, generate, load_scenario
from snappnt.sim.impairments import quantize

ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = ROOT / "scenarios"
CSV_PATH = ROOT / "docs" / "results" / "cn0_bias.csv"

# Per condition: scenario file, half width of the frequency search range in bins (the range is
# symmetric around 0 Hz, so 0 Hz is a bin centre), true code phase of the baseline
# (chips). The code phase is a multiple of one sample, so that the true lag is a whole number
# of samples. For navic_s_esp32c3 it is also chosen so that a code-period edge lies in the
# middle of the snapshot (the sign-change case); for navic_s_ideal code phase 0 does the same.
CONDITIONS = {
    "navic_s_ideal": {
        "file": "navic_s_ideal.yaml",
        "half_range_bins": 16,  # +-2 kHz
        "code_phase_chips": 0.0,
        "quantization_bits": 10,
        "n_blocks": (1, 4),
    },
    "navic_s_esp32c3": {
        "file": "navic_s_esp32c3.yaml",
        "half_range_bins": 4,  # +-9.8 kHz
        "code_phase_chips": 918.25,
        "quantization_bits": 10,
        "n_blocks": (1,),
    },
}

CAUSES = ("baseline", "frequency", "code_phase", "sign_change", "quantisation", "all")

CSV_COLUMNS = [
    "condition",
    "n_blocks",
    "cause",
    "setting",
    "refine",
    "trials",
    "bias_mean_db",
    "bias_se_db",
    "p_detect",
    "abs_code_err_chips",
    "abs_freq_err_hz",
]


@dataclass(frozen=True)
class Case:
    cause: str
    setting: str
    freq_frac: float = 0.0  # frequency offset from a bin centre, in grid steps
    code_frac: float = 0.0  # code phase offset from a sample, in samples
    flip: bool = False
    quantise: bool = False


def cases_for(name: str, n_blocks: int) -> list[Case]:
    out = [Case("baseline", "none")]
    out += [Case("frequency", f"{f} step", freq_frac=f) for f in (0.25, 0.5)]
    out += [Case("code_phase", f"{f} sample", code_frac=f) for f in (0.25, 0.5)]
    out += [Case("sign_change", "one flip in the middle", flip=True)]
    if CONDITIONS[name]["quantization_bits"] is not None:
        out += [Case("quantisation", "10 bit", quantise=True)]
    out += [Case("all", "0.5 step, 0.5 sample, flip, 10 bit", 0.5, 0.5, True, True)]
    return out


@contextmanager
def _signal_without_data():
    """Make the simulator build the satellite without navigation data."""
    module = sys.modules["snappnt.sim.generate"]

    def loader(name: str):
        return replace(load_signal(name), symbol_rate_hz=None)

    with mock.patch.object(module, "load_signal", loader):
        yield


def make_snapshot(name: str, case: Case, cn0_dbhz: float, seed: int, n_blocks: int):
    """Return (samples, scenario, truth satellite, frequency step in Hz)."""
    cond = CONDITIONS[name]
    scn = load_scenario(SCENARIOS / cond["file"])
    spec = load_signal(scn.signal)
    fs = scn.receiver.sample_rate_hz
    n = scn.receiver.n_samples
    step_hz = 1.0 / (2.0 * (n // n_blocks) / fs)
    chips_per_sample = spec.chip_rate_hz / fs
    sat = SatelliteTruth(
        prn=scn.satellites[0].prn,
        cn0_dbhz=cn0_dbhz,
        doppler_hz=case.freq_frac * step_hz,
        code_phase_chips=(cond["code_phase_chips"] + case.code_frac * chips_per_sample)
        % spec.code_length,
    )
    rx = replace(scn.receiver, clock_offset_ppm=0.0, quantization_bits=None)
    scn = replace(scn, receiver=rx, satellites=(sat,), seed=seed)
    with _signal_without_data():
        x, truth = generate(scn)
        noise, _ = generate(replace(scn, satellites=()))
    if case.flip:
        period = int(np.ceil(spec.code_period_s * fs))
        first_edge = round((spec.code_length - sat.code_phase_chips) / chips_per_sample)
        edges = first_edge % period + period * np.arange(-1, n // period + 2)
        edge = int(edges[np.argmin(np.abs(edges - n / 2))])
        signal = x - noise
        signal[edge:] *= -1.0
        x = (noise + signal).astype(np.complex64)
    if case.quantise:
        x = quantize(x, cond["quantization_bits"], scn.receiver.agc_backoff_db)
    return x, scn, truth["satellites"][0], step_hz


def measure(
    name: str,
    case: Case,
    cn0_dbhz: float,
    n_trials: int,
    n_blocks: int,
    *,
    refine: bool = False,
    seed0: int = 1000,
) -> dict:
    """Run ``n_trials`` snapshots (seeds seed0, seed0 + 1, ...) and summarise them."""
    cond = CONDITIONS[name]
    spec = load_signal(load_scenario(SCENARIOS / cond["file"]).signal)
    bias, code_err, freq_err, detected = [], [], [], []
    for i in range(n_trials):
        x, scn, sat, step_hz = make_snapshot(name, case, cn0_dbhz, seed0 + i, n_blocks)
        half_range_hz = cond["half_range_bins"] * step_hz
        res = acquire(
            x,
            scn.receiver.sample_rate_hz,
            spec,
            sat["prn"],
            freq_range_hz=(-half_range_hz, half_range_hz),
            n_blocks=n_blocks,
            refine=refine,
        )
        d_code = abs(res.code_phase_chips - sat["code_phase_chips"])
        code_err.append(min(d_code, spec.code_length - d_code))
        freq_err.append(abs(res.freq_offset_hz - sat["expected_freq_offset_hz"]))
        bias.append(res.cn0_dbhz_est - cn0_dbhz)
        detected.append(res.detected)
    bias = np.asarray(bias)
    return {
        "trials": n_trials,
        "bias_mean_db": float(bias.mean()),
        "bias_se_db": float(bias.std(ddof=1) / np.sqrt(n_trials)) if n_trials > 1 else 0.0,
        "p_detect": float(np.mean(detected)),
        "abs_code_err_chips": float(np.mean(code_err)),
        "abs_freq_err_hz": float(np.mean(freq_err)),
    }


# ----------------------------------------------------------------------------------------
# Tests


def test_parabolic_offset_recovers_vertex_of_a_parabola():
    for vertex in (-0.4, -0.1, 0.0, 0.3, 0.5):
        y = [-((s - vertex) ** 2) + 5.0 for s in (-1, 0, 1)]
        assert parabolic_offset(*y) == pytest.approx(vertex, abs=1e-12)


def test_parabolic_offset_flat_or_convex_data_gives_zero():
    assert parabolic_offset(1.0, 1.0, 1.0) == 0.0
    assert parabolic_offset(2.0, 1.0, 2.0) == 0.0


def test_parabolic_offset_is_limited_to_half_a_sample():
    assert parabolic_offset(0.0, 1.0, 0.999999) <= 0.5
    assert parabolic_offset(0.999999, 1.0, 0.0) >= -0.5


def _acquire_ideal(x, scn, **kwargs):
    spec = load_signal(scn.signal)
    return acquire(
        x,
        scn.receiver.sample_rate_hz,
        spec,
        scn.satellites[0].prn,
        freq_range_hz=(-2e3, 2e3),
        **kwargs,
    )


def test_refine_default_is_unchanged():
    case = Case("frequency", "0.3 step", freq_frac=0.3, code_frac=0.3)
    x, scn, _, _ = make_snapshot("navic_s_ideal", case, 50.0, seed=7, n_blocks=1)
    default = _acquire_ideal(x, scn)
    assert _acquire_ideal(x, scn, refine=False) == default
    refined = _acquire_ideal(x, scn, refine=True)
    for field in ("prn", "detected", "metric", "threshold", "cn0_dbhz_est", "n_cells"):
        assert getattr(refined, field) == getattr(default, field)
    assert refined.freq_step_hz == default.freq_step_hz
    assert refined.coherent_time_s == default.coherent_time_s


@pytest.mark.parametrize("freq_frac", [-0.5, -0.3, 0.1, 0.25, 0.5])
@pytest.mark.parametrize("code_frac", [-0.5, 0.2, 0.5])
def test_refine_accuracy(freq_frac, code_frac):
    """At 60 dB-Hz refinement gives < 0.1 chip and < a quarter of the frequency step."""
    for seed in (1, 2):
        case = Case("accuracy", "", freq_frac=freq_frac, code_frac=code_frac)
        # A bin-centre frequency is a whole number of steps; the offsets above are in steps
        # from the bin at 0 Hz, which is a bin centre.
        x, scn, sat, step_hz = make_snapshot("navic_s_ideal", case, 60.0, seed, n_blocks=1)
        res = _acquire_ideal(x, scn, refine=True)
        d_code = abs(res.code_phase_chips - sat["code_phase_chips"])
        d_code = min(d_code, 1023 - d_code)
        assert res.detected
        assert d_code < 0.1
        assert abs(res.freq_offset_hz - sat["expected_freq_offset_hz"]) < step_hz / 4.0


def test_refine_improves_frequency_error_between_bins():
    case = Case("frequency", "0.5 step", freq_frac=0.5)
    errs = {}
    for refine in (False, True):
        errs[refine] = measure("navic_s_ideal", case, 60.0, 4, 1, refine=refine)["abs_freq_err_hz"]
    assert errs[True] < errs[False] / 2.0


@pytest.mark.loopback
def test_baseline_bias_is_negative_and_bounded():
    """Regression guard for the baseline row of docs/results/cn0-bias.md (loose bounds)."""
    row = measure("navic_s_ideal", Case("baseline", "none"), 45.0, 6, 1)
    assert row["p_detect"] == 1.0
    assert -6.0 < row["bias_mean_db"] < 0.0


def test_results_csv_has_one_row_per_cause_and_condition():
    with CSV_PATH.open(newline="") as f:
        rows = list(csv.DictReader(f))
    assert list(rows[0]) == CSV_COLUMNS
    for name, cond in CONDITIONS.items():
        for n_blocks in cond["n_blocks"]:
            expected = {(c.cause, c.setting) for c in cases_for(name, n_blocks)}
            found = {
                (r["cause"], r["setting"])
                for r in rows
                if r["condition"] == name and r["n_blocks"] == str(n_blocks)
            }
            assert found == expected, (name, n_blocks)
    assert {r["cause"] for r in rows} == set(CAUSES)


# ----------------------------------------------------------------------------------------
# Reproduction of docs/results/cn0_bias.csv

TRUE_CN0_DBHZ = {"navic_s_ideal": 45.0, "navic_s_esp32c3": 58.0}


SIDELOBE_CSV_PATH = ROOT / "docs" / "results" / "cn0_bias_baseline_vs_cn0.csv"


def baseline_versus_cn0(n_trials: int = 100) -> None:
    """Baseline bias of both conditions at several true C/N0 (docs/results/cn0-bias.md)."""
    grid = {
        "navic_s_ideal": (35.0, 40.0, 45.0, 50.0, 55.0),
        "navic_s_esp32c3": (50, 54, 58, 62, 66),
    }
    with SIDELOBE_CSV_PATH.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["condition", "n_blocks", "cn0_dbhz", "trials", "bias_mean_db", "bias_se_db"])
        for name, cn0_list in grid.items():
            for cn0 in cn0_list:
                r = measure(name, Case("baseline", "none"), float(cn0), n_trials, 1)
                w.writerow(
                    [name, 1, cn0, n_trials, f"{r['bias_mean_db']:.4f}", f"{r['bias_se_db']:.4f}"]
                )
                print(name, cn0, r, flush=True)


def main(n_trials: int = 50, only: str | None = None) -> None:
    CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    existing = []
    if CSV_PATH.exists() and only is not None:
        with CSV_PATH.open(newline="") as f:
            existing = [r for r in csv.DictReader(f) if r["condition"] != only]
    rows = existing
    for name, cond in CONDITIONS.items():
        if only is not None and name != only:
            continue
        for n_blocks in cond["n_blocks"]:
            for case in cases_for(name, n_blocks):
                for refine in (False, True):
                    t0 = time.time()
                    stats_ = measure(
                        name,
                        case,
                        TRUE_CN0_DBHZ[name],
                        n_trials,
                        n_blocks,
                        refine=refine,
                    )
                    row = {
                        "condition": name,
                        "n_blocks": n_blocks,
                        "cause": case.cause,
                        "setting": case.setting,
                        "refine": int(refine),
                        **stats_,
                    }
                    rows.append(row)
                    print(row, f"{time.time() - t0:.0f} s", flush=True)
    with CSV_PATH.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        w.writeheader()
        for r in rows:
            w.writerow(
                {
                    k: (f"{v:.4f}" if isinstance(v, float) else v)
                    for k, v in ((c, r[c]) for c in CSV_COLUMNS)
                }
            )


if __name__ == "__main__":
    if sys.argv[1:2] == ["baseline_versus_cn0"]:
        baseline_versus_cn0()
        sys.exit(0)
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 50, sys.argv[2] if len(sys.argv) > 2 else None)
