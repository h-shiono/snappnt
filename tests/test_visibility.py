"""tools/visibility.py. Expected values come from closed-form geometry or printed references,
not from the code under test.

The TLE fixture tests/data/navic_celestrak_2026-10-03.tle was downloaded from CelesTrak
(https://celestrak.org/NORAD/elements/gp.php?NAME=IRNSS&FORMAT=TLE) on 2026-10-03; the
epochs inside are 2026-09-30 to 2026-10-02 (day 273.5 to 275.9 of 2026).
"""

from __future__ import annotations

import csv
import importlib.util
import io
import math
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
TLE_PATH = ROOT / "tests" / "data" / "navic_celestrak_2026-10-03.tle"

_spec = importlib.util.spec_from_file_location("visibility", ROOT / "tools" / "visibility.py")
vis = importlib.util.module_from_spec(_spec)
sys.modules["visibility"] = vis
_spec.loader.exec_module(vis)

R_GEO_M = 42164.0e3  # geostationary orbit radius
R_SPHERE_M = 6378137.0


def _sphere_point(lat_deg: float, lon_deg: float, r_m: float) -> np.ndarray:
    lat, lon = math.radians(lat_deg), math.radians(lon_deg)
    return r_m * np.array(
        [math.cos(lat) * math.cos(lon), math.cos(lat) * math.sin(lon), math.sin(lat)]
    )


def _geo_elevation_closed_form(lat_deg: float, dlon_deg: float) -> float:
    # Spherical Earth: cos(gamma) = cos(lat) cos(dlon); el = atan((cos g - R/r) / sin g)
    cg = math.cos(math.radians(lat_deg)) * math.cos(math.radians(dlon_deg))
    sg = math.sqrt(1.0 - cg * cg)
    return math.degrees(math.atan2(cg - R_SPHERE_M / R_GEO_M, sg))


def test_geodetic_to_ecef_reference_points():
    assert vis.geodetic_to_ecef(0, 0, 0) == pytest.approx([6378137.0, 0, 0], abs=1e-6)
    assert vis.geodetic_to_ecef(0, 90, 100) == pytest.approx([0, 6378237.0, 0], abs=1e-6)
    # polar radius b = a (1 - f) = 6356752.314 m
    assert vis.geodetic_to_ecef(90, 0, 0) == pytest.approx([0, 0, 6356752.314], abs=1e-3)


def test_geo_overhead_is_zenith():
    obs = _sphere_point(0, 129.5, R_SPHERE_M)
    la = vis.look_angles(obs, 0, 129.5, _sphere_point(0, 129.5, R_GEO_M))
    assert la.elevation_deg == pytest.approx(90.0, abs=1e-9)
    assert la.range_m == pytest.approx(R_GEO_M - R_SPHERE_M)


@pytest.mark.parametrize(
    ("lat_deg", "dlon_deg"),
    [(0, 30), (0, -60), (35, 0), (35, -10), (13, -52), (-30, 40), (50, 70)],
)
def test_geo_elevation_matches_closed_form(lat_deg, dlon_deg):
    obs = _sphere_point(lat_deg, 100.0, R_SPHERE_M)
    sat = _sphere_point(0, 100.0 + dlon_deg, R_GEO_M)
    la = vis.look_angles(obs, lat_deg, 100.0, sat)
    assert la.elevation_deg == pytest.approx(
        _geo_elevation_closed_form(lat_deg, dlon_deg), abs=1e-9
    )


def test_azimuth_directions():
    sat = _sphere_point(0, 100.0, R_GEO_M)
    north_obs = vis.look_angles(_sphere_point(35, 100, R_SPHERE_M), 35, 100, sat)
    south_obs = vis.look_angles(_sphere_point(-35, 100, R_SPHERE_M), -35, 100, sat)
    west_obs = vis.look_angles(_sphere_point(0, 70, R_SPHERE_M), 0, 70, sat)
    assert north_obs.azimuth_deg == pytest.approx(180.0, abs=1e-9)
    assert south_obs.azimuth_deg == pytest.approx(0.0, abs=1e-9) or south_obs.azimuth_deg == (
        pytest.approx(360.0, abs=1e-9)
    )
    assert west_obs.azimuth_deg == pytest.approx(90.0, abs=1e-9)


def test_gmst_vallado_example():
    # Vallado, Fundamentals of Astrodynamics and Applications, Example 3-5:
    # 1992 August 20, 12:14 UT1 -> GMST = 152.578787810 deg
    jd = vis.julian_date(datetime(1992, 8, 20, 12, 14, tzinfo=UTC))
    assert math.degrees(vis.gmst_rad(jd)) == pytest.approx(152.578787810, abs=1e-6)


def test_julian_date_j2000():
    assert vis.julian_date(datetime(2000, 1, 1, 12, tzinfo=UTC)) == 2451545.0


def test_read_tle_fixture():
    tles = vis.read_tle(TLE_PATH)
    by_id = {t.norad_id: t.name for t in tles}
    assert by_id[56759] == "NVS-01 (IRNSS-1J)"
    assert len(tles) == 10


def test_read_tle_rejects_garbage(tmp_path):
    p = tmp_path / "bad.tle"
    p.write_text("not a tle\n")
    with pytest.raises(ValueError):
        vis.read_tle(p)


