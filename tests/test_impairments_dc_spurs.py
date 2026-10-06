"""DC offset and fixed spurs in the simulated receiver (issue #42)."""

# ruff: noqa: E501  (the SHA-256 constants below are 64 characters long)

from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from snappnt.sim.generate import generate
from snappnt.sim.scenario import load_scenario, scenario_from_dict

SCENARIO_DIR = Path(__file__).resolve().parents[1] / "scenarios"
ARCHITECTURE = Path(__file__).resolve().parents[1] / "docs" / "design" / "architecture.md"

# SHA-256 of the complex64 bytes that ``generate`` returned on ``main`` before DC offset and
# spurs existed. Existing scenarios must keep producing exactly these samples.
SCENARIO_HASHES = {
    "cband_bpsk_generic_highside": "bd3892aad823aea987035ac625524e8a7b4529b21220fcd630704d1be3f88084",
    "cband_bpsk_generic_lowside": "b62436e37a4276863314b2f06afe827de8f33d73bff6fa1bf369f71882a36f35",
    "cband_leo_overhead": "d782d41d6023ef0f83b9b3b8a1771ba377694b92a1aad43d5064252210862dba",
    "navic_s_conducted_gen": "6bf1276ee50b7ecac5a9cf73c5860f9a3f8a8206fecece0cbd8de50eb56c8ae5",
    # Added with the files for the conducted test (issue #11), hashed when they were added.
    "navic_s_conducted_gen_cn0_50": "50164cd6dbfcc6b9ec5f824e286e11c39ed76500abe77f2e65de121ecfd20cdf",
    "navic_s_conducted_gen_cn0_51": "1179ff44da08b63787b85175d7c12801427814d67ea70e6c3cf442db08f10b0c",
    "navic_s_conducted_gen_cn0_52": "f9ff79b0b0d9bf974ee795e77f9b3f27de28f8223f214a5be8f98a64bb96e786",
    "navic_s_conducted_gen_cn0_53": "26785cdd1c1c11d727bb9199c8350ac426ac65284c8fcad11326455f7a570a32",
    "navic_s_conducted_gen_cn0_55": "8f777c2ce9ae55438278b62e974aab31c7ddf33ec9edd8bac23c0422f5283c2e",
    "navic_s_conducted_gen_noise": "bb9d8b81a951b026e101c2434514d07f72e5dc365a6de434bd0b0923e2d29e1c",
    "navic_s_esp32c3": "7919bd9d23f0d6e7c39016cf699647a889ee667bcea84b89e16578e49cb57201",
    "navic_s_esp32c61_4msps": "a5eb5d56b9fcc66d254e4f05488b3231457c238475b53b9c984acc48dfabb336",
    "navic_s_esp32c61_aliasing_ideal": "474287ba5ba2c9f4170a22ff1e64b5916648ffb4228d87c99b9717d099291f74",
    "navic_s_esp32c61_aliasing_ideal_b20": "474287ba5ba2c9f4170a22ff1e64b5916648ffb4228d87c99b9717d099291f74",
    "navic_s_esp32c61_aliasing_none": "b6dd63aee96f713d39d246efcab92a81b25cc8be1d459c5b338945a3b8a17ec0",
    "navic_s_esp32c61_aliasing_none_b20": "cde8024aaba18f036c363b3c40f1f95af7c53f4ad06f92d339ff2eb3cc70cd4f",
    "navic_s_ideal": "9e88ebaa177e7a32100cccd4bc185c8ddf1856ce773433af93ad5d727c9740cf",
    # Added with the scenario for the ESP32-C5 sky result (issue #87), hashed when it was added.
    "navic_s_esp32c5_4msps_b11": "208073476801a6058e7462bbe2500d17c0d077be1603a6e422b1d7d58d4e4a29",
}


def _noise_scenario(**receiver) -> dict:
    return {
        "name": "noise_only",
        "signal": "navic_s_sps",
        "seed": 5,
        "receiver": {"sample_rate_hz": 4_000_000, "n_samples": 4096, **receiver},
        "satellites": [],
    }


