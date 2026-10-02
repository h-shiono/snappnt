"""DC offset removal before acquisition (issue #43)."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from snappnt import cli
from snappnt.rx import acquire
from snappnt.rx.acquisition import remove_dc_offset
from snappnt.signals import load_signal
from snappnt.sim import generate, load_scenario

SCENARIOS = Path(__file__).resolve().parents[1] / "scenarios"
SPEC = load_signal("navic_s_sps")
FREQ = (-40e3, 40e3)


def _scenario(dc: bool, cn0_dbhz: float = 55.0):
    """The ESP32-C3 scenario with or without the DC offset, with no spur, same seed."""
    scn = load_scenario(SCENARIOS / "navic_s_esp32c3_dc.yaml")
    sat = replace(scn.satellites[0], cn0_dbhz=cn0_dbhz)
    rx = replace(scn.receiver, spurs=())
    if not dc:
        rx = replace(rx, dc_offset_i=None, dc_offset_q=None)
    return replace(scn, receiver=rx, satellites=(sat,))


def _acquire(x, scn, **kw):
    return acquire(
        x,
        scn.receiver.sample_rate_hz,
        SPEC,
        scn.satellites[0].prn,
        center_offset_hz=scn.receiver.baseband_offset_hz,
        freq_range_hz=FREQ,
        **kw,
    )


@pytest.fixture(scope="module")
def metrics():
    with_dc, truth = generate(_scenario(dc=True))
    without_dc, _ = generate(_scenario(dc=False))
    scn = _scenario(dc=True)
    return {
        "dc_none": _acquire(with_dc, scn).metric,
        "dc_mean": _acquire(with_dc, scn, remove_dc="mean").metric,
        "clean": _acquire(without_dc, scn).metric,
    }


def test_mean_removal_restores_the_metric(metrics):
    # Measured when written: see the assertion message for the values on failure.
    rel = abs(metrics["dc_mean"] - metrics["clean"]) / metrics["clean"]
    assert rel < 0.05, metrics


def test_without_removal_the_offset_lowers_the_metric(metrics):
    assert metrics["dc_none"] < 0.9 * metrics["clean"], metrics


def test_noise_only_peak_moves_between_seeds_only_with_removal():
    """The DC offset puts the largest cell at the same code phase whatever the noise (the
    frequency alternates between two nearly equal bins); after removal the peak is a noise
    peak whose code phase changes with the seed. Asserted for seeds 0 to 7 below; measured once
    with seeds 0 to 11: about 179 chips without removal in 11 of 12 seeds, and 12 different
    values with removal."""
    scn = load_scenario(SCENARIOS / "navic_s_esp32c3_dc.yaml")
    rx = replace(scn.receiver, spurs=())
    peaks = {"none": [], "mean": []}
    for seed in range(8):
        x, _ = generate(replace(scn, receiver=rx, satellites=(), seed=seed))
        for mode in peaks:
            r = _acquire(x, scn, remove_dc=mode)
            peaks[mode].append(r.code_phase_chips)
    near = {m: sum(abs(c - 179.2) < 3.0 for c in v) for m, v in peaks.items()}
    assert near["none"] >= 6, peaks  # measured: 7 of 8 (seed 3 peaks elsewhere, at 78 chips)
    assert near["mean"] <= 1, peaks


def test_linear_removes_a_drift_that_mean_leaves():
    n = 16384
    rng = np.random.default_rng(1)
    noise = (rng.normal(size=n) + 1j * rng.normal(size=n)).astype(np.complex64)
    drift = (np.linspace(-20.0, 20.0, n) + 1j * np.linspace(10.0, -10.0, n)).astype(np.complex64)
    x = noise + 100.0 + drift
    by_mean = remove_dc_offset(x, "mean")
    by_line = remove_dc_offset(x, "linear")
    assert np.abs(np.mean(by_line)) < 0.05
    assert np.std(by_line) < 1.5  # noise only (std sqrt(2) for I + jQ)
    assert np.std(by_mean) > 10.0  # the ramp is still there
    assert by_mean.dtype == by_line.dtype == np.complex64


def test_none_is_identical_to_not_passing_the_parameter():
    x, _ = generate(_scenario(dc=True))
    scn = _scenario(dc=True)
    assert _acquire(x, scn) == _acquire(x, scn, remove_dc="none")
    assert remove_dc_offset(x, "none") is x or np.array_equal(remove_dc_offset(x, "none"), x)


def test_does_not_modify_the_input():
    x, _ = generate(_scenario(dc=True))
    before = x.copy()
    for mode in ("mean", "linear"):
        remove_dc_offset(x, mode)
    assert np.array_equal(x, before)


def test_invalid_value_raises():
    x, _ = generate(_scenario(dc=True))
    with pytest.raises(ValueError, match="remove_dc"):
        _acquire(x, _scenario(dc=True), remove_dc="median")


def test_cli_acquire_and_sweep_accept_the_option(tmp_path, capsys):
    out = tmp_path / "dc"
    scenario = str(SCENARIOS / "navic_s_esp32c3_dc.yaml")
    assert cli.main(["sim", scenario, "-o", str(out)]) == 0
    capsys.readouterr()
    args = ["acquire", str(out), "--prn", "10", "--freq-span", "40000"]
    assert cli.main([*args, "--remove-dc", "mean"]) == 0
    assert "OK" in capsys.readouterr().out
    csv = tmp_path / "pd.csv"
    sweep = ["sweep", scenario, "--cn0", "58:58:1", "--trials", "2", "--freq-span", "40000"]
    assert cli.main([*sweep, "--remove-dc", "linear", "-o", str(csv)]) == 0
    assert csv.exists()
    with pytest.raises(SystemExit):
        cli.main(["acquire", str(out), "--remove-dc", "median"])
