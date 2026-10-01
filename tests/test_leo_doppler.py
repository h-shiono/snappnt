"""LEO pass model, rate-mismatch loss and Doppler-rate search in acquisition."""

from __future__ import annotations

import numpy as np
import pytest

from snappnt.rx.acquisition import _rate_grid, acquire, detection_threshold
from snappnt.signals import load_signal
from snappnt.sim import generate, load_scenario
from snappnt.sim.leo import leo_pass_doppler, rate_mismatch_loss_db
from snappnt.sim.scenario import scenario_from_dict

CARRIER_HZ = 5.02e9


def _scenario(cn0_dbhz: float, n_samples: int, sat: dict):
    return scenario_from_dict(
        {
            "name": "leo_test",
            "signal": "cband_bpsk_generic",
            "seed": 16,
            "receiver": {"sample_rate_hz": 4092000, "n_samples": n_samples},
            "satellites": [{"prn": 5, "cn0_dbhz": cn0_dbhz, "code_phase_chips": 500.4, **sat}],
        }
    )


def test_pass_overhead_peak_rate_and_sign():
    t = np.linspace(-300.0, 300.0, 60001)
    doppler, rate = leo_pass_doppler(CARRIER_HZ, 550e3, 90.0, t)
    mid = t.size // 2
    assert abs(doppler[mid]) < 1e-6
    assert doppler[0] > 0 > doppler[-1]  # positive while approaching
    # Peak rate magnitude at closest approach: v^2 / h-type geometry gives 1.6 kHz/s here
    # (the model value, 1614 Hz/s); the issue's "about 1.7 kHz/s" is a rounded figure.
    assert abs(rate[mid]) == pytest.approx(1.7e3, rel=0.10)
    assert abs(rate).max() == pytest.approx(abs(rate[mid]), rel=1e-6)
    # Maximum Doppler near the horizon of an overhead pass is of the order of 100 kHz.
    assert 100e3 < doppler.max() < 130e3


def test_pass_rate_is_derivative_of_doppler():
    t = np.array([-120.0, -30.0, 5.0, 80.0])
    h = 1e-3
    d_plus, _ = leo_pass_doppler(CARRIER_HZ, 550e3, 40.0, t + h)
    d_minus, _ = leo_pass_doppler(CARRIER_HZ, 550e3, 40.0, t - h)
    _, rate = leo_pass_doppler(CARRIER_HZ, 550e3, 40.0, t)
    np.testing.assert_allclose(rate, (d_plus - d_minus) / (2 * h), rtol=1e-5)


def test_pass_rejects_bad_geometry():
    with pytest.raises(ValueError):
        leo_pass_doppler(CARRIER_HZ, 550e3, 0.0, 0.0)
    with pytest.raises(ValueError):
        leo_pass_doppler(CARRIER_HZ, -1.0, 45.0, 0.0)


def test_scenario_pass_fills_doppler():
    scn = load_scenario("scenarios/cband_leo_overhead.yaml")
    sat = scn.satellites[0]
    doppler, rate = leo_pass_doppler(CARRIER_HZ, 550e3, 90.0, -10.0)
    assert sat.doppler_hz == pytest.approx(float(doppler))
    assert sat.doppler_rate_hzps == pytest.approx(float(rate))


@pytest.mark.parametrize("key", ["doppler_hz", "doppler_rate_hzps"])
def test_scenario_pass_conflicts_with_explicit_doppler(key):
    sat = {"pass": {"altitude_m": 550e3, "max_elevation_deg": 90}, key: 1.0}
    with pytest.raises(ValueError, match="pass"):
        _scenario(50, 4092, sat)


def test_loss_formula():
    assert rate_mismatch_loss_db(0.01, 0.0) == 0.0
    # Small mismatch: loss grows with T^2 (quartic in the phase, so ~T^4 in dB for the
    # coherent sum; the quadratic-phase error itself grows with T^2).
    small = rate_mismatch_loss_db(0.004, 1500.0)
    assert small < 1e-3
    assert rate_mismatch_loss_db(0.008, 1500.0) == pytest.approx(16 * small, rel=0.02)
    # Symmetric in the sign of the error, and increasing at larger mismatch.
    assert rate_mismatch_loss_db(0.04, -1500.0) == rate_mismatch_loss_db(0.04, 1500.0)
    assert rate_mismatch_loss_db(0.08, 1500.0) > rate_mismatch_loss_db(0.04, 1500.0) > 1.0


