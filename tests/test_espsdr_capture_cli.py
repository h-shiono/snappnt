"""``snappnt capture`` with a fake serial port.

Expected command lines are typed by hand from docs/design/espsdr-protocol.md. The payload
packer below is written from the 10-bit layout described there (a little-endian bit stream of
20-bit fields, I in the high field and Q in the low field), not taken from snappnt.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from snappnt import cli
from snappnt.io import espsdr_client
from snappnt.io.espsdr_capture import capture_paths
from tests.test_espsdr_client import LIMITS_C3, FakePort, data_reply

INFO = b"C3SDR 6 burst 16380\n"
SYNC = b"SYNC 1\n"
SCENARIOS = Path(__file__).resolve().parents[1] / "scenarios"
ZERO_BODY = bytes(640)  # 256 samples of 10 bits


def pack10(iq: np.ndarray) -> bytes:
    """Pack complex samples (-512..511) as 20-bit fields, I high, Q low, LSB first."""
    i = np.round(iq.real).astype(np.int64) & 0x3FF
    q = np.round(iq.imag).astype(np.int64) & 0x3FF
    words = (i << 10) | q
    bits = ((words[:, None] >> np.arange(20)) & 1).astype(np.uint8).reshape(-1)
    return np.packbits(bits, bitorder="little").tobytes()


@pytest.fixture
def fake_port(monkeypatch):
    """Make ``snappnt capture`` use a ``FakePort`` instead of a serial port."""
    holder: dict[str, FakePort] = {}
    real = espsdr_client.EspSdrClient

    def make(port: str = "", **kw):
        holder["opened_with"] = port  # type: ignore[assignment]
        return real(port=port, serial_port=holder["port"])

    monkeypatch.setattr(espsdr_client, "EspSdrClient", make)

    def install(*replies: bytes) -> FakePort:
        holder["port"] = FakePort(list(replies))
        return holder["port"]

    install.holder = holder  # type: ignore[attr-defined]
    return install


def run(*args: str) -> int:
    return cli.main(["capture", *args])


def lines(port: FakePort) -> list[str]:
    return [w.decode().strip() for w in port.written if w.strip()]


def test_dry_run_prints_the_command_sequence(capsys):
    code = run("--dry-run", "--freq-hz", "2492e6", "-n", "256", "--bandwidth-mhz", "40")
    assert code == 0
    captured = capsys.readouterr()
    assert captured.out.splitlines() == [
        "SYNC 1",
        "INFO",
        "FREQ 2492",
        "BANDWIDTH 40",
        "GAIN HARDWARE",
        "LIMITS?",
        "CAP20 256 0",
        "RELEASE",
    ]
    assert "not checked without a board" in captured.err


@pytest.mark.parametrize(
    "args",
    [
        ["--freq-hz", "2492.028e6"],
        ["--rate-sps", "5e6"],
        ["-n", "100"],
        ["--gain", "loud"],
        ["--gain", "-3"],
        ["--count", "0"],
        ["--bandwidth-mhz", "100"],
        ["--bandwidth-mhz", "5"],
    ],
)
def test_bad_arguments_exit_2_and_write_nothing(args, tmp_path, capsys):
    out = tmp_path / "x"
    assert run("--dry-run", *args) == 2
    assert run("PORT", *args, "-o", str(out)) == 2
    assert not list(tmp_path.iterdir())
    assert "error" in capsys.readouterr().err


def test_one_capture_sends_expected_lines_and_writes_one_file(fake_port, tmp_path, capsys):
    port = fake_port(SYNC, INFO, b"OK\n", b"OK\n", LIMITS_C3, data_reply(ZERO_BODY, 256), b"OK\n")
    out = tmp_path / "cap"
    assert run("PORT", "-n", "256", "-o", str(out)) == 0
    assert lines(port) == [
        "SYNC 1",
        "INFO",
        "FREQ 2492",
        "GAIN HARDWARE",
        "LIMITS?",
        "CAP20 256 0",
        "RELEASE",
    ]
    assert (tmp_path / "cap.sigmf-meta").exists()
    g = json.loads((tmp_path / "cap.sigmf-meta").read_text())["global"]
    assert g["core:hw"] == "ESP-SDR C3"
    assert g["snappnt:espsdr_info"] == "C3SDR 6 burst 16380"
    assert g["snappnt:gain_mode"] == "hardware" and g["snappnt:gain_index"] is None
    assert "wrote" in capsys.readouterr().out


def test_count_three_writes_numbered_files_with_own_time_and_gain(fake_port, tmp_path):
    replies = [SYNC, INFO, b"OK\n", b"OK\n", LIMITS_C3]
    replies += [data_reply(ZERO_BODY, 256)] * 3 + [b"OK\n"]
    port = fake_port(*replies)
    out = tmp_path / "run"
    assert run("PORT", "-n", "256", "--count", "3", "--gain", "30", "-o", str(out)) == 0
    assert [ln for ln in lines(port) if ln.startswith(("CAP", "GAIN"))] == [
        "GAIN MANUAL 30",
        "CAP20 256 0",
        "CAP20 256 0",
        "CAP20 256 0",
    ]
    times = []
    for i in range(3):
        meta = json.loads((tmp_path / f"run_{i:04d}.sigmf-meta").read_text())
        assert meta["global"]["snappnt:gain_mode"] == "manual"
        assert meta["global"]["snappnt:gain_index"] == 30
        assert meta["captures"][0]["core:datetime"] == meta["global"]["snappnt:host_time_utc"]
        times.append(meta["global"]["snappnt:host_time_utc"])
    assert times == sorted(times)
    assert not (tmp_path / "run.sigmf-meta").exists()


def test_capture_paths_naming():
    assert capture_paths("a/b", 1) == [Path("a/b")]
    assert capture_paths("a/b", 2) == [Path("a/b_0000"), Path("a/b_0001")]


def test_rate_not_offered_by_chip_writes_nothing(fake_port, tmp_path, capsys):
    port = fake_port(SYNC, INFO, b"OK\n", b"OK\n", LIMITS_C3, b"OK\n")
    code = run("PORT", "--rate-sps", "40e6", "-n", "256", "-o", str(tmp_path / "c"))
    assert code == 1
    assert not any(tmp_path.iterdir())
    assert not any(ln.startswith("CAP") for ln in lines(port))
    assert "not supported" in capsys.readouterr().err


def test_too_many_samples_writes_nothing(fake_port, tmp_path):
    fake_port(SYNC, INFO, b"OK\n", b"OK\n", LIMITS_C3, b"OK\n")
    assert run("PORT", "-n", "16384", "-o", str(tmp_path / "c")) == 1
    assert not any(tmp_path.iterdir())


def test_damaged_capture_resyncs_and_keeps_earlier_files(fake_port, tmp_path, capsys):
    replies = [SYNC, INFO, b"OK\n", b"OK\n", LIMITS_C3]
    replies += [data_reply(ZERO_BODY, 256), data_reply(ZERO_BODY, 256, crc=0)]
    replies += [b"SYNC 99\n", b"OK\n"]
    port = fake_port(*replies)
    assert run("PORT", "-n", "256", "--count", "3", "-o", str(tmp_path / "d")) == 1
    assert (tmp_path / "d_0000.sigmf-data").exists()
    assert not (tmp_path / "d_0001.sigmf-data").exists()
    assert not (tmp_path / "d_0002.sigmf-meta").exists()
    assert "SYNC 99" in lines(port)
    assert "damaged capture 2 of 3" in capsys.readouterr().err


def test_metadata_has_no_port_host_user_or_paths(fake_port, tmp_path, monkeypatch):
    import getpass
    import socket

    from tests.test_public_safety import cps

    fake_port(SYNC, INFO, b"OK\n", b"OK\n", LIMITS_C3, data_reply(ZERO_BODY, 256), b"OK\n")
    out = tmp_path / "cap"
    assert run("/dev/ttyPRIVATE0", "-n", "256", "-o", str(out)) == 0
    text = (tmp_path / "cap.sigmf-meta").read_text()
    for private in ("ttyPRIVATE0", socket.gethostname(), getpass.getuser(), str(tmp_path)):
        assert private not in text
    assert not [ln for ln in text.splitlines() if cps.scan_line(ln, [])]


def test_capture_then_acquire_finds_the_simulated_satellite(fake_port, tmp_path, capsys):
    from snappnt.sim import generate, load_scenario

    scn = load_scenario(SCENARIOS / "navic_s_esp32c3.yaml")
    x, truth = generate(scn)
    x = x[:16380]
    x = x * (500.0 / np.abs(x).max())  # fit the 10-bit range
    payload = pack10(x)
    fake_port(SYNC, INFO, b"OK\n", b"OK\n", LIMITS_C3, data_reply(payload, 16380), b"OK\n")
    out = tmp_path / "snap"
    assert run("PORT", "-n", "16380", "-o", str(out)) == 0
    capsys.readouterr()
    sat = truth["satellites"][0]
    code = cli.main(
        ["acquire", str(out), "--signal", "navic_s_sps", "--prn", str(sat["prn"]),
         "--freq-span", "60000"]
    )  # fmt: skip
    assert code == 0
    row = capsys.readouterr().out.splitlines()[-1].split()
    assert row[1] == "yes"
    code_phase = float(row[2])
    code_len = 1023
    d = abs(code_phase - sat["code_phase_chips"])
    assert min(d, code_len - d) < 1.0


def test_existing_output_is_refused_and_left_untouched(fake_port, tmp_path, capsys):
    out = tmp_path / "cap"
    (tmp_path / "cap.sigmf-data").write_bytes(b"old")
    port = fake_port()
    assert run("PORT", "-n", "256", "-o", str(out)) == 2
    assert (tmp_path / "cap.sigmf-data").read_bytes() == b"old"
    assert "--overwrite" in capsys.readouterr().err
    assert port.written == []


def test_count_refuses_when_a_later_file_exists(fake_port, tmp_path):
    (tmp_path / "r_0001.sigmf-meta").write_text("old")
    fake_port()
    assert run("PORT", "-n", "256", "--count", "2", "-o", str(tmp_path / "r")) == 2
    assert not (tmp_path / "r_0000.sigmf-data").exists()


def test_overwrite_replaces_existing_output(fake_port, tmp_path):
    (tmp_path / "cap.sigmf-data").write_bytes(b"old")
    fake_port(SYNC, INFO, b"OK\n", b"OK\n", LIMITS_C3, data_reply(ZERO_BODY, 256), b"OK\n")
    assert run("PORT", "-n", "256", "--overwrite", "-o", str(tmp_path / "cap")) == 0
    assert (tmp_path / "cap.sigmf-data").stat().st_size == 256 * 4
    assert json.loads((tmp_path / "cap.sigmf-meta").read_text())["captures"][0]["core:datetime"]


def test_write_error_is_reported_and_leaves_no_partial_files(
    fake_port, tmp_path, monkeypatch, capsys
):
    from snappnt.io import sigmf_io

    def fail(self, *a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(sigmf_io.Path, "write_text", fail)
    fake_port(SYNC, INFO, b"OK\n", b"OK\n", LIMITS_C3, data_reply(ZERO_BODY, 256), b"OK\n")
    assert run("PORT", "-n", "256", "-o", str(tmp_path / "cap")) == 1
    assert not any(tmp_path.iterdir())
    assert "cannot write capture 1 of 1: disk full" in capsys.readouterr().err
