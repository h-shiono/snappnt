"""tools/conducted_pd.py. Expected values are worked by hand (see the comments) or come from
simulated recordings whose truth is known."""

from __future__ import annotations

import importlib.util
import math
import sys
from pathlib import Path

import numpy as np
import pytest

from snappnt.io import write_sigmf
from snappnt.sim import generate, load_scenario

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("conducted_pd", ROOT / "tools" / "conducted_pd.py")
cpd = importlib.util.module_from_spec(_spec)
sys.modules["conducted_pd"] = cpd
_spec.loader.exec_module(cpd)


# --- rise -----------------------------------------------------------------------------------


def test_band_mask_excludes_lo_and_dc():
    f = np.arange(-10, 11) * 0.1e6  # -1.0 .. +1.0 MHz in 100 kHz steps
    m = cpd.band_mask(f, gen_center_hz=-0.5e6, half_band_hz=0.4e6, exclude_hz=0.15e6)
    # Inside the band: -0.9 .. -0.1 MHz. LO bins: -0.6 .. -0.4 MHz. DC bins: -0.1 .. +0.1 MHz.
    kept = np.round(f[m] / 1e6, 1).tolist()
    assert kept == [-0.9, -0.8, -0.7, -0.3, -0.2]


def test_band_rise_db():
    off = np.ones(8)
    on = np.full(8, 10.0)
    on[0] = 1000.0  # an excluded bin must not count
    mask = np.ones(8, dtype=bool)
    mask[0] = False
    assert cpd.band_rise_db(on, off, mask) == pytest.approx(10.0)


def test_at_limit_fraction():
    x = np.array([0, 511, -512 + 3j, 10 - 512j], dtype=np.complex64)
    assert cpd.at_limit_fraction(x) == pytest.approx(0.75)
    assert cpd.at_limit_fraction(x, -1000, 1000) == 0.0


def test_load_set_long_recording_in_segments(tmp_path):
    rng = np.random.default_rng(1)
    x = (rng.standard_normal(300_000) + 1j * rng.standard_normal(300_000)).astype(np.complex64)
    write_sigmf(tmp_path / "long", x * 10, 1e6, center_frequency_hz=2.49e9, datatype="ci8")
    psd, fs, worst = cpd.load_set(tmp_path / "long", -128, 127)
    assert fs == 1e6
    assert psd.shape == (cpd.FFT_SIZE,)
    assert worst == 0.0


# --- pd -------------------------------------------------------------------------------------


def _row(run, detected, freq_hz, metric=30.0, step_hz=2442.0, n_cells=1000):
    return {
        "run": run,
        "capture": f"{run}_x",
        "detected": int(detected),
        "metric": metric,
        "threshold": 20.0,
        "n_cells": n_cells,
        "freq_offset_hz": freq_hz,
        "freq_step_hz": step_hz,
        "code_phase_chips": 0.0,
        "cn0_dbhz_est": 0.0,
    }


def test_evaluate_run_one_bin_tolerance():
    step = 2442.0
    by_run = {
        "pre": [_row("pre", 1, 10 * step)] * 3,
        "post": [_row("post", 1, 10 * step)] * 3,
        "run": [
            _row("run", 1, 10 * step),  # at the reference: detection
            _row("run", 1, 11 * step),  # one bin away: detection
            _row("run", 1, 12 * step),  # two bins away: wrong detection
            _row("run", 0, 10 * step),  # below threshold: missed
        ],
    }
    res = cpd.evaluate_run(cpd.RunSpec("run", "52", "pre", "post"), by_run)
    assert (res.trials, res.detections, res.wrong, res.tol_bins) == (4, 2, 1, 1)
    assert res.ref_freq_hz == pytest.approx(10 * step)
    assert res.drift_hz == 0.0


def test_evaluate_run_widens_tolerance_after_drift():
    step = 2442.0
    by_run = {
        "pre": [_row("pre", 1, 10 * step)],
        "post": [_row("post", 1, 12 * step)],  # drift of two bins between the brackets
        "run": [_row("run", 1, 13 * step), _row("run", 1, 14 * step)],
    }
    res = cpd.evaluate_run(cpd.RunSpec("run", "52", "pre", "post"), by_run)
    # Reference = 11 bins; tolerance two bins: 13 is inside, 14 is not.
    assert res.tol_bins == 2
    assert res.ref_freq_hz == pytest.approx(11 * step)
    assert (res.detections, res.wrong) == (1, 1)


def test_bracket_without_detection_is_an_error():
    with pytest.raises(ValueError):
        cpd.bracket_freq_hz([_row("pre", 0, 0.0)])


