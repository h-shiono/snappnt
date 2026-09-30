"""Generate complex-baseband snapshots with known truth.

Noise model: complex white Gaussian noise with unit variance per sample, so the noise
density is N0 = 1 / fs. A satellite with C/N0 (dB-Hz) then has amplitude
sqrt(10^(C/N0 / 10) / fs).

Receiver clock model: one crystal drives both the LO and the ADC. An error of ``ppm``
shifts the carrier by ``-ppm * carrier_hz`` and makes the true sample rate ``fs * (1 + ppm)``.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from snappnt.signals import get_code, load_signal
from snappnt.sim.impairments import quantize
from snappnt.sim.scenario import Scenario


def expected_frequency_offset_hz(scn: Scenario, doppler_hz: float, carrier_hz: float) -> float:
    """Carrier offset the acquisition should find, relative to ``baseband_offset_hz``."""
    return doppler_hz - scn.receiver.clock_offset_ppm * 1e-6 * carrier_hz


def generate(scn: Scenario) -> tuple[np.ndarray, dict[str, Any]]:
    """Return (samples as complex64, truth dict suitable for SigMF annotations)."""
    spec = load_signal(scn.signal)
    rx = scn.receiver
    rng = np.random.default_rng(scn.seed)

    n = rx.n_samples
    fs_nominal = rx.sample_rate_hz
    fs_true = fs_nominal * (1.0 + rx.clock_offset_ppm * 1e-6)
    t = np.arange(n) / fs_true

    x = (rng.standard_normal(n) + 1j * rng.standard_normal(n)) / np.sqrt(2.0)

    truth_sats = []
    for sat in scn.satellites:
        code = get_code(spec, sat.prn)
        amp = np.sqrt(10 ** (sat.cn0_dbhz / 10.0) / fs_nominal)

        # Code: chip rate scaled by the Doppler of the carrier (code Doppler).
        code_rate = spec.chip_rate_hz * (1.0 + sat.doppler_hz / spec.carrier_hz)
        chip_pos = sat.code_phase_chips + code_rate * t
        chips = code[np.floor(chip_pos).astype(np.int64) % spec.code_length].astype(np.float32)

        # Data: symbol edges fall on code-period edges; the first edge is at a random epoch.
        if spec.symbol_rate_hz:
            chips_per_symbol = round(spec.chip_rate_hz / spec.symbol_rate_hz)
            periods_per_symbol = chips_per_symbol // spec.code_length
            start = int(rng.integers(0, periods_per_symbol)) * spec.code_length
            sym_idx = np.floor((chip_pos + start) / chips_per_symbol).astype(np.int64)
            symbols = rng.choice(np.array([1.0, -1.0], dtype=np.float32), size=sym_idx[-1] + 1)
            chips = chips * symbols[sym_idx]

        f_hz = rx.baseband_offset_hz + expected_frequency_offset_hz(
            scn, sat.doppler_hz, spec.carrier_hz
        )
        phase = 2 * np.pi * (f_hz * t + 0.5 * sat.doppler_rate_hzps * t**2) + sat.carrier_phase_rad
        x += amp * chips * np.exp(1j * phase)

        truth_sats.append(
            {
                "prn": sat.prn,
                "cn0_dbhz": sat.cn0_dbhz,
                "doppler_hz": sat.doppler_hz,
                "doppler_rate_hzps": sat.doppler_rate_hzps,
                "code_phase_chips": sat.code_phase_chips % spec.code_length,
                "expected_freq_offset_hz": f_hz - rx.baseband_offset_hz,
            }
        )

    if rx.quantization_bits is not None:
        x = quantize(x, rx.quantization_bits, rx.agc_backoff_db)

    truth = {
        "scenario": scn.name,
        "signal": spec.name,
        "sample_rate_hz": fs_nominal,
        "n_samples": n,
        "baseband_offset_hz": rx.baseband_offset_hz,
        "clock_offset_ppm": rx.clock_offset_ppm,
        "quantization_bits": rx.quantization_bits,
        "seed": scn.seed,
        "satellites": truth_sats,
    }
    return x.astype(np.complex64), truth