def test_measured_loss_matches_analytic_loss():
    """Peak power with rate 0 versus the true rate, at high C/N0 and a fine frequency step."""
    scn = load_scenario("scenarios/cband_leo_overhead.yaml")
    x, _ = generate(scn)
    sat = scn.satellites[0]
    spec = load_signal(scn.signal)
    t_s = scn.duration_s
    kwargs = dict(
        freq_range_hz=(sat.doppler_hz - 100, sat.doppler_hz + 100), freq_step_hz=1 / (8 * t_s)
    )
    zero = acquire(x, scn.receiver.sample_rate_hz, spec, 5, **kwargs)
    true = acquire(
        x, scn.receiver.sample_rate_hz, spec, 5, doppler_rate_hzps=sat.doppler_rate_hzps, **kwargs
    )
    measured_db = 10 * np.log10((true.metric - 1) / (zero.metric - 1))
    analytic_db = rate_mismatch_loss_db(t_s, sat.doppler_rate_hzps)
    assert analytic_db > 1.0
    assert measured_db == pytest.approx(analytic_db, abs=0.3)


def test_rate_search_recovers_rate_where_zero_rate_loses_power():
    """80 ms at 34 dB-Hz with a rate of -1572 Hz/s: the zero-rate peak is more than 3 dB lower."""
    n_samples = 327360  # 80 ms
    scn = _scenario(34.0, n_samples, {"doppler_hz": 16000.0, "doppler_rate_hzps": -1572.0})
    x, meta = generate(scn)
    truth = meta["satellites"][0]["expected_doppler_rate_hzps"]
    spec = load_signal(scn.signal)
    fs = scn.receiver.sample_rate_hz
    freq_range = (16000.0 - 80.0, 16000.0 + 80.0)

    zero = acquire(x, fs, spec, 5, freq_range_hz=freq_range)
    assert zero.doppler_rate_hzps == 0.0 and zero.rate_step_hzps == 0.0

    found = acquire(x, fs, spec, 5, freq_range_hz=freq_range, rate_range_hzps=(-1900.0, -1300.0))
    assert found.detected
    # The power is flat near the true rate (the loss at one step is below 0.01 dB), so noise can
    # move the peak by a step; two steps is the tolerance.
    assert abs(found.doppler_rate_hzps - truth) <= 2 * found.rate_step_hzps
    # The spacing is even, covers the range exactly and is not coarser than the default step.
    assert 0.0 < found.rate_step_hzps <= 0.25 / found.coherent_time_s**2
    assert found.metric > 2.0 * zero.metric


def test_rate_search_counts_rate_hypotheses_in_false_alarm_threshold():
    n_samples = 8184
    scn = _scenario(30.0, n_samples, {})
    x, _ = generate(scn)
    spec = load_signal(scn.signal)
    fs = scn.receiver.sample_rate_hz
    one = acquire(x, fs, spec, 5, freq_range_hz=(-1000, 1000))
    many = acquire(
        x, fs, spec, 5, freq_range_hz=(-1000, 1000), rate_range_hzps=(-1e6, 1e6), rate_step_hzps=1e6
    )
    assert many.n_cells == 3 * one.n_cells
    assert many.threshold == pytest.approx(detection_threshold(many.n_cells, 1, 1e-3))
    assert many.threshold > one.threshold


@pytest.mark.parametrize("width", [600.0, 601.0, 37.5, 10.0, 0.0])
def test_rate_grid_stays_inside_range_and_includes_both_ends(width):
    lo = -1900.0
    rates, step = _rate_grid((lo, lo + width), 39.0, 0.01, 1)
    assert rates[0] == lo
    assert rates[-1] == pytest.approx(lo + width)
    assert rates.min() >= lo and rates.max() <= lo + width
    assert step <= 39.0
    if rates.size > 1:
        assert np.diff(rates) == pytest.approx(step)


def test_rate_grid_default_step_follows_snapshot_length_with_blocks():
    t_coh = 0.005
    _, one = _rate_grid((0.0, 1e5), None, t_coh, 1)
    _, sixteen = _rate_grid((0.0, 1e5), None, t_coh, 16)
    assert one <= 0.25 / t_coh**2
    assert sixteen <= 0.5 / (t_coh * 16 * t_coh)
    assert sixteen < one


@pytest.mark.parametrize(
    "rate_range, step",
    [((1.0, -1.0), 10.0), ((0.0, 100.0), 0.0), ((0.0, 100.0), -5.0), ((0.0, float("nan")), None)],
)
def test_rate_grid_rejects_invalid_input(rate_range, step):
    with pytest.raises(ValueError, match="rate_"):
        _rate_grid(rate_range, step, 0.01, 1)
