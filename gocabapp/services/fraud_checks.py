"""
Lightweight abuse controls: excessive cancellations, either side, throttle
new matching until the rolling window clears. Not a full fraud-scoring
system — just the cheap, real checks that don't need device fingerprinting
or ML to be worth having.
"""
from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import User
from django.utils import timezone

from ..models import DriverCancellation, RideRequest

CANCELLATION_WINDOW = timedelta(hours=24)


def rider_cancellation_count(user: User) -> int:
    since = timezone.now() - CANCELLATION_WINDOW
    return RideRequest.objects.filter(
        passenger=user, status="cancelled", cancelled_at__gte=since
    ).count()


def is_rider_throttled(user: User) -> bool:
    return rider_cancellation_count(user) >= settings.RIDER_CANCELLATION_LIMIT


def driver_cancellation_count(user: User) -> int:
    since = timezone.now() - CANCELLATION_WINDOW
    return DriverCancellation.objects.filter(driver=user, cancelled_at__gte=since).count()


def is_driver_throttled(user: User) -> bool:
    return driver_cancellation_count(user) >= settings.DRIVER_CANCELLATION_LIMIT


def has_disputed_unpaid_ride(user: User) -> bool:
    """Blocks new ride requests only once an admin has actually reviewed a
    non-payment report and chosen to flag the account (payment_status ->
    "disputed" via PaymentDisputeAdmin.flag_rider) — a freshly filed report
    (payment_status == "reported") does NOT block on its own, since either
    side could file one falsely or out of spite and a human should look at
    it first. Once flagged, this is the only real lever available for a
    rider who simply doesn't pay; no API call can force a cash handover."""
    return RideRequest.objects.filter(passenger=user, payment_status="disputed").exists()


# Payment states of a finished trip that still owe money. "reported" is
# included deliberately: a driver's non-payment report used to leave a ride
# invisible to both this block AND /rides/active's own lookup — the rider
# could log back in, see nothing owing, and just book again with zero
# consequence. It's the honest thing to do regardless of who's "right": the
# rider genuinely hasn't had a confirmed payment recorded yet, exactly like
# a plain unpaid ride, so it's held the same way — and paying it for real
# is what actually resolves the report (see payment_service's
# _apply_verified_online_payment / confirm_cash_payment), no admin needed
# unless the rider disputes the report itself. Deliberately NOT "disputed" —
# that state means an admin already reviewed and is actively adjudicating,
# which is a different, human-in-the-loop situation on purpose.
UNPAID_PAYMENT_STATUSES = ["pending", "failed", "reported"]


def get_unpaid_completed_ride(user: User) -> RideRequest | None:
    """The rider's most recent finished trip that hasn't been paid for.
    GoCab charges after the trip, so without this a rider could complete a
    ride, never tap Pay, and just book again — the driver only gets paid once
    the rider does. New bookings are held until this is settled."""
    return (
        RideRequest.objects.filter(
            passenger=user,
            status="completed",
            payment_status__in=UNPAID_PAYMENT_STATUSES,
        )
        .order_by("-completed_at")
        .first()
    )


def is_cash_debt_blocked(user: User) -> bool:
    """GoCab never touches cash directly, so its commission on a cash ride
    is tracked as debt (Driver.cash_debt) rather than collected at payment
    time — this is what actually forces settlement instead of letting it
    grow forever. See services/cash_debt_service.py."""
    driver = getattr(user, "driver", None)
    return bool(driver) and driver.cash_debt >= settings.CASH_DEBT_BLOCK_THRESHOLD


def is_rider_flagged(user: User) -> bool:
    """Mirrors is_driver_flagged, other direction — blocks a rider from
    booking once an admin has flagged their account (PaymentDisputeAdmin.
    flag_rider), or once RIDER_NONPAYMENT_AUTO_FLAG_COUNT is crossed
    automatically (see payment_service.report_nonpayment)."""
    rider = getattr(user, "rider", None)
    return bool(rider) and rider.is_flagged


def is_driver_flagged(user: User) -> bool:
    """Mirrors has_disputed_unpaid_ride, other direction — blocks a driver
    from going online only once an admin has reviewed a rider's report and
    chosen to flag them (PaymentDisputeAdmin.flag_driver). Filing the
    report alone (see payment_service.report_driver) never sets this."""
    driver = getattr(user, "driver", None)
    return bool(driver) and driver.is_flagged