def _tone_power(x: np.ndarray, offset_hz: float, fs_hz: float, expect_peak: bool = True) -> float:
    """Power in the bins around ``offset_hz``, relative to the noise power per sample.

    A tone of power ``P`` has ``|X|^2 = P * N^2`` in its bin for a rectangular window.
    """
    n = len(x)
    spectrum = np.abs(np.fft.fft(x)) ** 2
    expected = int(round(offset_hz / fs_hz * n)) % n
    if expect_peak:
        assert abs(int(np.argmax(spectrum)) - expected) <= 1
    bins = [(expected + k) % n for k in (-1, 0, 1)]
    return float(spectrum[bins].sum() / n**2)


def test_existing_scenarios_are_bit_identical():
    for name, digest in SCENARIO_HASHES.items():
        samples, truth = generate(load_scenario(SCENARIO_DIR / f"{name}.yaml"))
        assert hashlib.sha256(samples.tobytes()).hexdigest() == digest, name
        assert "dc_offset_fullscale" not in truth
        assert "spurs" not in truth


def test_all_scenario_files_other_than_dc_are_hashed():
    files = {p.stem for p in SCENARIO_DIR.glob("*.yaml")}
    assert files - set(SCENARIO_HASHES) == {"navic_s_esp32c3_dc"}


@pytest.mark.parametrize(
    ("dc_i", "dc_q", "seed"), [(-0.5, 0.0, 5), (-0.5, 0.0, 11), (0.2, -0.25, 5)]
)
def test_dc_offset_mean_of_each_component(dc_i, dc_q, seed):
    d = _noise_scenario(n_samples=16380, quantization_bits=10, dc_offset={"i": dc_i, "q": dc_q})
    d["seed"] = seed
    x, truth = generate(scenario_from_dict(d))
    assert truth["dc_offset_fullscale"] == {"i": dc_i, "q": dc_q}
    for part, fraction in ((x.real, dc_i), (x.imag, dc_q)):
        tolerance = 4 * part.std() / np.sqrt(len(part)) + 0.5
        assert abs(part.mean() - fraction * 512) < tolerance
    # The AGC holds the level of the signal alone: 12 dB below full scale is 128 counts.
    assert x.real.std() == pytest.approx(128, rel=0.05)


def test_dc_offset_scenario_file():
    x, _ = generate(load_scenario(SCENARIO_DIR / "navic_s_esp32c3_dc.yaml"))
    assert abs(x.real.mean() + 256) < 4 * x.real.std() / np.sqrt(len(x)) + 0.5
    assert abs(x.imag.mean()) < 4 * x.imag.std() / np.sqrt(len(x)) + 0.5


def test_dc_offset_clips_at_full_scale():
    d = _noise_scenario(quantization_bits=10, dc_offset={"i": -0.99, "q": 0.99})
    x, _ = generate(scenario_from_dict(d))
    assert x.real.min() == -512
    assert x.imag.max() == 511


@pytest.mark.parametrize(
    "receiver",
    [
        {"dc_offset": {"i": -0.5}},  # no quantization
        {"quantization_bits": 10, "dc_offset": {"i": 1.0}},
        {"quantization_bits": 10, "dc_offset": {"q": -1.5}},
        {"spurs": [{"offset_hz": 2_000_000, "power_db": 0}]},  # at Nyquist
        {"spurs": [{"offset_hz": -3_000_000, "power_db": 0}]},  # above Nyquist
        {"dc_offset": {"i": 0, "q": 0}},  # explicit zero still needs quantization
        {"quantization_bits": 10, "dc_offset": {"i": float("nan")}},
        {"spurs": [{"offset_hz": float("nan"), "power_db": 0}]},
        {"spurs": [{"offset_hz": 1_000_000, "power_db": float("nan")}]},
        {"spurs": [{"offset_hz": 1_000_000, "power_db": float("inf")}]},
        {"spurs": [{"offset_hz": 1_000_000, "power_db": float("-inf")}]},
    ],
)
def test_validation(receiver):
    with pytest.raises(ValueError):
        scenario_from_dict(_noise_scenario(**receiver))


def test_explicit_zero_dc_offset_is_recorded_in_truth():
    _, truth = generate(
        scenario_from_dict(_noise_scenario(quantization_bits=10, dc_offset={"i": 0, "q": 0}))
    )
    assert truth["dc_offset_fullscale"] == {"i": 0.0, "q": 0.0}
    _, truth = generate(scenario_from_dict(_noise_scenario(quantization_bits=10)))
    assert "dc_offset_fullscale" not in truth


