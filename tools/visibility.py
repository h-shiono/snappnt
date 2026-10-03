"""Elevation and azimuth of satellites over time, from a TLE file, for one receiver position.

The receiver position is given on the command line only and is never written to a file by
this tool; the output CSV holds times, satellite names and look angles, not the position.

    uv sync --extra sky
    uv run python tools/visibility.py --tle tests/data/navic_celestrak_2026-10-03.tle \\
        --lat-deg 13.0 --lon-deg 77.6 --hours 24 --step-min 10 -o out/visibility.csv

Propagation uses the SGP4 model (``sgp4`` package, optional extra ``sky``). SGP4 gives
positions in the TEME frame; they are rotated to an Earth-fixed frame by the Greenwich mean
sidereal time (IAU 1982 model). Polar motion and the difference between UT1 and UTC are
ignored; together they change the look angles by far less than 0.01 degree, which is below
the accuracy of a TLE.

The coordinate conversions do not need ``sgp4`` and can be used and tested on their own.
"""

from __future__ import annotations

import argparse
import csv
import math
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np

# WGS-84 ellipsoid
WGS84_A_M = 6378137.0
WGS84_F = 1.0 / 298.257223563
WGS84_E2 = WGS84_F * (2.0 - WGS84_F)

CSV_COLUMNS = ["time_utc", "name", "norad_id", "elevation_deg", "azimuth_deg", "range_m"]

# Own choice, not a source value: SGP4 does not model station keeping, so the predicted
# position of a geostationary satellite drifts away from the real one as the TLE ages.
# A warning is printed when the computed times are further than this from the TLE epoch.
MAX_TLE_AGE_DAYS = 7.0


@dataclass(frozen=True)
class Tle:
    name: str
    line1: str
    line2: str

    @property
    def norad_id(self) -> int:
        return int(self.line1[2:7])

    @property
    def epoch(self) -> datetime:
        """Epoch from line 1: two-digit year (57-99 -> 19xx) and day of year with fraction."""
        yy = int(self.line1[18:20])
        year = 1900 + yy if yy >= 57 else 2000 + yy
        day = float(self.line1[20:32])
        return datetime(year, 1, 1, tzinfo=UTC) + timedelta(days=day - 1.0)


@dataclass(frozen=True)
class LookAngles:
    elevation_deg: float
    azimuth_deg: float  # clockwise from north, 0 to 360
    range_m: float


def read_tle(path: Path) -> list[Tle]:
    """Read a three-line TLE file (name line, line 1, line 2), as served by CelesTrak.

    Lines starting with ``#`` and blank lines are skipped.
    """
    lines = [
        ln.rstrip()
        for ln in path.read_text().splitlines()
        if ln.strip() and not ln.lstrip().startswith("#")
    ]
    out = []
    i = 0
    while i < len(lines):
        if lines[i].startswith("1 ") and i + 1 < len(lines) and lines[i + 1].startswith("2 "):
            name, l1, l2 = lines[i][2:7].strip(), lines[i], lines[i + 1]
            i += 2
        elif i + 2 < len(lines) and lines[i + 1].startswith("1 ") and lines[i + 2].startswith("2 "):
            name, l1, l2 = lines[i].strip(), lines[i + 1], lines[i + 2]
            i += 3
        else:
            raise ValueError(f"{path}: cannot read a TLE at line {i + 1}: {lines[i]!r}")
        out.append(Tle(name, l1, l2))
    return out


def geodetic_to_ecef(lat_deg: float, lon_deg: float, height_m: float) -> np.ndarray:
    """WGS-84 geodetic latitude, longitude and ellipsoidal height to ECEF metres."""
    lat, lon = math.radians(lat_deg), math.radians(lon_deg)
    n = WGS84_A_M / math.sqrt(1.0 - WGS84_E2 * math.sin(lat) ** 2)
    return np.array(
        [
            (n + height_m) * math.cos(lat) * math.cos(lon),
            (n + height_m) * math.cos(lat) * math.sin(lon),
            (n * (1.0 - WGS84_E2) + height_m) * math.sin(lat),
        ]
    )


