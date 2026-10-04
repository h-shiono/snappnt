"""Analysis of the conducted test of milestone M3 (GitHub issue #11).

The generator (B210 clone) plays a NavIC S-band SPS file with noise added in software and the
XIAO ESP32C3 records 0.2 ms captures with ``snappnt capture``. Subcommands:

``rise``  Power spectral density (PSD) of a set of generator-on captures against a set of
          generator-off (or reference) captures, in the generator's band. Bins of the
          generator's LO leakage line and the DC bins are excluded, so that neither inflates
          the rise. Also reports samples at the ends of the 10-bit range and narrow lines in
          the generator-on PSD.

          uv run python tools/conducted_pd.py rise out/m3/off out/m3/level_on

``acquire`` Acquisition of every capture in one or more directories, one CSV row per capture
          (peak detection metric, threshold, frequency, code phase, C/N0 estimate).

          uv run python tools/conducted_pd.py acquire out/m3/b0 out/m3/cn55 ... \\
              --center-hz 28000 --freq-span-hz 40000 --remove-dc mean -o out/m3/acq.csv

``pd``    Detection probability per run from that CSV. The true code phase and carrier
          frequency of a real capture are unknown, so a capture counts as a detection when its
          metric exceeds the threshold and its frequency is within ``tol`` bins of the run's
          reference frequency, the median frequency of the detections in the 60 dB-Hz bracket
          runs recorded before and after it. ``tol`` is one bin, or two bins when the reference
          frequency drifted by more than one bin between the two brackets. For a noise-only run
          the peak metrics are compared with the distribution the threshold assumes.

          uv run python tools/conducted_pd.py pd out/m3/acq.csv \\
              --run cn55:55:b0:b1 --run cn52:52:b1:b2 --run noise:noise:b4:b5 -o pd.csv

``cn0``   C/N0 estimate of one long recording (for example the reference recorded by a
          HackRF One, or the playback file itself), from the prompt correlations of 1 ms
          blocks by the M2M4 moments estimator, averaged over segments. Run it on the
          playback file and on the recording alike and compare: losses inside the estimator
          cancel in the difference.

          uv run python tools/conducted_pd.py cn0 out/m3/hackrf/on50 --carrier-hz 2029750 \\
              --blocks 100 --segments 90

``plot``  Measured detection probability over the simulated curve of ``snappnt sweep``
          (needs the ``plot`` extra).

Results: docs/results/conducted-m3.md.

Terms: *capture*, one ``CAP20`` request (16380 samples at 80 MSa/s, 204.75 us); *bin*, the
frequency step of the acquisition grid, 1/(2T) for a capture of length T; *metric*, the peak
correlation power divided by the mean power of the other cells (``snappnt.rx.acquire``).
The recordings themselves are not committed (``out/`` is ignored by git).
"""

from __future__ import annotations

import argparse
import csv
import math
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

import numpy as np
from scipy import stats

FFT_SIZE = 1024
ADC_MIN = -512  # ends of the 10-bit range of CAP20
ADC_MAX = 511
LINE_MIN_DB = 8.0  # a local maximum this far above the local floor is a line
FLOOR_BINS = 31  # running-median length for the local floor

# Frequency plan of the conducted test, as offsets in the XIAO's baseband (tuned to 2492 MHz).
# The generator is centred at 2490.528 MHz and its 8 MSa/s playback spans +/-4 MHz around it.
GEN_CENTER_HZ = -1.472e6
GEN_HALF_BAND_HZ = 4.0e6
EXCLUDE_HZ = 250e3  # half-width excluded around the LO line and around DC (3 bins of 78 kHz)

CSV_FIELDS = (
    "run",
    "capture",
    "detected",
    "metric",
    "threshold",
    "n_cells",
    "freq_offset_hz",
    "freq_step_hz",
    "code_phase_chips",
    "cn0_dbhz_est",
)


# --- rise -----------------------------------------------------------------------------------


def capture_psd(x: np.ndarray) -> np.ndarray:
    """Mean of Hann-windowed periodograms of the mean-removed capture, centred on 0 Hz."""
    y = x - x.mean()
    n_seg = y.size // FFT_SIZE
    seg = y[: n_seg * FFT_SIZE].reshape(n_seg, FFT_SIZE) * np.hanning(FFT_SIZE)
    return np.mean(np.abs(np.fft.fftshift(np.fft.fft(seg, axis=1), axes=1)) ** 2, axis=0)


