"""Reference acquisition: the per-bin FFT loop used before the batched version (frozen copy).

Kept so that tests and tools/bench_acquire.py can compare the optimised code with it.
"""

from __future__ import annotations

import numpy as np

from snappnt.rx.acquisition import AcqResult, _replica, detection_threshold, parabolic_offset
from snappnt.signals import SignalSpec, get_code


def acquire_reference(
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
