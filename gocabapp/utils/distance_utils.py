from __future__ import annotations

import logging
import math
from datetime import datetime

import googlemaps
from django.conf import settings
from django.core.cache import cache

from ..models import RideRequest
from .fare_pricing import estimate_pickup_time

logger = logging.getLogger(__name__)
gmaps = googlemaps.Client(key=settings.GOOGLE_MAPS_API_KEY)

# ---------------------------------------------------------------------------
# Constants — defined once at module level
# ---------------------------------------------------------------------------

CITY_BOUNDARIES: dict[str, dict] = {
    # min_lng widened from 3.0 to 2.6 (2026-09-30) — the old edge sat just
    # east of Badagry/Ibereko along the Lagos-Badagry Expressway, so a real
    # Lagos pickup out there was detected as "unknown" while its destination
    # further into the city detected as "lagos". _ride_qualifies requires
    # pickup/destination/driver to share one city label, so that mismatch
    # silently hid the ride from every driver, including one 0.55km from the
    # pickup point (ride #399). 2.6 reaches past Seme border, still short of
    # Benin's box (min_lng 5.5), so there's no overlap.
    "lagos":         {"min_lat": 6.3,  "max_lat": 6.7,  "min_lng": 2.6, "max_lng": 3.8},
    "benin":         {"min_lat": 6.2,  "max_lat": 6.4,  "min_lng": 5.5, "max_lng": 5.8},
    "ibadan":        {"min_lat": 7.3,  "max_lat": 7.5,  "min_lng": 3.8, "max_lng": 4.0},
    "abuja":         {"min_lat": 8.9,  "max_lat": 9.2,  "min_lng": 7.3, "max_lng": 7.6},
    "port harcourt": {"min_lat": 4.7,  "max_lat": 5.0,  "min_lng": 6.9, "max_lng": 7.1},
    "kano":          {"min_lat": 11.9, "max_lat": 12.1, "min_lng": 8.4, "max_lng": 8.6},
    "ilorin":        {"min_lat": 8.4,  "max_lat": 8.6,  "min_lng": 4.5, "max_lng": 4.7},
    "aba":           {"min_lat": 5.1,  "max_lat": 5.2,  "min_lng": 7.3, "max_lng": 7.4},
    "owerri":        {"min_lat": 5.4,  "max_lat": 5.5,  "min_lng": 7.0, "max_lng": 7.1},
}

CITY_DISTANCE_LIMITS: dict[str, dict] = {
    # Widened 2026-10-01 — a real pending ride (#401, Badagry pickup) sat
    # unmatched because the closest online driver was 10.74km away, just
    # outside the old 8km cap. Turns out that cap was mostly decorative:
    # estimate_pickup_time already gives 36min for an 8km pickup in Lagos's
    # slow 20km/h city-speed estimate, so the old 25min time cap was the
    # real (stricter) limit all along, rejecting anything past ~5.6km.
    # Raised both together — distance alone wouldn't have changed anything.
    "lagos":         {"max_pickup_distance": 12, "max_ride_distance": 25, "max_pickup_time": 50},
    "benin":         {"max_pickup_distance": 6,  "max_ride_distance": 20, "max_pickup_time": 20},
    "ibadan":        {"max_pickup_distance": 7,  "max_ride_distance": 22, "max_pickup_time": 22},
    "abuja":         {"max_pickup_distance": 10, "max_ride_distance": 30, "max_pickup_time": 25},
    "port harcourt": {"max_pickup_distance": 6,  "max_ride_distance": 18, "max_pickup_time": 20},
    "kano":          {"max_pickup_distance": 6,  "max_ride_distance": 20, "max_pickup_time": 20},
    "ilorin":        {"max_pickup_distance": 6,  "max_ride_distance": 20, "max_pickup_time": 20},
    "aba":           {"max_pickup_distance": 6,  "max_ride_distance": 20, "max_pickup_time": 20},
    "owerri":        {"max_pickup_distance": 6,  "max_ride_distance": 20, "max_pickup_time": 20},
    "default":       {"max_pickup_distance": 6,  "max_ride_distance": 20, "max_pickup_time": 20},
}

# ---------------------------------------------------------------------------
# City detection
# ---------------------------------------------------------------------------

def detect_city(lat: float, lng: float) -> str:
    for city, b in CITY_BOUNDARIES.items():
        if b["min_lat"] <= lat <= b["max_lat"] and b["min_lng"] <= lng <= b["max_lng"]:
            return city
    return "unknown"


def city_limits(lat: float, lng: float) -> dict:
    return CITY_DISTANCE_LIMITS.get(detect_city(lat, lng), CITY_DISTANCE_LIMITS["default"])

# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------

def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float | None:
    try:
        R = 6371
        dlat = math.radians(lat2 - lat1)
        dlng = math.radians(lng2 - lng1)
        a = (math.sin(dlat / 2) ** 2
             + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
             * math.sin(dlng / 2) ** 2)
        return round(R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)), 2)
    except Exception as e:
        logger.error("haversine_km error: %s", e)
        return None

