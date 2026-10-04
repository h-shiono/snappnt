import importlib.util
import struct
import zlib
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parents[1] / "tools" / "check_public_safety.py"
_spec = importlib.util.spec_from_file_location("check_public_safety", _PATH)
cps = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cps)


@pytest.mark.parametrize(
    "line",
    [
        "contact: someone@gmail.com",
        "path = '/Users/alice/data/run1.sigmf'",
        "see /home/bob/snappnt/out",
        r"C:\Users\carol\Documents",
        "lat: 12.3456",
        "longitude = -98.76543",
        '{"lat": 12.34567, "lon": 98.76543}',
        "'lat_deg': -12.345",
        '"core:geolocation": {}',
    ],
)
def test_flags(line):
    assert cps.scan_line(line, [])


@pytest.mark.parametrize(
    "line",
    [
        "Co-Authored-By: Claude <noreply@anthropic.com>",
        "Signed-off-by: Your Name <you@example.com>",
        "12345+user@users.noreply.github.com",
        "carrier_hz: 2492028000.0",
        "doppler_hz: 1234.567",
        "runs-on /home/runner/work",
        "lat: 35.0",
    ],
)
def test_passes(line):
    assert not cps.scan_line(line, [])


def test_ignore_marker_is_documented():
    assert cps.IGNORE_MARKER == "public-safety: ignore"


def test_private_terms():
    assert cps.scan_line("meet at Example Street", ["example street"])
    assert not cps.scan_line("nothing here", ["example street"])


# Image metadata. Images are built byte by byte in tmp_path rather than committed, because a
# committed image would itself be scanned by the check.

ORIENTATION = (0x0112, 3, 1)  # Orientation, SHORT: kept by tools that strip metadata
MAKE = (0x010F, 2, 4)  # Make, ASCII
MODEL = (0x0110, 2, 4)  # Model, ASCII
DATE_TIME_ORIGINAL = (0x9003, 2, 20)  # DateTimeOriginal, ASCII
GPS_LATITUDE_REF = (0x0001, 2, 2)  # GPSLatitudeRef, ASCII


def _ifd(entries, order):
    out = struct.pack(order + "H", len(entries))
    for tag, typ, count, *value in sorted(entries):
        out += struct.pack(order + "HHI", tag, typ, count) + (value[0] if value else b"\0" * 4)
    return out + struct.pack(order + "I", 0)


def tiff_bytes(ifd0=(), exif=(), gps=(), order="<"):
    """A TIFF/EXIF block with IFD0, an optional Exif sub-IFD and an optional GPS IFD.

    Values are dummy bytes: the check looks at which tags are present, not at their values.
    """
    ifd0 = list(ifd0)
    offset = 8 + 2 + 12 * (len(ifd0) + bool(exif) + bool(gps)) + 4
    if exif:
        ifd0.append((cps.EXIF_IFD_TAG, 4, 1, struct.pack(order + "I", offset)))
        offset += 2 + 12 * len(exif) + 4
    if gps:
        ifd0.append((cps.GPS_IFD_TAG, 4, 1, struct.pack(order + "I", offset)))
    out = (b"II" if order == "<" else b"MM") + struct.pack(order + "HI", 42, 8)
    out += _ifd(ifd0, order)
    if exif:
        out += _ifd(exif, order)
    if gps:
        out += _ifd(gps, order)
    return out


def _segment(marker, payload):
    return bytes([0xFF, marker]) + struct.pack(">H", len(payload) + 2) + payload


