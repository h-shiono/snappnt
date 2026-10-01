"""Device descriptions loaded from ``frontend/devices/*.yaml``.

Only a few fields are interpreted by code (sample rates, ADC bits, capture length); the rest
is documentation kept next to the numbers it explains.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from importlib import resources
from typing import Any

import yaml

_DEVICES_PACKAGE = "snappnt.frontend.devices"


@dataclass(frozen=True)
class DeviceSpec:
    name: str
    kind: str
    role: str
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def sample_rates_sps(self) -> list[float]:
        return [float(r) for r in self.raw.get("sample_rates_sps", [])]

    @property
    def adc_bits(self) -> int | None:
        bits = self.raw.get("adc_bits")
        return None if bits is None else int(bits)

    @property
    def max_capture_samples(self) -> int | None:
        n = self.raw.get("max_capture_samples")
        return None if n is None else int(n)

    @property
    def analog_bandwidth_hz(self) -> float | None:
        """Analog bandwidth; when the YAML gives [lower, upper] bounds, the lower bound."""
        bw = self.raw.get("analog_bandwidth_hz")
        if bw is None:
            return None
        if isinstance(bw, (list, tuple)):
            return float(bw[0])
        return float(bw)


def list_devices() -> list[str]:
    files = resources.files(_DEVICES_PACKAGE).iterdir()
    return sorted(f.name.removesuffix(".yaml") for f in files if f.name.endswith(".yaml"))


def load_device(name: str) -> DeviceSpec:
    path = resources.files(_DEVICES_PACKAGE).joinpath(f"{name}.yaml")
    if not path.is_file():
        raise KeyError(f"unknown device '{name}'. Available: {', '.join(list_devices())}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return DeviceSpec(name=raw["name"], kind=raw["kind"], role=raw["role"], raw=raw)
