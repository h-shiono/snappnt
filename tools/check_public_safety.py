#!/usr/bin/env python3
"""Scan tracked files for information that must not be published.

Generic patterns only (see docs/development/public-safety.md). In text files:
  * email addresses, except an allow list of project and placeholder addresses
  * absolute paths into a personal home directory
  * coordinate-like keys (lat, lon, latitude, longitude, alt) with precise values
  * the SigMF key core:geolocation

In image files (JPEG, PNG, WebP, TIFF), the metadata a camera or phone writes:
  * any GPS data (an entry in the EXIF GPS IFD, exif:GPS* properties in XMP, PNG text
    keywords exif:GPS*)
  * EXIF date/time (DateTime, DateTimeOriginal, DateTimeDigitized, also as PNG text keywords
    exif:DateTime*), the XMP creation date, and the PNG text keyword "Creation Time"
  * camera make and model (EXIF Make and Model, XMP tiff:Make and tiff:Model, PNG text
    keywords exif:Make and exif:Model)
EXIF is read from JPEG APP1 segments (including those of further images appended after the
main one), PNG eXIf chunks and "Raw profile type exif" text chunks, WebP EXIF chunks, and TIFF
files. An EXIF block without these tags (for example Orientation only) is not a finding. The
PNG text keywords "date:create", "date:modify" and "date:timestamp" and the PNG tIME chunk,
which ImageMagick and other tools write with the time they wrote the file, are not findings on
purpose: they say when the file was written, not when or where a photo was taken. Metadata
that cannot be parsed is a finding, because it cannot be shown to be clean. HEIC, HEIF and AVIF
files are not parsed and are always findings. Parsing uses the standard library only.

Optional: SNAPPNT_PRIVATE_TERMS=<file outside the repository> adds case-insensitive terms,
one per line. That file must never be committed.

A line containing the marker "public-safety: ignore" is skipped; use it only where a pattern is
named on purpose (for example in the rules page). Test fixtures for this checker are excluded.

Exit status 1 when anything is found. Findings print as file:line: reason for text files and
file: reason for images.
"""

from __future__ import annotations

import os
import re
import struct
import subprocess
import sys
import zlib
from pathlib import Path

ALLOWED_EMAILS = {
    "noreply@anthropic.com",
    "you@example.com",
}
ALLOWED_EMAIL_SUFFIXES = ("@users.noreply.github.com", "@example.com", "@example.org")

EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
HOME_PATH = re.compile(
    r"(/Users/[^/\s<>\"'`]+/|/home/(?!runner/|<)[^/\s<>\"'`]+/|[A-Za-z]:\\Users\\[^\\\s<>]+\\)"
)
COORD = re.compile(
    r"\b(lat|lon|lng|latitude|longitude|alt|altitude)(_deg|_m)?\b[\"']?\s*[:=]\s*-?\d+\.\d{3,}",
    re.IGNORECASE,
)
GEOLOCATION = re.compile(r"core:geolocation")

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff"}
UNCHECKED_IMAGE_SUFFIXES = {".heic", ".heif", ".avif"}
SKIP_SUFFIXES = {".gif", ".pdf", ".zip", ".sigmf-data", ".i8", ".sc16"}
SKIP_FILES = {"tools/check_public_safety.py", "tests/test_public_safety.py"}
IGNORE_MARKER = "public-safety: ignore"

GPS_FINDING = "GPS data in image metadata"
DATE_FINDING = "date/time in image metadata"
CAMERA_FINDING = "camera make/model in image metadata"
UNREADABLE_FINDING = "image metadata could not be read"
UNKNOWN_FORMAT_FINDING = "image format not recognised; metadata not checked"
UNCHECKED_FINDING = "image metadata not checked; convert to JPEG or PNG with metadata stripped"

EXIF_IFD_TAG = 0x8769
GPS_IFD_TAG = 0x8825
DATE_TAGS = {0x0132, 0x9003, 0x9004}  # DateTime, DateTimeOriginal, DateTimeDigitized
CAMERA_TAGS = {0x010F, 0x0110}  # Make, Model
EXIF_HEADER = b"Exif\x00\x00"
EMBEDDED_EXIF = re.compile(rb"\xff\xe1..Exif\x00\x00(?:II\*\x00|MM\x00\*)", re.DOTALL)
XMP_PATTERNS = (
    (re.compile(rb"\bexif:GPS[A-Za-z]+"), GPS_FINDING),
    (
        re.compile(rb"\b(?:xmp:CreateDate|exif:DateTimeOriginal|exif:DateTimeDigitized)\b"),
        DATE_FINDING,
    ),
    (re.compile(rb"\btiff:(?:Make|Model)\b"), CAMERA_FINDING),
)


def tracked_files(root: Path) -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "-z"], cwd=root, capture_output=True, check=True
    ).stdout.decode()
    return [root / p for p in out.split("\0") if p]