def test_half_set_dc_offset_in_code_treats_other_component_as_zero():
    scn = scenario_from_dict(_noise_scenario(quantization_bits=10, dc_offset={"i": 0.25, "q": 0}))
    both, truth_both = generate(scn)
    for half in (
        replace(scn.receiver, dc_offset_i=0.25, dc_offset_q=None),
        replace(scn.receiver, dc_offset_i=0.25),
    ):
        x, truth = generate(replace(scn, receiver=half))
        assert truth["dc_offset_fullscale"] == {"i": 0.25, "q": 0.0}
        assert np.array_equal(x, both)
    only_q = replace(scn.receiver, dc_offset_i=None, dc_offset_q=-0.25)
    _, truth = generate(replace(scn, receiver=only_q))
    assert truth["dc_offset_fullscale"] == {"i": 0.0, "q": -0.25}


def test_spur_inside_band_direct_rate():
    offset_hz = 100 * 4_000_000 / 4096  # exactly on a bin
    d = _noise_scenario(spurs=[{"offset_hz": offset_hz, "power_db": 3.0}])
    x, truth = generate(scenario_from_dict(d))
    assert truth["spurs"] == [{"offset_hz": offset_hz, "power_db": 3.0}]
    power = _tone_power(x, offset_hz, 4e6)
    assert 10 * np.log10(power) == pytest.approx(3.0, abs=0.5)


_DECIMATED = {"generate_rate_hz": 80_000_000, "decimation": {"factor": 20, "method": "ideal"}}


def test_spur_inside_output_band_after_decimation():
    d = _noise_scenario(analog_bandwidth_hz=62e6, **_DECIMATED)
    d["receiver"]["spurs"] = [{"offset_hz": 1_000_000, "power_db": 0.5}]
    x, _ = generate(scenario_from_dict(d))
    power = _tone_power(x, 1e6, 4e6)
    assert 10 * np.log10(power) == pytest.approx(0.5, abs=0.5)


def test_spur_outside_analog_bandwidth_is_removed():
    receiver = {
        "analog_bandwidth_hz": 14e6,
        "generate_rate_hz": 80_000_000,
        "decimation": {"factor": 20, "method": "none"},
        "spurs": [{"offset_hz": 29_000_000, "power_db": 0.0}],
    }
    x, _ = generate(scenario_from_dict(_noise_scenario(**receiver)))
    power = _tone_power(x, 1e6, 4e6, expect_peak=False)  # where it would fold to
    assert 10 * np.log10(power) < -20.0


def test_spur_outside_output_band_folds_without_antialias_filter():
    receiver = {
        "analog_bandwidth_hz": 62e6,
        "generate_rate_hz": 80_000_000,
        "decimation": {"factor": 20, "method": "none"},
        "spurs": [{"offset_hz": 29_000_000, "power_db": 0.0}],
    }
    x, _ = generate(scenario_from_dict(_noise_scenario(**receiver)))
    power = _tone_power(x, 1e6, 4e6)  # 29 MHz folds to 1 MHz at 4 MSa/s
    assert 10 * np.log10(power) == pytest.approx(0.0, abs=0.5)


def test_spurs_leave_the_other_random_draws_unchanged():
    base = _noise_scenario()
    base["satellites"] = [{"prn": 10, "cn0_dbhz": 50, "code_phase_chips": 10.0}]
    with_spur = _noise_scenario(spurs=[{"offset_hz": 1e6, "power_db": -300.0}])
    with_spur["satellites"] = base["satellites"]
    a, _ = generate(scenario_from_dict(base))
    b, _ = generate(scenario_from_dict(with_spur))
    np.testing.assert_allclose(a, b, atol=1e-12)


def test_new_keys_are_documented():
    text = ARCHITECTURE.read_text(encoding="utf-8")
    for key in ("dc_offset", "spurs", "offset_hz", "power_db"):
        assert key in text


@pytest.mark.parametrize(
    "kwargs",
    [{"dc_offset_i": 0.25}, {"dc_offset_q": -0.25}, {"dc_offset_i": 0.0, "dc_offset_q": 0.0}],
)
def test_code_built_dc_offset_without_quantization_is_rejected(kwargs):
    scn = scenario_from_dict(_noise_scenario())
    with pytest.raises(ValueError, match="quantization_bits"):
        replace(scn.receiver, quantization_bits=None, **kwargs)
