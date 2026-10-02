"""Statistics and figure for ESP-SDR captures made without an RF source.

Reads SigMF recordings written by ``snappnt capture``, groups them by tuned frequency, gain
setting and analog bandwidth (from the metadata), and prints for each group:

- per-component mean, standard deviation and extremes on the 10-bit scale (-512..511),
- power after removing the capture mean, in dB on the same scale,
- narrow lines in the median power spectral density (PSD) over captures, as baseband offset
  and as radio frequency (tuned frequency + offset).

When two groups from the same directory differ only in tuned frequency, it also checks the
sign of frequency: if the spectrum is not mirrored, signals at fixed radio frequencies move by
minus the change of the tuned frequency in baseband. With ``--acquire-prn`` it runs acquisition
on the first ``--acquire-max`` captures of each group, as recorded and with the capture mean
subtracted.

    uv run --extra plot python tools/plot_esp32_bench.py out/noise out/sign \\
        -o docs/results/esp32c3-bench-no-rf.png
    uv run --extra plot python tools/plot_esp32_bench.py out/noise \\
        --acquire-prn 10 --acquire-center-hz 28000

Used for docs/results/esp32c3-bench-no-rf.md. The recordings themselves are not committed.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from snappnt.io import read_sigmf

FFT_SIZE = 1024
LINE_MIN_DB = 8.0  # a local maximum this far above the local floor is a line
FLOOR_BINS = 31  # running-median length for the local floor (about 2.4 MHz at 80 MSa/s)
FULL_SCALE = 511

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_MUTED = "#52514e"
GRID = "#e4e3df"
COLOURS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#8a5cd1", "#d1477a", "#52514e"]


@dataclass(eq=False)
class Group:
    source: str
    frequency_hz: float
    gain: str
    bandwidth: str
    sample_rate_hz: float = 0.0
    paths: list[Path] = field(default_factory=list)
    stats: list[dict[str, float]] = field(default_factory=list)
    psds: list[np.ndarray] = field(default_factory=list)

    @property
    def label(self) -> str:
        freq_mhz = self.frequency_hz / 1e6
        return f"{self.source}: {freq_mhz:g} MHz, {self.gain}, bandwidth {self.bandwidth}"


def group_key(source: str, meta: dict) -> tuple[str, float, str, str]:
    g = meta["global"]
    freq = float(meta["captures"][0]["core:frequency"])
    if g.get("snappnt:gain_mode") == "manual":
        gain = f"gain {g['snappnt:gain_index']}"
    else:
        gain = "hardware AGC"
    bw = g.get("snappnt:analog_bandwidth_mhz")
    bandwidth = f"{bw:g} MHz" if bw is not None else "not recorded"
    return source, freq, gain, bandwidth


def capture_stats(x: np.ndarray) -> dict[str, float]:
    i, q = x.real, x.imag
    y = x - x.mean()
    return {
        "i_mean": float(i.mean()),
        "q_mean": float(q.mean()),
        "i_std": float(i.std()),
        "q_std": float(q.std()),
        "i_min": float(i.min()),
        "i_max": float(i.max()),
        "q_min": float(q.min()),
        "q_max": float(q.max()),
        "at_limit_pct": float(np.mean((np.abs(i) >= FULL_SCALE) | (np.abs(q) >= FULL_SCALE)) * 100),
        "power_db": float(10 * np.log10(np.mean(np.abs(y) ** 2))),
    }


def capture_psd(x: np.ndarray) -> np.ndarray:
    """Mean of Hann-windowed periodograms of the mean-removed capture, centred on 0 Hz."""
    y = x - x.mean()
    n_seg = y.size // FFT_SIZE
    seg = y[: n_seg * FFT_SIZE].reshape(n_seg, FFT_SIZE) * np.hanning(FFT_SIZE)
    return np.mean(np.abs(np.fft.fftshift(np.fft.fft(seg, axis=1), axes=1)) ** 2, axis=0)


def offsets_hz(sample_rate_hz: float) -> np.ndarray:
    return np.fft.fftshift(np.fft.fftfreq(FFT_SIZE, 1 / sample_rate_hz))


def median_psd_db(g: Group) -> np.ndarray:
    return 10 * np.log10(np.median(g.psds, axis=0))


def find_lines(psd_db: np.ndarray) -> list[tuple[int, float]]:
    """Indices and heights above the local floor of narrow local maxima. The local floor is a
    running median over ``FLOOR_BINS`` bins, so that the edges of the analog filter's pass
    band are not taken for lines."""
    from scipy.ndimage import median_filter

    floor = median_filter(psd_db, FLOOR_BINS, mode="nearest")
    out = []
    for k in range(2, psd_db.size - 2):
        height = float(psd_db[k] - floor[k])
        if psd_db[k] == psd_db[k - 2 : k + 3].max() and height > LINE_MIN_DB:
            out.append((k, height))
    return out


def load_groups(dirs: list[Path]) -> list[Group]:
    """Group the captures of each directory. A directory is named by its last component only,
    so that no machine-specific path reaches the printed tables or the figure; two different
    directories with the same name are therefore refused rather than merged."""
    seen: dict[str, Path] = {}
    for d in dirs:
        if seen.setdefault(d.name, d.resolve()) != d.resolve():
            raise SystemExit(f"two different directories are both named {d.name!r}; rename one")
    groups: dict[tuple[str, float, str, str], Group] = {}
    for d in dict.fromkeys(dirs):
        for meta_path in sorted(d.glob("*.sigmf-meta")):
            x, meta = read_sigmf(meta_path)
            if x.size < FFT_SIZE:
                raise SystemExit(
                    f"{meta_path.name}: {x.size} samples, fewer than the {FFT_SIZE} needed for one "
                    "PSD segment; leave such captures out"
                )
            key = group_key(d.name, meta)
            g = groups.setdefault(key, Group(*key))
            g.sample_rate_hz = float(meta["global"]["core:sample_rate"])
            g.paths.append(meta_path)
            g.stats.append(capture_stats(x.astype(np.complex128)))
            g.psds.append(capture_psd(x.astype(np.complex128)))
    return sorted(groups.values(), key=lambda g: (g.source, g.frequency_hz, g.gain, g.bandwidth))


def rng(values: list[float], fmt: str = "{:.1f}") -> str:
    lo, hi = min(values), max(values)
    return fmt.format(lo) if np.isclose(lo, hi) else f"{fmt.format(lo)} to {fmt.format(hi)}"


def print_summary(groups: list[Group]) -> None:
    print("| Setting | Captures | I mean | Q mean | I std | Q std | I min..max | Q min..max "
          "| At ±511 (%) | Power (dB) |")  # fmt: skip
    print("|---|---|---|---|---|---|---|---|---|---|")
    for g in groups:
        s = {k: [c[k] for c in g.stats] for k in g.stats[0]}
        print(
            f"| {g.label} | {len(g.stats)} | {rng(s['i_mean'], '{:.0f}')} "
            f"| {rng(s['q_mean'], '{:.0f}')} | {rng(s['i_std'])} | {rng(s['q_std'])} "
            f"| {min(s['i_min']):.0f}..{max(s['i_max']):.0f} "
            f"| {min(s['q_min']):.0f}..{max(s['q_max']):.0f} "
            f"| {max(s['at_limit_pct']):.3f} | {rng(s['power_db'])} |"
        )
    print()
    for g in groups:
        f_hz = offsets_hz(g.sample_rate_hz)
        lines = find_lines(median_psd_db(g))
        text = ", ".join(
            f"{f_hz[k] / 1e6:+.1f} MHz ({(g.frequency_hz + f_hz[k]) / 1e6:.1f} MHz, {h:.0f} dB)"
            for k, h in lines
        )
        print(f"lines, {g.label}: {text or 'none'}")


def sign_pairs(groups: list[Group]) -> list[tuple[Group, Group]]:
    pairs = []
    for a in groups:
        for b in groups:
            same = (a.source, a.gain, a.bandwidth, a.sample_rate_hz) == (
                b.source,
                b.gain,
                b.bandwidth,
                b.sample_rate_hz,
            )
            if same and b.frequency_hz > a.frequency_hz:
                pairs.append((a, b))
    return pairs


def shift_correlation(a: Group, b: Group, max_shift_hz: float) -> list[tuple[float, float]]:
    """Correlation of PSD_a(f) with PSD_b(f + s) for shifts s, on median-filtered mean PSDs
    (the filter suppresses narrow lines so that broad signals decide)."""
    from scipy.ndimage import median_filter

    f_hz = offsets_hz(a.sample_rate_hz)
    df = f_hz[1] - f_hz[0]
    edge = 0.95 * f_hz.max()
    pa = median_filter(10 * np.log10(np.mean(a.psds, axis=0)), 9)
    pb = median_filter(10 * np.log10(np.mean(b.psds, axis=0)), 9)
    out = []
    for k in range(-int(max_shift_hz / df), int(max_shift_hz / df) + 1):
        idx = np.where((np.abs(f_hz) < edge) & (np.abs(f_hz + k * df) < edge))[0]
        out.append((k * df, float(np.corrcoef(pa[idx], pb[idx + k])[0, 1])))
    return out


def print_sign_check(a: Group, b: Group) -> None:
    step_hz = b.frequency_hz - a.frequency_hz
    corr = shift_correlation(a, b, 1.5 * step_hz)
    best_s, best_c = max(corr, key=lambda t: t[1])

    def at(s: float) -> float:
        return min(corr, key=lambda t: abs(t[0] - s))[1]

    print(f"\nsign check, {a.label} -> {b.label}:")
    print(f"  best shift {best_s / 1e6:+.1f} MHz (correlation {best_c:.2f}); "
          f"{-step_hz / 1e6:+.0f} MHz (not mirrored): {at(-step_hz):.2f}; "
          f"{step_hz / 1e6:+.0f} MHz (mirrored): {at(step_hz):.2f}")  # fmt: skip
    f_hz = offsets_hz(a.sample_rate_hz)
    for name, sign in (("not mirrored", 1), ("mirrored", -1)):
        rf_a = {
            round((a.frequency_hz + sign * f_hz[k]) / 1e6, 1): h
            for k, h in find_lines(median_psd_db(a))
        }
        rf_b = {
            round((b.frequency_hz + sign * f_hz[k]) / 1e6, 1): h
            for k, h in find_lines(median_psd_db(b))
        }
        common = sorted(set(rf_a) & set(rf_b))
        text = ", ".join(f"{f:.1f} MHz ({rf_a[f]:.0f} / {rf_b[f]:.0f} dB)" for f in common)
        print(f"  lines on the same radio frequency if {name}: {text or 'none'}")


def print_acquisition(
    groups: list[Group], prn: int, center_hz: float, span_hz: float, n_max: int, white_trials: int
) -> None:
    from snappnt.rx import acquire
    from snappnt.signals import load_signal

    spec = load_signal("navic_s_sps")
    print(f"\nacquisition, {spec.name} PRN {prn}, centre {center_hz:g} Hz, search ±{span_hz:g} Hz")
    print(
        "| Setting | Capture | As recorded: code (chips), freq (Hz), metric "
        "| Mean removed: same | Threshold |"
    )
    print("|---|---|---|---|---|")
    for g in groups:
        for path in g.paths[:n_max]:
            x, _ = read_sigmf(path)
            res = [
                acquire(y, g.sample_rate_hz, spec, prn, center_offset_hz=center_hz,
                        freq_range_hz=(-span_hz, span_hz))
                for y in (x, x - x.mean())
            ]  # fmt: skip
            cells = [
                f"{r.code_phase_chips:.1f}, {r.freq_offset_hz:.0f}, {r.metric:.1f}" for r in res
            ]
            print(f"| {g.label} | {path.stem} | {cells[0]} | {cells[1]} | {res[0].threshold:.1f} |")
    if white_trials and groups:
        # Reference: complex white Gaussian noise of the same length, seeds 0, 1, 2, ...
        n, fs = len(read_sigmf(groups[0].paths[0])[0]), groups[0].sample_rate_hz
        metrics = []
        for seed in range(white_trials):
            r = np.random.default_rng(seed)
            w = ((r.normal(size=n) + 1j * r.normal(size=n)) / np.sqrt(2)).astype(np.complex64)
            res = acquire(
                w, fs, spec, prn, center_offset_hz=center_hz, freq_range_hz=(-span_hz, span_hz)
            )
            metrics.append(res.metric)
        m = np.array(metrics)
        print(
            f"\nwhite Gaussian noise, {n} samples, {white_trials} trials (seeds 0 to "
            f"{white_trials - 1}): metric {m.min():.1f} to {m.max():.1f}, median {np.median(m):.1f}"
        )


def style(ax) -> None:
    ax.set_facecolor(SURFACE)
    ax.grid(color=GRID, linewidth=0.6)
    ax.tick_params(colors=INK_MUTED, labelsize=8)
    for spine in ax.spines.values():
        spine.set_color(GRID)


def plot(groups: list[Group], pairs: list[tuple[Group, Group]], out: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    # Groups that belong to a frequency pair are drawn in that pair's panel; the others share
    # the first panel. Every group therefore appears exactly once or in each of its pairs.
    single = [g for g in groups if not any(g in p for p in pairs)]
    n_panels = (1 if single else 0) + len(pairs)
    fig, axes = plt.subplots(n_panels, 1, figsize=(9, 4.4 * n_panels), facecolor=SURFACE)
    axes = list(np.atleast_1d(axes))
    if single:
        ax = axes.pop(0)
        sources = {g.source for g in single}
        for c, g in zip(COLOURS * (len(single) // len(COLOURS) + 1), single, strict=False):
            name = f"{g.source}: " if len(sources) > 1 else ""
            label = f"{name}{g.gain}, bandwidth {g.bandwidth} ({len(g.psds)} captures)"
            ax.plot(offsets_hz(g.sample_rate_hz) / 1e6, median_psd_db(g), color=c, lw=0.9,
                    label=label)  # fmt: skip
        freqs = sorted({g.frequency_hz for g in single})
        tuned = ", ".join(f"{f / 1e6:g}" for f in freqs)
        ax.set_title(f"Median PSD, tuned to {tuned} MHz, no RF source", color=INK, fontsize=10)
        ax.set_xlabel("Offset from tuned frequency (MHz)", color=INK_MUTED, fontsize=9)
        ax.set_ylabel("PSD (dB, 10-bit scale, arbitrary)", color=INK_MUTED, fontsize=9)
        ax.legend(fontsize=7, frameon=False, ncol=2, loc="upper center", bbox_to_anchor=(0.5, -0.2))
        style(ax)
    for (a, b), ax in zip(pairs, axes, strict=True):
        for c, g in zip(COLOURS, (a, b), strict=False):
            rf_mhz = (g.frequency_hz + offsets_hz(g.sample_rate_hz)) / 1e6
            label = f"tuned to {g.frequency_hz / 1e6:g} MHz ({len(g.psds)} captures)"
            ax.plot(rf_mhz, 10 * np.log10(np.mean(g.psds, axis=0)), color=c, lw=0.8, label=label)
        ax.set_title(f"Mean PSD drawn as not mirrored (radio frequency = tuned + offset), "
                     f"{a.gain}, bandwidth {a.bandwidth}", color=INK, fontsize=10)  # fmt: skip
        ax.set_xlabel("Radio frequency (MHz)", color=INK_MUTED, fontsize=9)
        ax.set_ylabel("PSD (dB, arbitrary)", color=INK_MUTED, fontsize=9)
        ax.legend(fontsize=7, frameon=False)
        style(ax)
    fig.tight_layout()
    fig.savefig(out, dpi=110, facecolor=SURFACE, metadata={"Software": None})
    print(f"\nwrote {out.name}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("dirs", nargs="+", type=Path, help="directories with .sigmf-meta files")
    p.add_argument("-o", "--output", type=Path, help="write the figure here")
    p.add_argument("--acquire-prn", type=int, help="run NavIC S-band acquisition for this PRN")
    p.add_argument("--acquire-center-hz", type=float, default=28000.0)
    p.add_argument("--acquire-span-hz", type=float, default=40000.0)
    p.add_argument("--acquire-max", type=int, default=5, help="captures per group")
    p.add_argument("--white-trials", type=int, default=30, help="white-noise reference trials")
    a = p.parse_args()
    groups = load_groups(a.dirs)
    if not groups:
        raise SystemExit("no .sigmf-meta files found")
    print_summary(groups)
    pairs = sign_pairs(groups)
    for pa, pb in pairs:
        print_sign_check(pa, pb)
    if a.acquire_prn is not None:
        print_acquisition(
            groups,
            a.acquire_prn,
            a.acquire_center_hz,
            a.acquire_span_hz,
            a.acquire_max,
            a.white_trials,
        )
    if a.output:
        plot(groups, pairs, a.output)


if __name__ == "__main__":
    main()
