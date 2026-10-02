"""Lets a ride's recipient (recipient_phone_number — the person actually
getting the package, who has no GoCab account at all) watch it arrive
without logging in, same pattern as Uber's "share my trip".

Signed, not stored — same reasoning as fare_quote.py and payment_confirm.py:
the public tracking endpoint doesn't need a DB write just to mint one.
Only ever grants read access to a ride's live position/status, nothing
financial or account-identifying, so a generous max_age is fine; it's not
guarding anything sensitive enough to need a short fuse.
"""
from __future__ import annotations

from django.core import signing

_SALT = "gocab.ride-tracking"
_MAX_AGE_SECONDS = 24 * 60 * 60  # a day comfortably covers any real delivery


def make_tracking_token(ride_id: int) -> str:
    return signing.dumps({"ride_id": ride_id}, salt=_SALT)


def resolve_tracking_ride_id(token: str) -> int | None:
    try:
        data = signing.loads(token, salt=_SALT, max_age=_MAX_AGE_SECONDS)
    except signing.BadSignature:
        return None
    ride_id = data.get("ride_id")
    return ride_id if isinstance(ride_id, int) else None
