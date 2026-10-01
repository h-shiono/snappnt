"""Snapshot acquisition: search code phase and carrier frequency in one short capture.

Works for snapshots shorter than one code period (ESP32 at 80 MSa/s holds only ~0.2 ms,
a fifth of a NavIC code period) as well as longer ones.

Method
------
For each carrier-frequency bin the snapshot y[n] (length N) is correlated against a local
replica r[m] that starts at code phase 0 and is N + K samples long, where K is the number
of samples in one code period::

    c[k] = sum_n y[n] * r[n + k],   k = 0 .. K-1

Lag k means "the snapshot starts k samples into the code period". The correlation is
computed with one FFT pair per frequency bin, zero-padded so there is no circular wrap.

With ``n_blocks > 1`` the snapshot is cut into blocks that are correlated separately and
added in power (non-coherent). This tolerates data-bit flips and residual frequency error
at the cost of some sensitivity.

Detection: under noise alone each cell's normalised power follows a Gamma(B, 1/B)
distribution (B = n_blocks). The threshold is set so that the probability of any false
peak over the whole search grid is ``pfa``.

Refinement: with ``refine=True`` the code phase and frequency of the peak cell are refined by
three-point parabolic interpolation of the power grid (see ``parabolic_offset``). Only the
reported ``code_phase_chips`` and ``freq_offset_hz`` change; the detection metric, the
threshold and the C/N0 estimate are those of the peak cell.

Not yet modelled: code Doppler within the snapshot (negligible for captures of a few ms),
Doppler-rate search (parameter accepted, applied as a fixed hypothesis).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import stats

from snappnt.signals import SignalSpec, get_code


@dataclass(frozen=True)
class AcqResult:
    prn: int
    detected: bool
    code_phase_chips: float
    freq_offset_hz: float
    metric: float  # peak power / mean noise power
    threshold: float
    cn0_dbhz_est: float
    n_cells: int
    freq_step_hz: float
    coherent_time_s: float


def _replica(code: np.ndarray, chip_rate_hz: float, fs: float, n: int) -> np.ndarray:
    idx = np.floor(np.arange(n) * chip_rate_hz / fs).astype(np.int64) % code.size
    return code[idx].astype(np.float32)


def detection_threshold(n_cells: int, n_blocks: int, pfa: float) -> float:
    """Normalised power threshold for a grid of ``n_cells`` with overall false-alarm ``pfa``."""
    return float(stats.gamma.isf(pfa / n_cells, a=n_blocks, scale=1.0 / n_blocks))


def parabolic_offset(y_minus: float, y_zero: float, y_plus: float) -> float:
    """Vertex of the parabola through three equally spaced samples, in sample spacings.

    ``y_zero`` is the largest of the three. The result lies in [-0.5, 0.5]; it is 0 when the
    three values are on a straight line (no curvature).
    """
    denom = y_minus - 2.0 * y_zero + y_plus
    if denom >= 0.0:
        return 0.0
    return float(np.clip(0.5 * (y_minus - y_plus) / denom, -0.5, 0.5))


def acquire(
    x: np.ndarray,
    fs: float,
    spec: SignalSpec,
    prn: int,
    *,
    center_offset_hz: float = 0.0,
    freq_range_hz: tuple[float, float] = (-50e3, 50e3),
    freq_step_hz: float | None = None,
    doppler_rate_hzps: float = 0.0,
    n_blocks: int = 1,
    pfa: float = 1e-3,
    refine: bool = False,
) -> AcqResult:
    """Search one PRN.

    ``center_offset_hz`` is where the carrier would sit with zero Doppler and zero clock error
    (the frequency plan's baseband offset). ``freq_range_hz`` is searched around it.

    ``refine`` interpolates the peak between grid points along code phase and frequency. It
    changes only ``code_phase_chips`` and ``freq_offset_hz``. No frequency refinement is made
    when the peak is on the edge of the searched range.
    """
    x = np.asarray(x, dtype=np.complex64)
    n = x.size
    k = int(np.ceil(spec.code_period_s * fs))  # lags to test
    block = n // n_blocks
    t_coh = block / fs
    step = freq_step_hz if freq_step_hz is not None else 1.0 / (2.0 * t_coh)
    freqs = np.arange(freq_range_hz[0], freq_range_hz[1] + step / 2, step)

    code = get_code(spec, prn)
    rep = _replica(code, spec.chip_rate_hz, fs, n + k)
    # Each block only needs the replica segment it can overlap: [start, start + block + k).
    nfft = 1 << int(np.ceil(np.log2(2 * block + k)))
    rep_f = [np.fft.fft(rep[b * block : b * block + block + k], nfft) for b in range(n_blocks)]

    t = np.arange(n) / fs
    power = np.zeros((freqs.size, k), dtype=np.float64)
    for i, f in enumerate(freqs):
        wipe = np.exp(-2j * np.pi * ((center_offset_hz + f) * t + 0.5 * doppler_rate_hzps * t**2))
        y = (x * wipe).astype(np.complex64)
        for b in range(n_blocks):
            yb_f = np.fft.fft(y[b * block : (b + 1) * block], nfft)
            corr = np.fft.ifft(rep_f[b] * np.conj(yb_f))[:k]
            power[i] += np.abs(corr) ** 2

    # Noise level: mean power away from the peak (exclude +/-1 chip and +/-1 frequency bin).
    fi, ki = np.unravel_index(np.argmax(power), power.shape)
    guard = int(np.ceil(fs / spec.chip_rate_hz)) + 1
    mask = np.ones_like(power, dtype=bool)
    lag_sel = (np.arange(k)[None, :] - ki) % k
    near_lag = (lag_sel <= guard) | (lag_sel >= k - guard)
    near_f = np.abs(np.arange(freqs.size)[:, None] - fi) <= 1
    mask[near_f & near_lag] = False
    noise = float(np.mean(power[mask])) if mask.any() else float(np.mean(power))

    metric = float(power[fi, ki] / noise)
    n_cells = power.size
    thr = detection_threshold(n_cells, n_blocks, pfa)

    # Post-correlation SNR per block ~ metric - 1, and C/N0 ~ SNR / T_block (losses ignored).
    snr = max(metric - 1.0, 1e-12)
    cn0 = 10.0 * np.log10(snr / t_coh)

    lag = float(ki)
    freq_hz = float(freqs[fi])
    if refine:
        lag += parabolic_offset(power[fi, (ki - 1) % k], power[fi, ki], power[fi, (ki + 1) % k])
        if 0 < fi < freqs.size - 1:
            freq_hz += step * parabolic_offset(power[fi - 1, ki], power[fi, ki], power[fi + 1, ki])

    return AcqResult(
        prn=prn,
        detected=metric > thr,
        code_phase_chips=float((lag * spec.chip_rate_hz / fs) % spec.code_length),
        freq_offset_hz=freq_hz,
        metric=metric,
        threshold=thr,
        cn0_dbhz_est=float(cn0),
        n_cells=n_cells,
        freq_step_hz=float(step),
        coherent_time_s=float(t_coh),
    )


def acquire_many(x: np.ndarray, fs: float, spec: SignalSpec, prns, **kwargs) -> list[AcqResult]:
    return [acquire(x, fs, spec, prn, **kwargs) for prn in prns]
