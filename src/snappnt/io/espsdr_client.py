"""Host-side client for the ESP-SDR firmware over a serial port.

The protocol, with file and line citations into the firmware and browser-client sources, is
in docs/design/espsdr-protocol.md. Status: written from those sources; **not verified on
hardware** (issue #11).

Commands used here: INFO, LIMITS?, RANGE?, FREQ, BANDWIDTH, LPF?, GAIN, CAP16/CAP20, RELEASE.
Nothing here transmits; the firmware has no transmit command.
UART default: 2,000,000 baud 8N1.
"""

from __future__ import annotations

import re
import zlib
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from snappnt.io.espsdr_iq import payload_size, unpack_payload

# Rate index used in capture commands -> nominal sample rate (firmware README).
RATE_INDEX_BY_SPS = {
    80_000_000: 0,
    40_000_000: 1,
    20_000_000: 2,
    10_000_000: 3,
    8_000_000: 4,
    4_000_000: 5,
    16_000_000: 6,
}
MIN_CAPTURE_SAMPLES = 256
FREQ_MIN_MHZ = 100
FREQ_MAX_MHZ = 6000
_DATA_HEADER = re.compile(r"^DATA (\d+) ([0-9a-fA-F]{1,8}) (\d+)$")
_INFO = re.compile(r"^(\w+)SDR (\d+) burst (\d+)$")


class EspSdrError(RuntimeError):
    """The firmware answered ``ERR <reason>`` or an unexpected line."""


class EspSdrTimeout(TimeoutError):
    """No complete reply within the serial timeout."""


class EspSdrDamagedCapture(EspSdrError):
    """Header, length or CRC-32 of a capture reply is wrong."""


@dataclass
class EspSdrCapture:
    """One decoded capture. ``samples`` are complex64 on the 10-bit scale (-512..511)."""

    samples: np.ndarray
    sample_rate_hz: float
    bits: int
    capture_us: int
    payload_crc32: int
    center_frequency_hz: float | None = None


