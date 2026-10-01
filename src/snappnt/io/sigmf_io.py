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


def _replace_pair(pairs: list[tuple[Path, Path]]) -> None:
    """Rename each ``(temporary, final)`` pair into place so that all succeed or none does.

    An existing final file is first moved to a backup name (``.bak`` added). If any rename
    fails, the files already placed are removed, the backups are moved back and the error is
    raised, so an existing recording stays complete. The backups are deleted after every
    rename has succeeded. If moving a backup back fails too, the remaining backups are kept
    and the raised error names them."""
    backups: dict[Path, Path] = {}
    placed: list[Path] = []
    try:
        for _, final in pairs:
            if final.exists():
                backup = final.with_name(final.name + ".bak")
                final.replace(backup)
                backups[final] = backup
        for tmp, final in pairs:
            tmp.replace(final)
            placed.append(final)
    except OSError:
        stuck: list[Path] = []
        for final in placed:
            if final not in backups:
                final.unlink(missing_ok=True)
        for final, backup in backups.items():
            try:
                backup.replace(final)
            except OSError:
                stuck.append(backup)
        if stuck:
            names = ", ".join(str(b) for b in stuck)
            raise OSError(
                f"could not restore the previous recording; its files are kept as {names}"
            ) from None
        raise
    for backup in backups.values():
        backup.unlink(missing_ok=True)


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
    sample file and the metadata file are first written under temporary names (``.tmp`` added)
    and renamed only when both are complete. An existing recording with the same base name is
    moved to backup names (``.bak`` added) during the rename and deleted after both new files
    are in place. If anything fails, the temporary files are removed and the existing recording
    is restored complete. Only if that restore fails too are the ``.bak`` files kept, and the
    raised error names them."""
    base = _base(path)
    base.parent.mkdir(parents=True, exist_ok=True)
    x = np.asarray(samples)
    if datatype == "cf32_le":
        raw = x.astype("<c8")
    elif datatype in ("ci16_le", "ci8"):
        raw = np.empty(x.size, dtype=_DTYPES[datatype])
        raw["i"] = np.round(x.real)
        raw["q"] = np.round(x.imag)
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
    data_path = _with(base, ".sigmf-data")
    meta_path = _with(base, ".sigmf-meta")
    data_tmp = data_path.with_name(data_path.name + ".tmp")
    meta_tmp = meta_path.with_name(meta_path.name + ".tmp")
    try:
        raw.tofile(data_tmp)
        meta_tmp.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        _replace_pair([(data_tmp, data_path), (meta_tmp, meta_path)])
    finally:
        data_tmp.unlink(missing_ok=True)
        meta_tmp.unlink(missing_ok=True)
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