def test_null_cdf():
    # One cell: unit-mean exponential, F(m) = 1 - exp(-m).
    assert cpd.null_cdf(np.array([1.0]), 1)[0] == pytest.approx(1 - math.exp(-1))
    # n cells: F(m) = (1 - exp(-m))^n; at m = ln(n) this is (1 - 1/n)^n.
    assert cpd.null_cdf(np.array([math.log(1000)]), 1000)[0] == pytest.approx((1 - 1e-3) ** 1000)


def test_noise_check_upper_bound():
    rows = [_row("noise", 0, 0.0, metric=m) for m in np.linspace(5, 15, 200)]
    nc = cpd.noise_check(rows)
    # No false alarm in 200 trials: one-sided 95 % Clopper-Pearson limit 1 - 0.05^(1/200).
    assert nc["false_alarms"] == 0
    assert nc["pfa_upper_95"] == pytest.approx(1 - 0.05 ** (1 / 200), rel=1e-6)
    # Median of the largest of 1000 unit exponentials: -ln(1 - 0.5^(1/1000)).
    assert nc["median_metric_null"] == pytest.approx(-math.log(1 - 0.5 ** (1 / 1000)))


def test_crossing_dbhz():
    cn0 = np.array([50.0, 51.0, 52.0])
    pd = np.array([0.2, 0.6, 0.95])
    assert cpd.crossing_dbhz(cn0, pd, 0.5) == pytest.approx(50.75)
    assert cpd.crossing_dbhz(cn0, pd, 0.99) is None


# --- acquire and cn0 on simulated recordings --------------------------------------------------


def _scenario(tmp_path, cn0_dbhz, n_samples, fs, offset_hz, seed):
    sats = f"  - {{prn: 10, cn0_dbhz: {cn0_dbhz}, doppler_hz: 0, code_phase_chips: 300.0}}"
    text = (
        f"name: t\nsignal: navic_s_sps\nseed: {seed}\nreceiver:\n"
        f"  sample_rate_hz: {fs}\n  n_samples: {n_samples}\n"
        f"  baseband_offset_hz: {offset_hz}\n  clock_offset_ppm: 0\n"
        f"satellites:\n{sats}\n"
    )
    p = tmp_path / f"s{seed}.yaml"
    p.write_text(text)
    return load_scenario(p)


def test_acquire_dir_on_simulated_captures(tmp_path):
    d = tmp_path / "run"
    d.mkdir()
    for seed in range(3):
        x, meta = generate(_scenario(tmp_path, 60, 16380, 80e6, 28000, seed))
        write_sigmf(d / f"c_{seed}", x, 80e6, center_frequency_hz=2492e6)
    rows = cpd.acquire_dir(
        d, prn=10, signal="navic_s_sps", center_hz=28000, freq_span_hz=10000,
        remove_dc="mean", pfa=1e-3,
    )  # fmt: skip
    assert len(rows) == 3
    assert all(r["detected"] == 1 for r in rows)
    # The carrier is exactly at the centre (0 Hz); the grid starts at -10 kHz, so the nearest
    # grid point is within half a step of 0 Hz. Code phase 300 chips.
    assert all(abs(r["freq_offset_hz"]) <= r["freq_step_hz"] / 2 for r in rows)
    assert all(abs(r["code_phase_chips"] - 300.0) < 0.1 for r in rows)


def test_m2m4_snr():
    rng = np.random.default_rng(3)
    n = rng.standard_normal(200_000) + 1j * rng.standard_normal(200_000)  # power 2
    phase = np.exp(2j * np.pi * rng.random(200_000))
    y = 10.0 * phase + n  # signal power 100: SNR 50
    assert cpd.m2m4_snr(y) == pytest.approx(50.0, rel=0.03)


def test_estimate_cn0_tracks_scenario_difference(tmp_path):
    """The estimate is lowered by correlation losses, but by the same amount for two
    recordings processed alike, so a 10 dB difference in the scenario reads as 10 dB."""
    fs = 4e6
    est = []
    for cn0 in (60, 50):
        x, _ = generate(_scenario(tmp_path, cn0, 400_000, fs, 0, 7))
        r = cpd.estimate_cn0(x, fs, _spec_navic(), 10, carrier_hz=0.0, n_blocks=100)
        assert r["carrier_hz"] == 0.0
        est.append(r["cn0_dbhz"])
    assert est[0] - est[1] == pytest.approx(10.0, abs=0.3)
    assert 58.5 < est[0] < 60.3


def _spec_navic():
    from snappnt.signals import load_signal

    return load_signal("navic_s_sps")
