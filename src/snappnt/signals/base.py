"""Signal parameters.

A signal is described declaratively in ``catalog/<name>.yaml``. The YAML says *what* is
transmitted (carrier, chip rate, code length, modulation, data symbol rate); the spreading
code itself is produced by the generator registered under ``code_family``
(see ``snappnt.signals.codes``).

Units are SI and appear in field names: ``_hz`` for frequencies and rates, ``_s`` for seconds.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from importlib import resources
from typing import Any

import yaml

_CATALOG_PACKAGE = "snappnt.signals.catalog"


@dataclass(frozen=True)
class SignalSpec:
    name: str
    system: str
    band: str
    carrier_hz: float
    chip_rate_hz: float
    code_length: int
    modulation: str
    code_family: str
    prn_range: tuple[int, int]
    symbol_rate_hz: float | None = None
    pilot: bool = False
    source: str = ""
    notes: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def code_period_s(self) -> float:
        """Duration of one primary-code period."""
        return self.code_length / self.chip_rate_hz

    @property
    def symbol_period_s(self) -> float | None:
        return None if not self.symbol_rate_hz else 1.0 / self.symbol_rate_hz

    def prns(self) -> range:
        lo, hi = self.prn_range
        return range(lo, hi + 1)


_KNOWN_KEYS = {f for f in SignalSpec.__dataclass_fields__ if f != "extra"}


def _from_dict(d: dict[str, Any]) -> SignalSpec:
    known = {k: v for k, v in d.items() if k in _KNOWN_KEYS}
    extra = {k: v for k, v in d.items() if k not in _KNOWN_KEYS}
    # PyYAML (YAML 1.1) reads "2492.028e6" as a string, so numbers are cast explicitly.
    for key in ("carrier_hz", "chip_rate_hz"):
        known[key] = float(known[key])
    known["code_length"] = int(known["code_length"])
    if known.get("symbol_rate_hz") is not None:
        known["symbol_rate_hz"] = float(known["symbol_rate_hz"])
    known["prn_range"] = tuple(int(p) for p in known["prn_range"])
    return SignalSpec(**known, extra=extra)


def list_signals() -> list[str]:
    files = resources.files(_CATALOG_PACKAGE).iterdir()
    return sorted(f.name.removesuffix(".yaml") for f in files if f.name.endswith(".yaml"))


def load_signal(name: str) -> SignalSpec:
    path = resources.files(_CATALOG_PACKAGE).joinpath(f"{name}.yaml")
    if not path.is_file():
        raise KeyError(f"unknown signal '{name}'. Available: {', '.join(list_signals())}")
    return _from_dict(yaml.safe_load(path.read_text(encoding="utf-8")))
