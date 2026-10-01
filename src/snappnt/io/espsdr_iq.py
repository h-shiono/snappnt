"""Decode raw ESP32 IQ dump words.

Word format (per ESPARGOS ESP-SDR documentation, 2026-09), most significant bit first:

    bits 31-28  AGC state machine (inferred)
    bits 27-20  RX gain index (into the chip's gain table)
    bits 19-10  I, signed 10-bit two's complement (-512..511)
    bits  9-0   Q, signed 10-bit two's complement

The firmware repacks samples (8-bit or packed 10-bit) before sending them to the host
(docs/design/espsdr-protocol.md). ``unpack_words`` decodes the in-memory 32-bit words;
``unpack_payload`` decodes the host transfer payload with the same I/Q convention.
"""

from __future__ import annotations

import numpy as np

PAYLOAD_BITS = (8, 10)


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


def payload_size(n_samples: int, bits: int) -> int:
    """Payload bytes for ``n_samples`` samples at ``bits`` per component (8 or 10)."""
    if bits not in PAYLOAD_BITS:
        raise ValueError(f"bits must be one of {PAYLOAD_BITS}, got {bits}")
    return (n_samples * bits * 2 + 7) // 8


def unpack_payload(payload: bytes, n_samples: int, bits: int) -> np.ndarray:
    """Decode a capture payload into complex64 samples on the 10-bit scale (-512..511).

    ``bits=10``: a little-endian bit stream of 20-bit fields, least significant bit of each
    byte first. ``bits=8``: two signed bytes per sample; the first byte is the upper eight
    bits of the word's low 10-bit field, the second byte those of the high field. Eight-bit
    values are multiplied by 4 to return to the 10-bit scale.

    The high field is I and the low field is Q, as in ``unpack_words``.
    """
    need = payload_size(n_samples, bits)
    if len(payload) != need:
        raise ValueError(f"payload has {len(payload)} bytes, expected {need}")
    raw = np.frombuffer(payload, dtype=np.uint8)
    if bits == 8:
        pairs = raw.view(np.int8).reshape(n_samples, 2).astype(np.int32) * 4
        return (pairs[:, 1] + 1j * pairs[:, 0]).astype(np.complex64)
    stream = np.unpackbits(raw, bitorder="little")[: n_samples * 20].reshape(n_samples, 20)
    words = (stream.astype(np.uint32) << np.arange(20, dtype=np.uint32)).sum(axis=1)
    iq, _, _ = unpack_words(words)
    return iq