def offsets_hz(sample_rate_hz: float) -> np.ndarray:
    return np.fft.fftshift(np.fft.fftfreq(FFT_SIZE, 1 / sample_rate_hz))


def band_mask(
    f_hz: np.ndarray,
    gen_center_hz: float = GEN_CENTER_HZ,
    half_band_hz: float = GEN_HALF_BAND_HZ,
    exclude_hz: float = EXCLUDE_HZ,
) -> np.ndarray:
    """Bins inside the generator's band, without the LO-leakage bins and the DC bins."""
    inside = np.abs(f_hz - gen_center_hz) <= half_band_hz
    near_lo = np.abs(f_hz - gen_center_hz) <= exclude_hz
    near_dc = np.abs(f_hz) <= exclude_hz
    return inside & ~near_lo & ~near_dc


def band_rise_db(psd_on: np.ndarray, psd_off: np.ndarray, mask: np.ndarray) -> float:
    """Ratio in dB of the mean PSD over the selected bins, generator on against off."""
    return float(10 * np.log10(np.mean(psd_on[mask]) / np.mean(psd_off[mask])))


def at_limit_fraction(x: np.ndarray, low: float = ADC_MIN, high: float = ADC_MAX) -> float:
    """Fraction of samples with I or Q at an end of the converter's range."""
    i, q = x.real, x.imag
    hit = (i <= low) | (i >= high) | (q <= low) | (q >= high)
    return float(np.mean(hit))


def find_lines(psd_db: np.ndarray) -> list[tuple[int, float]]:
    """Indices and heights above the local floor (running median) of narrow local maxima."""
    from scipy.ndimage import median_filter

    floor = median_filter(psd_db, FLOOR_BINS, mode="nearest")
    out = []
    for k in range(2, psd_db.size - 2):
        height = float(psd_db[k] - floor[k])
        if psd_db[k] == psd_db[k - 2 : k + 3].max() and height > LINE_MIN_DB:
            out.append((k, height))
    return out


def recordings(directory: Path) -> list[Path]:
    return sorted(directory.glob("*.sigmf-meta"))


def _meta_path(path: Path) -> Path:
    return path if path.name.endswith(".sigmf-meta") else Path(f"{path}.sigmf-meta")


