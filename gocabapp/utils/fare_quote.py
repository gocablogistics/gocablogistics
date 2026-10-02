"""Locks the price a rider was shown.

The estimate endpoint signs {pickup, destination, fare} into a short-lived
quote; booking hands it back, so the fare charged is the fare shown even if
surge pricing or the route calculation moved in between. Signed (not stored)
so the estimate endpoint, which is public, doesn't need to write anything.
"""
from __future__ import annotations

from django.conf import settings
from django.core import signing
from ninja.errors import HttpError

_SALT = "gocab.fare-quote"


def _max_age() -> int:
    return getattr(settings, "FARE_QUOTE_MAX_AGE_SECONDS", 15 * 60)


def make_fare_quote(pickup: str, destination: str, fare: float, vehicle_type: str) -> str:
    return signing.dumps(
        {"p": pickup, "d": destination, "f": float(fare), "v": vehicle_type}, salt=_SALT
    )


def resolve_fare(
    quote: str | None, pickup: str, destination: str, vehicle_type: str, fresh_fare: float
) -> float:
    """The fare to charge. Falls back to the freshly computed fare when there's
    no usable quote (old clients, tampering, a different address or vehicle
    type than what was quoted). If a genuine quote has expired AND the price
    has since changed, the rider is asked to re-estimate rather than silently
    charged a different amount."""
    if not quote:
        return fresh_fare
    try:
        data = signing.loads(quote, salt=_SALT, max_age=_max_age())
    except signing.SignatureExpired:
        try:
            data = signing.loads(quote, salt=_SALT)
        except signing.BadSignature:
            return fresh_fare
        if data.get("p") != pickup or data.get("d") != destination or data.get("v") != vehicle_type:
            return fresh_fare
        if abs(float(data["f"]) - float(fresh_fare)) < 1:
            return float(data["f"])
        raise HttpError(409, "Prices have changed since your estimate. Please get a new estimate.")
    except signing.BadSignature:
        return fresh_fare

    if data.get("p") != pickup or data.get("d") != destination or data.get("v") != vehicle_type:
        return fresh_fare
    return float(data["f"])
