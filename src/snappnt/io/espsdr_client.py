"""Host-side client for the ESP-SDR firmware over USB serial.

Status: skeleton. Command names below come from the esp-sdr README (2026-09); the exact
syntax of tuning and capture commands and the binary transfer format still need to be
read from the firmware source and confirmed on a real board (milestone M3).

Known from the README:
  INFO, CAPS, LIMITS?, RANGE?        queries
  GAIN MANUAL <index> / GAIN HARDWARE
  BANDWIDTH <MHz>                    0 selects the widest setting
  RELEASE                            frees the radio (also after 5 s idle)
  UART default: 2,000,000 baud 8N1; native USB ignores the baud setting.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class EspSdrClient:
    port: str
    baudrate: int = 2_000_000
    timeout_s: float = 2.0

    def __post_init__(self) -> None:
        try:
            import serial  # type: ignore[import-not-found]
        except ImportError as e:  # pragma: no cover - optional dependency
            raise ImportError('install the hardware extra: pip install -e ".[hw]"') from e
        self._ser = serial.Serial(self.port, self.baudrate, timeout=self.timeout_s)

    def command(self, line: str) -> str:
        self._ser.write((line.strip() + "\n").encode("ascii"))
        return self._ser.readline().decode("ascii", errors="replace").strip()

    def info(self) -> str:
        return self.command("INFO")

    def limits(self) -> str:
        return self.command("LIMITS?")

    def set_gain_manual(self, index: int) -> str:
        return self.command(f"GAIN MANUAL {int(index)}")

    def set_gain_hardware(self) -> str:
        return self.command("GAIN HARDWARE")

    def set_bandwidth_mhz(self, mhz: float) -> str:
        return self.command(f"BANDWIDTH {mhz:g}")

    def release(self) -> str:
        return self.command("RELEASE")

    def tune(self, frequency_hz: float) -> str:
        raise NotImplementedError("TODO(M3): confirm the tuning command in esp-sdr firmware source")

    def capture(self, n_samples: int, sample_rate_hz: float):
        raise NotImplementedError("TODO(M3): confirm capture command and transfer format")

    def close(self) -> None:
        self._ser.close()
