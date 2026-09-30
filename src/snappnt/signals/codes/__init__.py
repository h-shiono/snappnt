"""Spreading-code registry.

``get_code(spec, prn)`` returns the primary code of one period as +/-1 int8.
To add a signal: write a generator, register it in ``_REGISTRY`` under the ``code_family``
used in the catalog YAML, and add an ICD check test (see docs/architecture.md).
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np

from snappnt.signals.base import SignalSpec
from snappnt.signals.codes.generic import random_code
from snappnt.signals.codes.gps import gps_l1ca
from snappnt.signals.codes.navic import navic_l5_sps, navic_s_sps

_REGISTRY: dict[str, Callable[[int], np.ndarray]] = {
    "navic_s_sps": navic_s_sps,
    "navic_l5_sps": navic_l5_sps,
    "gps_l1ca": gps_l1ca,
}


def get_code(spec: SignalSpec, prn: int) -> np.ndarray:
    if spec.code_family.startswith("random:"):
        return random_code(spec.code_family, prn, spec.code_length)
    try:
        gen = _REGISTRY[spec.code_family]
    except KeyError:
        raise KeyError(f"no code generator registered for '{spec.code_family}'") from None
    code = gen(prn)
    if code.size != spec.code_length:
        raise ValueError(
            f"{spec.name}: generator gave {code.size} chips, expected {spec.code_length}"
        )
    return code