# ---------------------------------------------------------------------------
# Google Maps calls (both cached)
# ---------------------------------------------------------------------------

def geocode(address: str) -> dict | None:
    key = f"geocode_{address}"
    cached = cache.get(key)
    if cached:
        return cached
    try:
        result = gmaps.geocode(address)
        if result:
            loc = result[0]["geometry"]["location"]
            coords = {"lat": loc["lat"], "lng": loc["lng"]}
            cache.set(key, coords, 3600)
            return coords
    except Exception as e:
        logger.error("geocode error for %r: %s", address, e)
    return None


def google_distance(origin: str, destination: str) -> tuple[float | None, float | None]:
    key = f"gdist_{origin}_{destination}"
    cached = cache.get(key)
    if cached:
        return cached["distance"], cached["duration"]
    try:
        result = gmaps.distance_matrix(
            origins=[origin],
            destinations=[destination],
            mode="driving",
            units="metric",
            departure_time=datetime.now(),
            traffic_model="best_guess",
        )
        if result["status"] != "OK":
            logger.error("Distance Matrix API error: %s", result.get("error_message"))
            return None, None
        element = result["rows"][0]["elements"][0]
        if element["status"] != "OK":
            logger.error("Distance Matrix element error: %s", element.get("status"))
            return None, None
        distance = element["distance"]["value"] / 1000
        duration = element["duration_in_traffic"]["value"] / 60
        cache.set(key, {"distance": distance, "duration": duration}, 900)
        return distance, duration
    except Exception as e:
        logger.error("google_distance error: %s", e)
        return None, None


def route_with_coords(
    origin: str, destination: str
) -> tuple[float | None, float | None, dict | None, dict | None]:
    """Return (distance_km, duration_min, pickup_coords, dest_coords)."""
    pickup_coords = geocode(origin)
    dest_coords = geocode(destination)

    if not pickup_coords or not dest_coords:
        logger.error("Could not geocode: origin=%r destination=%r", origin, destination)
        return None, None, None, None

    distance_km, duration_min = google_distance(origin, destination)

    # Sanity-check: driving distance shouldn't be less than half the straight line
    if distance_km and (straight := haversine_km(
        pickup_coords["lat"], pickup_coords["lng"],
        dest_coords["lat"], dest_coords["lng"],
    )):
        if distance_km < straight * 0.5:
            logger.warning(
                "Implausible driving distance (%skm) vs straight-line (%skm); using estimate",
                distance_km, straight,
            )
            distance_km = round(straight * 1.2, 2)
            duration_min = round((distance_km / 40) * 60, 1)

    return distance_km, duration_min, pickup_coords, dest_coords

# ---------------------------------------------------------------------------
# Nearby-ride filtering
# ---------------------------------------------------------------------------

def _ride_qualifies(
    driver_lat: float, driver_lng: float, driver_city: str,
    ride: RideRequest, max_distance: float, max_pickup_time: int,
) -> bool:
    dist = haversine_km(driver_lat, driver_lng, ride.pickup_latitude, ride.pickup_longitude)
    if dist is None or dist > max_distance:
        return False

    # Same-city check for both pickup and destination
    if detect_city(ride.pickup_latitude, ride.pickup_longitude) != driver_city:
        return False
    if detect_city(ride.destination_latitude, ride.destination_longitude) != driver_city:
        return False

    pickup_time = estimate_pickup_time(dist, driver_city)
    if pickup_time > max_pickup_time:
        return False

    ride.distance_from_driver = dist
    ride.estimated_pickup_time = pickup_time
    return True


def get_nearby_rides(driver_lat: float, driver_lng: float, driver_vehicle_type: str | None = None) -> list:
    if not driver_lat or not driver_lng:
        return []

    driver_city = detect_city(driver_lat, driver_lng)
    limits = CITY_DISTANCE_LIMITS.get(driver_city, CITY_DISTANCE_LIMITS["default"])
    max_distance = limits["max_pickup_distance"]
    max_pickup_time = limits["max_pickup_time"]

    pending = list(
        RideRequest.objects.filter(
            status="pending",
            driver__isnull=True,
            pickup_latitude__isnull=False,
            pickup_longitude__isnull=False,
            destination_latitude__isnull=False,
            destination_longitude__isnull=False,
            # A Bike-priced ride only goes to Bike drivers, and likewise for
            # Bicycle — they're no longer interchangeable now that they're
            # priced differently (see fare_pricing.VEHICLE_RATES). Optional
            # param (rather than required) so a caller that genuinely
            # doesn't know the driver's vehicle_type yet degrades to the
            # old any-vehicle behavior instead of erroring.
            **({"vehicle_type": driver_vehicle_type} if driver_vehicle_type else {}),
        ).select_related("passenger")
    )

    valid = [
        r for r in pending
        if _ride_qualifies(driver_lat, driver_lng, driver_city, r, max_distance, max_pickup_time)
    ]
    valid.sort(key=lambda r: r.distance_from_driver)

    logger.info("get_nearby_rides: %s/%s rides qualify for driver in %s", len(valid), len(pending), driver_city)
    return valid