def read_segments(path: Path, seg_len: int, n_seg: int) -> tuple[list[np.ndarray], float]:
    """Up to ``n_seg`` segments of ``seg_len`` samples, spread evenly over one long SigMF
    recording, read through a memory map so that the whole file is never loaded."""
    import json

    from snappnt.io.sigmf_io import _DTYPES

    meta_path = _meta_path(path)
    meta = json.loads(meta_path.read_text())
    fs = float(meta["global"]["core:sample_rate"])
    raw = np.memmap(
        meta_path.with_name(meta_path.name.replace(".sigmf-meta", ".sigmf-data")),
        dtype=_DTYPES[meta["global"]["core:datatype"]],
        mode="r",
    )
    seg_len = min(seg_len, raw.size)
    starts = np.linspace(0, raw.size - seg_len, min(n_seg, raw.size // seg_len)).astype(int)
    out = []
    for st in starts:
        r = raw[st : st + seg_len]
        if r.dtype.names:
            x = r["i"].astype(np.float32) + 1j * r["q"].astype(np.float32)
        else:
            x = np.asarray(r)
        out.append(x.astype(np.complex64))
    return out, fs


def load_set(
    path: Path, low: float = ADC_MIN, high: float = ADC_MAX
) -> tuple[np.ndarray, float, float]:
    """Median PSD, sample rate and worst fraction of samples at the converter limits.

    ``path`` is a directory of short captures (each capture is one PSD) or one long recording
    (200 segments of 100 FFT lengths, spread over the file, each one PSD)."""
    from snappnt.io import read_sigmf

    if path.is_dir():
        paths = recordings(path)
        if not paths:
            raise SystemExit(f"no SigMF recordings in {path}")
        segs, fs = [], 0.0
        for p in paths:
            x, meta = read_sigmf(p)
            capture_fs = float(meta["global"]["core:sample_rate"])
            if segs and capture_fs != fs:
                raise SystemExit(f"captures in {path} have different sample rates")
            fs = capture_fs
            segs.append(x)
    else:
        segs, fs = read_segments(path, 100 * FFT_SIZE, 200)
    psds = [capture_psd(x) for x in segs]
    worst = max(at_limit_fraction(x, low, high) for x in segs)
    return np.median(psds, axis=0), fs, worst


def cmd_rise(a: argparse.Namespace) -> int:
    psd_off, fs, lim_off = load_set(Path(a.off), a.adc_min, a.adc_max)
    psd_on, fs_on, lim_on = load_set(Path(a.on), a.adc_min, a.adc_max)
    if fs != fs_on:
        raise SystemExit("the two sets have different sample rates")
    f = offsets_hz(fs)
    mask = band_mask(f, a.gen_center_hz, a.half_band_hz, a.exclude_hz)
    rise = band_rise_db(psd_on, psd_off, mask)
    lo = np.abs(f - a.gen_center_hz) <= a.exclude_hz
    print(f"bins used: {int(mask.sum())} of {f.size} ({(f[1] - f[0]) / 1e3:.1f} kHz each)")
    print(f"in-band rise, on against off: {rise:.2f} dB (pass if >= {a.min_rise_db:g} dB)")
    print(f"LO-leakage bins, on against off: {band_rise_db(psd_on, psd_off, lo):.2f} dB")
    print(f"samples at the converter limits, worst capture: off {lim_off:.2e}, on {lim_on:.2e}")
    on_db = 10 * np.log10(psd_on)
    off_db = 10 * np.log10(psd_off)
    print("narrow lines in the generator-on PSD (offset, RF, height above floor, on-off):")
    for k, h in find_lines(on_db):
        rf_mhz = (a.tuned_hz + f[k]) / 1e6
        print(
            f"  {f[k] / 1e6:+8.3f} MHz  {rf_mhz:9.3f} MHz  {h:5.1f} dB  "
            f"{on_db[k] - off_db[k]:+5.1f} dB"
        )
    ok = rise >= a.min_rise_db and lim_on == 0.0
    return 0 if ok else 1


# --- acquire --------------------------------------------------------------------------------


def acquire_dir(
    directory: Path,
    *,
    prn: int,
    signal: str,
    center_hz: float,
    freq_span_hz: float,
    remove_dc: str,
    pfa: float,
    refine: bool = False,
    freq_step_hz: float | None = None,
) -> list[dict]:
    from snappnt.io import read_sigmf
    from snappnt.rx import acquire
    from snappnt.signals import load_signal

    spec = load_signal(signal)
    rows = []
    for p in recordings(directory):
        x, meta = read_sigmf(p)
        fs = float(meta["global"]["core:sample_rate"])
        r = acquire(
            x, fs, spec, prn,
            center_offset_hz=center_hz,
            freq_range_hz=(-freq_span_hz, freq_span_hz),
            pfa=pfa,
            remove_dc=remove_dc,
            freq_step_hz=freq_step_hz,
            refine=refine,
        )  # fmt: skip
        rows.append(
            {
                "run": directory.name,
                "capture": p.name.removesuffix(".sigmf-meta"),
                "detected": int(r.detected),
                "metric": round(r.metric, 3),
                "threshold": round(r.threshold, 3),
                "n_cells": r.n_cells,
                "freq_offset_hz": round(r.freq_offset_hz, 1),
                "freq_step_hz": round(r.freq_step_hz, 3),
                "code_phase_chips": round(r.code_phase_chips, 3),
                "cn0_dbhz_est": round(r.cn0_dbhz_est, 2),
            }
        )
    return rows


def cmd_acquire(a: argparse.Namespace) -> int:
    rows = []
    for d in a.dirs:
        got = acquire_dir(
            Path(d),
            prn=a.prn,
            signal=a.signal,
            center_hz=a.center_hz,
            freq_span_hz=a.freq_span_hz,
            remove_dc=a.remove_dc,
            pfa=a.pfa,
            refine=a.refine,
            freq_step_hz=a.freq_step_hz,
        )
        n_det = sum(r["detected"] for r in got)
        freqs = [r["freq_offset_hz"] for r in got if r["detected"]]
        med = f"{np.median(freqs):+.0f} Hz" if freqs else "-"
        print(f"{Path(d).name}: {len(got)} captures, {n_det} above threshold, median freq {med}")
        rows += got
    with open(a.output, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {a.output}")
    return 0


# --- pd -------------------------------------------------------------------------------------


@dataclass(frozen=True)
class RunSpec:
    name: str
    cn0: str  # dB-Hz as text, or "noise"
    pre: str
    post: str

    @classmethod
    def parse(cls, text: str) -> RunSpec:
        parts = text.split(":")
        if len(parts) != 4:
            raise argparse.ArgumentTypeError("expected name:cn0:pre_bracket:post_bracket")
        return cls(*parts)


@dataclass(frozen=True)
class RunResult:
    run: str
    cn0: str
    trials: int
    detections: int
    wrong: int
    ref_freq_hz: float
    drift_hz: float
    tol_bins: int
    freq_step_hz: float

    @property
    def p_detect(self) -> float:
        return self.detections / self.trials

    @property
    def p_wrong(self) -> float:
        return self.wrong / self.trials


def read_rows(path: str | Path) -> list[dict]:
    with open(path, newline="") as fh:
        rows = list(csv.DictReader(fh))
    for r in rows:
        r["detected"] = int(r["detected"])
        for k in (
            "metric",
            "threshold",
            "freq_offset_hz",
            "freq_step_hz",
            "code_phase_chips",
            "cn0_dbhz_est",
        ):
            r[k] = float(r[k])
        r["n_cells"] = int(r["n_cells"])
    return rows


def bracket_freq_hz(rows: Sequence[dict]) -> float:
    freqs = [r["freq_offset_hz"] for r in rows if r["detected"]]
    if not freqs:
        raise ValueError(f"no detection in bracket {rows[0]['run'] if rows else '(empty)'}")
    return float(np.median(freqs))


def evaluate_run(spec: RunSpec, by_run: dict[str, list[dict]]) -> RunResult:
    rows = by_run[spec.name]
    f_pre = bracket_freq_hz(by_run[spec.pre])
    f_post = bracket_freq_hz(by_run[spec.post])
    step = rows[0]["freq_step_hz"]
    drift = f_post - f_pre
    tol = 1 if abs(drift) <= step else 2
    ref = 0.5 * (f_pre + f_post)
    near = [abs(r["freq_offset_hz"] - ref) <= tol * step + 1e-6 for r in rows]
    det = sum(1 for r, n in zip(rows, near, strict=True) if r["detected"] and n)
    wrong = sum(1 for r, n in zip(rows, near, strict=True) if r["detected"] and not n)
    return RunResult(spec.name, spec.cn0, len(rows), det, wrong, ref, drift, tol, step)


def null_cdf(metric: np.ndarray, n_cells: int) -> np.ndarray:
    """CDF of the largest of ``n_cells`` independent unit-mean exponential cell powers, the
    noise-only distribution the threshold of a single-block search assumes."""
    return np.exp(n_cells * np.log1p(-np.exp(-np.asarray(metric, dtype=float))))


def noise_check(rows: Sequence[dict]) -> dict[str, float]:
    """False alarms of a noise-only run and a Kolmogorov-Smirnov comparison of its peak
    metrics with ``null_cdf``. The upper bound on the false-alarm probability is the one-sided
    95 % Clopper-Pearson limit."""
    m = np.array([r["metric"] for r in rows])
    n_cells = rows[0]["n_cells"]
    k = sum(r["detected"] for r in rows)
    n = len(rows)
    ks = stats.kstest(m, lambda v: null_cdf(v, n_cells))
    upper = float(stats.beta.ppf(0.95, k + 1, n - k)) if k < n else 1.0
    # Median of the assumed distribution: solve F(m) = 0.5.
    med_null = -math.log(1 - 0.5 ** (1 / n_cells))
    return {
        "trials": n,
        "false_alarms": k,
        "pfa_upper_95": upper,
        "ks_statistic": float(ks.statistic),
        "ks_pvalue": float(ks.pvalue),
        "median_metric": float(np.median(m)),
        "median_metric_null": med_null,
    }


def cmd_pd(a: argparse.Namespace) -> int:
    rows = read_rows(a.csv)
    by_run: dict[str, list[dict]] = {}
    for r in rows:
        by_run.setdefault(r["run"], []).append(r)
    out = []
    print(" run      C/N0   trials  p_detect  p_wrong  ref[Hz]   drift[Hz]  tol")
    for spec in a.run:
        res = evaluate_run(spec, by_run)
        out.append(res)
        print(
            f" {res.run:8s} {res.cn0:>5s}  {res.trials:6d}  {res.p_detect:8.3f}  {res.p_wrong:7.3f}"
            f"  {res.ref_freq_hz:+8.0f}  {res.drift_hz:+9.0f}  {res.tol_bins}"
        )
        if spec.cn0 == "noise":
            nc = noise_check(by_run[spec.name])
            print(
                f"   noise only: {nc['false_alarms']} of {nc['trials']} above threshold, "
                f"pfa < {nc['pfa_upper_95']:.4f} (95 %); median metric {nc['median_metric']:.2f} "
                f"(assumed {nc['median_metric_null']:.2f}); KS D = {nc['ks_statistic']:.3f}, "
                f"p = {nc['ks_pvalue']:.3f}"
            )
    if a.output:
        with open(a.output, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(
                [
                    "run",
                    "cn0_dbhz",
                    "trials",
                    "p_detect",
                    "p_wrong",
                    "ref_freq_hz",
                    "drift_hz",
                    "tol_bins",
                ]
            )
            for res in out:
                w.writerow(
                    [res.run, res.cn0, res.trials, f"{res.p_detect:.4f}", f"{res.p_wrong:.4f}",
                     f"{res.ref_freq_hz:.1f}", f"{res.drift_hz:.1f}", res.tol_bins]
                )  # fmt: skip
        print(f"wrote {a.output}")
    return 0


# --- cn0 ------------------------------------------------------------------------------------


def code_replica(spec, prn: int, fs: float) -> np.ndarray:
    """One code period of the spreading code sampled at ``fs`` (rectangular chips)."""
    from snappnt.signals import get_code

    n = int(round(spec.code_period_s * fs))
    if abs(n - spec.code_period_s * fs) > 1e-6:
        raise ValueError("fs times the code period must be a whole number of samples")
    code = get_code(spec, prn)
    idx = np.floor(np.arange(n) * spec.chip_rate_hz / fs).astype(np.int64) % code.size
    return code[idx].astype(np.float32)


def block_correlations(
    blocks: np.ndarray, fs: float, replica: np.ndarray, carrier_hz: float
) -> np.ndarray:
    """Circular correlation of each block (one code period long) with the replica, after the
    carrier is removed: array (blocks, lags), complex."""
    n = replica.size
    t = np.arange(n) / fs
    wipe = np.exp(-2j * np.pi * carrier_hz * t).astype(np.complex64)
    rep_f = np.conj(np.fft.fft(replica))
    out = np.empty(blocks.shape, dtype=np.complex64)
    for k, b in enumerate(blocks):
        # The carrier phase restarts in each block; only |y| and moments of |y| are used.
        out[k] = np.fft.ifft(np.fft.fft(b * wipe) * rep_f)
    return out


def prompt_values(
    blocks: np.ndarray, fs: float, spec, prn: int, carrier_hz: float, lags: np.ndarray
) -> np.ndarray:
    """Prompt correlation of each block with a replica delayed by ``lags`` samples (not
    rounded). The replica's chips are sampled at ``fs`` with the same fractional delay as the
    received code, so the prompt amplitude does not change as the code phase moves across the
    sample grid."""
    from snappnt.signals import get_code

    code = get_code(spec, prn).astype(np.float32)
    n = blocks.shape[1]
    t = np.arange(n)
    wipe = np.exp(-2j * np.pi * carrier_hz * t / fs).astype(np.complex64)
    out = np.empty(blocks.shape[0], dtype=np.complex64)
    for k, b in enumerate(blocks):
        idx = np.floor((t - lags[k]) * spec.chip_rate_hz / fs).astype(np.int64) % code.size
        out[k] = np.sum(b * wipe * code[idx])
    return out


def m2m4_snr(prompt: np.ndarray) -> float:
    """Signal-to-noise ratio of complex values y = A e^(j phi) + n with constant A and
    circular Gaussian noise, from the second and fourth moments (M2M4 estimator):
    S = sqrt(2 M2^2 - M4), N = M2 - S."""
    m2 = float(np.mean(np.abs(prompt) ** 2))
    m4 = float(np.mean(np.abs(prompt) ** 4))
    s = math.sqrt(max(2 * m2 * m2 - m4, 0.0))
    return s / (m2 - s)


def estimate_cn0(
    x: np.ndarray,
    fs: float,
    spec,
    prn: int,
    *,
    carrier_hz: float,
    n_blocks: int,
    span_hz: float = 100.0,
    step_hz: float = 10.0,
    remove_dc: str = "mean",
    _aligned: bool = False,
) -> dict[str, float]:
    """C/N0 in dB-Hz of a long recording, from blocks of one code period T.

    1. The carrier frequency is chosen on a grid of ``step_hz`` within ``carrier_hz`` +/-
       ``span_hz``, as the one that maximises the mean peak power over the blocks.
    2. The code phase (lag in samples) of each block is the peak of its correlation; a
       straight line is fitted to these lags against the block number, so that the drift of
       the code phase between the clocks of transmitter and receiver is followed without
       picking noise peaks. The prompt value of each block is the correlation with a replica
       delayed by the fitted, unrounded lag (``prompt_values``).
    3. The recording is cut again so that each block starts at a code epoch. Data symbols
       change sign only at code epochs, so a block then holds one symbol and the prompt
       value has a constant amplitude, as M2M4 assumes (up to the slow code drift).
    4. SNR from the prompt values by M2M4 (``m2m4_snr``); C/N0 = SNR / T.

    Correlation losses (code phase between samples, a data-symbol edge inside a block, band
    limiting) lower the estimate in the same way for recordings processed alike."""
    from scipy.ndimage import median_filter

    from snappnt.rx.acquisition import remove_dc_offset

    rep = code_replica(spec, prn, fs)
    n = rep.size
    nb = min(n_blocks, x.size // n)
    if nb < 2:
        raise ValueError(f"need at least two whole code periods, got {nb}")
    blocks = remove_dc_offset(x[: nb * n], remove_dc).reshape(nb, n)
    freqs = np.arange(carrier_hz - span_hz, carrier_hz + span_hz + step_hz / 2, step_hz)
    probe = blocks[: min(nb, 50)]
    score = [
        np.mean(np.max(np.abs(block_correlations(probe, fs, rep, f)) ** 2, axis=1)) for f in freqs
    ]
    f_best = float(freqs[int(np.argmax(score))])
    corr = block_correlations(blocks, fs, rep, f_best)
    lags = np.argmax(np.abs(corr), axis=1).astype(float)
    k = np.arange(nb, dtype=float)
    # Unwrap lags across the code period before fitting.
    lags = np.unwrap(lags * 2 * np.pi / n) * n / (2 * np.pi)
    # A block holding a data-symbol sign change has a weak, misplaced peak; a running median
    # over five blocks keeps such single outliers out of the fit.
    lags = median_filter(lags, 5, mode="nearest")
    slope, intercept = np.polyfit(k, lags, 1)
    fit = np.round(intercept + slope * k).astype(np.int64) % n
    if not _aligned and fit[0] != 0:
        return estimate_cn0(
            x[int(fit[0]) :], fs, spec, prn, carrier_hz=f_best, n_blocks=n_blocks,
            span_hz=step_hz, step_hz=step_hz, remove_dc=remove_dc, _aligned=True,
        )  # fmt: skip
    prompt = prompt_values(blocks, fs, spec, prn, f_best, intercept + slope * k)
    snr = m2m4_snr(prompt)
    if not snr > 0:
        raise ValueError("no signal power in the prompt values (code phase not found)")
    t_s = n / fs
    return {
        "cn0_dbhz": 10 * math.log10(snr / t_s),
        "carrier_hz": f_best,
        "code_drift_chips_per_s": slope * spec.chip_rate_hz / fs / t_s,
        "blocks": nb,
    }


def cmd_cn0(a: argparse.Namespace) -> int:
    import json

    from scipy.signal import resample_poly

    from snappnt.signals import load_signal

    spec = load_signal(a.signal)
    path = Path(a.recording)
    meta = json.loads(_meta_path(path).read_text())
    fs = float(meta["global"]["core:sample_rate"])
    # One code period more than asked for: aligning the blocks to a code epoch drops the
    # samples before the first epoch.
    n_in = int(math.ceil(spec.code_period_s * fs * (a.blocks + 1)))
    segs, fs_in = read_segments(path, n_in, a.segments)
    values = []
    for x in segs:
        fs = fs_in
        if a.resample_sps and a.resample_sps != fs:
            frac = Fraction(a.resample_sps / fs).limit_denominator(1000)
            x = resample_poly(x, frac.numerator, frac.denominator).astype(np.complex64)
            fs = fs * frac.numerator / frac.denominator
        try:
            r = estimate_cn0(
                x, fs, spec, a.prn, carrier_hz=a.carrier_hz, n_blocks=a.blocks,
                span_hz=a.span_hz, step_hz=a.step_hz, remove_dc=a.remove_dc,
            )  # fmt: skip
        except ValueError as e:
            print(f"{path.name}: segment skipped: {e}")
            continue
        values.append(r["cn0_dbhz"])
        print(
            f"{path.name}: {r['blocks']} blocks of {spec.code_period_s * 1e3:g} ms at "
            f"{fs / 1e6:g} MSa/s, carrier {r['carrier_hz']:.0f} Hz, code drift "
            f"{r['code_drift_chips_per_s']:+.3f} chip/s, C/N0 estimate {r['cn0_dbhz']:.2f} dB-Hz"
        )
    if not values:
        print(f"{path.name}: no segment gave an estimate", file=sys.stderr)
        return 1
    if len(values) > 1:
        v = np.array(values)
        sd = v.std(ddof=1)
        print(
            f"{path.name}: {v.size} segments, mean {v.mean():.2f} dB-Hz, standard deviation "
            f"{sd:.2f} dB, standard error of the mean {sd / np.sqrt(v.size):.2f} dB"
        )
    return 0


# --- plot -----------------------------------------------------------------------------------


def crossing_dbhz(cn0_dbhz: np.ndarray, pd: np.ndarray, level: float) -> float | None:
    """C/N0 where Pd first reaches ``level`` (linear interpolation between grid points);
    None if it never does."""
    idx = np.nonzero(pd >= level)[0]
    if idx.size == 0:
        return None
    i = int(idx[0])
    if i == 0:
        return float(cn0_dbhz[0])
    x0, x1, y0, y1 = cn0_dbhz[i - 1], cn0_dbhz[i], pd[i - 1], pd[i]
    return float(x0 + (level - y0) * (x1 - x0) / (y1 - y0))


def read_pd(path: str | Path, cn0_key: str) -> dict[str, np.ndarray]:
    """C/N0, p_detect and trials of the rows whose C/N0 is a number, sorted by C/N0."""
    with open(path, newline="") as fh:
        rows = [r for r in csv.DictReader(fh) if r[cn0_key].replace(".", "", 1).isdigit()]
    rows.sort(key=lambda r: float(r[cn0_key]))
    return {
        "cn0": np.array([float(r[cn0_key]) for r in rows]),
        "pd": np.array([float(r["p_detect"]) for r in rows]),
        "n": np.array([float(r["trials"]) for r in rows]),
    }


def cmd_plot(a: argparse.Namespace) -> int:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    surface, ink, ink_muted, grid = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
    sim_label = "Simulation, navic_s_esp32c3 (issue #2)"
    curves = [
        (read_pd(a.simulated, "cn0_dbhz"), sim_label, "#2a78d6", "o"),
        (read_pd(a.measured, "cn0_dbhz"), "Conducted test, DC removal mean", "#eb6834", "s"),
    ]
    if a.measured_dc_none:
        curves.append(
            (
                read_pd(a.measured_dc_none, "cn0_dbhz"),
                "Conducted test, no DC removal",
                "#52514e",
                "^",
            )
        )
    fig, ax = plt.subplots(figsize=(8, 5.2), dpi=120, facecolor=surface)
    ax.set_facecolor(surface)
    print("| Curve | 50 % point [dB-Hz] | 90 % point [dB-Hz] |")
    print("|---|---|---|")
    for c, label, colour, marker in curves:
        err = np.sqrt(c["pd"] * (1.0 - c["pd"]) / c["n"])  # binomial standard deviation
        ax.errorbar(
            c["cn0"], c["pd"], yerr=err, color=colour, marker=marker, markersize=5,
            markeredgecolor=surface, linewidth=2, elinewidth=1, capsize=0, label=label,
        )  # fmt: skip
        pts = [crossing_dbhz(c["cn0"], c["pd"], lv) for lv in (0.5, 0.9)]
        cells = [f"{p:.1f}" if p is not None else "not reached" for p in pts]
        print(f"| {label} | {cells[0]} | {cells[1]} |")
    for lv in (0.5, 0.9):
        ax.axhline(lv, color=ink_muted, linewidth=0.8, linestyle=(0, (4, 3)), zorder=0)
    ax.set_xlim(45.5, 60.5)
    ax.set_ylim(-0.02, 1.02)
    ax.set_xticks(range(46, 61, 1))
    ax.set_xlabel("C/N0 set in the scenario [dB-Hz]", color=ink)
    ax.set_ylabel("Detection probability", color=ink)
    ax.set_title(
        "NavIC S-band SPS, XIAO ESP32C3, 0.2 ms captures, pfa = 1e-3, 200 trials per point",
        color=ink, fontsize=10, loc="left",
    )  # fmt: skip
    ax.grid(True, color=grid, linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(ink_muted)
    ax.tick_params(colors=ink_muted)
    legend = ax.legend(loc="lower right", frameon=False, fontsize=9)
    for text in legend.get_texts():
        text.set_color(ink)
    fig.tight_layout()
    # Fixed metadata so that rerunning on the same CSV files gives the same file.
    fig.savefig(a.output, facecolor=surface, metadata={"Software": None})
    print(f"wrote {a.output}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("rise", help="in-band PSD rise, generator on against off")
    r.add_argument("off", help="directory of generator-off (or reference) captures")
    r.add_argument("on", help="directory of generator-on captures")
    r.add_argument("--gen-center-hz", type=float, default=GEN_CENTER_HZ)
    r.add_argument("--half-band-hz", type=float, default=GEN_HALF_BAND_HZ)
    r.add_argument("--exclude-hz", type=float, default=EXCLUDE_HZ)
    r.add_argument("--tuned-hz", type=float, default=2492e6, help="only for printing RF of lines")
    r.add_argument("--adc-min", type=float, default=ADC_MIN, help="lower converter limit")
    r.add_argument("--adc-max", type=float, default=ADC_MAX, help="upper converter limit")
    r.add_argument("--min-rise-db", type=float, default=10.0)
    r.set_defaults(func=cmd_rise)

    q = sub.add_parser("acquire", help="acquire every capture, one CSV row each")
    q.add_argument("dirs", nargs="+")
    q.add_argument("-o", "--output", required=True)
    q.add_argument("--signal", default="navic_s_sps")
    q.add_argument("--prn", type=int, default=10)
    q.add_argument("--center-hz", type=float, required=True)
    q.add_argument("--freq-span-hz", type=float, required=True)
    q.add_argument("--remove-dc", choices=("none", "mean", "linear"), required=True)
    q.add_argument("--pfa", type=float, default=1e-3)
    q.add_argument(
        "--freq-step-hz",
        type=float,
        default=None,
        help="frequency step of the search (default of acquire: 1/(2T))",
    )
    q.add_argument(
        "--refine",
        action="store_true",
        help="interpolate the peak in frequency and code phase (detection is unchanged)",
    )
    q.set_defaults(func=cmd_acquire)

    p = sub.add_parser("pd", help="detection probability per run from the acquisition CSV")
    p.add_argument("csv")
    p.add_argument(
        "--run",
        type=RunSpec.parse,
        action="append",
        required=True,
        help="name:cn0:pre_bracket:post_bracket (cn0 'noise' for a noise-only run)",
    )
    p.add_argument("-o", "--output")
    p.set_defaults(func=cmd_pd)

    c = sub.add_parser("cn0", help="C/N0 estimate of one long recording (M2M4 over code periods)")
    c.add_argument("recording", help="SigMF base path or .sigmf-meta")
    c.add_argument("--carrier-hz", type=float, required=True, help="carrier offset in baseband")
    c.add_argument("--signal", default="navic_s_sps")
    c.add_argument("--prn", type=int, default=10)
    c.add_argument("--blocks", type=int, default=1000, help="code periods from the start")
    c.add_argument(
        "--segments", type=int, default=1, help="segments spread over the recording, each estimated"
    )
    c.add_argument("--span-hz", type=float, default=100.0)
    c.add_argument("--step-hz", type=float, default=10.0)
    c.add_argument("--remove-dc", choices=("none", "mean", "linear"), default="mean")
    c.add_argument("--resample-sps", type=float, default=None, help="resample before correlating")
    c.set_defaults(func=cmd_cn0)

    g = sub.add_parser("plot", help="measured detection probability over the simulated curve")
    g.add_argument("measured", help="CSV written by the pd subcommand")
    g.add_argument("--simulated", required=True, help="CSV written by snappnt sweep")
    g.add_argument("--measured-dc-none", help="pd CSV of the same captures without DC removal")
    g.add_argument("-o", "--output", required=True)
    g.set_defaults(func=cmd_plot)

    a = ap.parse_args(argv)
    return a.func(a)


if __name__ == "__main__":
    raise SystemExit(main())
