"""ESP-SDR client tests with a fake serial port.

Expected bytes and sample values are typed by hand from the format in
docs/design/espsdr-protocol.md (firmware receiver.c pack_iq / pack_iq8), not made by the
encoder in snappnt.
"""

from __future__ import annotations

import zlib

import numpy as np
import pytest

from snappnt.io import read_sigmf
from snappnt.io.espsdr_capture import save_capture_sigmf
from snappnt.io.espsdr_client import (
    EspSdrClient,
    EspSdrDamagedCapture,
    EspSdrError,
    EspSdrTimeout,
)
from snappnt.io.espsdr_iq import unpack_payload

LIMITS_C3 = b'LIMITS {"gain":[0,79,1],"bandwidth":[14,62,1,0],"rates":[80000000],"bits":[8,10]}\n'


class FakePort:
    """Serves queued reply bytes; records everything written."""

    def __init__(self, replies: list[bytes] | None = None):
        self.buf = bytearray(b"".join(replies or []))
        self.written: list[bytes] = []

    def write(self, data: bytes) -> int:
        self.written.append(bytes(data))
        return len(data)

    def readline(self) -> bytes:
        i = self.buf.find(b"\n")
        end = len(self.buf) if i < 0 else i + 1
        out = bytes(self.buf[:end])
        del self.buf[:end]
        return out

    def read(self, n: int) -> bytes:
        out = bytes(self.buf[:n])
        del self.buf[:n]
        return out

    def close(self) -> None:
        pass


def data_reply(payload: bytes, n: int, crc: int | None = None) -> bytes:
    c = zlib.crc32(payload) if crc is None else crc
    return f"DATA {n} {c:08x} 250\n".encode() + payload


def client(*replies: bytes) -> tuple[EspSdrClient, FakePort]:
    port = FakePort(list(replies))
    return EspSdrClient(serial_port=port, sync_on_open=False), port


def test_unpack_payload_10bit_hand_values():
    # 4 samples = 10 bytes. Fields: A=0x007ff B=0x801ff C=0x00000 D=0x01403.
    # bytes: A0=ff A1=07 | (A>>16)=0 | B<<4 low nibble: B&0xf=f -> 0xf0 ; so byte2 = 0xf0
    payload = bytes([0xFF, 0x07, 0xF0, 0x1F, 0x80, 0x00, 0x00, 0x30, 0x40, 0x01])
    out = unpack_payload(payload, 4, 10)
    expected = np.array([1 - 1j, -512 + 511j, 0 + 0j, 5 + 3j], dtype=np.complex64)
    # A=(high 1, low -1) -> I=high=1, Q=low=-1
    assert np.array_equal(out, expected)


def test_unpack_payload_odd_count_uses_three_byte_tail():
    # One sample (0x007ff) takes ceil(20/8) = 3 bytes.
    out = unpack_payload(bytes([0xFF, 0x07, 0x00]), 1, 10)
    assert np.array_equal(out, np.array([1 - 1j], dtype=np.complex64))


def test_unpack_payload_8bit_hand_values():
    # Per sample: first byte = low field upper 8 bits (Q), second = high field (I); x4.
    payload = bytes([0xFF, 0x01, 0x7F, 0x80])  # (Q=-1, I=1), (Q=127, I=-128)
    out = unpack_payload(payload, 2, 8)
    assert np.array_equal(out, np.array([4 - 4j, -512 + 508j], dtype=np.complex64))


def test_unpack_payload_wrong_length():
    with pytest.raises(ValueError):
        unpack_payload(b"\x00" * 9, 4, 10)


def test_tune_writes_freq_in_whole_mhz():
    c, port = client(b"OK\n")
    assert c.tune(2412e6) == "OK"
    assert port.written == [b"FREQ 2412\n"]


@pytest.mark.parametrize("hz", [2492.028e6, 99e6, 6001e6])
def test_tune_rejects_unsupported_frequency_without_writing(hz):
    c, port = client()
    with pytest.raises(ValueError):
        c.tune(hz)
    assert port.written == []


def test_tune_error_reply_and_timeout():
    c, _ = client(b"ERR command\n")
    with pytest.raises(EspSdrError, match="ERR command"):
        c.tune(2412e6)
    c, _ = client()  # nothing to read
    with pytest.raises(EspSdrTimeout):
        c.tune(2412e6)
    c, _ = client(b"ERR busy\n")
    with pytest.raises(EspSdrError, match="busy"):
        c.tune(2412e6)


def test_set_sample_rate_checks_limits():
    c, port = client(LIMITS_C3, LIMITS_C3)
    assert c.set_sample_rate(80e6) == 0
    assert port.written == [b"LIMITS?\n"]
    with pytest.raises(ValueError):
        c.set_sample_rate(40e6)  # an ESP-SDR rate, but not offered by this chip
    with pytest.raises(ValueError):
        c.set_sample_rate(5e6)  # not an ESP-SDR rate


