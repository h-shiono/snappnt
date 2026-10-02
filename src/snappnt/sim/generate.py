"""Generate complex-baseband snapshots with known truth.

Noise model: complex white Gaussian noise with unit variance per sample, so the noise
density is N0 = 1 / fs. A satellite with C/N0 (dB-Hz) then has amplitude
sqrt(10^(C/N0 / 10) / fs).

Receiver clock model: one crystal drives both the LO and the ADC. An error of ``ppm``
shifts the carrier by ``-ppm * carrier_hz`` and makes the true sample rate ``fs * (1 + ppm)``.

With a frequency plan (external mixer) the carrier offset at baseband is
``doppler_sign * doppler_hz - clock_offset_ppm * tuned_hz - doppler_sign * lo_offset_ppm * lo_hz``
(ppm as 1e-6): the receiver crystal error acts on the tuned frequency, the external LO error
moves the IF in the opposite direction of the LO shift for a low-side LO and in the same
direction for a high-side LO. The carrier Doppler rate is mirrored like the Doppler
(``doppler_sign * doppler_rate_hzps``). Code Doppler keeps the RF sign; the mixer
does not change the code rate, and the chip rate is held constant over a snapshot.

Optional band limiting and decimation: when the receiver sets ``generate_rate_hz``, signal and
noise are created at that rate (noise density still 1 / generate rate), low-pass filtered to
``analog_bandwidth_hz`` and reduced to ``sample_rate_hz``. Method ``none`` keeps every n-th
sample, so noise from the whole analog bandwidth folds into the output band; method ``ideal``
low-pass filters to the output band first. Without these keys the samples are created
directly at ``sample_rate_hz``.

Optional receiver impairments (order in ``sim/impairments.py``): fixed spurs, tones at a
baseband offset from the tuned frequency whose power is given relative to the total noise
power per sample (amplitude ``10^(power_db / 20)``), added at the generation rate before the
analog low-pass; and a DC offset per component as a fraction of ADC full scale, added in the
quantiser. Spur phases come from a separate random generator derived from the scenario seed, so
the draws of the main generator (noise, data symbols) do not change when spurs are set.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from snappnt.frontend.freqplan import FrequencyPlan
from snappnt.signals import get_code, load_signal
from snappnt.sim.impairments import (
    add_spurs,
    decimate_without_filter,
    lowpass,
    quantize,
    quantize_with_offset,
)
from snappnt.sim.scenario import Scenario


def expected_frequency_offset_hz(
    scn: Scenario,
    doppler_hz: float,
    carrier_hz: float,
    plan: FrequencyPlan | None = None,
) -> float:
    """Carrier offset the acquisition should find, relative to ``baseband_offset_hz``.

    ``plan`` defaults to the scenario's own frequency plan.
    """
    plan = scn.frequency_plan if plan is None else plan
    rx = scn.receiver
    if plan is None:
        return doppler_hz - rx.clock_offset_ppm * 1e-6 * carrier_hz
    sign = plan.doppler_sign
    lo_shift_hz = rx.lo_offset_ppm * 1e-6 * (plan.lo_hz or 0.0)
    return sign * doppler_hz - rx.clock_offset_ppm * 1e-6 * plan.tuned_hz - sign * lo_shift_hz


def generate(scn: Scenario) -> tuple[np.ndarray, dict[str, Any]]:
    """Return (samples as complex64, truth dict suitable for SigMF annotations)."""
    spec = load_signal(scn.signal)
    rx = scn.receiver
    rng = np.random.default_rng(scn.seed)

    n = rx.n_samples
    fs_nominal = rx.sample_rate_hz
    # Rate at which signal and noise are created: the output rate unless a higher one is set.
    if rx.generate_rate_hz is None:
        fs_gen, n_gen = fs_nominal, n
    else:
        fs_gen, n_gen = rx.generate_rate_hz, n * rx.decimation_factor
    fs_true = fs_gen * (1.0 + rx.clock_offset_ppm * 1e-6)
    t = np.arange(n_gen) / fs_true

    x = (rng.standard_normal(n_gen) + 1j * rng.standard_normal(n_gen)) / np.sqrt(2.0)

    rate_sign = 1 if scn.frequency_plan is None else scn.frequency_plan.doppler_sign
    truth_sats = []
    for sat in scn.satellites:
        code = get_code(spec, sat.prn)
        amp = np.sqrt(10 ** (sat.cn0_dbhz / 10.0) / fs_gen)

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
        rate_hzps = rate_sign * sat.doppler_rate_hzps
        phase = 2 * np.pi * (f_hz * t + 0.5 * rate_hzps * t**2) + sat.carrier_phase_rad
        x += amp * chips * np.exp(1j * phase)

        truth_sats.append(
            {
                "prn": sat.prn,
                "cn0_dbhz": sat.cn0_dbhz,
                "doppler_hz": sat.doppler_hz,
                "doppler_rate_hzps": sat.doppler_rate_hzps,
                "expected_doppler_rate_hzps": rate_sign * sat.doppler_rate_hzps,
                "code_phase_chips": sat.code_phase_chips % spec.code_length,
                "expected_freq_offset_hz": f_hz - rx.baseband_offset_hz,
            }
        )

    if rx.spurs:
        x = add_spurs(x, fs_gen, rx.spurs, np.random.default_rng([scn.seed, 1]))

    if rx.generate_rate_hz is not None:
        if rx.analog_bandwidth_hz is not None:
            x = lowpass(x, fs_gen, rx.analog_bandwidth_hz)
        if rx.decimation_method == "ideal":
            x = lowpass(x, fs_gen, fs_nominal)
        x = decimate_without_filter(x, rx.decimation_factor)

    has_dc = rx.dc_offset_i is not None and rx.dc_offset_q is not None
    if rx.quantization_bits is not None:
        if has_dc:
            x = quantize_with_offset(
                x, rx.quantization_bits, rx.agc_backoff_db, (rx.dc_offset_i, rx.dc_offset_q)
            )
        else:
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
        **(
            {
                "frequency_plan": {
                    "rf_hz": scn.frequency_plan.rf_hz,
                    "lo_hz": scn.frequency_plan.lo_hz,
                    "lo_side": scn.frequency_plan.lo_side,
                    "tuned_hz": scn.frequency_plan.tuned_hz,
                    "if_hz": scn.frequency_plan.if_hz,
                },
                "lo_offset_ppm": rx.lo_offset_ppm,
            }
            if scn.frequency_plan is not None
            else {}
        ),
        **(
            {
                "generate_rate_hz": rx.generate_rate_hz,
                "decimation_factor": rx.decimation_factor,
                "decimation_method": rx.decimation_method,
                "analog_bandwidth_hz": rx.analog_bandwidth_hz,
            }
            if rx.generate_rate_hz is not None
            else {}
        ),
        **({"dc_offset_fullscale": {"i": rx.dc_offset_i, "q": rx.dc_offset_q}} if has_dc else {}),
        **({"spurs": [{"offset_hz": f, "power_db": p} for f, p in rx.spurs]} if rx.spurs else {}),
        "satellites": truth_sats,
    }
    return x.astype(np.complex64), truth