def look_angles(
    observer_ecef_m: np.ndarray, lat_deg: float, lon_deg: float, satellite_ecef_m: np.ndarray
) -> LookAngles:
    """Elevation, azimuth and range from an observer to a satellite.

    ``lat_deg`` and ``lon_deg`` define the local vertical (east-north-up frame); for an
    observer from :func:`geodetic_to_ecef` they are its geodetic latitude and longitude.
    """
    lat, lon = math.radians(lat_deg), math.radians(lon_deg)
    d = np.asarray(satellite_ecef_m, dtype=float) - np.asarray(observer_ecef_m, dtype=float)
    east = -math.sin(lon) * d[0] + math.cos(lon) * d[1]
    north = (
        -math.sin(lat) * math.cos(lon) * d[0]
        - math.sin(lat) * math.sin(lon) * d[1]
        + math.cos(lat) * d[2]
    )
    up = (
        math.cos(lat) * math.cos(lon) * d[0]
        + math.cos(lat) * math.sin(lon) * d[1]
        + math.sin(lat) * d[2]
    )
    rng = float(np.linalg.norm(d))
    el = math.degrees(math.asin(up / rng))
    az = math.degrees(math.atan2(east, north)) % 360.0
    return LookAngles(el, az, rng)


def julian_date(t: datetime) -> float:
    """Julian date of a timezone-aware datetime (UTC scale)."""
    t = t.astimezone(UTC)
    j2000 = datetime(2000, 1, 1, 12, tzinfo=UTC)
    return 2451545.0 + (t - j2000) / timedelta(days=1)


def gmst_rad(jd_ut1: float) -> float:
    """Greenwich mean sidereal time, IAU 1982 model (as used with SGP4), in radians."""
    tu = (jd_ut1 - 2451545.0) / 36525.0
    seconds = (
        67310.54841 + (876600.0 * 3600.0 + 8640184.812866) * tu + 0.093104 * tu**2 - 6.2e-6 * tu**3
    )
    return math.radians((seconds % 86400.0) / 240.0)


def teme_to_ecef(r_teme_m: np.ndarray, jd_ut1: float) -> np.ndarray:
    """Rotate a TEME position to an Earth-fixed frame (polar motion ignored)."""
    g = gmst_rad(jd_ut1)
    x, y, z = r_teme_m
    return np.array(
        [math.cos(g) * x + math.sin(g) * y, -math.sin(g) * x + math.cos(g) * y, z], dtype=float
    )


def subsatellite_lon_deg(satellite_ecef_m: np.ndarray) -> float:
    """Geocentric longitude of a satellite, -180 to 180 degrees."""
    return math.degrees(math.atan2(satellite_ecef_m[1], satellite_ecef_m[0]))


def satellite_ecef_m(tle: Tle, t: datetime) -> np.ndarray:
    """ECEF position of a satellite at time t, by SGP4. Needs the ``sky`` extra."""
    try:
        from sgp4.api import Satrec
    except ImportError as e:  # pragma: no cover - depends on the environment
        raise SystemExit("sgp4 is not installed: run `uv sync --extra sky`") from e
    sat = Satrec.twoline2rv(tle.line1, tle.line2)
    jd = julian_date(t)
    jd_int = math.floor(jd - 0.5) + 0.5
    err, r_km, _v = sat.sgp4(jd_int, jd - jd_int)
    if err != 0:
        raise ValueError(f"SGP4 error {err} for {tle.name} at {t.isoformat()}")
    return teme_to_ecef(np.array(r_km) * 1e3, jd)


def track(
    tles: list[Tle],
    lat_deg: float,
    lon_deg: float,
    height_m: float,
    start: datetime,
    duration_s: float,
    step_s: float,
) -> list[dict]:
    """Rows of look angles for each satellite at each time step (start to start + duration)."""
    obs = geodetic_to_ecef(lat_deg, lon_deg, height_m)
    n = int(math.floor(duration_s / step_s)) + 1
    # Whole seconds unless the step or the start needs a fraction, so that no two rows of
    # one satellite share a time stamp.
    time_format = (
        "%Y-%m-%dT%H:%M:%S.%fZ"
        if step_s != math.floor(step_s) or start.microsecond != 0
        else "%Y-%m-%dT%H:%M:%SZ"
    )
    rows = []
    for k in range(n):
        t = start + timedelta(seconds=k * step_s)
        for tle in tles:
            la = look_angles(obs, lat_deg, lon_deg, satellite_ecef_m(tle, t))
            rows.append(
                {
                    "time_utc": t.astimezone(UTC).strftime(time_format),
                    "name": tle.name,
                    "norad_id": tle.norad_id,
                    "elevation_deg": round(la.elevation_deg, 3),
                    "azimuth_deg": round(la.azimuth_deg, 3),
                    "range_m": round(la.range_m, 1),
                }
            )
    return rows


