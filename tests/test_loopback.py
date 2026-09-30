"""One full loop: simulator -> (SigMF) -> acquisition -> comparison with truth.

These are the tests CI must keep green: if a change breaks the code generator, the
simulator or the acquisition, the truth comparison fails here.
"""

from dataclasses import replace
from pathlib import Path

import pytest

from snappnt.eval import is_correct
from snappnt.io import get_truth, read_sigmf, write_sigmf
from snappnt.rx import acquire
from snappnt.signals import load_signal
from snappnt.sim import generate, load_scenario

SCENARIOS = Path(__file__).resolve().parents[1] / "scenarios"


def _run(scn, **acq_kwargs):
    spec = load_signal(scn.signal)
    x, truth = generate(scn)
    sat = truth["satellites"][0]
    res = acquire(
        x,
        scn.receiver.sample_rate_hz,
        spec,
        sat["prn"],
        center_offset_hz=scn.receiver.baseband_offset_hz,
        **acq_kwargs,
    )
    return spec, res, sat


@pytest.mark.loopback
def test_ideal_4ms():
    scn = load_scenario(SCENARIOS / "navic_s_ideal.yaml")
    spec, res, sat = _run(scn, freq_range_hz=(-2e3, 2e3))
    assert res.detected
    assert is_correct(res, sat, spec.code_length, code_tol_chips=0.5)


@pytest.mark.loopback
def test_esp32c3_snapshot_shorter_than_code_period():
    scn = load_scenario(SCENARIOS / "navic_s_esp32c3.yaml")
    assert scn.duration_s < load_signal(scn.signal).code_period_s
    spec, res, sat = _run(scn, freq_range_hz=(-40e3, 40e3))
    assert res.detected
    assert is_correct(res, sat, spec.code_length, code_tol_chips=0.5)


@pytest.mark.loopback
def test_noise_only_is_not_detected():
    scn = load_scenario(SCENARIOS / "navic_s_ideal.yaml")
    scn = replace(scn, satellites=(replace(scn.satellites[0], cn0_dbhz=-50.0),), seed=123)
    _, res, _ = _run(scn, freq_range_hz=(-2e3, 2e3))
    assert not res.detected


@pytest.mark.loopback
def test_noncoherent_blocks():
    scn = load_scenario(SCENARIOS / "navic_s_ideal.yaml")
    spec, res, sat = _run(scn, freq_range_hz=(-1e3, 1e3), n_blocks=4)
    assert res.detected
    assert is_correct(res, sat, spec.code_length, code_tol_chips=0.5)


@pytest.mark.loopback
def test_through_sigmf(tmp_path):
    scn = load_scenario(SCENARIOS / "navic_s_ideal.yaml")
    x, truth = generate(scn)
    base = write_sigmf(tmp_path / "run.1", x, scn.receiver.sample_rate_hz, truth=truth)
    y, meta = read_sigmf(str(base) + ".sigmf-meta")
    t = get_truth(meta)
    spec = load_signal(t["signal"])
    sat = t["satellites"][0]
    res = acquire(
        y, meta["global"]["core:sample_rate"], spec, sat["prn"], freq_range_hz=(-2e3, 2e3)
    )
    assert res.detected and is_correct(res, sat, spec.code_length, 0.5)