def load_private_terms() -> list[str]:
    path = os.environ.get("SNAPPNT_PRIVATE_TERMS")
    if not path:
        return []
    p = Path(path).expanduser()
    return [t.strip() for t in p.read_text(encoding="utf-8").splitlines() if t.strip()]


def scan_line(line: str, terms: list[str]) -> list[str]:
    reasons = []
    for m in EMAIL.finditer(line):
        addr = m.group(0).lower()
        if addr not in ALLOWED_EMAILS and not addr.endswith(ALLOWED_EMAIL_SUFFIXES):
            reasons.append(f"email address {m.group(0)!r}")
    if HOME_PATH.search(line):
        reasons.append("absolute path into a home directory")
    if COORD.search(line):
        reasons.append("precise coordinate value")
    if GEOLOCATION.search(line):
        reasons.append("SigMF core:geolocation key")
    low = line.lower()
    for t in terms:
        if t.lower() in low:
            reasons.append("private term from SNAPPNT_PRIVATE_TERMS")
    return reasons


def _take(data: bytes, start: int, length: int) -> bytes:
    """Return data[start:start + length], or raise ValueError if it runs past the end."""
    if start < 0 or length < 0 or start + length > len(data):
        raise ValueError("offset outside the metadata block")
    return data[start : start + length]


def scan_exif(tiff: bytes, reasons: set[str]) -> None:
    """Add findings for an EXIF block given as TIFF bytes (header "II*\\0" or "MM\\0*").

    Walks IFD0 and the IFDs chained after it, the Exif sub-IFD and the GPS IFD. Tag values are
    not read; the presence of a tag is enough. Raises ValueError if the block is malformed.
    """
    if tiff.startswith(EXIF_HEADER):
        tiff = tiff[len(EXIF_HEADER) :]
    order = {b"II": "<", b"MM": ">"}.get(_take(tiff, 0, 2))
    if order is None or struct.unpack(order + "H", _take(tiff, 2, 2))[0] != 42:
        raise ValueError("not a TIFF header")
    pending = [(struct.unpack(order + "I", _take(tiff, 4, 4))[0], "main")]
    visited = set()
    while pending:
        offset, kind = pending.pop()
        if offset == 0 or offset in visited:
            continue
        visited.add(offset)
        (count,) = struct.unpack(order + "H", _take(tiff, offset, 2))
        for i in range(count):
            entry = _take(tiff, offset + 2 + 12 * i, 12)
            tag, _type, _count, value = struct.unpack(order + "HHII", entry)
            if kind == "gps":
                reasons.add(GPS_FINDING)
            if tag in DATE_TAGS:
                reasons.add(DATE_FINDING)
            if tag in CAMERA_TAGS:
                reasons.add(CAMERA_FINDING)
            if tag == EXIF_IFD_TAG:
                pending.append((value, "exif"))
            elif tag == GPS_IFD_TAG:
                pending.append((value, "gps"))
        if kind == "main":
            next_at = offset + 2 + 12 * count
            if next_at + 4 <= len(tiff):
                pending.append((struct.unpack(order + "I", tiff[next_at : next_at + 4])[0], kind))


def scan_xmp(xmp: bytes, reasons: set[str]) -> None:
    for pattern, reason in XMP_PATTERNS:
        if pattern.search(xmp):
            reasons.add(reason)


def _scan_jpeg(data: bytes, reasons: set[str]) -> None:
    pos = 2
    while True:
        while _take(data, pos, 1) == b"\xff" and _take(data, pos + 1, 1) == b"\xff":
            pos += 1  # fill bytes before a marker
        if _take(data, pos, 1) != b"\xff":
            raise ValueError("expected a JPEG marker")
        marker = _take(data, pos + 1, 1)[0]
        if marker == 0xD9 or marker == 0xDA:  # EOI, or SOS: metadata segments come before it
            break
        if marker == 0x01 or 0xD0 <= marker <= 0xD8:  # markers without a length field
            pos += 2
            continue
        (length,) = struct.unpack(">H", _take(data, pos + 2, 2))
        payload = _take(data, pos + 4, length - 2)
        if marker == 0xE1 and payload.startswith(EXIF_HEADER):
            scan_exif(payload, reasons)
        elif marker == 0xE1 and payload.startswith(b"http://ns.adobe.com/"):
            scan_xmp(payload, reasons)
        pos += 2 + length
    # Phones append further JPEG images after the main one (MPF: previews, depth or gain maps),
    # each with its own EXIF segment. Look for those after the main image's metadata.
    for m in EMBEDDED_EXIF.finditer(data, pos):
        (length,) = struct.unpack(">H", data[m.start() + 2 : m.start() + 4])
        scan_exif(_take(data, m.start() + 4, length - 2), reasons)


