"""Receiver-side impairments applied to an ideal baseband signal.

Order in ``sim/generate.py``: signal + noise (at the generation rate) -> fixed spurs
(``add_spurs``) -> analog low-pass -> output-band low-pass (method ``ideal``) -> decimation ->
quantisation with DC offset (``quantize_with_offset``) or plain ``quantize``. A spur is added
before the analog low-pass, so one outside the analog bandwidth is removed, and one outside the
output band folds to an aliased frequency when the decimation method is ``none``. The DC offset
is added in the ADC, after the AGC gain is set, so it is not part of the level the AGC holds.
"""

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


def quantize_with_offset(
    x: np.ndarray,
    bits: int,
    backoff_db: float = 12.0,
    dc_fullscale: tuple[float, float] = (0.0, 0.0),
) -> np.ndarray:
    """Like ``quantize``, with a DC offset added in the ADC.

    ``dc_fullscale`` is (I, Q) as a fraction of ADC full scale (``2 ** (bits - 1)`` counts), so
    -0.5 on I with 10 bits is -256 counts. The AGC gain is set from the RMS of ``x`` without
    the offset, because a real AGC regulates the signal level and not the constant. The offset
    is constant over the snapshot; the drift seen on real hardware (about 25 counts in 205 us)
    is not modelled. Output is rounded and clipped to -full_scale..full_scale - 1.
    """
    full_scale = 2 ** (bits - 1)
    rms = np.sqrt(np.mean(np.abs(x) ** 2) / 2.0)  # per component
    gain = full_scale * 10 ** (-backoff_db / 20.0) / max(rms, 1e-30)
    i = np.clip(np.round(x.real * gain + dc_fullscale[0] * full_scale), -full_scale, full_scale - 1)
    q = np.clip(np.round(x.imag * gain + dc_fullscale[1] * full_scale), -full_scale, full_scale - 1)
    return (i + 1j * q).astype(np.complex64)


def add_spurs(
    x: np.ndarray,
    fs_hz: float,
    spurs: tuple[tuple[float, float], ...],
    rng: np.random.Generator,
) -> np.ndarray:
    """Add complex tones ``(offset_hz, power_db)`` at the sample rate ``fs_hz`` of ``x``.

    ``power_db`` is the tone power divided by the total noise power per sample (noise has unit
    variance), so the amplitude is ``10 ** (power_db / 20)``. This is not the height above the
    noise floor in a spectrum: in an N-point spectrum a tone of power ratio 1 stands
    ``10 * log10(N)`` dB above the floor of one bin. Each tone has a random start phase drawn
    from ``rng``.
    """
    t = np.arange(len(x)) / fs_hz
    out = x.copy()
    for offset_hz, power_db in spurs:
        phase = rng.uniform(0.0, 2 * np.pi)
        out += 10 ** (power_db / 20.0) * np.exp(1j * (2 * np.pi * offset_hz * t + phase))
    return out


def lowpass(x: np.ndarray, fs_hz: float, bandwidth_hz: float) -> np.ndarray:
    """Brick-wall low-pass of a complex baseband signal, passband +-``bandwidth_hz`` / 2.

    Applied in the frequency domain over the whole snapshot (no filter transient, no ripple).
    A bandwidth at or above ``fs_hz`` leaves the signal unchanged.
    """
    if bandwidth_hz >= fs_hz:
        return x
    spectrum = np.fft.fft(x)
    freqs = np.fft.fftfreq(len(x), d=1.0 / fs_hz)
    spectrum[np.abs(freqs) > bandwidth_hz / 2.0] = 0.0
    return np.fft.ifft(spectrum)


def decimate_without_filter(x: np.ndarray, factor: int) -> np.ndarray:
    """Keep every ``factor``-th sample, with no anti-alias filter.

    Hypothesis model for a low sample rate obtained by dividing the ADC clock: noise from
    the whole analog bandwidth folds into the new, narrower band.
    """
    return x[::factor].copy()


def truncate_capture(x: np.ndarray, max_samples: int | None) -> np.ndarray:
    return x if max_samples is None else x[:max_samples]
