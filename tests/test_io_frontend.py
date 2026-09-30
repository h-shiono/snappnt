import numpy as np
import pytest

from snappnt.frontend import FrequencyPlan, load_device
from snappnt.io import get_truth, read_sigmf, write_sigmf
from snappnt.io.espsdr_iq import pack_words, unpack_words
from snappnt.io.generators import hackrf_transfer_cmd
from snappnt.sim.impairments import quantize


def test_sigmf_roundtrip_cf32(tmp_path):
    x = (np.arange(10) + 1j * np.arange(10)[::-1]).astype(np.complex64)
    base = write_sigmf(tmp_path / "a", x, 1e6, center_frequency_hz=2.4e9, truth={"k": 1})
    y, meta = read_sigmf(base)
    assert np.array_equal(x, y)
    assert get_truth(meta) == {"k": 1}
    assert meta["global"]["core:extensions"][0]["name"] == "snappnt"


def test_sigmf_roundtrip_ci16(tmp_path):
    x = np.array([1 + 2j, -3 - 4j, 511 - 512j], dtype=np.complex64)
    base = write_sigmf(tmp_path / "b", x, 80e6, datatype="ci16_le")
    y, _ = read_sigmf(str(base) + ".sigmf-data")
    assert np.array_equal(x, y)


def test_espsdr_word_roundtrip():
    iq = np.array([0 + 0j, 511 - 512j, -1 + 1j, -300 + 200j], dtype=np.complex64)
    words = pack_words(iq, gain=37, agc=5)
    out, gain, agc = unpack_words(words)
    assert np.array_equal(out, iq)
    assert (gain == 37).all() and (agc == 5).all()


def test_quantize_range():
    rng = np.random.default_rng(0)
    x = rng.standard_normal(1000) + 1j * rng.standard_normal(1000)
    q = quantize(x, 10, backoff_db=12)
    assert q.real.min() >= -512 and q.real.max() <= 511


def test_freqplan_cband_low_side():
    p = FrequencyPlan(rf_hz=5020e6, tuned_hz=2484e6, lo_hz=2536e6, lo_side="low")
    assert p.if_hz == pytest.approx(2484e6)
    assert p.baseband_offset_hz == pytest.approx(0.0)
    assert p.image_hz == pytest.approx(52e6)
    assert p.doppler_sign == 1


def test_freqplan_high_side_inverts():
    p = FrequencyPlan(rf_hz=5020e6, tuned_hz=2484e6, lo_hz=7504e6, lo_side="high")
    assert p.if_hz == pytest.approx(2484e6)
    assert p.inverted and p.doppler_sign == -1


def test_freqplan_direct():
    p = FrequencyPlan(rf_hz=2492.028e6, tuned_hz=2492e6)
    assert p.baseband_offset_hz == pytest.approx(28e3)


def test_hackrf_cmd_keeps_amp_and_bias_off():
    cmd = hackrf_transfer_cmd("x.i8", 2490.528e6, 8e6)
    assert cmd[cmd.index("-a") + 1] == "0"
    assert cmd[cmd.index("-p") + 1] == "0"


def test_device_catalog():
    dev = load_device("esp32c3")
    assert dev.adc_bits == 10 and dev.sample_rates_sps == [80e6]
