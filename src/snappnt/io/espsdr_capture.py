"""Turn ESP-SDR captures into SigMF and plan the command sequence of ``snappnt capture``.

The capture is decoded and CRC-checked by ``EspSdrClient.capture``; the payload layout is
in docs/design/espsdr-protocol.md and the decoder in ``espsdr_iq``.
"""

from __future__ import annotations

import json
import re
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

_CHIP = re.compile(r"^(\w+)SDR\b")


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
) -> Path:
    """Write ``capture`` as SigMF (``ci16_le``, 10-bit scale) and return the base path.

    ``center_frequency_hz`` defaults to the frequency the client tuned to. The firmware's
    capture time and the bit depth of the transfer are stored under ``snappnt:`` keys.

    Optional context: ``firmware_info`` (the ``INFO`` reply; its chip family goes into
    ``core:hw``), ``gain`` (manual gain index; ``None`` means the hardware AGC, whose state
    the firmware does not report), ``analog_bandwidth_mhz`` and ``host_time_utc`` (written
    as ``snappnt:host_time_utc`` and ``core:datetime``). The serial port, host and user
    names and the output path are never recorded.
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
    if analog_bandwidth_mhz is not None:
        extra["analog_bandwidth_mhz"] = analog_bandwidth_mhz
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
    )
    if stamp is not None:
        meta_path = base.with_name(base.name + ".sigmf-meta")
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta["captures"][0]["core:datetime"] = stamp
        meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return base


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
    lines += [f"CAP{bits * 2} {n_samples} {index}"] * count
    return lines


def utc_now() -> datetime:
    return datetime.now(UTC)
