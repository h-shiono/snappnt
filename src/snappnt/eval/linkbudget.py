"""Input level and C/N0 for a conducted test (generator, attenuators, receiver).

All levels are in dBm, losses in dB (positive numbers), noise densities in dBm/Hz and C/N0 in
dB-Hz. The receiver's noise density is k*T0 + NF with T0 = 290 K, which is -174 dBm/Hz + NF
(the usual convention for a noise figure). The signal power is taken as the power in the
received band; implementation losses of the receiver (quantisation, filter loss) are ignored.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

BOLTZMANN_J_PER_K = 1.380649e-23
REFERENCE_TEMPERATURE_K = 290.0
# Own choice, not a source value: a margin of 10 dB gives a C/N0 error of about 0.4 dB.
DEFAULT_MARGIN_DB = 10.0


def _db_sum(levels_db: Sequence[float]) -> float:
    return 10.0 * math.log10(sum(10.0 ** (x / 10.0) for x in levels_db))


def input_level_dbm(generator_dbm: float, losses_db: Sequence[float]) -> float:
    """Generator output minus the sum of the losses on the path (all losses >= 0 dB)."""
    if any(x < 0 for x in losses_db):
        raise ValueError("losses must be zero or positive (in dB)")
    return generator_dbm - sum(losses_db)


def noise_density_dbm_hz(nf_db: float, temperature_k: float = REFERENCE_TEMPERATURE_K) -> float:
    """Receiver noise density 10*log10(k*T/1 mW per Hz) + NF; -174 dBm/Hz + NF at 290 K."""
    if temperature_k <= 0:
        raise ValueError("temperature_k must be positive")
    return 10.0 * math.log10(BOLTZMANN_J_PER_K * temperature_k / 1e-3) + nf_db


def cn0_dbhz(p_in_dbm: float, nf_db: float) -> float:
    """C/N0 of a noise-free signal at p_in_dbm, limited by the receiver's own noise."""
    return p_in_dbm - noise_density_dbm_hz(nf_db)


@dataclass(frozen=True)
class NoiseCheck:
    """Result of the software-noise check (noise is added in the playback file)."""

    injected_dbm_hz: float  # N0_inj = P_in - scenario C/N0
    receiver_dbm_hz: float
    ratio_db: float  # injected minus receiver noise density
    ok: bool  # ratio_db >= margin_db
    effective_cn0_dbhz: float  # what the receiver sees with both noises
    error_db: float  # scenario C/N0 minus effective C/N0 (>= 0)


def check_injected_noise(
    scenario_cn0_dbhz: float,
    p_in_dbm: float,
    nf_db: float,
    margin_db: float = DEFAULT_MARGIN_DB,
) -> NoiseCheck:
    """Check that noise added in software dominates the receiver's own noise."""
    n_inj = p_in_dbm - scenario_cn0_dbhz
    n_rx = noise_density_dbm_hz(nf_db)
    ratio = n_inj - n_rx
    effective = p_in_dbm - _db_sum([n_inj, n_rx])
    return NoiseCheck(
        n_inj, n_rx, ratio, ratio >= margin_db, effective, scenario_cn0_dbhz - effective
    )


@dataclass(frozen=True)
class LinkBudget:
    """One receiver branch."""

    name: str
    p_in_dbm: float
    nf_db: float
    noise_dbm_hz: float
    cn0_dbhz: float  # noise-free signal, receiver noise only
    noise_check: NoiseCheck | None


def evaluate(
    name: str,
    generator_dbm: float,
    losses_db: Sequence[float],
    nf_db: float,
    scenario_cn0_dbhz: float | None = None,
    margin_db: float = DEFAULT_MARGIN_DB,
) -> LinkBudget:
    p_in = input_level_dbm(generator_dbm, losses_db)
    check = (
        None
        if scenario_cn0_dbhz is None
        else check_injected_noise(scenario_cn0_dbhz, p_in, nf_db, margin_db)
    )
    return LinkBudget(name, p_in, nf_db, noise_density_dbm_hz(nf_db), cn0_dbhz(p_in, nf_db), check)


def evaluate_branches(
    generator_dbm: float,
    common_losses_db: Sequence[float],
    branches: dict[str, tuple[Sequence[float], float]],
    scenario_cn0_dbhz: float | None = None,
    margin_db: float = DEFAULT_MARGIN_DB,
) -> list[LinkBudget]:
    """Evaluate several receivers; branches maps name -> (branch losses in dB, NF in dB)."""
    return [
        evaluate(
            name,
            generator_dbm,
            [*common_losses_db, *losses],
            nf_db,
            scenario_cn0_dbhz,
            margin_db,
        )
        for name, (losses, nf_db) in branches.items()
    ]
