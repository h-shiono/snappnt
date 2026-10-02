"""Simulation scenarios: what is transmitted, how it is received, and the truth to compare against.

Scenarios are YAML files (see ``scenarios/``). Example::

    name: navic_s_esp32c3
    signal: navic_s_sps
    seed: 1
    receiver:
      device: esp32c3          # optional; fills sample rate / bits / capture length
      sample_rate_hz: 4000000
      n_samples: 16384
      baseband_offset_hz: 0    # carrier position in baseband from the frequency plan
      clock_offset_ppm: 12.0   # receiver crystal error (shifts carrier and sample clock)
      quantization_bits: 10    # null = keep floating point
      agc_backoff_db: 12       # RMS level below ADC full scale
      # Optional: generate at a higher rate, band-limit, then reduce to sample_rate_hz
      generate_rate_hz: 80000000
      analog_bandwidth_hz: 13000000   # default: first (lower) value of the device YAML
      decimation: {factor: 20, method: none}   # none = keep every n-th sample, ideal = filter first
      # Optional: DC offset (fraction of ADC full scale, needs quantization_bits) and fixed spurs
      # (offset from the tuned frequency; power = tone power / total noise power per sample)
      dc_offset: {i: -0.5, q: 0.0}
      spurs:
        - {offset_hz: -12000000, power_db: -12}
    satellites:
      - {prn: 1, cn0_dbhz: 55, doppler_hz: 0, code_phase_chips: 123.4}

A satellite may give ``pass: {altitude_m, max_elevation_deg, time_s}`` instead of ``doppler_hz``
and ``doppler_rate_hzps``. These are then computed for a circular-orbit pass at ``time_s``
seconds from the closest approach (negative before it); see ``snappnt.sim.leo``::

      - {prn: 5, cn0_dbhz: 48, pass: {altitude_m: 550000, max_elevation_deg: 90, time_s: -60}}

An external mixer is described by an optional top-level ``frequency_plan``. The RF frequency
is the signal's ``carrier_hz``. With a plan, ``baseband_offset_hz`` comes from the plan (do not
set it in ``receiver``), and ``receiver.lo_offset_ppm`` is the error of the external LO::

    frequency_plan: {lo_hz: 2536000000, lo_side: low, tuned_hz: 2484000000}
    receiver:
      lo_offset_ppm: 1.5       # external LO error, separate from clock_offset_ppm
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from snappnt.frontend.device import load_device
from snappnt.frontend.freqplan import FrequencyPlan
from snappnt.signals import load_signal
from snappnt.sim.leo import leo_pass_doppler


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
    lo_offset_ppm: float = 0.0  # external LO error; only valid with a frequency plan
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
    # Fraction of ADC full scale, added before rounding. None means dc_offset is not set;
    # an explicit zero is kept so that the truth records it.
    dc_offset_i: float | None = None
    dc_offset_q: float | None = None
    spurs: tuple[tuple[float, float], ...] = ()  # (baseband offset_hz, power_db re noise power)


@dataclass(frozen=True)
class Scenario:
    name: str
    signal: str
    receiver: ReceiverConfig
    satellites: tuple[SatelliteTruth, ...]
    seed: int = 0
    frequency_plan: FrequencyPlan | None = None
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
    raw_factor = dec["factor"]
    factor = int(raw_factor)
    if factor != raw_factor:
        raise ValueError(f"decimation.factor must be an integer, not {raw_factor}")
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


def _dc_and_spurs_from_dict(
    d: dict[str, Any], sample_rate_hz: float, generate_rate_hz: float | None
) -> tuple[float | None, float | None, tuple[tuple[float, float], ...]]:
    dc = d.get("dc_offset")
    dc_i: float | None = None
    dc_q: float | None = None
    if dc is not None:
        dc_i, dc_q = float(dc.get("i", 0.0)), float(dc.get("q", 0.0))
        for name, value in (("i", dc_i), ("q", dc_q)):
            if not -1.0 <= value < 1.0:  # false for NaN as well
                raise ValueError(f"dc_offset.{name} must be in [-1, 1), not {value}")
        if d.get("quantization_bits") is None:
            raise ValueError("receiver.dc_offset needs quantization_bits")
    nyquist_hz = (generate_rate_hz or sample_rate_hz) / 2.0
    spurs = []
    for spur in d.get("spurs") or []:
        offset_hz, power_db = float(spur["offset_hz"]), float(spur["power_db"])
        if not np.isfinite(power_db):
            raise ValueError(f"spur power_db must be a finite number, not {power_db}")
        if not abs(offset_hz) < nyquist_hz:  # true for NaN as well
            raise ValueError(
                f"spur offset_hz ({offset_hz}) must be inside +-{nyquist_hz} Hz "
                "(half the rate at which samples are generated)"
            )
        spurs.append((offset_hz, power_db))
    return dc_i, dc_q, tuple(spurs)


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
        bandwidth = dev.raw.get("analog_bandwidth_hz")
        if bandwidth is not None:
            # The device file may give [lower, upper] bounds; the lower bound is used.
            lower = bandwidth[0] if isinstance(bandwidth, (list, tuple)) else bandwidth
            d.setdefault("analog_bandwidth_hz", lower)
    if d.get("sample_rate_hz") is None or d.get("n_samples") is None:
        raise ValueError("receiver needs sample_rate_hz and n_samples (directly or via device)")
    sample_rate_hz = float(d["sample_rate_hz"])
    generate_rate_hz, factor, method = _decimation_from_dict(d, sample_rate_hz)
    bandwidth = d.get("analog_bandwidth_hz")
    if bandwidth is not None and float(bandwidth) <= 0:
        raise ValueError(f"analog_bandwidth_hz must be positive, not {bandwidth}")
    dc_i, dc_q, spurs = _dc_and_spurs_from_dict(d, sample_rate_hz, generate_rate_hz)
    return ReceiverConfig(
        sample_rate_hz=sample_rate_hz,
        n_samples=int(d["n_samples"]),
        baseband_offset_hz=float(d.get("baseband_offset_hz", 0.0)),
        clock_offset_ppm=float(d.get("clock_offset_ppm", 0.0)),
        lo_offset_ppm=float(d.get("lo_offset_ppm", 0.0)),
        quantization_bits=None
        if d.get("quantization_bits") is None
        else int(d["quantization_bits"]),
        agc_backoff_db=float(d.get("agc_backoff_db", 12.0)),
        device=device,
        generate_rate_hz=generate_rate_hz,
        decimation_factor=factor,
        decimation_method=method,
        analog_bandwidth_hz=None if bandwidth is None else float(bandwidth),
        dc_offset_i=dc_i,
        dc_offset_q=dc_q,
        spurs=spurs,
    )


def _satellite_from_dict(s: dict[str, Any], signal: str) -> SatelliteTruth:
    s = dict(s)
    pass_dict = s.pop("pass", None)
    if pass_dict is not None:
        clash = [k for k in ("doppler_hz", "doppler_rate_hzps") if k in s]
        if clash:
            raise ValueError(f"satellite 'pass' cannot be combined with {', '.join(clash)}")
        doppler, rate = leo_pass_doppler(
            load_signal(signal).carrier_hz,
            float(pass_dict["altitude_m"]),
            float(pass_dict["max_elevation_deg"]),
            float(pass_dict.get("time_s", 0.0)),
        )
        s["doppler_hz"] = float(doppler)
        s["doppler_rate_hzps"] = float(rate)
    return SatelliteTruth(**{k: (int(v) if k == "prn" else float(v)) for k, v in s.items()})


def scenario_from_dict(d: dict[str, Any]) -> Scenario:
    known = {"name", "signal", "receiver", "satellites", "seed", "frequency_plan"}
    sats = tuple(_satellite_from_dict(s, d["signal"]) for s in d.get("satellites", []))
    receiver = _receiver_from_dict(d["receiver"])
    plan = None
    plan_dict = d.get("frequency_plan")
    if plan_dict is not None:
        if "baseband_offset_hz" in d["receiver"]:
            raise ValueError(
                "receiver.baseband_offset_hz cannot be combined with frequency_plan; "
                "it is computed from the plan"
            )
        plan = FrequencyPlan(
            rf_hz=load_signal(d["signal"]).carrier_hz,
            tuned_hz=float(plan_dict["tuned_hz"]),
            lo_hz=float(plan_dict["lo_hz"]),
            lo_side=str(plan_dict.get("lo_side", "low")),
        )
        receiver = replace(receiver, baseband_offset_hz=plan.baseband_offset_hz)
    elif receiver.lo_offset_ppm != 0.0:
        raise ValueError("receiver.lo_offset_ppm needs a frequency_plan")
    return Scenario(
        name=d["name"],
        signal=d["signal"],
        receiver=receiver,
        frequency_plan=plan,
        satellites=sats,
        seed=int(d.get("seed", 0)),
        extra={k: v for k, v in d.items() if k not in known},
    )


def load_scenario(path: str | Path) -> Scenario:
    return scenario_from_dict(yaml.safe_load(Path(path).read_text(encoding="utf-8")))
