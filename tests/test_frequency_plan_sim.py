"""External-mixer frequency plans in the simulator: sign of Doppler, LO error, baseband offset."""

from dataclasses import replace
from pathlib import Path

import pytest

from snappnt.eval import is_correct
from snappnt.rx import acquire
from snappnt.signals import load_signal
from snappnt.sim import generate, load_scenario
from snappnt.sim.generate import expected_frequency_offset_hz
from snappnt.sim.scenario import scenario_from_dict

SCENARIOS = Path(__file__).resolve().parents[1] / "scenarios"
LOW = SCENARIOS / "cband_bpsk_generic_lowside.yaml"
HIGH = SCENARIOS / "cband_bpsk_generic_highside.yaml"
TUNED_HZ = 2484e6


def _with(scn, doppler_hz=None, **rx_changes):
    sats = scn.satellites
    if doppler_hz is not None:
        sats = (replace(sats[0], doppler_hz=doppler_hz),)
    return replace(scn, satellites=sats, receiver=replace(scn.receiver, **rx_changes))


def _acquire(scn):
    spec = load_signal(scn.signal)
    x, truth = generate(scn)
    sat = truth["satellites"][0]
    res = acquire(
        x,
        scn.receiver.sample_rate_hz,
        spec,
        sat["prn"],
        center_offset_hz=scn.receiver.baseband_offset_hz,
        freq_range_hz=(-60e3, 60e3),
    )
    return spec, res, sat, truth


@pytest.mark.loopback
@pytest.mark.parametrize("path", [LOW, HIGH], ids=["low-side", "high-side"])
def test_loop_with_plan(path):
    spec, res, sat, _ = _acquire(load_scenario(path))
    assert res.detected
    assert is_correct(res, sat, spec.code_length, code_tol_chips=0.5)


@pytest.mark.loopback
def test_high_side_positive_doppler_is_negative_offset():
    spec, res, sat, _ = _acquire(_with(load_scenario(HIGH), doppler_hz=20e3))
    assert sat["expected_freq_offset_hz"] == -20e3
    assert res.detected
    assert res.freq_offset_hz < 0
    assert abs(res.freq_offset_hz + 20e3) <= res.freq_step_hz
    assert is_correct(res, sat, spec.code_length, code_tol_chips=0.5)


@pytest.mark.loopback
def test_low_side_positive_doppler_is_positive_offset():
    _, res, sat, _ = _acquire(_with(load_scenario(LOW), doppler_hz=20e3))
    assert sat["expected_freq_offset_hz"] == 20e3
    assert res.detected
    assert abs(res.freq_offset_hz - 20e3) <= res.freq_step_hz


@pytest.mark.loopback
@pytest.mark.parametrize("path", [LOW, HIGH], ids=["low-side", "high-side"])
def test_loop_with_lo_and_crystal_errors(path):
    scn = _with(load_scenario(path), clock_offset_ppm=3.0, lo_offset_ppm=2.0)
    spec, res, sat, _ = _acquire(scn)
    assert res.detected
    assert is_correct(res, sat, spec.code_length, code_tol_chips=0.5)


@pytest.mark.parametrize(
    "path, lo_hz, sign", [(LOW, 2536e6, 1), (HIGH, 7504e6, -1)], ids=["low-side", "high-side"]
)
def test_ppm_errors_formula(path, lo_hz, sign):
    base = load_scenario(path)
    # Crystal error acts on the tuned frequency: -3 ppm of 2484 MHz.
    scn = _with(base, doppler_hz=0.0, clock_offset_ppm=3.0)
    assert expected_frequency_offset_hz(scn, 0.0, 5020e6) == pytest.approx(-3e-6 * TUNED_HZ)
    # LO error: low side shifts the IF by -delta, high side by +delta.
    scn = _with(base, doppler_hz=0.0, lo_offset_ppm=2.0)
    assert expected_frequency_offset_hz(scn, 0.0, 5020e6) == pytest.approx(-sign * 2e-6 * lo_hz)
    # Both together, with Doppler.
    scn = _with(base, clock_offset_ppm=3.0, lo_offset_ppm=2.0)
    expected = sign * 1000.0 - 3e-6 * TUNED_HZ - sign * 2e-6 * lo_hz
    assert expected_frequency_offset_hz(scn, 1000.0, 5020e6) == pytest.approx(expected)


def test_truth_records_plan():
    _, truth = generate(_with(load_scenario(HIGH), lo_offset_ppm=1.0))
    plan = truth["frequency_plan"]
    assert (plan["rf_hz"], plan["lo_hz"], plan["lo_side"]) == (5020e6, 7504e6, "high")
    assert plan["tuned_hz"] == TUNED_HZ and plan["if_hz"] == 2484e6
    assert truth["lo_offset_ppm"] == 1.0
    sat = truth["satellites"][0]
    assert sat["expected_freq_offset_hz"] == pytest.approx(-20e3 + 1e-6 * 7504e6)


def _plan_dict(tuned_hz, **receiver):
    return {
        "name": "t",
        "signal": "cband_bpsk_generic",
        "frequency_plan": {"lo_hz": 2536e6, "lo_side": "low", "tuned_hz": tuned_hz},
        "receiver": {"sample_rate_hz": 8184000, "n_samples": 8184, **receiver},
        "satellites": [{"prn": 5, "cn0_dbhz": 50}],
    }


def test_baseband_offset_comes_from_plan():
    scn = scenario_from_dict(_plan_dict(2480e6))
    assert scn.frequency_plan.baseband_offset_hz == 4e6
    assert scn.receiver.baseband_offset_hz == 4e6


def test_plan_with_explicit_baseband_offset_is_an_error():
    with pytest.raises(ValueError, match="baseband_offset_hz"):
        scenario_from_dict(_plan_dict(2484e6, baseband_offset_hz=0))


def test_lo_offset_without_plan_is_an_error():
    d = _plan_dict(2484e6, lo_offset_ppm=1.0)
    del d["frequency_plan"]
    with pytest.raises(ValueError, match="lo_offset_ppm"):
        scenario_from_dict(d)


@pytest.mark.parametrize("path", sorted(SCENARIOS.glob("navic_*.yaml")), ids=lambda p: p.stem)
def test_existing_scenarios_have_no_plan(path):
    scn = load_scenario(path)
    assert scn.frequency_plan is None
    assert scn.receiver.lo_offset_ppm == 0.0
    spec = load_signal(scn.signal)
    expected = 500.0 - scn.receiver.clock_offset_ppm * 1e-6 * spec.carrier_hz
    assert expected_frequency_offset_hz(scn, 500.0, spec.carrier_hz) == pytest.approx(expected)
