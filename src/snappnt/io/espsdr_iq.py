"""Decode raw ESP32 IQ dump words.

Word format (per ESPARGOS ESP-SDR documentation, 2026-09), most significant bit first:

    bits 31-28  AGC state machine (inferred)
    bits 27-20  RX gain index (into the chip's gain table)
    bits 19-10  I, signed 10-bit two's complement (-512..511)
    bits  9-0   Q, signed 10-bit two's complement

Note: the firmware may repack samples (8/10-bit) before sending them to the host.
This module decodes the in-memory 32-bit words; the host transfer format is handled in
``espsdr_client`` once the protocol is pinned down.
"""

from __future__ import annotations

import numpy as np


def _signed10(v: np.ndarray) -> np.ndarray:
    v = v.astype(np.int32)
    return np.where(v & 0x200, v - 0x400, v)


def unpack_words(words: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return (iq complex64, gain index uint8, agc state uint8)."""
    w = np.asarray(words, dtype=np.uint32)
    i = _signed10((w >> 10) & 0x3FF)
    q = _signed10(w & 0x3FF)
    gain = ((w >> 20) & 0xFF).astype(np.uint8)
    agc = ((w >> 28) & 0xF).astype(np.uint8)
    return (i + 1j * q).astype(np.complex64), gain, agc


def pack_words(iq: np.ndarray, gain: int = 0, agc: int = 0) -> np.ndarray:
    """Inverse of ``unpack_words`` (used for tests and for replaying captures)."""
    i = np.asarray(np.round(iq.real), dtype=np.int32) & 0x3FF
    q = np.asarray(np.round(iq.imag), dtype=np.int32) & 0x3FF
    return ((agc & 0xF) << 28 | (gain & 0xFF) << 20 | i << 10 | q).astype(np.uint32)
