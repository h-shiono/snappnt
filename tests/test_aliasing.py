"""Band limiting and decimation of snapshots generated at a higher rate (issue #3)."""

from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from snappnt.eval import is_correct
from snappnt.rx import acquire
from snappnt.signals import load_signal
from snappnt.sim import generate, load_scenario
from snappnt.sim.impairments import lowpass
from snappnt.sim.scenario import scenario_from_dict

SCENARIOS = Path(__file__).resolve().parents[1] / "scenarios"


def _noise_only(method: str, bandwidth_hz: float, n_samples: int = 4096, seed: int = 1):
    scn = load_scenario(SCENARIOS / f"navic_s_esp32c61_aliasing_{method}.yaml")
    rx = replace(
        scn.receiver,
        n_samples=n_samples,
        analog_bandwidth_hz=bandwidth_hz,
        quantization_bits=None,  # the AGC would rescale both methods to the same power
    )
    return replace(scn, receiver=rx, satellites=(), seed=seed)


def test_lowpass_keeps_in_band_tone_and_removes_out_of_band_tone():
    fs = 80e6
    n = 8192
    t = np.arange(n) / fs
    in_band = np.exp(2j * np.pi * (100 * fs / n) * t)
    out_of_band = np.exp(2j * np.pi * (1024 * fs / n) * t)
    # Tones at 0.98 MHz and 10 MHz are exact FFT bins, so the filter leaks nothing.
    assert np.allclose(lowpass(in_band, fs, 13e6), in_band)
    assert np.max(np.abs(lowpass(out_of_band, fs, 13e6))) < 1e-9


def test_lowpass_with_bandwidth_at_or_above_rate_is_identity():
    x = np.arange(16, dtype=complex)
    assert lowpass(x, 4e6, 4e6) is x


@pytest.mark.parametrize("bandwidth_hz", [13e6, 20e6])
def test_none_to_ideal_noise_power_ratio_is_bandwidth_over_output_rate(bandwidth_hz):
    ratios = []
    for seed in range(1, 6):
        p_none = np.mean(np.abs(generate(_noise_only("none", bandwidth_hz, seed=seed))[0]) ** 2)
        p_ideal = np.mean(np.abs(generate(_noise_only("ideal", bandwidth_hz, seed=seed))[0]) ** 2)
        ratios.append(p_none / p_ideal)
    expected = bandwidth_hz / 4e6
    assert np.mean(ratios) == pytest.approx(expected, rel=0.10)


def test_generate_rate_must_match_factor():
    scn = load_scenario(SCENARIOS / "navic_s_esp32c61_aliasing_none.yaml")
    d = {
        "name": "bad",
        "signal": "navic_s_sps",
        "receiver": {
            "sample_rate_hz": 4e6,
            "n_samples": 1024,
            "generate_rate_hz": 40e6,
            "decimation": {"factor": 20, "method": "none"},
        },
    }
    with pytest.raises(ValueError, match="generate_rate_hz"):
        scenario_from_dict(d)
    assert scn.receiver.generate_rate_hz == 80e6


def test_unknown_method_raises():
    d = {
        "name": "bad",
        "signal": "navic_s_sps",
        "receiver": {
            "sample_rate_hz": 4e6,
            "n_samples": 1024,
            "decimation": {"factor": 20, "method": "sinc"},
        },
    }
    with pytest.raises(ValueError, match="method"):
        scenario_from_dict(d)


def test_device_gives_lower_analog_bandwidth_and_explicit_value_overrides():
    base = {"name": "s", "signal": "navic_s_sps", "receiver": {"device": "esp32c61"}}
    assert scenario_from_dict(base).receiver.analog_bandwidth_hz == 13e6
    base["receiver"]["analog_bandwidth_hz"] = 20e6
    assert scenario_from_dict(base).receiver.analog_bandwidth_hz == 20e6


def test_scenarios_without_the_new_keys_are_unchanged():
    # Noise-only output of the direct path is the plain unit-variance generator stream.
    scn = load_scenario(SCENARIOS / "navic_s_esp32c61_4msps.yaml")
    assert scn.receiver.generate_rate_hz is None
    scn = replace(
        scn, satellites=(), seed=7, receiver=replace(scn.receiver, quantization_bits=None)
    )
    x, truth = generate(scn)
    rng = np.random.default_rng(7)
    n = scn.receiver.n_samples
    expected = (rng.standard_normal(n) + 1j * rng.standard_normal(n)) / np.sqrt(2.0)
    assert np.array_equal(x, expected.astype(np.complex64))
    assert "generate_rate_hz" not in truth


@pytest.mark.loopback
@pytest.mark.parametrize("method", ["none", "ideal"])
def test_loopback_with_decimation(method):
    scn = load_scenario(SCENARIOS / f"navic_s_esp32c61_aliasing_{method}.yaml")
    scn = replace(scn, satellites=(replace(scn.satellites[0], cn0_dbhz=55.0),))
    spec = load_signal(scn.signal)
    x, truth = generate(scn)
    assert len(x) == scn.receiver.n_samples
    assert truth["decimation_method"] == method
    sat = truth["satellites"][0]
    res = acquire(x, scn.receiver.sample_rate_hz, spec, sat["prn"], freq_range_hz=(-40e3, 40e3))
    assert res.detected
    assert is_correct(res, sat, spec.code_length, code_tol_chips=0.5)


def test_ideal_decimation_does_not_depend_on_wider_analog_bandwidth():
    # Both analog bandwidths pass the whole 4 MHz output band, so the ideal output filter
    # leaves the same samples.
    x13, _ = generate(_noise_only("ideal", 13e6))
    x20, _ = generate(_noise_only("ideal", 20e6))
    assert np.allclose(x13, x20, atol=1e-5)


def _receiver(**extra):
    return {
        "name": "bad",
        "signal": "navic_s_sps",
        "receiver": {"sample_rate_hz": 4e6, "n_samples": 1024, **extra},
    }


def test_fractional_decimation_factor_raises():
    d = _receiver(decimation={"factor": 20.5, "method": "none"})
    with pytest.raises(ValueError, match="integer"):
        scenario_from_dict(d)


@pytest.mark.parametrize("bandwidth_hz", [0, -1e6])
def test_non_positive_analog_bandwidth_raises(bandwidth_hz):
    d = _receiver(analog_bandwidth_hz=bandwidth_hz, decimation={"factor": 20, "method": "ideal"})
    with pytest.raises(ValueError, match="positive"):
        scenario_from_dict(d)
