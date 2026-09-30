import importlib.util
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