@dataclass
class EspSdrClient:
    """Serial client. Pass ``serial_port`` (any object with write/readline/read/close) to
    use an already opened port, for example a fake one in tests. With ``sync_on_open`` (the
    default) the constructor sends ``SYNC`` up to three times and waits for the echo, because
    opening a UART bridge can reset the board and a command sent during boot is lost;
    ``EspSdrTimeout`` is raised if the firmware never answers."""

    port: str = ""
    baudrate: int = 2_000_000
    timeout_s: float = 2.0
    serial_port: Any = None
    sync_on_open: bool = True
    _rate_index: int | None = field(default=None, init=False, repr=False)
    _max_samples: int | None = field(default=None, init=False, repr=False)
    _frequency_hz: float | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.serial_port is not None:
            self._ser = self.serial_port
            self._sync_after_open()
            return
        try:
            import serial  # type: ignore[import-not-found]
        except ImportError as e:  # pragma: no cover - optional dependency
            raise ImportError('install the hardware extra: pip install -e ".[hw]"') from e
        self._ser = serial.Serial(self.port, self.baudrate, timeout=self.timeout_s)
        self._sync_after_open()

    def _sync_after_open(self) -> None:
        if not self.sync_on_open:
            return
        for attempt in range(1, 4):
            try:
                self.resync(attempt)
                return
            except EspSdrTimeout:
                if attempt == 3:
                    self._ser.close()
                    raise

    def _readline(self) -> str:
        raw = self._ser.readline()
        if not raw.endswith(b"\n"):
            raise EspSdrTimeout("no complete reply line from the ESP-SDR firmware")
        return raw.decode("ascii", errors="replace").strip()

    def command(self, line: str) -> str:
        """Send one command line and return the first reply line (no error checking)."""
        self._ser.write((line.strip() + "\n").encode("ascii"))
        return self._readline()

    def _checked(self, line: str, expect_prefix: str = "OK") -> str:
        reply = self.command(line)
        if reply.startswith("ERR"):
            raise EspSdrError(f"{line.strip()!r} failed: {reply}")
        if not reply.startswith(expect_prefix):
            raise EspSdrError(f"{line.strip()!r}: unexpected reply {reply!r}")
        return reply

    def info(self) -> str:
        reply = self._checked("INFO", "")
        m = _INFO.match(reply)
        if m:
            self._max_samples = int(m.group(3))
        return reply

    def limits(self) -> str:
        return self.command("LIMITS?")

    def set_gain_manual(self, index: int) -> str:
        return self._checked(f"GAIN MANUAL {int(index)}")

    def set_gain_hardware(self) -> str:
        return self._checked("GAIN HARDWARE")

    def set_bandwidth_mhz(self, mhz: float) -> str:
        return self._checked(f"BANDWIDTH {mhz:g}")

    def lpf(self) -> str:
        """Send ``LPF?`` and return the reply line unchecked: ``LPF <code> <reg4> <reg5>`` on
        firmware that has the command, ``ERR ...`` otherwise. ``parse_lpf_reply`` in
        ``espsdr_capture`` explains the fields."""
        return self.command("LPF?")

    def release(self) -> str:
        return self.command("RELEASE")

    def tune(self, frequency_hz: float) -> str:
        """Tune to a whole number of MHz (100 to 6000). The firmware replies ``OK`` without
        checking PLL lock; the remainder of a non-integer-MHz centre must be handled as a
        frequency offset in processing."""
        mhz = frequency_hz / 1e6
        if mhz != round(mhz) or not FREQ_MIN_MHZ <= mhz <= FREQ_MAX_MHZ:
            raise ValueError(
                f"the firmware tunes whole MHz from {FREQ_MIN_MHZ} to {FREQ_MAX_MHZ}, "
                f"got {frequency_hz} Hz"
            )
        reply = self._checked(f"FREQ {int(round(mhz))}")
        self._frequency_hz = float(round(mhz)) * 1e6
        return reply

    def set_sample_rate(self, sample_rate_hz: float) -> int:
        """Choose the sample rate for later captures; returns the rate index.

        The firmware has no sample-rate command: the rate index is an argument of each
        capture command. This method asks ``LIMITS?`` which rates the chip accepts and
        raises ``ValueError`` if ``sample_rate_hz`` is not among them.
        """
        index = _rate_index(sample_rate_hz)
        reply = self._checked("LIMITS?", "LIMITS ")
        advertised = _parse_limits_rates(reply)
        if sample_rate_hz not in advertised:
            raise ValueError(
                f"{sample_rate_hz} sps not supported by this chip; it offers {advertised}"
            )
        self._rate_index = index
        return index

    def capture(
        self, n_samples: int, sample_rate_hz: float | None = None, bits: int = 10
    ) -> EspSdrCapture:
        """Request one snapshot and return it decoded and CRC-checked.

        ``sample_rate_hz`` defaults to the rate chosen with ``set_sample_rate``. ``bits`` is 8
        (``CAP16``) or 10 (``CAP20``). The maximum sample count comes from ``INFO`` (sent
        once if not yet known). Raises ``EspSdrError`` on ``ERR`` replies,
        ``EspSdrTimeout`` on missing data and ``EspSdrDamagedCapture`` on a header, length
        or CRC mismatch; after a damaged capture, call ``resync``.
        """
        if sample_rate_hz is None:
            if self._rate_index is None:
                raise ValueError("no sample rate: pass sample_rate_hz or call set_sample_rate")
            index = self._rate_index
            sample_rate_hz = next(r for r, i in RATE_INDEX_BY_SPS.items() if i == index)
        else:
            index = _rate_index(sample_rate_hz)
        size = payload_size(n_samples, bits)  # validates bits
        if self._max_samples is None:
            self.info()
        limit = self._max_samples or 0
        if not MIN_CAPTURE_SAMPLES <= n_samples <= limit:
            raise ValueError(f"n_samples must be {MIN_CAPTURE_SAMPLES} to {limit}, got {n_samples}")
        header = self.command(f"CAP{bits * 2} {n_samples} {index}")
        if header.startswith("ERR"):
            raise EspSdrError(f"capture failed: {header}")
        m = _DATA_HEADER.match(header)
        if not m or int(m.group(1)) != n_samples:
            raise EspSdrDamagedCapture(f"unexpected capture header {header!r}")
        payload = self._read_payload(size)
        crc = zlib.crc32(payload)
        if crc != int(m.group(2), 16):
            raise EspSdrDamagedCapture(f"payload CRC-32 {crc:08x} differs from header {m.group(2)}")
        return EspSdrCapture(
            samples=unpack_payload(payload, n_samples, bits),
            sample_rate_hz=float(sample_rate_hz),
            bits=bits,
            capture_us=int(m.group(3)),
            payload_crc32=crc,
            center_frequency_hz=self._frequency_hz,
        )

    def _read_payload(self, size: int) -> bytes:
        payload = self._ser.read(size)
        if len(payload) != size:
            raise EspSdrTimeout(f"payload has {len(payload)} of {size} bytes")
        return payload

    def resync(self, nonce: int = 1) -> None:
        """Find the end of stale bytes after an incomplete transfer: send ``SYNC <nonce>``
        and read lines until a line ends with the echo. Stale binary bytes without a newline can
        precede the echo on the same line, so the line is not compared as a whole."""
        if hasattr(self._ser, "reset_input_buffer"):
            self._ser.reset_input_buffer()
        self._ser.write(f"\nSYNC {int(nonce)}\n".encode("ascii"))
        for _ in range(70_000):
            if self._readline().endswith(f"SYNC {int(nonce)}"):
                return
        raise EspSdrError("no SYNC echo")  # pragma: no cover - needs a stuck port

    def close(self) -> None:
        self._ser.close()


def _rate_index(sample_rate_hz: float) -> int:
    try:
        return RATE_INDEX_BY_SPS[sample_rate_hz]
    except KeyError:
        raise ValueError(
            f"{sample_rate_hz} sps is not an ESP-SDR rate; "
            f"choose one of {sorted(RATE_INDEX_BY_SPS)}"
        ) from None


def _parse_limits_rates(reply: str) -> list[int]:
    import json

    try:
        return [int(r) for r in json.loads(reply[len("LIMITS ") :])["rates"]]
    except (ValueError, KeyError, TypeError) as e:
        raise EspSdrError(f"invalid LIMITS reply {reply!r}") from e
