"""Turn an ESP-SDR capture into SigMF.

The capture is decoded and CRC-checked by ``EspSdrClient.capture``; the payload layout is
in docs/design/espsdr-protocol.md and the decoder in ``espsdr_iq``.
"""

from __future__ import annotations

from pathlib import Path

from snappnt.io.espsdr_client import EspSdrCapture
from snappnt.io.sigmf_io import write_sigmf


def save_capture_sigmf(
    capture: EspSdrCapture,
    path: str | Path,
    *,
    center_frequency_hz: float | None = None,
    description: str = "",
) -> Path:
    """Write ``capture`` as SigMF (``ci16_le``, 10-bit scale) and return the base path.

    ``center_frequency_hz`` defaults to the frequency the client tuned to. The firmware's
    capture time and the bit depth of the transfer are stored under ``snappnt:`` keys.
    """
    center = center_frequency_hz if center_frequency_hz is not None else capture.center_frequency_hz
    return write_sigmf(
        path,
        capture.samples,
        capture.sample_rate_hz,
        center_frequency_hz=center,
        datatype="ci16_le",
        description=description,
        hw="ESP-SDR",
        extra_global={
            "espsdr_transfer_bits": capture.bits,
            "espsdr_capture_us": capture.capture_us,
        },
    )
