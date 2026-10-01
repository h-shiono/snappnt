"""Simulation scenarios: what is transmitted, how it is received, and the truth to compare against.

Scenarios are YAML files (see ``scenarios/``). Example::

    name: navic_s_esp32c3
    signal: navic_s_sps
    seed: 1
    receiver:
      device: esp32c3          # optional; fills sample rate / bits / capture length
      sample_rate_hz: 80000000
      n_samples: 16384
      baseband_offset_hz: 0    # carrier position in baseband from the frequency plan
      clock_offset_ppm: 12.0   # receiver crystal error (shifts carrier and sample clock)
      quantization_bits: 10    # null = keep floating point
      agc_backoff_db: 12       # RMS level below ADC full scale
      # Optional: generate at a higher rate, band-limit, then reduce to sample_rate_hz
      generate_rate_hz: 80000000
      analog_bandwidth_hz: 13000000   # default: first (lower) value of the device YAML
      decimation: {factor: 20, method: none}   # none = keep every n-th sample, ideal = filter first
    satellites:
      - {prn: 1, cn0_dbhz: 55, doppler_hz: 0, code_phase_chips: 123.4}
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from snappnt.frontend.device import load_device


@dataclass(frozen=True)
class SatelliteTruth:
    prn: int
    cn0_dbhz: float
    doppler_hz: float = 0.0
    doppler_rate_hzps: float = 0.0
    code_phase_chips: float = 0.0  # code phase at the first sample
    carrier_phase_rad: float = 0.0


@dataclass(frozen=True)
class ReceiverConfig:
    sample_rate_hz: float
    n_samples: int
    baseband_offset_hz: float = 0.0
    clock_offset_ppm: float = 0.0
    quantization_bits: int | None = None
    agc_backoff_db: float = 12.0
    device: str | None = None
    # generate_rate_hz, decimation_factor and decimation_method are set together: samples are
    # generated at generate_rate_hz, band-limited to analog_bandwidth_hz (if set), then reduced
    # by decimation_factor. analog_bandwidth_hz has no effect without them.
    generate_rate_hz: float | None = None
    decimation_factor: int | None = None
    decimation_method: str | None = None
    analog_bandwidth_hz: float | None = None


@dataclass(frozen=True)
class Scenario:
    name: str
    signal: str
    receiver: ReceiverConfig
    satellites: tuple[SatelliteTruth, ...]
    seed: int = 0
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def duration_s(self) -> float:
        return self.receiver.n_samples / self.receiver.sample_rate_hz


def _decimation_from_dict(
    d: dict[str, Any], sample_rate_hz: float
) -> tuple[float | None, int | None, str | None]:
    generate_rate = d.get("generate_rate_hz")
    dec = d.get("decimation")
    if generate_rate is None and dec is None:
        return None, None, None
    if dec is None:
        raise ValueError("receiver.generate_rate_hz needs receiver.decimation")
    factor = int(dec["factor"])
    method = str(dec.get("method", "none"))
    if factor < 1:
        raise ValueError("decimation.factor must be at least 1")
    if method not in ("none", "ideal"):
        raise ValueError(f"decimation.method must be 'none' or 'ideal', not '{method}'")
    expected = sample_rate_hz * factor
    if generate_rate is None:
        generate_rate = expected
    elif not np.isclose(float(generate_rate), expected, rtol=1e-9):
        raise ValueError(
            f"generate_rate_hz ({generate_rate}) must equal sample_rate_hz * factor ({expected})"
        )
    return float(generate_rate), factor, method


def _receiver_from_dict(d: dict[str, Any]) -> ReceiverConfig:
    d = dict(d)
    device = d.get("device")
    if device is not None:
        dev = load_device(device)
        rates = dev.sample_rates_sps
        d.setdefault("sample_rate_hz", rates[0] if rates else None)
        d.setdefault("quantization_bits", dev.adc_bits)
        if dev.max_capture_samples is not None:
            d.setdefault("n_samples", dev.max_capture_samples)
        if dev.analog_bandwidth_hz is not None:
            d.setdefault("analog_bandwidth_hz", dev.analog_bandwidth_hz)
    if d.get("sample_rate_hz") is None or d.get("n_samples") is None:
        raise ValueError("receiver needs sample_rate_hz and n_samples (directly or via device)")
    sample_rate_hz = float(d["sample_rate_hz"])
    generate_rate_hz, factor, method = _decimation_from_dict(d, sample_rate_hz)
    bandwidth = d.get("analog_bandwidth_hz")
    return ReceiverConfig(
        sample_rate_hz=sample_rate_hz,
        n_samples=int(d["n_samples"]),
        baseband_offset_hz=float(d.get("baseband_offset_hz", 0.0)),
        clock_offset_ppm=float(d.get("clock_offset_ppm", 0.0)),
        quantization_bits=None
        if d.get("quantization_bits") is None
        else int(d["quantization_bits"]),
        agc_backoff_db=float(d.get("agc_backoff_db", 12.0)),
        device=device,
        generate_rate_hz=generate_rate_hz,
        decimation_factor=factor,
        decimation_method=method,
        analog_bandwidth_hz=None if bandwidth is None else float(bandwidth),
    )


def scenario_from_dict(d: dict[str, Any]) -> Scenario:
    known = {"name", "signal", "receiver", "satellites", "seed"}
    sats = tuple(
        SatelliteTruth(**{k: (int(v) if k == "prn" else float(v)) for k, v in s.items()})
        for s in d.get("satellites", [])
    )
    return Scenario(
        name=d["name"],
        signal=d["signal"],
        receiver=_receiver_from_dict(d["receiver"]),
        satellites=sats,
        seed=int(d.get("seed", 0)),
        extra={k: v for k, v in d.items() if k not in known},
    )


def load_scenario(path: str | Path) -> Scenario:
    return scenario_from_dict(yaml.safe_load(Path(path).read_text(encoding="utf-8")))
