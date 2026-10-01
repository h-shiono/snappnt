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

Doppler rate: by default one hypothesis, ``doppler_rate_hzps``. With ``rate_range_hzps`` the
whole grid is computed for each rate hypothesis, and the peak is the maximum over all
(rate, frequency, lag) cells. The false-alarm threshold counts the rate hypotheses.

Not yet modelled: code Doppler within the snapshot (negligible for captures of a few ms).
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import numpy as np
from scipy import fft as sp_fft
from scipy import stats

from snappnt.signals import SignalSpec, get_code

_WORKERS = os.cpu_count() or 1


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
    doppler_rate_hzps: float = 0.0  # rate hypothesis of the peak cell
    rate_step_hzps: float = 0.0  # 0 when a single rate hypothesis was used


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


# Working-memory budget for one batch, in bytes per temporary array. The number of frequency
# bins per batch is chosen so that each temporary array (float64 cycles, complex64 wipe-off,
# the FFT buffers) holds about this many bytes, whatever the snapshot length.
_BATCH_BYTES = 32 * 2**20
_MAX_CHUNK_BINS = 64


def _power_grid(
    x: np.ndarray,
    fs: float,
    carriers_hz: np.ndarray,
    doppler_rate_hzps: float,
    rep_f: list[np.ndarray],
    block: int,
    n_blocks: int,
    nfft: int,
    k: int,
) -> np.ndarray:
    """Non-coherent power of the correlation for every (carrier frequency, lag) cell.

    The frequency bins are processed in batches with one 2-D FFT call per block. The carrier
    wipe-off is built one block at a time, and the batch size is chosen from the FFT length, so
    the working memory is about ``_BATCH_BYTES`` per temporary array and does not grow with the
    snapshot length. The carrier phase is computed in float64 and reduced to one cycle before
    it is cast to single precision, so the phase stays accurate for long snapshots.
    """
    t = np.arange(n_blocks * block) / fs
    quad_cycles = 0.5 * doppler_rate_hzps * t**2
    power = np.zeros((carriers_hz.size, k), dtype=np.float32)
    chunk_bins = int(np.clip(_BATCH_BYTES // (8 * max(nfft, block)), 1, _MAX_CHUNK_BINS))
    for lo in range(0, carriers_hz.size, chunk_bins):
        sel = carriers_hz[lo : lo + chunk_bins]
        acc = power[lo : lo + sel.size]
        for b in range(n_blocks):
            seg = slice(b * block, (b + 1) * block)
            cycles = np.outer(sel, t[seg])
            cycles += quad_cycles[seg]
            cycles -= np.floor(cycles)
            phase = (cycles * (-2.0 * np.pi)).astype(np.float32)
            del cycles
            yb = np.empty(phase.shape, dtype=np.complex64)
            yb.real = np.cos(phase)
            yb.imag = np.sin(phase)
            del phase
            yb *= x[seg]
            yb_f = sp_fft.fft(yb, nfft, axis=-1, workers=_WORKERS)
            del yb
            yb_f = np.conj(yb_f)
            yb_f *= rep_f[b]
            corr = sp_fft.ifft(yb_f, axis=-1, workers=_WORKERS)[:, :k]
            acc += corr.real**2 + corr.imag**2
    return power


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
    rate_range_hzps: tuple[float, float] | None = None,
    rate_step_hzps: float | None = None,
) -> AcqResult:
    """Search one PRN.

    ``center_offset_hz`` is where the carrier would sit with zero Doppler and zero clock error
    (the frequency plan's baseband offset). ``freq_range_hz`` is searched around it.

    ``refine`` interpolates the peak between grid points along code phase and frequency. It
    changes only ``code_phase_chips`` and ``freq_offset_hz``. No frequency refinement is made
    when the peak is on the edge of the searched range.

    ``rate_range_hzps`` (absolute Doppler rates, Hz/s) switches on a Doppler-rate search;
    ``doppler_rate_hzps`` is then ignored. The step defaults to ``1 / (4 T^2)`` for coherent
    time ``T``, which keeps the residual quadratic phase at the edge of a step below 1/16 cycle.
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
    rep_f = [
        sp_fft.fft(rep[b * block : b * block + block + k], nfft).astype(np.complex64)
        for b in range(n_blocks)
    ]

    if rate_range_hzps is None:
        rates = np.array([doppler_rate_hzps])
        used_rate_step = 0.0
    else:
        used_rate_step = rate_step_hzps if rate_step_hzps is not None else 0.25 / t_coh**2
        rates = np.arange(
            rate_range_hzps[0], rate_range_hzps[1] + used_rate_step / 2, used_rate_step
        )

    # Keep the grid of the rate hypothesis with the highest peak; the noise level and the
    # refinement use that grid.
    power = None
    best_rate = float(rates[0])
    for rate in rates:
        grid = _power_grid(
            x, fs, freqs + center_offset_hz, float(rate), rep_f, block, n_blocks, nfft, k
        )
        if power is None or grid.max() > power.max():
            power, best_rate = grid, float(rate)

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
    n_cells = power.size * rates.size
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
        doppler_rate_hzps=best_rate,
        rate_step_hzps=float(used_rate_step),
    )


def acquire_many(x: np.ndarray, fs: float, spec: SignalSpec, prns, **kwargs) -> list[AcqResult]:
    return [acquire(x, fs, spec, prn, **kwargs) for prn in prns]