def test_nvs01_longitude_over_one_day():
    pytest.importorskip("sgp4")
    nvs01 = next(t for t in vis.read_tle(TLE_PATH) if t.norad_id == 56759)
    t0 = datetime(2026, 10, 3, tzinfo=UTC)
    lons = [
        vis.subsatellite_lon_deg(vis.satellite_ecef_m(nvs01, t0 + timedelta(hours=h)))
        for h in range(25)
    ]
    # ISRO: geostationary slot at 129.5 deg E (www.isro.gov.in/SatelliteNavigationServices.html)
    assert min(lons) > 129.0 and max(lons) < 130.0


def test_cli_csv(capsys):
    pytest.importorskip("sgp4")
    args = ["--tle", str(TLE_PATH), "--lat-deg", "0", "--lon-deg", "129.5"]
    args += ["--start", "2026-10-03T00:00:00Z", "--hours", "1", "--step-min", "30"]
    assert vis.main([*args, "--name", "NVS-01"]) == 0
    captured = capsys.readouterr()
    rows = list(csv.DictReader(io.StringIO(captured.out)))
    assert list(rows[0]) == vis.CSV_COLUMNS
    assert [r["time_utc"] for r in rows] == [
        "2026-10-03T00:00:00Z",
        "2026-10-03T00:30:00Z",
        "2026-10-03T01:00:00Z",
    ]
    # under the satellite (inclination about 2 deg): elevation close to 90 deg
    assert all(float(r["elevation_deg"]) > 85.0 for r in rows)
    assert "NVS-01" in captured.err


def test_cli_rejects_bad_latitude():
    with pytest.raises(SystemExit):
        vis.main(["--tle", str(TLE_PATH), "--lat-deg", "91", "--lon-deg", "0"])


@pytest.mark.parametrize(
    "extra",
    [
        ["--hours", "nan"],
        ["--hours", "inf"],
        ["--step-min", "nan"],
        ["--lon-deg", "nan"],
        ["--height-m", "inf"],
        ["--min-elevation-deg", "nan"],
    ],
)
def test_cli_rejects_non_finite(extra, capsys):
    base = ["--tle", str(TLE_PATH), "--lat-deg", "0", "--lon-deg", "129.5"]
    with pytest.raises(SystemExit) as e:
        vis.main([*base, *extra])
    assert e.value.code == 2
    assert "finite" in capsys.readouterr().err


def test_tle_epoch_from_line1():
    # NVS-01 line 1 epoch field "26275.91908652": 2026, day 275 = 2 October (2026 is not a
    # leap year; day 273 = 30 September), 0.91908652 day = 22:03:29.07
    nvs01 = next(t for t in vis.read_tle(TLE_PATH) if t.norad_id == 56759)
    assert abs(nvs01.epoch - datetime(2026, 10, 2, 22, 3, 29, 75000, tzinfo=UTC)) < timedelta(
        milliseconds=1
    )
    # two-digit years 57-99 belong to the 1900s
    old = vis.Tle("x", "1 00005U 58002B   99001.50000000" + " " * 38, "2 00005")
    assert old.epoch == datetime(1999, 1, 1, 12, tzinfo=UTC)


def test_stale_tles():
    nvs01 = next(t for t in vis.read_tle(TLE_PATH) if t.norad_id == 56759)
    e = nvs01.epoch
    assert vis.stale_tles([nvs01], e, e + timedelta(days=1)) == []
    assert vis.stale_tles([nvs01], e - timedelta(days=6), e + timedelta(days=6)) == []
    stale = vis.stale_tles([nvs01], e + timedelta(days=30), e + timedelta(days=31))
    assert [t.norad_id for t, _ in stale] == [56759]
    assert stale[0][1] == pytest.approx(31.0)


def test_cli_warns_on_old_tle(capsys):
    pytest.importorskip("sgp4")
    args = ["--tle", str(TLE_PATH), "--lat-deg", "0", "--lon-deg", "129.5", "--name", "NVS-01"]
    assert vis.main([*args, "--start", "2027-10-03T00:00:00Z", "--hours", "0"]) == 0
    err = capsys.readouterr().err
    assert "TLE epoch 2026-10-02 22:03 UTC" in err
    assert "warning: NVS-01" in err
    assert vis.main([*args, "--start", "2026-10-03T00:00:00Z", "--hours", "1"]) == 0
    assert "warning" not in capsys.readouterr().err


def test_cli_sub_second_steps_have_distinct_times(capsys):
    pytest.importorskip("sgp4")
    args = ["--tle", str(TLE_PATH), "--lat-deg", "0", "--lon-deg", "129.5", "--name", "NVS-01"]
    # step 0.005 min = 0.3 s over 0.0005 h = 1.8 s: 7 rows
    args += ["--start", "2026-10-03T00:00:00Z", "--hours", "0.0005", "--step-min", "0.005"]
    assert vis.main(args) == 0
    rows = list(csv.DictReader(io.StringIO(capsys.readouterr().out)))
    times = [r["time_utc"] for r in rows]
    assert len(times) == 7 and len(set(times)) == 7
    assert times[1] == "2026-10-03T00:00:00.300000Z"