def test_capture_sequence_and_decode():
    payload = bytes([0xFF, 0x07, 0xF0, 0x1F, 0x80, 0x00, 0x00, 0x30, 0x40, 0x01])
    # n = 4 is below the firmware minimum; use a client whose INFO says maximum 16380
    # and request 256 samples of the same 4-sample pattern repeated (64 x 10 bytes).
    body = payload * 64
    c, port = client(b"C3SDR 6 burst 16380\n", data_reply(body, 256))
    cap = c.capture(256, 80e6)
    assert port.written == [b"INFO\n", b"CAP20 256 0\n"]
    assert cap.samples.shape == (256,)
    assert cap.samples[:4].tolist() == [1 - 1j, -512 + 511j, 0j, 5 + 3j]
    assert cap.bits == 10 and cap.capture_us == 250 and cap.sample_rate_hz == 80e6
    # INFO is not repeated for a second capture
    c._ser.buf += data_reply(body, 256)
    c.capture(256, 80e6)
    assert port.written[2:] == [b"CAP20 256 0\n"]


def test_capture_8bit_command():
    body = bytes([0xFF, 0x01]) * 256
    c, port = client(b"C3SDR 6 burst 16380\n", data_reply(body, 256))
    cap = c.capture(256, 80e6, bits=8)
    assert port.written[-1] == b"CAP16 256 0\n"
    assert cap.samples[0] == 4 - 4j


def test_capture_uses_rate_from_set_sample_rate():
    body = bytes(640)
    c, port = client(LIMITS_C3, b"C3SDR 6 burst 16380\n", data_reply(body, 256))
    c.set_sample_rate(80e6)
    c.capture(256)
    assert port.written == [b"LIMITS?\n", b"INFO\n", b"CAP20 256 0\n"]


def test_capture_rate_error_from_firmware():
    c, _ = client(b"C3SDR 6 burst 16380\n", b"ERR rate\n")
    with pytest.raises(EspSdrError, match="ERR rate"):
        c.capture(256, 40e6)


def test_capture_rejects_bad_sizes():
    c, port = client(b"C3SDR 6 burst 16380\n")
    for n in (255, 16381):
        with pytest.raises(ValueError):
            c.capture(n, 80e6)
    with pytest.raises(ValueError):
        c.capture(256, 80e6, bits=12)
    assert port.written == [b"INFO\n"]


def test_capture_damaged():
    body = bytes(640)
    info = b"C3SDR 6 burst 16380\n"
    c, _ = client(info, data_reply(body, 256, crc=0))
    with pytest.raises(EspSdrDamagedCapture, match="CRC"):
        c.capture(256, 80e6)
    c, _ = client(info, data_reply(body, 255))
    with pytest.raises(EspSdrDamagedCapture, match="header"):
        c.capture(256, 80e6)
    c, _ = client(info, data_reply(body[:-1], 256))
    with pytest.raises(EspSdrTimeout, match="payload"):
        c.capture(256, 80e6)
    c, _ = client(info, b"garbage\n")
    with pytest.raises(EspSdrDamagedCapture):
        c.capture(256, 80e6)


def test_resync_reads_until_echo():
    c, port = client(b"\x01\x02junk\n", b"SYNC 7\n")
    c.resync(7)
    assert port.written == [b"\nSYNC 7\n"]


def test_crc_is_standard_crc32():
    # CRC-32 check value of "123456789" is 0xcbf43926 (the standard reflected CRC-32).
    assert zlib.crc32(b"123456789") == 0xCBF43926


def test_save_capture_sigmf_roundtrip(tmp_path):
    body = bytes([0xFF, 0x07, 0xF0, 0x1F, 0x80, 0x00, 0x00, 0x30, 0x40, 0x01]) * 64
    c, _ = client(b"OK\n", b"C3SDR 6 burst 16380\n", data_reply(body, 256))
    c.tune(2412e6)
    cap = c.capture(256, 80e6)
    base = save_capture_sigmf(cap, tmp_path / "cap")
    x, meta = read_sigmf(str(base) + ".sigmf-meta")
    assert np.array_equal(x, cap.samples)
    g = meta["global"]
    assert g["core:sample_rate"] == 80e6 and g["core:datatype"] == "ci16_le"
    assert g["snappnt:espsdr_transfer_bits"] == 10
    assert meta["captures"][0]["core:frequency"] == 2412e6


def test_resync_finds_echo_after_stale_bytes_on_the_same_line():
    c, _ = client(b"\x01\x02\xffSYNC 7\n")
    c.resync(7)


def test_resync_ignores_longer_nonce():
    c, _ = client(b"SYNC 17\n", b"SYNC 1\n")
    c.resync(1)
    assert c._ser.buf == b""


def test_open_syncs_and_retries_after_lost_first_attempt():
    port = FakePort([b"boot garbage with no newline"])  # attempt 1 gets no echo
    port_replies = {"n": 0}
    real_write = port.write

    def write(data: bytes) -> int:
        n = real_write(data)
        port_replies["n"] += 1
        if port_replies["n"] == 2:  # the board is up by the second attempt
            port.buf += b"SYNC 2\n"
        return n

    port.write = write  # type: ignore[method-assign]
    EspSdrClient(serial_port=port)
    assert port.written == [b"\nSYNC 1\n", b"\nSYNC 2\n"]


def test_open_raises_timeout_when_firmware_never_answers():
    port = FakePort()
    with pytest.raises(EspSdrTimeout):
        EspSdrClient(serial_port=port)
    assert len(port.written) == 3


@pytest.mark.parametrize("rate", [80_000_000.5, 79_999_999.9])
def test_fractional_rate_is_rejected(rate):
    c, port = client(LIMITS_C3)
    with pytest.raises(ValueError):
        c.set_sample_rate(rate)
    with pytest.raises(ValueError):
        c.capture(256, rate)
    assert port.written == []
