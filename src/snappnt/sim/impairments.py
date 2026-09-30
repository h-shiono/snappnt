"""Receiver-side impairments applied to an ideal baseband signal."""

from __future__ import annotations

import numpy as np


def quantize(x: np.ndarray, bits: int, backoff_db: float = 12.0) -> np.ndarray:
    """Model an AGC followed by a ``bits``-bit ADC on I and Q.

    The AGC scales the input so its RMS per component sits ``backoff_db`` below full scale.
    Output keeps the integer levels (e.g. -512..511 for 10 bits) as complex64.
    """
    full_scale = 2 ** (bits - 1)
    rms = np.sqrt(np.mean(np.abs(x) ** 2) / 2.0)  # per component
    gain = full_scale * 10 ** (-backoff_db / 20.0) / max(rms, 1e-30)
    i = np.clip(np.round(x.real * gain), -full_scale, full_scale - 1)
    q = np.clip(np.round(x.imag * gain), -full_scale, full_scale - 1)
    return (i + 1j * q).astype(np.complex64)


def decimate_without_filter(x: np.ndarray, factor: int) -> np.ndarray:
    """Keep every ``factor``-th sample, with no anti-alias filter.

    Hypothesis model for a low sample rate obtained by dividing the ADC clock: noise from
    the whole analog bandwidth folds into the new, narrower band.
    """
    return x[::factor].copy()


def truncate_capture(x: np.ndarray, max_samples: int | None) -> np.ndarray:
    return x if max_samples is None else x[:max_samples]
