"""Write simulator output in the formats signal generators play back.

These functions only write files. Transmitting is always a manual step done by a person
with cables and attenuators in place (docs/guides/conducted-test.md); nothing in snappnt starts
a transmission on its own.

Loop playback: generators repeat the file, so its length should be a whole number of data
symbols (20 ms for NavIC SPS) to avoid a discontinuity at the wrap point.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np


def _scale(x: np.ndarray, peak: float) -> np.ndarray:
    m = max(np.max(np.abs(x.real)), np.max(np.abs(x.imag)), 1e-30)
    return x * (peak / m)


def write_hackrf_int8(x: np.ndarray, path: str | Path, peak: float = 0.9) -> Path:
    """Interleaved signed 8-bit I/Q, the format of ``hackrf_transfer -t``."""
    y = _scale(x, peak * 127.0)
    out = np.empty(2 * y.size, dtype=np.int8)
    out[0::2] = np.round(y.real).astype(np.int8)
    out[1::2] = np.round(y.imag).astype(np.int8)
    path = Path(path)
    out.tofile(path)
    return path


def write_uhd_sc16(x: np.ndarray, path: str | Path, peak: float = 0.7) -> Path:
    """Interleaved signed 16-bit I/Q, the default ``--type short`` of UHD's tx_samples_from_file."""
    y = _scale(x, peak * 32767.0)
    out = np.empty(2 * y.size, dtype=np.int16)
    out[0::2] = np.round(y.real).astype(np.int16)
    out[1::2] = np.round(y.imag).astype(np.int16)
    path = Path(path)
    out.tofile(path)
    return path
