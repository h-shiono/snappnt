"""Doppler and Doppler rate of a LEO satellite pass, and the loss from ignoring the rate.

Pass model
----------
Circular orbit of radius ``R + h`` around a spherical, non-rotating Earth (``R`` = 6371 km)
with no atmosphere. The receiver is on the surface. ``max_elevation_deg`` is the elevation
at the closest approach; 90 degrees is an overhead pass. The satellite moves at the angular
rate ``omega = sqrt(mu / (R + h)^3)``.

With the satellite at angle ``theta = omega * t`` from the closest approach and ``gamma`` the
Earth-centre angle between the receiver and the satellite at the closest approach, the slant
range is::

    rho(t) = sqrt(r^2 + R^2 - 2 r R cos(gamma) cos(omega t))

The Doppler shift is ``-f * d(rho)/dt / c`` and the Doppler rate its time derivative. Time is
zero at the closest approach, negative while the satellite approaches (positive Doppler).
"""

from __future__ import annotations

import numpy as np
from scipy import special

EARTH_RADIUS_M = 6_371_000.0
EARTH_MU_M3PS2 = 3.986004418e14
SPEED_OF_LIGHT_MPS = 299_792_458.0


def leo_pass_doppler(
    carrier_hz: float,
    altitude_m: float,
    max_elevation_deg: float,
    time_from_closest_approach_s,
) -> tuple[np.ndarray, np.ndarray]:
    """Doppler shift (Hz) and Doppler rate (Hz/s) at the given times within a pass."""
    if altitude_m <= 0:
        raise ValueError(f"altitude_m must be positive, not {altitude_m}")
    if not 0.0 < max_elevation_deg <= 90.0:
        raise ValueError(f"max_elevation_deg must be in (0, 90], not {max_elevation_deg}")
    t = np.asarray(time_from_closest_approach_s, dtype=np.float64)
    big_r = EARTH_RADIUS_M
    r = big_r + altitude_m
    omega = np.sqrt(EARTH_MU_M3PS2 / r**3)
    el = np.radians(max_elevation_deg)
    # Earth-centre angle between receiver and satellite at the closest approach.
    cos_gamma = np.cos(np.arccos(big_r * np.cos(el) / r) - el)
    k = r * big_r * cos_gamma
    rho = np.sqrt(r**2 + big_r**2 - 2.0 * k * np.cos(omega * t))
    rho_dot = k * omega * np.sin(omega * t) / rho
    rho_ddot = k * omega**2 * np.cos(omega * t) / rho - rho_dot**2 / rho
    scale = -carrier_hz / SPEED_OF_LIGHT_MPS
    return scale * rho_dot, scale * rho_ddot


def rate_mismatch_loss_db(coherent_time_s: float, rate_error_hzps: float) -> float:
    """Power loss (dB, positive) from a Doppler-rate error over one coherent integration.

    The carrier frequency is assumed to be matched at the middle of the integration (the best
    frequency bin). The residual phase is ``pi * e * t^2`` for ``t`` from ``-T/2`` to ``T/2``
    with rate error ``e`` and coherent time ``T``. The normalised coherent sum is
    ``(C(x)^2 + S(x)^2) / x^2`` with the Fresnel integrals C, S and ``x = (T/2) sqrt(2 |e|)``.
    """
    x = 0.5 * coherent_time_s * np.sqrt(2.0 * abs(rate_error_hzps))
    if x < 1e-9:
        return 0.0
    s, c = special.fresnel(x)
    return float(-10.0 * np.log10((c**2 + s**2) / x**2))
