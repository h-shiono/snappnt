"""Turn ESP-SDR captures into SigMF and plan the command sequence of ``snappnt capture``.

The capture is decoded and CRC-checked by ``EspSdrClient.capture``; the payload layout is
in docs/design/espsdr-protocol.md and the decoder in ``espsdr_iq``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from snappnt.io.espsdr_client import (
    FREQ_MAX_MHZ,
    FREQ_MIN_MHZ,
    MIN_CAPTURE_SAMPLES,
    RATE_INDEX_BY_SPS,
    EspSdrCapture,
)
from snappnt.io.sigmf_io import write_sigmf

# From the ``LIMITS`` reply in docs/design/espsdr-protocol.md: "bandwidth":[14,62,1,0].
BANDWIDTH_MIN_MHZ = 14
BANDWIDTH_MAX_MHZ = 62

_CHIP = re.compile(r"^(\w+)SDR\b")
LPF_CODE_MAX = 63
_LPF = re.compile(r"^LPF (-1|\d+) (\d+) (\d+)$")


@dataclass(frozen=True)
class LpfState:
    """The analog low-pass setting reported by ``LPF?`` (docs/design/espsdr-protocol.md).

    ``code`` is the capacitor code the firmware writes into the filter registers for the
    duration of each capture: 0 (widest) to 63 (narrowest), or -1 when the chip's own
    calibrated codes are left in place (power-up state and after ``LPF AUTO``). ``BANDWIDTH``
    converts MHz to such a code through an approximate per-chip table, so the code, not a
    bandwidth in MHz, is what the firmware keeps. ``calibrated_codes`` are the two register
    codes read outside a capture, which are the calibrated values.
    """

    code: int
    calibrated_codes: tuple[int, int]


def parse_lpf_reply(reply: str) -> LpfState | None:
    """``LPF 40 34 34`` -> ``LpfState(40, (34, 34))``; ``None`` for any other reply, such as
    ``ERR command`` from firmware without the command, or one with a code outside 0 to 63."""
    m = _LPF.match(reply.strip())
    if not m:
        return None
    code, reg4, reg5 = (int(g) for g in m.groups())
    # The firmware's codes are 6 bits wide; anything else is not a reply it can send.
    if code > LPF_CODE_MAX or reg4 > LPF_CODE_MAX or reg5 > LPF_CODE_MAX:
        return None
    return LpfState(code, (reg4, reg5))


def chip_name(firmware_info: str | None) -> str:
    """Chip family from an ``INFO`` reply (``C3SDR 6 burst 16380`` -> ``C3``), or ``""``."""
    m = _CHIP.match(firmware_info or "")
    return m.group(1) if m else ""


def save_capture_sigmf(
    capture: EspSdrCapture,
    path: str | Path,
    *,
    center_frequency_hz: float | None = None,
    description: str = "",
    firmware_info: str | None = None,
    gain: int | None = None,
    analog_bandwidth_mhz: float | None = None,
    host_time_utc: datetime | None = None,
    lpf_reply: str | None = None,
) -> Path:
    """Write ``capture`` as SigMF (``ci16_le``, 10-bit scale) and return the base path.

    ``center_frequency_hz`` defaults to the frequency the client tuned to. The firmware's
    capture time and the bit depth of the transfer are stored under ``snappnt:`` keys.

    Optional context: ``firmware_info`` (the ``INFO`` reply; its chip family goes into
    ``core:hw``), ``gain`` (manual gain index; ``None`` means the hardware AGC, whose state
    the firmware does not report), ``analog_bandwidth_mhz`` and ``host_time_utc`` (written
    as ``snappnt:host_time_utc`` and ``core:datetime``). The serial port, host and user
    names and the output path are never recorded.

    With ``firmware_info`` given, ``snappnt:analog_bandwidth_mhz`` is always written; ``null``
    means the bandwidth in MHz is unknown, because the firmware keeps its last setting while
    powered and reports it only as a capacitor code. ``lpf_reply`` (the ``LPF?`` reply) is
    written as ``snappnt:espsdr_lpf_reply``, with ``snappnt:espsdr_lpf_code`` and
    ``snappnt:espsdr_lpf_calibrated_codes`` parsed from it (see ``LpfState``), or ``null``
    when the reply is not an ``LPF`` line.
    """
    center = center_frequency_hz if center_frequency_hz is not None else capture.center_frequency_hz
    chip = chip_name(firmware_info)
    extra: dict[str, object] = {
        "espsdr_transfer_bits": capture.bits,
        "espsdr_capture_us": capture.capture_us,
    }
    if firmware_info is not None:
        extra["espsdr_info"] = firmware_info
        extra["gain_mode"] = "hardware" if gain is None else "manual"
        extra["gain_index"] = gain
    if firmware_info is not None or analog_bandwidth_mhz is not None:
        extra["analog_bandwidth_mhz"] = analog_bandwidth_mhz
    if lpf_reply is not None:
        lpf = parse_lpf_reply(lpf_reply)
        extra["espsdr_lpf_reply"] = lpf_reply
        extra["espsdr_lpf_code"] = None if lpf is None else lpf.code
        extra["espsdr_lpf_calibrated_codes"] = None if lpf is None else list(lpf.calibrated_codes)
    stamp = None
    if host_time_utc is not None:
        stamp = host_time_utc.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        extra["host_time_utc"] = stamp
    base = write_sigmf(
        path,
        capture.samples,
        capture.sample_rate_hz,
        center_frequency_hz=center,
        datatype="ci16_le",
        description=description,
        hw=f"ESP-SDR {chip}".strip() if firmware_info is not None else "ESP-SDR",
        extra_global=extra,
        extra_capture={"core:datetime": stamp} if stamp is not None else None,
    )
    return base


def existing_outputs(paths: list[Path]) -> list[Path]:
    """The SigMF files of ``paths`` that already exist."""
    found = []
    for p in paths:
        for suffix in (".sigmf-data", ".sigmf-meta"):
            f = p.with_name(p.name + suffix)
            if f.exists():
                found.append(f)
    return found


def capture_paths(base: str | Path, count: int) -> list[Path]:
    """Output base paths: ``base`` itself for one capture, ``base_0000``, ``base_0001``, ...
    for several. Each capture is its own recording because separate captures are not
    contiguous in time (docs/project/decisions.md, D-011)."""
    base = Path(base)
    if count < 1:
        raise ValueError(f"count must be at least 1, got {count}")
    if count == 1:
        return [base]
    return [base.with_name(f"{base.name}_{i:04d}") for i in range(count)]


def command_plan(
    *,
    frequency_hz: float,
    sample_rate_hz: float,
    n_samples: int,
    gain: int | None = None,
    bandwidth_mhz: float | None = None,
    bits: int = 10,
    count: int = 1,
    max_samples: int | None = None,
) -> list[str]:
    """Validate the arguments and return the command lines ``snappnt capture`` sends, in
    order. Raises ``ValueError`` for an argument the firmware would refuse. ``max_samples``
    (from ``INFO``) is only known on a live port; without it the upper limit is not checked."""
    mhz = frequency_hz / 1e6
    if mhz != round(mhz) or not FREQ_MIN_MHZ <= mhz <= FREQ_MAX_MHZ:
        raise ValueError(
            f"the firmware tunes whole MHz from {FREQ_MIN_MHZ} to {FREQ_MAX_MHZ}, "
            f"got {frequency_hz} Hz"
        )
    if sample_rate_hz not in RATE_INDEX_BY_SPS:
        raise ValueError(
            f"{sample_rate_hz} sps is not an ESP-SDR rate; "
            f"choose one of {sorted(RATE_INDEX_BY_SPS)}"
        )
    if bandwidth_mhz is not None and not (
        bandwidth_mhz == 0 or BANDWIDTH_MIN_MHZ <= bandwidth_mhz <= BANDWIDTH_MAX_MHZ
    ):
        raise ValueError(
            f"bandwidth must be 0 (widest) or {BANDWIDTH_MIN_MHZ} to {BANDWIDTH_MAX_MHZ} MHz, "
            f"got {bandwidth_mhz}"
        )
    if bits not in (8, 10):
        raise ValueError(f"bits must be 8 or 10, got {bits}")
    limit = max_samples if max_samples is not None else n_samples
    if not MIN_CAPTURE_SAMPLES <= n_samples <= limit:
        raise ValueError(f"n_samples must be {MIN_CAPTURE_SAMPLES} to {limit}, got {n_samples}")
    if count < 1:
        raise ValueError(f"count must be at least 1, got {count}")
    lines = ["SYNC 1", "INFO", f"FREQ {int(round(mhz))}"]
    if bandwidth_mhz is not None:
        lines.append(f"BANDWIDTH {bandwidth_mhz:g}")
    lines.append("GAIN HARDWARE" if gain is None else f"GAIN MANUAL {int(gain)}")
    lines.append("LIMITS?")
    index = RATE_INDEX_BY_SPS[int(sample_rate_hz)]
    # LPF? before every capture: the firmware applies its low-pass code at capture time, and
    # another client may change it if the hold lapses (5 s without a command) between captures.
    lines += ["LPF?", f"CAP{bits * 2} {n_samples} {index}"] * count
    lines.append("RELEASE")
    return lines


# Limits that only the board reports (``LIMITS?`` and ``INFO``), so a dry run cannot check them.
LIVE_ONLY_CHECKS = (
    "not checked without a board: the maximum gain index, the sample rates the chip offers "
    "and the maximum samples per capture"
)


def utc_now() -> datetime:
    return datetime.now(UTC)
