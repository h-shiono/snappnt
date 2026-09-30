"""Linear feedback shift registers (Fibonacci form) as used by GPS/NavIC Gold codes.

Convention used throughout snappnt
----------------------------------
* A register of n stages is numbered 1..n as in the ICDs. Stage n is the output stage.
* The feedback polynomial ``1 + x^a + ... + x^n`` is given as its exponents, e.g.
  G1 = 1 + x^3 + x^10  ->  ``taps=(3, 10)``. The new value entering stage 1 is the XOR
  of the stages listed in ``taps``; every other stage k takes the old value of stage k-1.
* ``init`` is written in the order the bits leave the register: the first character is
  the first output bit. This matches how the NavIC ICD (Table 7) prints the G2 initial
  states, which ``tests/test_codes_navic.py`` verifies against the printed first chips.
* Bits are {0, 1}. Conversion to chips uses the GNSS convention 0 -> +1, 1 -> -1.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np


def lfsr_bits(init: str | Sequence[int], taps: Sequence[int], length: int) -> np.ndarray:
    """Return ``length`` output bits of a Fibonacci LFSR.

    ``init`` is a bit string or sequence whose first element is the first output bit.
    """
    bits = [int(c) for c in init]
    n = len(bits)
    if any(b not in (0, 1) for b in bits):
        raise ValueError("init must contain only 0/1")
    if max(taps) != n:
        raise ValueError(f"highest tap ({max(taps)}) must equal register length ({n})")
    # reg[0] is stage n (output), reg[n-1] is stage 1.
    reg = list(bits)
    tap_idx = [n - t for t in taps]  # stage t lives at index n - t
    out = np.empty(length, dtype=np.uint8)
    for i in range(length):
        out[i] = reg[0]
        fb = 0
        for j in tap_idx:
            fb ^= reg[j]
        reg = reg[1:] + [fb]
    return out


def bits_to_chips(bits: np.ndarray) -> np.ndarray:
    """Map {0,1} bits to {+1,-1} chips as int8."""
    return (1 - 2 * np.asarray(bits, dtype=np.int8)).astype(np.int8)


def chips_to_bits(chips: np.ndarray) -> np.ndarray:
    return (np.asarray(chips) < 0).astype(np.uint8)


def first_chips_octal(chips: np.ndarray, n: int = 10) -> str:
    """First ``n`` chips as the octal string printed in GPS/NavIC ICD tables.

    Chips are converted back to bits (+1 -> 0, -1 -> 1). With n = 10 the bits are grouped
    1 + 3 + 3 + 3, e.g. GPS PRN 1 gives '1440'.
    """
    bits = chips_to_bits(chips[:n])
    value = int("".join(str(int(b)) for b in bits), 2)
    width = -(-n // 3)
    return format(value, "o").zfill(width)