def jpeg_bytes(*segments):
    """SOI, the given segments, a start of scan with a few bytes of scan data, EOI."""
    jfif = _segment(0xE0, b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00")
    sos = _segment(0xDA, b"\x01\x01\x00\x00\x3f\x00") + b"\x12\x34\x56"
    return b"\xff\xd8" + jfif + b"".join(segments) + sos + b"\xff\xd9"


def exif_segment(tiff):
    return _segment(0xE1, cps.EXIF_HEADER + tiff)


def _chunk(ctype, data):
    return struct.pack(">I", len(data)) + ctype + data + struct.pack(">I", zlib.crc32(ctype + data))


def png_bytes(*chunks):
    """A 1x1 grayscale PNG with the given chunks before the image data."""
    ihdr = _chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 0, 0, 0, 0))
    idat = _chunk(b"IDAT", zlib.compress(b"\x00\x00"))
    return b"\x89PNG\r\n\x1a\n" + ihdr + b"".join(chunks) + idat + _chunk(b"IEND", b"")


def png_text(keyword, text):
    return _chunk(b"tEXt", keyword.encode("latin-1") + b"\x00" + text.encode("latin-1"))


def raw_profile(tiff):
    """The value ImageMagick writes for the PNG text keyword "Raw profile type exif"."""
    data = cps.EXIF_HEADER + tiff
    hexdata = data.hex()
    lines = "\n".join(hexdata[i : i + 72] for i in range(0, len(hexdata), 72))
    return f"\nexif\n{len(data):8d}\n{lines}\n"


def write_and_scan(tmp_path, name, data):
    path = tmp_path / name
    path.write_bytes(data)
    return cps.scan_image(path.read_bytes())


GPS_TIFF = tiff_bytes(ifd0=[ORIENTATION], gps=[GPS_LATITUDE_REF])
DATE_CAMERA_TIFF = tiff_bytes(ifd0=[MAKE, MODEL, ORIENTATION], exif=[DATE_TIME_ORIGINAL])


@pytest.mark.parametrize("order", ["<", ">"])
def test_jpeg_with_gps_is_a_finding(tmp_path, order):
    tiff = tiff_bytes(ifd0=[ORIENTATION], gps=[GPS_LATITUDE_REF], order=order)
    reasons = write_and_scan(tmp_path, "gps.jpg", jpeg_bytes(exif_segment(tiff)))
    assert reasons == [cps.GPS_FINDING]


def test_jpeg_with_date_and_camera_is_a_finding(tmp_path):
    reasons = write_and_scan(tmp_path, "camera.jpg", jpeg_bytes(exif_segment(DATE_CAMERA_TIFF)))
    assert reasons == sorted([cps.CAMERA_FINDING, cps.DATE_FINDING])


def test_jpeg_with_date_only_is_a_finding(tmp_path):
    tiff = tiff_bytes(exif=[DATE_TIME_ORIGINAL])
    assert write_and_scan(tmp_path, "date.jpg", jpeg_bytes(exif_segment(tiff))) == [
        cps.DATE_FINDING
    ]


def test_jpeg_without_metadata_passes(tmp_path):
    assert write_and_scan(tmp_path, "clean.jpg", jpeg_bytes()) == []


def test_jpeg_with_orientation_only_passes(tmp_path):
    tiff = tiff_bytes(ifd0=[ORIENTATION])
    assert write_and_scan(tmp_path, "orient.jpg", jpeg_bytes(exif_segment(tiff))) == []


def test_jpeg_xmp_with_gps_is_a_finding(tmp_path):
    xmp = (
        b"http://ns.adobe.com/xap/1.0/\x00<x:xmpmeta><rdf:Description "
        b'exif:GPSLatitude="12,30.0N"/></x:xmpmeta>'
    )
    assert write_and_scan(tmp_path, "xmp.jpg", jpeg_bytes(_segment(0xE1, xmp))) == [cps.GPS_FINDING]


def test_jpeg_embedded_image_with_gps_is_a_finding(tmp_path):
    # A second JPEG appended after the main image, as in MPF files written by phones.
    data = jpeg_bytes() + jpeg_bytes(exif_segment(GPS_TIFF))
    assert write_and_scan(tmp_path, "mpf.jpg", data) == [cps.GPS_FINDING]


def test_truncated_exif_is_a_finding(tmp_path):
    tiff = DATE_CAMERA_TIFF[:20]  # header and IFD0 count, entries cut off
    reasons = write_and_scan(tmp_path, "cut.jpg", jpeg_bytes(exif_segment(tiff)))
    assert reasons == [cps.UNREADABLE_FINDING]


