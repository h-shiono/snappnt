"""Plot detection probability versus C/N0 from the CSV files written by ``snappnt sweep``.

Writes docs/results/pd-curves.png and prints the 50 % and 90 % points of each curve
(linear interpolation between the two C/N0 grid points where Pd first reaches the level).

    uv run --extra plot python tools/plot_pd_curves.py
"""

from __future__ import annotations

import csv
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

RESULTS = Path(__file__).resolve().parents[1] / "docs" / "results"

# (CSV file, label, colour, marker). Colours: fixed categorical order, checked for
# colour-vision deficiency on a light surface; markers give a second encoding.
CURVES = [
    ("pd_navic_s_esp32c3.csv", "ESP32-C3, 80 MSa/s, 0.2 ms, 1 block", "#2a78d6", "o"),
    ("pd_navic_s_ideal.csv", "Ideal, 8.184 MSa/s, 4 ms, 1 block", "#eb6834", "s"),
    ("pd_navic_s_esp32c61_4msps_b1.csv", "ESP32-C61, 4 MSa/s, 4 ms, 1 block", "#1baf7a", "^"),
    ("pd_navic_s_esp32c61_4msps_b4.csv", "ESP32-C61, 4 MSa/s, 4 ms, 4 blocks", "#eda100", "D"),
]
LEVELS = (0.5, 0.9)
SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_MUTED = "#52514e"
GRID = "#e4e3df"


def read_curve(path: Path) -> dict[str, np.ndarray]:
    with path.open(newline="") as f:
        rows = list(csv.DictReader(f))
    return {k: np.array([float(r[k]) for r in rows]) for k in rows[0]}


def crossing_dbhz(cn0_dbhz: np.ndarray, pd: np.ndarray, level: float) -> float | None:
    """C/N0 where Pd first reaches ``level``; None if it never does in the grid."""
    idx = np.nonzero(pd >= level)[0]
    if idx.size == 0:
        return None
    i = int(idx[0])
    if i == 0:
        return float(cn0_dbhz[0])
    x0, x1, y0, y1 = cn0_dbhz[i - 1], cn0_dbhz[i], pd[i - 1], pd[i]
    return float(x0 + (level - y0) * (x1 - x0) / (y1 - y0))


def main() -> None:
    fig, ax = plt.subplots(figsize=(8, 5.6), dpi=120, facecolor=SURFACE)
    ax.set_facecolor(SURFACE)

    print("| Curve | 50 % point [dB-Hz] | 90 % point [dB-Hz] |")
    print("|---|---|---|")
    for name, label, colour, marker in CURVES:
        c = read_curve(RESULTS / name)
        cn0, pd, n = c["cn0_dbhz"], c["p_detect"], c["trials"]
        err = np.sqrt(pd * (1.0 - pd) / n)  # binomial standard deviation
        ax.errorbar(
            cn0,
            pd,
            yerr=err,
            color=colour,
            marker=marker,
            markersize=5,
            markeredgecolor=SURFACE,
            linewidth=2,
            elinewidth=1,
            capsize=0,
            label=label,
        )
        pts = [crossing_dbhz(cn0, pd, lv) for lv in LEVELS]
        cells = [f"{p:.1f}" if p is not None else "not reached" for p in pts]
        print(f"| {label} | {cells[0]} | {cells[1]} |")

    for lv in LEVELS:
        ax.axhline(lv, color=INK_MUTED, linewidth=0.8, linestyle=(0, (4, 3)), zorder=0)
        ax.text(29.2, lv + 0.015, f"{lv:.0%}", color=INK_MUTED, fontsize=9)

    ax.set_xlim(29, 61)
    ax.set_ylim(-0.02, 1.02)
    ax.set_xticks(range(30, 61, 2))
    ax.set_xlabel("C/N0 [dB-Hz]", color=INK)
    ax.set_ylabel("Detection probability", color=INK)
    ax.set_title(
        "NavIC S-band SPS acquisition, pfa = 1e-3, 200 trials per point",
        color=INK,
        fontsize=11,
        loc="left",
    )
    ax.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(INK_MUTED)
    ax.tick_params(colors=INK_MUTED)
    legend = ax.legend(
        loc="upper center", bbox_to_anchor=(0.5, -0.13), ncol=2, frameon=False, fontsize=9
    )
    for text in legend.get_texts():
        text.set_color(INK)

    fig.tight_layout()
    out = RESULTS / "pd-curves.png"
    # Fixed metadata so that rerunning on the same CSV files gives the same file.
    fig.savefig(out, facecolor=SURFACE, metadata={"Software": None})
    print(f"wrote {out.relative_to(RESULTS.parents[1])}")


if __name__ == "__main__":
    main()
