"""Minimal SigMF reader/writer (https://sigmf.org), without the sigmf package dependency.

Layout: ``<base>.sigmf-data`` holds raw samples, ``<base>.sigmf-meta`` holds JSON metadata.
snappnt stores simulator truth in an annotation labelled "truth" under the ``snappnt:``
namespace, declared in ``core:extensions`` as SigMF requires.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from snappnt import __version__

SIGMF_VERSION = "1.2.0"
_DTYPES = {
    "cf32_le": np.dtype("<c8"),
    "ci16_le": np.dtype([("i", "<i2"), ("q", "<i2")]),
    "ci8": np.dtype([("i", "i1"), ("q", "i1")]),
}


def _base(path: str | Path) -> Path:
    p = Path(path)
    for suffix in (".sigmf-meta", ".sigmf-data", ".sigmf"):
        if p.name.endswith(suffix):
            return p.with_name(p.name[: -len(suffix)])
    return p


def _with(base: Path, suffix: str) -> Path:
    return base.with_name(base.name + suffix)


def write_sigmf(
    path: str | Path,
    samples: np.ndarray,
    sample_rate_hz: float,
    *,
    center_frequency_hz: float | None = None,
    datatype: str = "cf32_le",
    description: str = "",
    hw: str = "",
    truth: dict[str, Any] | None = None,
    extra_global: dict[str, Any] | None = None,
    extra_capture: dict[str, Any] | None = None,
) -> Path:
    """Write samples + metadata. Returns the base path (without suffix).

    ``extra_capture`` adds keys to the capture segment (for example ``core:datetime``). The
    metadata file is written to a temporary file and renamed, so an interrupted write never
    leaves a truncated ``.sigmf-meta`` next to the sample file."""
    base = _base(path)
    base.parent.mkdir(parents=True, exist_ok=True)
    x = np.asarray(samples)
    if datatype == "cf32_le":
        x.astype("<c8").tofile(_with(base, ".sigmf-data"))
    elif datatype in ("ci16_le", "ci8"):
        arr = np.empty(x.size, dtype=_DTYPES[datatype])
        arr["i"] = np.round(x.real)
        arr["q"] = np.round(x.imag)
        arr.tofile(_with(base, ".sigmf-data"))
    else:
        raise ValueError(f"unsupported datatype {datatype}")

    global_ = {
        "core:datatype": datatype,
        "core:sample_rate": float(sample_rate_hz),
        "core:version": SIGMF_VERSION,
        "core:recorder": f"snappnt {__version__}",
        "core:extensions": [{"name": "snappnt", "version": __version__, "optional": True}],
    }
    if description:
        global_["core:description"] = description
    if hw:
        global_["core:hw"] = hw
    if extra_global:
        global_.update({k if ":" in k else f"snappnt:{k}": v for k, v in extra_global.items()})

    capture: dict[str, Any] = {"core:sample_start": 0}
    if center_frequency_hz is not None:
        capture["core:frequency"] = float(center_frequency_hz)
    if extra_capture:
        capture.update(extra_capture)

    annotations = []
    if truth is not None:
        annotations.append(
            {
                "core:sample_start": 0,
                "core:sample_count": int(x.size),
                "core:label": "truth",
                "snappnt:truth": truth,
            }
        )

    meta = {"global": global_, "captures": [capture], "annotations": annotations}
    meta_path = _with(base, ".sigmf-meta")
    tmp_path = meta_path.with_name(meta_path.name + ".tmp")
    tmp_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    tmp_path.replace(meta_path)
    return base


def read_sigmf(path: str | Path) -> tuple[np.ndarray, dict[str, Any]]:
    """Return (samples as complex64, metadata dict)."""
    base = _base(path)
    meta = json.loads(_with(base, ".sigmf-meta").read_text(encoding="utf-8"))
    datatype = meta["global"]["core:datatype"]
    if datatype not in _DTYPES:
        raise ValueError(f"unsupported datatype {datatype}")
    raw = np.fromfile(_with(base, ".sigmf-data"), dtype=_DTYPES[datatype])
    if datatype == "cf32_le":
        x = raw.astype(np.complex64)
    else:
        x = (raw["i"].astype(np.float32) + 1j * raw["q"].astype(np.float32)).astype(np.complex64)
    return x, meta


def get_truth(meta: dict[str, Any]) -> dict[str, Any] | None:
    for ann in meta.get("annotations", []):
        if ann.get("core:label") == "truth":
            return ann.get("snappnt:truth")
    return None
