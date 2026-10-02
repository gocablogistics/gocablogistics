"""Proves "this browser really did just start paying for ride X" independent
of whichever account happens to be logged in by the time Paystack's redirect
lands back on the callback page.

Confirmed root cause of two real, verified-paid-on-Paystack rides (277, 278)
plus a third caught live (281) that all 404'd as "Ride not found": the rider
paid from one account, but another tab of the same browser did its own login
or background token refresh in the meantime — both tabs share one
localStorage slot — so by the time the full-page redirect back from Paystack
reloaded the app, a *different* account was the one actually logged in. The
ride and payment were always legitimate; only the ownership check on the way
back was wrong to rely on ambient session state for that.

This token is generated once, at /rides/{id}/pay time, and travels inside
the callback_url itself — so confirming payment no longer depends on the
JWT active in that tab still matching whoever originally paid.
"""
from __future__ import annotations

from django.core import signing

_SALT = "gocab.payment-confirm"
_MAX_AGE_SECONDS = 30 * 60  # generous — checkout + a slow bank/OTP step can take a while


def make_payment_confirm_token(ride_id: int) -> str:
    return signing.dumps({"ride_id": ride_id}, salt=_SALT)


def payment_confirm_token_matches(token: str | None, ride_id: int) -> bool:
    if not token:
        return False
    try:
        data = signing.loads(token, salt=_SALT, max_age=_MAX_AGE_SECONDS)
    except signing.BadSignature:
        return False
    return data.get("ride_id") == ride_id