def test_truncated_jpeg_is_a_finding(tmp_path):
    data = jpeg_bytes(exif_segment(GPS_TIFF))[:30]
    assert cps.UNREADABLE_FINDING in write_and_scan(tmp_path, "cut2.jpg", data)


def test_png_exif_chunk_with_gps_is_a_finding(tmp_path):
    reasons = write_and_scan(tmp_path, "gps.png", png_bytes(_chunk(b"eXIf", GPS_TIFF)))
    assert reasons == [cps.GPS_FINDING]


def test_png_raw_profile_is_a_finding(tmp_path):
    chunk = png_text("Raw profile type exif", raw_profile(DATE_CAMERA_TIFF))
    reasons = write_and_scan(tmp_path, "raw.png", png_bytes(chunk))
    assert reasons == sorted([cps.CAMERA_FINDING, cps.DATE_FINDING])


def test_png_compressed_xmp_with_camera_is_a_finding(tmp_path):
    xmp = zlib.compress(b'<x:xmpmeta><rdf:Description tiff:Model="X"/></x:xmpmeta>')
    chunk = _chunk(b"iTXt", b"XML:com.adobe.xmp\x00\x01\x00\x00\x00" + xmp)
    assert write_and_scan(tmp_path, "xmp.png", png_bytes(chunk)) == [cps.CAMERA_FINDING]


@pytest.mark.parametrize(
    ("keyword", "reason"),
    [
        ("exif:GPSLatitude", cps.GPS_FINDING),
        ("exif:DateTimeOriginal", cps.DATE_FINDING),
        ("exif:Model", cps.CAMERA_FINDING),
    ],
)
def test_png_imagemagick_exif_keywords_are_findings(tmp_path, keyword, reason):
    chunk = png_text(keyword, "1")
    assert write_and_scan(tmp_path, "im.png", png_bytes(chunk)) == [reason]


def test_png_creation_time_is_a_finding(tmp_path):
    chunk = png_text("Creation Time", "2026:01:01 00:00:00")
    assert write_and_scan(tmp_path, "ctime.png", png_bytes(chunk)) == [cps.DATE_FINDING]


def test_png_software_and_conversion_dates_pass(tmp_path):
    chunks = [
        png_text("Software", "Matplotlib version3.9.0, https://matplotlib.org/"),
        png_text("date:create", "2026-01-01T00:00:00+00:00"),
        png_text("date:modify", "2026-01-01T00:00:00+00:00"),
        png_text("date:timestamp", "2026-01-01T00:00:00+00:00"),
        png_text("exif:Orientation", "1"),
    ]
    assert write_and_scan(tmp_path, "plot.png", png_bytes(*chunks)) == []


def test_webp_exif_with_gps_is_a_finding(tmp_path):
    exif = b"EXIF" + struct.pack("<I", len(GPS_TIFF)) + GPS_TIFF + b"\0" * (len(GPS_TIFF) & 1)
    data = b"RIFF" + struct.pack("<I", 4 + len(exif)) + b"WEBP" + exif
    assert write_and_scan(tmp_path, "gps.webp", data) == [cps.GPS_FINDING]


def test_tiff_with_camera_is_a_finding(tmp_path):
    data = tiff_bytes(ifd0=[MAKE, ORIENTATION])
    assert write_and_scan(tmp_path, "camera.tif", data) == [cps.CAMERA_FINDING]


def test_unknown_image_format_is_a_finding(tmp_path):
    assert write_and_scan(tmp_path, "fake.png", b"not an image") == [cps.UNKNOWN_FORMAT_FINDING]


def test_tracked_images_pass():
    root = Path(__file__).resolve().parents[1]
    images = [p for p in cps.tracked_files(root) if p.suffix.lower() in cps.IMAGE_SUFFIXES]
    assert images
    for path in images:
        assert cps.scan_image(path.read_bytes()) == [], path.name
