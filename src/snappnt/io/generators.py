"""Build (never run) playback commands for signal generators.

The commands are returned as lists for a person to review and run by hand, with the RF
path closed by cables and attenuators. See docs/conducted-test.md.
"""

from __future__ import annotations

from pathlib import Path


def hackrf_transfer_cmd(
    path: str | Path,
    center_frequency_hz: float,
    sample_rate_hz: float,
    tx_vga_db: int = 0,
    repeat: bool = True,
) -> list[str]:
    """``-a 0`` keeps the RF amplifier off and ``-p 0`` keeps antenna-port power off."""
    if not 0 <= tx_vga_db <= 47:
        raise ValueError("tx_vga_db must be 0..47")
    cmd = [
        "hackrf_transfer",
        "-t", str(path),
        "-f", str(int(round(center_frequency_hz))),
        "-s", str(int(round(sample_rate_hz))),
        "-x", str(int(tx_vga_db)),
        "-a", "0",
        "-p", "0",
    ]  # fmt: skip
    if repeat:
        cmd.append("-R")
    return cmd


def uhd_tx_cmd(
    path: str | Path,
    center_frequency_hz: float,
    sample_rate_hz: float,
    gain_db: float = 0.0,
    args: str = "",
    repeat: bool = True,
) -> list[str]:
    """UHD example ``tx_samples_from_file`` with sc16 input (see sim.export.write_uhd_sc16)."""
    cmd = [
        "tx_samples_from_file",
        "--file", str(path),
        "--type", "short",
        "--freq", str(center_frequency_hz),
        "--rate", str(sample_rate_hz),
        "--gain", str(gain_db),
    ]  # fmt: skip
    if args:
        cmd += ["--args", args]
    if repeat:
        cmd.append("--repeat")
    return cmd
