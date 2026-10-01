"""Convert raw I/Q files of the reference receivers to SigMF.

The sample values are copied unchanged: no resampling and no scaling. Integer files stay
integer (``ci16_le``, ``ci8``) and float files stay float (``cf32_le``), so the converted
recording holds exactly the values that were written by the recording program.

Formats (interleaved I, Q, I, Q, ...):

- ``uhd-short``: signed 16-bit integers, the ``--type short`` of UHD ``rx_samples_to_file``.
  UHD writes host byte order; this module reads little endian (x86 and ARM hosts).
- ``uhd-float``: 32-bit floats, the ``--type float`` of UHD ``rx_samples_to_file``. Little
  endian, for the same reason.
- ``hackrf``: signed 8-bit integers, the format of ``hackrf_transfer -r`` (the HackRF
  documentation describes the samples as signed 8-bit I/Q).

The formats of real recordings are not verified here, because there is no hardware on the
build machine.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from snappnt.io.sigmf_io import write_sigmf


@dataclass(frozen=True)
class RawFormat:
    sigmf_datatype: str
    component_dtype: str  # NumPy dtype of one I or Q value in the input file

    @property
    def bytes_per_sample(self) -> int:
        return 2 * np.dtype(self.component_dtype).itemsize


FORMATS: dict[str, RawFormat] = {
    "uhd-short": RawFormat("ci16_le", "<i2"),
    "uhd-float": RawFormat("cf32_le", "<f4"),
    "hackrf": RawFormat("ci8", "i1"),
}


def convert_iq(
    input_path: str | Path,
    output_base: str | Path,
    fmt: str,
    sample_rate_hz: float,
    center_frequency_hz: float,
    hw: str,
    *,
    description: str = "",
    overwrite: bool = False,
) -> Path:
    """Write ``input_path`` as SigMF at ``output_base``; returns the base path.

    Raises ``ValueError`` for an unknown format, an empty input, an input size that is not a
    whole number of samples, a sample rate that is not finite and positive, a centre frequency
    that is not finite, or an input that is the same file as an output file or its temporary
    file; and ``FileExistsError`` if the output exists and ``overwrite`` is false."""
    if fmt not in FORMATS:
        raise ValueError(f"unknown format {fmt!r}; choose one of {', '.join(FORMATS)}")
    spec = FORMATS[fmt]
    if not (math.isfinite(sample_rate_hz) and sample_rate_hz > 0):
        raise ValueError(f"sample rate must be finite and positive, got {sample_rate_hz}")
    if not math.isfinite(center_frequency_hz):
        raise ValueError(f"centre frequency must be finite, got {center_frequency_hz}")
    path = Path(input_path)
    size = path.stat().st_size
    if size == 0:
        raise ValueError(f"{path}: file is empty")
    if size % spec.bytes_per_sample:
        raise ValueError(
            f"{path}: file size {size} bytes is not a whole number of {fmt} samples "
            f"({spec.bytes_per_sample} bytes per sample)"
        )
    base = Path(output_base)
    for suffix in (".sigmf-meta", ".sigmf-data", ".sigmf"):
        if base.name.endswith(suffix):
            base = base.with_name(base.name[: -len(suffix)])
    for suffix in (".sigmf-data", ".sigmf-meta"):
        for output in (
            base.with_name(base.name + suffix),
            base.with_name(base.name + suffix + ".tmp"),
        ):
            if output.resolve() == path.resolve() or (
                output.exists() and os.path.samefile(output, path)
            ):
                raise ValueError(f"{path} is the same file as the output {output}")
    if not overwrite:
        for suffix in (".sigmf-data", ".sigmf-meta"):
            existing = base.with_name(base.name + suffix)
            if existing.exists():
                raise FileExistsError(f"{existing} exists; pass overwrite to replace it")

    raw = np.fromfile(path, dtype=spec.component_dtype)
    if fmt == "uhd-float":
        # View the interleaved floats as complex64: no arithmetic, so NaN, infinity and
        # negative zero keep their bit patterns.
        x = np.ascontiguousarray(raw, dtype="<f4").view("<c8")
    else:
        # int16 and int8 values are exactly representable in float32, so nothing is rounded.
        x = np.empty(raw.size // 2, dtype=np.complex64)
        x.real = raw[0::2]
        x.imag = raw[1::2]
    return write_sigmf(
        base,
        x,
        sample_rate_hz,
        center_frequency_hz=center_frequency_hz,
        datatype=spec.sigmf_datatype,
        description=description or f"converted from {fmt} raw file",
        hw=hw,
    )
