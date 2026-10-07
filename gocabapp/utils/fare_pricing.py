from __future__ import annotations

import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# Keys match Driver.vehicle_type / RideRequest.vehicle_type exactly
# ("Bike"/"Bicycle", the same two values DriverRegisterIn already
# validates against) — one shared convention end to end instead of a
# second lowercase naming scheme just for pricing.
#
# "Bike" recalibrated 2026-09-30 against a real InDrive quote (a rider
# reported ₦4,900 on InDrive for a 28.66km/42.77min Lagos trip that GoCab
# priced at ₦9,306.53 — almost double). The old numbers (base ₦1000,
# ₦200/km, ₦10/min, under the old "standard" key that every booking used
# regardless of vehicle) were a car-class rate table never revisited after
# GoCab became bike/bicycle-only. These reproduce that same InDrive trip
# to within 0.3% (₦4,883.62) — see _surge_multiplier for the matching
# surge cut.
#
# "Bicycle" added the same day — until now EVERY ride was priced with the
# rates below regardless of which vehicle type a driver actually had, so a
# pedal bicycle earned exactly the same as a motorbike for the same trip.
# Priced ~20-23% below Bike (rounded to clean numbers, not an exact 25%),
# reflecting a bicycle courier's lower operating cost but real (if slower)
# delivery service. request_ride now requires the rider to choose one of
# these two at booking time, and get_nearby_rides only shows a ride to a
# driver whose own vehicle_type matches it.
VEHICLE_RATES: dict[str, dict] = {
    "Bike":    {"base": 500.0, "per_km": 130.0, "per_min": 5.0, "min_fare": 500.0},
    "Bicycle": {"base": 400.0, "per_km": 100.0, "per_min": 4.0, "min_fare": 400.0},
}

# Average city speeds in km/h — used for pickup-time estimates
CITY_SPEEDS: dict[str, int] = {
    "lagos": 20, "benin": 30, "ibadan": 25,
    "abuja": 35, "port harcourt": 25, "default": 25,
}

MAX_FARE = 30_000


# Platform commission is 20% — drivers keep the rest. Card-paid rides
# route this split into a real DriverPayout row (services/payout_service.py);
# cash rides never touch it since the driver already holds the full cash
# amount in hand.
DRIVER_EARNINGS_RATE = 0.80


def _surge_multiplier() -> float:
    # Cut 2026-09-30 alongside the VEHICLE_RATES recalibration above — the
    # old 1.3x weekday-rush / 1.2x weekend multipliers were stacking on top
    # of an already car-class rate table, which is most of why a real
    # booking came out almost double InDrive's quote for the same trip.
    # Weekend surge dropped entirely; weekday rush kept, much smaller, as
    # the one lever still available for genuine peak-demand pricing.
    now = datetime.now()
    weekday = now.weekday() < 5
    hour = now.hour
    if weekday and (7 <= hour <= 9 or 17 <= hour <= 19):
        return 1.1
    return 1.0


def calculate_ride_fare(
    distance_km: float,
    duration_min: float,
    vehicle_type: str = "Bike",
) -> dict | None:
    if not distance_km or not duration_min or distance_km <= 0 or duration_min <= 0:
        logger.warning("calculate_ride_fare: invalid inputs distance=%s duration=%s", distance_km, duration_min)
        return None

    rates = VEHICLE_RATES.get(vehicle_type) or VEHICLE_RATES["Bike"]
    surge = _surge_multiplier()

    # The total is rounded to the nearest ₦10 (2026-10-03): ₦10 is the
    # smallest amount a Nigerian bank transfer is matched on, so an odd
    # figure like ₦7,497 made the payer's transfer look like the wrong
    # amount and Paystack reversed it. Line items are whole naira, and the
    # rounding difference is absorbed into distance so they still add up.
    distance_fare = round(distance_km * rates["per_km"])
    time_fare = round(duration_min * rates["per_min"])
    subtotal = round((rates["base"] + distance_fare + time_fare) * surge)
    total = max(subtotal, round(rates["min_fare"]))
    if distance_km > 50:
        total = min(total, MAX_FARE)
    rounded_total = ((total + 5) // 10) * 10
    if rounded_total != total and total == subtotal and surge == 1.0:
        distance_fare += rounded_total - total
    total = rounded_total

    result = {
        "base_fare":        rates["base"],
        "distance_km":      round(distance_km, 2),
        "duration_min":     round(duration_min, 2),
        "distance_fare":    distance_fare,
        "time_fare":        time_fare,
        "surge_multiplier": surge,
        "total_fare":       total,
        "vehicle_type":     vehicle_type if vehicle_type in VEHICLE_RATES else "Bike",
        "currency":         "NGN",
    }
    logger.info("Fare: ₦%s for %.1fkm (%s)", result["total_fare"], distance_km, vehicle_type)
    return result


def estimate_pickup_minutes(distance_km: float, city: str) -> float:
    """
    Estimate pickup time in (fractional) minutes.
    Formula: travel time at city avg speed + 1.5 min/km traffic buffer.
    """
    speed = CITY_SPEEDS.get(city.lower(), CITY_SPEEDS["default"])
    travel_min = (distance_km / speed) * 60
    buffer_min = distance_km * 1.5   # ~1.5 extra min per km for traffic/stops
    return travel_min + buffer_min


def estimate_pickup_time(distance_km: float, city: str) -> int:
    """Whole-minute version, used to decide which rides a driver can see."""
    return round(estimate_pickup_minutes(distance_km, city))