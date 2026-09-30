"""NavIC (IRNSS) SPS spreading codes for L5 and S bands.

Source: IRNSS Signal-in-Space ICD for Standard Positioning Service, version 1.1 (ISRO, 2017),
Section 3 and Table 7 (code phase assignment).

* 1023-chip Gold codes, 1.023 Mchip/s (1 ms period).
* G1 = 1 + x^3 + x^10, initialised to all ones.
* G2 = 1 + x^2 + x^3 + x^6 + x^8 + x^9 + x^10, initialised per PRN (table below).
* Code = G1 xor G2.

The G2 initial states below are copied from the ICD table in the printed bit order; the
"first 10 chips (octal)" column of the same table is checked in tests/test_codes_navic.py.
They were additionally cross-checked against the tables in PocketSDR (BSD-2-Clause).
"""

from __future__ import annotations

from functools import lru_cache

import numpy as np

from snappnt.signals.codes.lfsr import bits_to_chips, lfsr_bits

CODE_LENGTH = 1023
G1_TAPS = (3, 10)
G2_TAPS = (2, 3, 6, 8, 9, 10)

# ICD v1.1 Table 7, PRN 1..14
G2_INIT: dict[str, tuple[str, ...]] = {
    "L5": (
        "1110100111", "0000100110", "1000110100", "0101110010", "1110110000",
        "0001101011", "0000010100", "0100110000", "0010011000", "1101100100",
        "0001001100", "1101111100", "1011010010", "0111101010",
    ),
    "S": (
        "0011101111", "0101111101", "1000110001", "0010101011", "1010010001",
        "0100101100", "0010001110", "0100100110", "1100001110", "1010111110",
        "1110010001", "1101101001", "0101000101", "0100001101",
    ),
}  # fmt: skip


@lru_cache(maxsize=64)
def _navic_sps(band: str, prn: int) -> np.ndarray:
    table = G2_INIT[band]
    if not 1 <= prn <= len(table):
        raise ValueError(f"NavIC {band} SPS PRN must be 1..{len(table)}, got {prn}")
    g1 = lfsr_bits("1" * 10, G1_TAPS, CODE_LENGTH)
    g2 = lfsr_bits(table[prn - 1], G2_TAPS, CODE_LENGTH)
    chips = bits_to_chips(g1 ^ g2)
    chips.setflags(write=False)
    return chips


def navic_s_sps(prn: int) -> np.ndarray:
    """NavIC S-band SPS code (2492.028 MHz), +/-1 int8, length 1023."""
    return _navic_sps("S", prn)


def navic_l5_sps(prn: int) -> np.ndarray:
    """NavIC L5-band SPS code (1176.45 MHz), +/-1 int8, length 1023."""
    return _navic_sps("L5", prn)
