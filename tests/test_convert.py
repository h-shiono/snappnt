"""Conversion of reference-receiver raw files to SigMF.

Raw files are written here with plain NumPy from known values, independently of
``snappnt.io.convert``.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from snappnt import cli
from snappnt.io import convert_iq, read_sigmf
from snappnt.sim import generate, load_scenario

SCENARIOS = Path(__file__).resolve().parents[1] / "scenarios"

CASES = {
    "uhd-short": ("<i2", "ci16_le", [-32768, 32767, 0, 1, -1, 1234, -4321, 7]),
    "hackrf": ("i1", "ci8", [-128, 127, 0, 1, -1, 42, -43, 5]),
    "uhd-float": ("<f4", "cf32_le", [-1.5, 0.1, 3.25e-7, -2.0e5, 0.0, 1.0, 0.333333, -0.7]),
}


@pytest.mark.parametrize("fmt", CASES)
def test_values_identical(tmp_path, fmt):
    dtype, datatype, values = CASES[fmt]
    raw = np.array(values, dtype=dtype)  # I, Q, I, Q, ...
    src = tmp_path / "rec.raw"
    raw.tofile(src)
    base = convert_iq(src, tmp_path / "out", fmt, 4e6, 2492.028e6, "reference receiver")
    x, meta = read_sigmf(base)
    expected = raw[0::2].astype(np.float64) + 1j * raw[1::2].astype(np.float64)
    assert np.array_equal(x, expected.astype(np.complex64))
    g = meta["global"]
    assert g["core:datatype"] == datatype
    assert g["core:sample_rate"] == 4e6
    assert g["core:hw"] == "reference receiver"
    assert meta["captures"][0]["core:frequency"] == 2492.028e6


@pytest.mark.parametrize(("fmt", "size"), [("uhd-short", 6), ("uhd-float", 12), ("hackrf", 3)])
def test_partial_sample_is_an_error(tmp_path, fmt, size):
    src = tmp_path / "rec.raw"
    src.write_bytes(bytes(size))
    with pytest.raises(ValueError, match=rf"file size {size} bytes"):
        convert_iq(src, tmp_path / "out", fmt, 1e6, 1e9, "x")
    assert not (tmp_path / "out.sigmf-data").exists()


def test_existing_output_is_kept_without_overwrite(tmp_path):
    src = tmp_path / "rec.raw"
    np.zeros(4, dtype="i1").tofile(src)
    convert_iq(src, tmp_path / "out", "hackrf", 1e6, 1e9, "x")
    np.ones(4, dtype="i1").tofile(src)
    with pytest.raises(FileExistsError):
        convert_iq(src, tmp_path / "out", "hackrf", 1e6, 1e9, "x")
    assert np.all(read_sigmf(tmp_path / "out")[0] == 0)
    convert_iq(src, tmp_path / "out", "hackrf", 1e6, 1e9, "x", overwrite=True)
    assert np.all(read_sigmf(tmp_path / "out")[0] == 1 + 1j)


def test_cli_errors(tmp_path, capsys):
    src = tmp_path / "rec.raw"
    src.write_bytes(bytes(3))
    args = ["convert", str(src), "-o", str(tmp_path / "o"), "--format", "hackrf"]
    args += ["--rate-sps", "1e6", "--freq-hz", "1e9", "--device", "d"]
    assert cli.main(args) == 2
    assert "file size 3 bytes" in capsys.readouterr().err
    assert cli.main([*args[:1], str(tmp_path / "missing.raw"), *args[2:]]) == 2


def _to_raw(x: np.ndarray, fmt: str) -> np.ndarray:
    """Scale and round simulator samples to the raw layout of ``fmt``."""
    if fmt == "uhd-float":
        out = np.empty(2 * x.size, dtype="<f4")
        scale = 1.0
    else:
        full = 32767.0 if fmt == "uhd-short" else 127.0
        out = np.empty(2 * x.size, dtype="<i2" if fmt == "uhd-short" else "i1")
        scale = 0.7 * full / max(np.abs(x.real).max(), np.abs(x.imag).max())
    out[0::2] = np.round(x.real * scale) if fmt != "uhd-float" else x.real
    out[1::2] = np.round(x.imag * scale) if fmt != "uhd-float" else x.imag
    return out


@pytest.mark.loopback
@pytest.mark.parametrize("fmt", ["uhd-short", "uhd-float", "hackrf"])
def test_converted_file_is_acquired(tmp_path, capsys, fmt):
    scn = load_scenario(SCENARIOS / "navic_s_ideal.yaml")
    x, truth = generate(scn)
    prn = truth["satellites"][0]["prn"]
    src = tmp_path / "rec.raw"
    _to_raw(x, fmt).tofile(src)
    fs = scn.receiver.sample_rate_hz
    out = tmp_path / "conv"
    rc = cli.main(
        ["convert", str(src), "-o", str(out), "--format", fmt, "--rate-sps", str(fs)]
        + ["--freq-hz", "2492.028e6", "--device", "test"]
    )
    assert rc == 0
    capsys.readouterr()
    rc = cli.main(
        ["acquire", str(out), "--signal", scn.signal, "--prn", str(prn), "--freq-span", "2000"]
    )
    assert rc == 0
    row = [ln for ln in capsys.readouterr().out.splitlines() if ln.split()[:1] == [str(prn)]]
    assert row and row[0].split()[1] == "yes"
