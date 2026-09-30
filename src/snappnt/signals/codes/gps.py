"""GPS L1 C/A codes (IS-GPS-200), used only to validate the shared LFSR code path.

The ESP32 cannot tune to L1, so GPS here is a software-only reference: its code tables are
widely reproduced, which makes it a good independent check of snappnt's conventions.

Code = G1 xor (G2 delayed by a PRN-specific number of chips). Delays for PRN 1..32 follow
the "code delay (chips)" column of IS-GPS-200 Table 3-Ia.
"""

from __future__ import annotations

from functools import lru_cache

import numpy as np

from snappnt.signals.codes.lfsr import bits_to_chips, lfsr_bits

CODE_LENGTH = 1023
G1_TAPS = (3, 10)
G2_TAPS = (2, 3, 6, 8, 9, 10)

G2_DELAY_CHIPS = (
    5, 6, 7, 8, 17, 18, 139, 140, 141, 251, 252, 254, 255, 256, 257, 258,
    469, 470, 471, 472, 473, 474, 509, 512, 513, 514, 515, 516, 859, 860, 861, 862,
)  # fmt: skip


@lru_cache(maxsize=64)
def gps_l1ca(prn: int) -> np.ndarray:
    if not 1 <= prn <= len(G2_DELAY_CHIPS):
        raise ValueError(f"GPS L1 C/A PRN must be 1..{len(G2_DELAY_CHIPS)}, got {prn}")
    g1 = lfsr_bits("1" * 10, G1_TAPS, CODE_LENGTH)
    g2 = lfsr_bits("1" * 10, G2_TAPS, CODE_LENGTH)
    g2_delayed = np.roll(g2, G2_DELAY_CHIPS[prn - 1])
    chips = bits_to_chips(g1 ^ g2_delayed)
    chips.setflags(write=False)
    return chips
