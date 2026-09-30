"""Stand-in codes for signals whose ICD is not public (e.g. C-band LEO-PNT).

Until a real code definition exists, a hypothetical signal uses a pseudo-random +/-1
sequence seeded by (family name, PRN). It is deterministic, so simulator and receiver
agree, but it says nothing about the real system's codes.
"""

from __future__ import annotations

import hashlib

import numpy as np


def random_code(family: str, prn: int, length: int) -> np.ndarray:
    seed = int.from_bytes(hashlib.sha256(f"{family}:{prn}".encode()).digest()[:8], "little")
    rng = np.random.default_rng(seed)
    chips = rng.choice(np.array([1, -1], dtype=np.int8), size=length)
    chips.setflags(write=False)
    return chips