def summary(rows: list[dict], min_elevation_deg: float) -> list[str]:
    """One line per satellite: minimum and maximum elevation and time above the mask."""
    lines = []
    for name in dict.fromkeys(r["name"] for r in rows):
        el = np.array([r["elevation_deg"] for r in rows if r["name"] == name])
        above = float(np.mean(el >= min_elevation_deg)) * 100.0
        lines.append(
            f"{name}: elevation {el.min():.1f} to {el.max():.1f} deg, "
            f"{above:.0f} % of samples at or above {min_elevation_deg:g} deg"
        )
    return lines


def stale_tles(
    tles: list[Tle], start: datetime, end: datetime, max_days: float = MAX_TLE_AGE_DAYS
) -> list[tuple[Tle, float]]:
    """TLEs whose epoch is more than max_days from start or end, with that distance in days."""
    out = []
    for tle in tles:
        days = max(abs(start - tle.epoch), abs(end - tle.epoch)) / timedelta(days=1)
        if days > max_days:
            out.append((tle, days))
    return out


def _parse_time(s: str) -> datetime:
    t = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return t if t.tzinfo else t.replace(tzinfo=UTC)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--tle", type=Path, required=True, help="three-line TLE file")
    p.add_argument("--lat-deg", type=float, required=True, help="geodetic latitude (WGS-84)")
    p.add_argument("--lon-deg", type=float, required=True, help="longitude, east positive")
    p.add_argument("--height-m", type=float, default=0.0, help="ellipsoidal height")
    p.add_argument("--start", type=_parse_time, help="UTC start, ISO 8601 (default: now)")
    p.add_argument("--hours", type=float, default=24.0)
    p.add_argument("--step-min", type=float, default=10.0)
    p.add_argument("--name", action="append", help="keep satellites whose name contains this")
    p.add_argument(
        "--min-elevation-deg",
        type=float,
        default=5.0,
        help="elevation mask for the summary (the ICD power levels assume more than 5 deg)",
    )
    p.add_argument("-o", "--output", type=Path, help="CSV file (default: stdout)")
    a = p.parse_args(argv)

    for opt in ("lat_deg", "lon_deg", "height_m", "hours", "step_min", "min_elevation_deg"):
        if not math.isfinite(getattr(a, opt)):
            p.error(f"--{opt.replace('_', '-')} must be a finite number")
    if not -90.0 <= a.lat_deg <= 90.0:
        p.error("--lat-deg must be between -90 and 90")
    if a.hours < 0 or a.step_min <= 0:
        p.error("--hours must be >= 0 and --step-min > 0")
    tles = read_tle(a.tle)
    if a.name:
        tles = [t for t in tles if any(s.lower() in t.name.lower() for s in a.name)]
    if not tles:
        p.error("no satellite in the TLE file matches")
    start = a.start or datetime.now(UTC)
    rows = track(tles, a.lat_deg, a.lon_deg, a.height_m, start, a.hours * 3600.0, a.step_min * 60.0)

    if a.output:
        a.output.parent.mkdir(parents=True, exist_ok=True)
        f = a.output.open("w", newline="")
    else:
        f = sys.stdout
    try:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    finally:
        if a.output:
            f.close()
    for tle in tles:
        print(f"{tle.name}: TLE epoch {tle.epoch:%Y-%m-%d %H:%M} UTC", file=sys.stderr)
    for line in summary(rows, a.min_elevation_deg):
        print(line, file=sys.stderr)
    end = start + timedelta(hours=a.hours)
    for tle, days in stale_tles(tles, start, end):
        print(
            f"warning: {tle.name}: computed times are up to {days:.1f} days from the TLE "
            f"epoch (more than {MAX_TLE_AGE_DAYS:g}); download a current TLE file",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
