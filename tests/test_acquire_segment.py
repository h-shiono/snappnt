"""Acquisition of a segment of a recording (issue #73)."""

from pathlib import Path

import numpy as np
import pytest

from snappnt.cli import main
from snappnt.io import read_sigmf, sigmf_io, write_sigmf

SCENARIOS = Path(__file__).resolve().parents[1] / "scenarios"
FS_HZ = 8.184e6


def _recording(tmp_path):
    out = tmp_path / "ideal"
    assert main(["sim", str(SCENARIOS / "navic_s_ideal.yaml"), "-o", str(out)]) == 0
    return out


@pytest.mark.parametrize("datatype", ["cf32_le", "ci16_le", "ci8"])
def test_read_segment_equals_slice(tmp_path, datatype):
    rng = np.random.default_rng(0)
    x = (rng.integers(-100, 100, 1000) + 1j * rng.integers(-100, 100, 1000)).astype(np.complex64)
    base = write_sigmf(tmp_path / "x", x, 1e3, datatype=datatype)
    y, _ = read_sigmf(base, start_s=0.25, duration_s=0.5)
    assert np.array_equal(y, x[250:750])
    y, _ = read_sigmf(base, start_s=0.9)
    assert np.array_equal(y, x[900:])
    y, _ = read_sigmf(base, duration_s=0.1)
    assert np.array_equal(y, x[:100])


def test_read_segment_reads_only_needed_samples(tmp_path, monkeypatch):
    base = write_sigmf(tmp_path / "x", np.ones(1000, np.complex64), 1e3)
    calls = []
    fromfile = np.fromfile

    def spy(*args, **kwargs):
        calls.append(kwargs)
        return fromfile(*args, **kwargs)

    monkeypatch.setattr(sigmf_io.np, "fromfile", spy)
    read_sigmf(base, start_s=0.25, duration_s=0.5)
    assert calls == [{"dtype": np.dtype("<c8"), "offset": 250 * 8, "count": 500}]


@pytest.mark.parametrize(
    ("start_s", "duration_s"),
    [(1.0, None), (1.5, 0.1), (0.9, 0.2), (-0.1, 0.5), (0.5, 0.0)],
)
def test_read_segment_outside_recording(tmp_path, start_s, duration_s):
    base = write_sigmf(tmp_path / "x", np.ones(1000, np.complex64), 1e3)
    with pytest.raises(ValueError, match="not within the recording, which holds 1000 samples"):
        read_sigmf(base, start_s=start_s, duration_s=duration_s)


def test_cli_segment_matches_file_of_segment(tmp_path, capsys):
    # Acquiring samples [start, start + n) of a recording gives the same table rows as
    # acquiring a file that holds only those samples. The code phase therefore refers to the
    # first sample of the segment.
    out = _recording(tmp_path)
    start_s, duration_s = 1.5e-3, 2e-3
    start, n = round(start_s * FS_HZ), round(duration_s * FS_HZ)
    x, _ = read_sigmf(out)
    seg = write_sigmf(tmp_path / "seg", x[start : start + n], FS_HZ)
    common = ["--signal", "navic_s_sps", "--center", "0", "--prn", "10", "--freq-span", "2000"]
    capsys.readouterr()

    assert main(["acquire", str(seg), *common]) == 0
    whole_rows = capsys.readouterr().out.splitlines()[1:]
    segment = ["--start-s", str(start_s), "--duration-s", str(duration_s)]
    args = ["acquire", str(out), *common, *segment]
    assert main(args) == 0
    lines = capsys.readouterr().out.splitlines()
    assert f"{n} samples" in lines[0]
    assert f"from sample {start}" in lines[0]
    assert lines[1].startswith("truth refers to the first sample of the file")
    assert lines[2:] == whole_rows
    assert " 10  yes" in whole_rows[1]


def test_cli_segment_from_start_compares_truth(tmp_path, capsys):
    out = _recording(tmp_path)
    capsys.readouterr()
    args = ["acquire", str(out), "--prn", "10", "--freq-span", "2000", "--duration-s", "2e-3"]
    assert main(args) == 0
    assert "OK" in capsys.readouterr().out


@pytest.mark.parametrize(("start_s", "duration_s"), [("5e-3", None), ("3e-3", "2e-3")])
def test_cli_segment_past_end(tmp_path, capsys, start_s, duration_s):
    out = _recording(tmp_path)
    capsys.readouterr()
    args = ["acquire", str(out), "--prn", "10", "--start-s", start_s]
    if duration_s is not None:
        args += ["--duration-s", duration_s]
    assert main(args) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "error: segment from" in captured.err
    assert "not within the recording, which holds 32736 samples" in captured.err


@pytest.mark.parametrize(
    ("start_s", "duration_s"),
    [(float("inf"), None), (float("nan"), None), (0.0, float("inf")), (0.1, float("nan"))],
)
def test_read_segment_not_finite(tmp_path, start_s, duration_s):
    base = write_sigmf(tmp_path / "x", np.ones(1000, np.complex64), 1e3)
    with pytest.raises(ValueError, match="must be a finite number of seconds"):
        read_sigmf(base, start_s=start_s, duration_s=duration_s)


@pytest.mark.parametrize("option", ["--start-s", "--duration-s"])
@pytest.mark.parametrize("value", ["inf", "nan"])
def test_cli_segment_not_finite(tmp_path, capsys, option, value):
    out = _recording(tmp_path)
    capsys.readouterr()
    assert main(["acquire", str(out), "--prn", "10", option, value]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "error: segment" in captured.err
    assert "must be a finite number of seconds" in captured.err


def test_read_segment_short_read(tmp_path, monkeypatch):
    # A file that shrinks between the size check and the read gives fewer samples.
    base = write_sigmf(tmp_path / "x", np.ones(1000, np.complex64), 1e3)
    fromfile = np.fromfile
    monkeypatch.setattr(sigmf_io.np, "fromfile", lambda *a, **k: fromfile(*a, **k)[:-1])
    with pytest.raises(ValueError, match="read 499 samples of the segment from sample 250"):
        read_sigmf(base, start_s=0.25, duration_s=0.5)
