"""Live "your driver arrives in N min" for the rider.

The base estimate is the same formula the app already uses to decide which
rides a driver can see (fare_pricing.estimate_pickup_minutes), recomputed from
the driver's latest position — so it counts down smoothly as they approach.
On top of that, a traffic-aware Google Distance Matrix reading is used to
calibrate it, but only occasionally (cached per ride) so a driver pinging
every 15 seconds never means a paid Google call every 15 seconds.
"""
from __future__ import annotations

import logging
import math

import googlemaps
from django.conf import settings
from django.core.cache import cache

from ..utils.distance_utils import detect_city, haversine_km
from ..utils.fare_pricing import estimate_pickup_minutes

logger = logging.getLogger(__name__)

# Within this distance of the pickup point the driver is treated as arrived.
ARRIVED_KM = 0.08
# How long one Google reading is reused before asking again.
CALIBRATION_TTL_SECONDS = 90
# Keeps one odd reading (a road closure, a GPS jump) from producing an absurd ETA.
_RATIO_MIN, _RATIO_MAX = 0.6, 3.0

_client: googlemaps.Client | None = None


def _gmaps() -> googlemaps.Client:
    # Its own client with short timeouts: the shared one has none, and this runs
    # inside the driver's location request, which must never hang on Google.
    global _client
    if _client is None:
        _client = googlemaps.Client(
            key=settings.GOOGLE_MAPS_API_KEY,
            connect_timeout=3, read_timeout=3, retry_timeout=4,
        )
    return _client


def _traffic_ratio(ride_id: int, d_lat: float, d_lng: float, p_lat: float, p_lng: float,
                   base_minutes: float, allow_google_call: bool) -> float:
    """Google's traffic-aware minutes divided by the formula's minutes, cached."""
    key = f"pickup_eta_ratio_{ride_id}"
    cached = cache.get(key)
    if cached is not None:
        return cached
    if not allow_google_call or base_minutes < 1:
        return 1.0

    ratio = 1.0
    try:
        result = _gmaps().distance_matrix(
            origins=[(d_lat, d_lng)], destinations=[(p_lat, p_lng)],
            mode="driving", units="metric",
            departure_time="now", traffic_model="best_guess",
        )
        element = result["rows"][0]["elements"][0]
        if result.get("status") == "OK" and element.get("status") == "OK":
            seconds = (element.get("duration_in_traffic") or element["duration"])["value"]
            ratio = min(max((seconds / 60) / base_minutes, _RATIO_MIN), _RATIO_MAX)
    except Exception:
        logger.warning("Pickup ETA calibration failed for ride=%s", ride_id, exc_info=True)
    # Cached even on failure, so a Google outage doesn't turn into a call per ping.
    cache.set(key, ratio, CALIBRATION_TTL_SECONDS)
    return ratio


def compute_pickup_eta(ride, driver_lat, driver_lng, allow_google_call: bool = True) -> dict | None:
    """{"eta_min": int, "distance_km": float} for a driver heading to pickup, or
    None when there isn't enough information (no coordinates yet).

    allow_google_call=False never touches the network — use it anywhere this
    runs inside a database transaction."""
    if None in (ride.pickup_latitude, ride.pickup_longitude, driver_lat, driver_lng):
        return None
    straight_km = haversine_km(driver_lat, driver_lng, ride.pickup_latitude, ride.pickup_longitude)
    if straight_km is None:
        return None
    if straight_km <= ARRIVED_KM:
        return {"eta_min": 0, "distance_km": straight_km}

    city = detect_city(ride.pickup_latitude, ride.pickup_longitude)
    base = estimate_pickup_minutes(straight_km, city)
    ratio = _traffic_ratio(
        ride.id, driver_lat, driver_lng, ride.pickup_latitude, ride.pickup_longitude,
        base, allow_google_call,
    )
    return {"eta_min": max(1, math.ceil(base * ratio)), "distance_km": round(straight_km, 1)}
