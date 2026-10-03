"""C/N0 of a satellite signal received from the sky through an antenna and a receive chain.

    uv run python tools/sky_link_budget.py --antenna-gain-dbic 3 --antenna-temp-k 100 \\
        --stage cable:-0.5:0.5 --stage lna:20:1.0 --stage bpf:-2:2 --stage cable:-1:1 \\
        --receiver-nf-db 5 10 15

The received power is given at the output of an ideally matched right-hand circularly
polarised (RHCP) antenna with 0 dBi gain, which is how the IRNSS SPS ICD (v1.1, section
3.8.1, Table 4) states its minimum level: -162.3 dBW for the S-band SPS signal, for a
satellite more than 5 degrees above the horizon. The actual antenna's gain towards the
satellite, in dBic, is added to it; a linearly polarised antenna receiving a circularly
polarised signal loses about 3 dB more, which is included by giving a lower gain.

All noise is referred to the antenna output:

    T_sys = T_ant + T_e,   T_e = T_1 + T_2 / G_1 + T_3 / (G_1 G_2) + ...   (Friis)
    T_i = T0 (F_i - 1),    T0 = 290 K,   F_i = 10^(NF_i / 10)
    C/N0 = P_rx + G_ant - 10 log10(k T_sys)

A passive part with loss L dB (cable, filter) at room temperature is a stage with gain -L dB
and noise figure L dB. The last stage is the receiver itself (for example the ESP32 radio);
its gain does not matter. Implementation losses after the receiver input (quantisation,
filtering, sample-rate effects) are not included here: they are part of the detection
curves in docs/results/pd-curves.md, which take C/N0 at the receiver input as their input.
"""

from __future__ import annotations

import argparse
import math
from collections.abc import Sequence
from dataclasses import dataclass

from snappnt.eval.linkbudget import BOLTZMANN_J_PER_K, REFERENCE_TEMPERATURE_K

# IRNSS SIS ICD for SPS v1.1 (ISRO, 2017), section 3.8.1, Table 4: S-band SPS minimum.
NAVIC_S_MIN_POWER_DBW = -162.3


@dataclass(frozen=True)
class Stage:
    name: str
    gain_db: float
    nf_db: float


@dataclass(frozen=True)
class SkyBudget:
    receiver_nf_db: float
    chain_temp_k: float  # T_e of the whole chain, referred to the antenna output
    system_temp_k: float  # T_ant + T_e
    n0_dbw_hz: float
    cn0_dbhz: float


def _check(**values: float) -> None:
    for name, v in values.items():
        if not math.isfinite(v):
            raise ValueError(f"{name} must be a finite number, got {v}")


def noise_temp_k(nf_db: float) -> float:
    """Equivalent input noise temperature T0 (F - 1) of a stage with noise figure nf_db."""
    _check(nf_db=nf_db)
    if nf_db < 0:
        raise ValueError("a noise figure cannot be negative")
    return REFERENCE_TEMPERATURE_K * (10.0 ** (nf_db / 10.0) - 1.0)


def cascade_temp_k(stages: Sequence[Stage]) -> float:
    """Friis formula: noise temperature of the chain, referred to its input."""
    total, gain = 0.0, 1.0
    for s in stages:
        _check(gain_db=s.gain_db)
        total += noise_temp_k(s.nf_db) / gain
        gain *= 10.0 ** (s.gain_db / 10.0)
    return total


def sky_cn0(
    received_power_dbw: float,
    antenna_gain_dbic: float,
    antenna_temp_k: float,
    stages: Sequence[Stage],
    receiver_nf_db: float,
) -> SkyBudget:
    """C/N0 for one receive chain; ``stages`` lie between the antenna and the receiver."""
    _check(
        received_power_dbw=received_power_dbw,
        antenna_gain_dbic=antenna_gain_dbic,
        antenna_temp_k=antenna_temp_k,
    )
    if antenna_temp_k < 0:
        raise ValueError("antenna_temp_k must be zero or positive")
    te = cascade_temp_k([*stages, Stage("receiver", 0.0, receiver_nf_db)])
    tsys = antenna_temp_k + te
    if tsys <= 0:
        raise ValueError("system noise temperature must be positive")
    n0 = 10.0 * math.log10(BOLTZMANN_J_PER_K * tsys)
    return SkyBudget(receiver_nf_db, te, tsys, n0, received_power_dbw + antenna_gain_dbic - n0)


def parse_stage(text: str) -> Stage:
    """``name:gain_db:nf_db``, for example ``lna:20:1.0`` or ``cable:-1.5:1.5``."""
    parts = text.split(":")
    if len(parts) != 3:
        raise argparse.ArgumentTypeError(f"expected name:gain_db:nf_db, got {text!r}")
    try:
        stage = Stage(parts[0], float(parts[1]), float(parts[2]))
        _check(gain_db=stage.gain_db, nf_db=stage.nf_db)
    except ValueError as e:
        raise argparse.ArgumentTypeError(f"{text!r}: {e}") from e
    if stage.nf_db < 0:
        raise argparse.ArgumentTypeError(f"{text!r}: a noise figure cannot be negative")
    return stage


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument(
        "--received-power-dbw",
        type=float,
        default=NAVIC_S_MIN_POWER_DBW,
        help="power at an RHCP 0 dBi antenna (default: NavIC S-band SPS ICD minimum)",
    )
    p.add_argument("--antenna-gain-dbic", type=float, required=True)
    p.add_argument("--antenna-temp-k", type=float, required=True)
    p.add_argument(
        "--stage",
        type=parse_stage,
        action="append",
        default=[],
        help="name:gain_db:nf_db, in order from the antenna; repeat for each part",
    )
    p.add_argument("--receiver-nf-db", type=float, nargs="+", required=True)
    a = p.parse_args(argv)

    try:
        results = [
            sky_cn0(a.received_power_dbw, a.antenna_gain_dbic, a.antenna_temp_k, a.stage, nf)
            for nf in a.receiver_nf_db
        ]
    except ValueError as e:
        p.error(str(e))
    print(f"received power at RHCP 0 dBi: {a.received_power_dbw:.2f} dBW")
    print(
        f"antenna gain: {a.antenna_gain_dbic:.2f} dBic, antenna temperature {a.antenna_temp_k:g} K"
    )
    for s in a.stage:
        print(f"stage {s.name}: gain {s.gain_db:+.2f} dB, NF {s.nf_db:.2f} dB")
    print("receiver NF (dB) | T_e (K) | T_sys (K) | N0 (dBW/Hz) | C/N0 (dB-Hz)")
    for r in results:
        print(
            f"{r.receiver_nf_db:16.2f} | {r.chain_temp_k:7.1f} | {r.system_temp_k:9.1f} | "
            f"{r.n0_dbw_hz:11.2f} | {r.cn0_dbhz:12.2f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