def _png_text(ctype: bytes, payload: bytes) -> tuple[str, bytes]:
    """Return the keyword and the (decompressed) text of a tEXt, zTXt or iTXt chunk."""
    keyword, sep, rest = payload.partition(b"\x00")
    if not sep:
        raise ValueError("PNG text chunk without a keyword")
    if ctype == b"zTXt":
        rest = zlib.decompress(rest[1:])
    elif ctype == b"iTXt":
        compressed = rest[:1] == b"\x01"
        _lang, _, rest = rest[2:].partition(b"\x00")
        _translated, _, rest = rest.partition(b"\x00")
        if compressed:
            rest = zlib.decompress(rest)
    return keyword.decode("latin-1"), rest


def _raw_profile(text: bytes) -> bytes:
    """Decode an ImageMagick "Raw profile type ..." value: name, length, then hex lines."""
    lines = text.split()
    if len(lines) < 2:
        raise ValueError("raw profile without a length")
    return bytes.fromhex(b"".join(lines[2:]).decode("ascii"))


def _scan_exif_keyword(name: str, reasons: set[str]) -> None:
    """Add findings for a PNG text keyword "exif:<tag name>" (ImageMagick copies EXIF there)."""
    if name.startswith("GPS"):
        reasons.add(GPS_FINDING)
    elif name in ("DateTime", "DateTimeOriginal", "DateTimeDigitized"):
        reasons.add(DATE_FINDING)
    elif name in ("Make", "Model"):
        reasons.add(CAMERA_FINDING)


def _scan_png(data: bytes, reasons: set[str]) -> None:
    pos = 8
    while pos < len(data):
        (length,) = struct.unpack(">I", _take(data, pos, 4))
        ctype = _take(data, pos + 4, 4)
        payload = _take(data, pos + 8, length)
        if ctype == b"eXIf":
            scan_exif(payload, reasons)
        elif ctype in (b"tEXt", b"zTXt", b"iTXt"):
            keyword, text = _png_text(ctype, payload)
            if keyword in ("Raw profile type exif", "Raw profile type APP1"):
                scan_exif(_raw_profile(text), reasons)
            elif keyword == "Raw profile type xmp":
                scan_xmp(_raw_profile(text), reasons)
            elif keyword == "XML:com.adobe.xmp":
                scan_xmp(text, reasons)
            elif keyword == "Creation Time":
                reasons.add(DATE_FINDING)
            elif keyword.startswith("exif:"):
                _scan_exif_keyword(keyword.removeprefix("exif:"), reasons)
        elif ctype == b"IEND":
            break
        pos += 12 + length


def _scan_webp(data: bytes, reasons: set[str]) -> None:
    pos = 12
    while pos + 8 <= len(data):
        fourcc = data[pos : pos + 4]
        (length,) = struct.unpack("<I", data[pos + 4 : pos + 8])
        payload = _take(data, pos + 8, length)
        if fourcc == b"EXIF":
            scan_exif(payload, reasons)
        elif fourcc == b"XMP ":
            scan_xmp(payload, reasons)
        pos += 8 + length + (length & 1)


def scan_image(data: bytes) -> list[str]:
    """Return the findings for the metadata of one image file (JPEG, PNG, WebP or TIFF)."""
    reasons: set[str] = set()
    try:
        if data.startswith(b"\xff\xd8"):
            _scan_jpeg(data, reasons)
        elif data.startswith(b"\x89PNG\r\n\x1a\n"):
            _scan_png(data, reasons)
        elif data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            _scan_webp(data, reasons)
        elif data[:4] in (b"II*\x00", b"MM\x00*"):
            scan_exif(data, reasons)
        else:
            reasons.add(UNKNOWN_FORMAT_FINDING)
    except (ValueError, struct.error, zlib.error):
        reasons.add(UNREADABLE_FINDING)
    return sorted(reasons)


def main() -> int:
    root = Path(
        subprocess.run(
            ["git", "rev-parse", "--show-toplevel"], capture_output=True, check=True, text=True
        ).stdout.strip()
    )
    terms = load_private_terms()
    findings = 0
    for path in tracked_files(root):
        rel = path.relative_to(root).as_posix()
        suffix = path.suffix.lower()
        if rel in SKIP_FILES or suffix in SKIP_SUFFIXES or not path.is_file():
            continue
        if suffix in IMAGE_SUFFIXES or suffix in UNCHECKED_IMAGE_SUFFIXES:
            reasons = [UNCHECKED_FINDING]
            if suffix in IMAGE_SUFFIXES:
                reasons = scan_image(path.read_bytes())
            for reason in reasons:
                findings += 1
                print(f"{rel}: {reason}")
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for n, line in enumerate(text.splitlines(), start=1):
            if IGNORE_MARKER in line:
                continue
            for reason in scan_line(line, terms):
                findings += 1
                print(f"{rel}:{n}: {reason}")
    if findings:
        print(f"\n{findings} finding(s). See docs/development/public-safety.md.")
        return 1
    print("public-safety check: no findings")
    return 0


if __name__ == "__main__":
    sys.exit(main())
