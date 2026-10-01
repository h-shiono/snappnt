"""Frequency plan: where the signal lands after an optional external mixer.

    antenna (rf_hz) --[mixer, LO lo_hz]--> IF (if_hz) --[receiver tuned to tuned_hz]--> baseband

* Direct reception (no mixer): IF = RF.
* Low-side LO (LO < RF): IF = RF - LO, spectrum keeps its orientation.
* High-side LO (LO > RF): IF = LO - RF, spectrum is mirrored, so a positive Doppler shift
  at RF appears as a negative shift at baseband.

Example (C-band via a 2.4 GHz ESP32): RF 5020 MHz, low-side LO 2536 MHz -> IF 2484 MHz
(Wi-Fi channel 14 centre, rarely used). Image band is LO - IF = 52 MHz.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class FrequencyPlan:
    rf_hz: float
    tuned_hz: float
    lo_hz: float | None = None
    lo_side: Literal["low", "high"] = "low"

    def __post_init__(self) -> None:
        if self.lo_side not in ("low", "high"):
            raise ValueError(f"lo_side must be 'low' or 'high', got {self.lo_side!r}")
        if self.lo_hz is None:
            return
        if self.lo_side == "low" and not self.lo_hz < self.rf_hz:
            raise ValueError("low-side LO must be below RF")
        if self.lo_side == "high" and not self.lo_hz > self.rf_hz:
            raise ValueError("high-side LO must be above RF")

    @property
    def if_hz(self) -> float:
        if self.lo_hz is None:
            return self.rf_hz
        return self.rf_hz - self.lo_hz if self.lo_side == "low" else self.lo_hz - self.rf_hz

    @property
    def inverted(self) -> bool:
        return self.lo_hz is not None and self.lo_side == "high"

    @property
    def doppler_sign(self) -> int:
        """Multiply an RF Doppler shift by this to get the baseband shift."""
        return -1 if self.inverted else 1

    @property
    def baseband_offset_hz(self) -> float:
        """Carrier position in complex baseband (before Doppler and clock errors)."""
        return self.if_hz - self.tuned_hz

    @property
    def image_hz(self) -> float | None:
        """RF frequency that would land on the same IF from the other side of the LO."""
        if self.lo_hz is None:
            return None
        return self.lo_hz - self.if_hz if self.lo_side == "low" else self.lo_hz + self.if_hz
