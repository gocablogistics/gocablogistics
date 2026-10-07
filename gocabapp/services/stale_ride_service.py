"""Catches RideRequests that Django's own signals never resolve on their
own — see settings.STALE_PENDING_ALERT_MINUTES / STALE_ACCEPTED_TIMEOUT_MINUTES
/ STALE_STARTED_ALERT_MINUTES for the reasoning behind each window. Run
periodically via /internal/sweep-stale-rides (see api/main.py), not
in-process — nothing else in this app runs on a schedule."""
from __future__ import annotations

import logging
from datetime import timedelta

from django.conf import settings
from ..utils.branded_mail import send_branded_email
from django.utils import timezone

from ..models import RideRequest
from .driver_trip_service import run_driver_cancel_ride
from .fraud_checks import UNPAID_PAYMENT_STATUSES
from .push_service import send_push_to_user
from .ride_events import notify_rider

logger = logging.getLogger(__name__)


def _notify_admin_stale(ride: RideRequest, subject_suffix: str, body: str) -> None:
    """Mirrors payment_service._notify_admin_of_dispute's pattern — silently
    no-ops with no address configured; the ride is still fully visible in
    Django admin either way."""
    if not settings.ADMIN_NOTIFICATION_EMAIL:
        return

    admin_url = f"{settings.ADMIN_SITE_URL}/admin/gocabapp/riderequest/{ride.id}/change/"
    try:
        send_branded_email(
            subject=f"GoCab stale ride #{ride.id}, {subject_suffix}",
            to=[settings.ADMIN_NOTIFICATION_EMAIL],
            template_name="email/admin_alert.html",
            context={
                "heading": f"Stale ride #{ride.id}",
                "intro": subject_suffix[0].upper() + subject_suffix[1:] + ".",
                "note": body,
                "button_label": "Review ride",
                "button_url": admin_url,
            },
        )
    except Exception:
        # Never let a notification failure block the rest of the sweep.
        logger.exception("Failed to email admin about stale ride %s", ride.id)


def _sweep_unmatched_pending() -> int:
    """Case 1: nobody's accepted it after STALE_PENDING_ALERT_MINUTES.
    Used to be alert-only — a ride could sit "pending" forever with zero
    consequence, which is exactly what happened in practice. Now actually
    cancelled: the rider is told plainly and pointed at trying again (the
    same "no drivers available" message already shown in-app at the
    earlier NO_DRIVERS_MESSAGE_MINUTES mark), and admin gets an
    informational email — nothing left needing manual cleanup."""
    cutoff = timezone.now() - timedelta(minutes=settings.STALE_PENDING_ALERT_MINUTES)
    stale = RideRequest.objects.filter(
        status="pending", requested_at__lte=cutoff, pending_alert_sent_at__isnull=True
    )
    count = 0
    for ride in stale:
        ride.status = "cancelled"
        ride.cancelled_at = timezone.now()
        ride.pending_alert_sent_at = timezone.now()
        ride.save(update_fields=["status", "cancelled_at", "pending_alert_sent_at"])

        notify_rider(ride.id, {
            "type": "ride_update", "event": "cancelled", "ride_id": ride.id,
            "message": "No drivers were available for your ride, so it's been cancelled. Please try booking again.",
        })

        _notify_admin_stale(
            ride,
            "auto-cancelled, no driver found",
            f"Ride #{ride.id} ({ride.current_location} → {ride.destination}) sat "
            f"unmatched for over {settings.STALE_PENDING_ALERT_MINUTES} minutes and "
            "was auto-cancelled. No action needed, this is informational.",
        )
        count += 1
    return count


def _sweep_accepted_timeout() -> int:
    """Case 2: a driver accepted and then went quiet — unlike case 1, this
    is safe to auto-resolve, since it's the exact same effect as the driver
    tapping cancel themselves (see driver_trip_service.run_driver_cancel_ride),
    just triggered by silence instead of an explicit action."""
    cutoff = timezone.now() - timedelta(minutes=settings.STALE_ACCEPTED_TIMEOUT_MINUTES)
    stale = RideRequest.objects.filter(
        status="accepted", accepted_at__lte=cutoff, started_at__isnull=True
    )
    count = 0
    for ride in list(stale):
        if not ride.driver_id or not hasattr(ride.driver, "driver"):
            continue
        result, status_code = run_driver_cancel_ride(ride.driver, ride.id)
        if status_code == 200:
            _notify_admin_stale(
                ride,
                "driver went quiet",
                f"Ride #{ride.id} was accepted but not started for over "
                f"{settings.STALE_ACCEPTED_TIMEOUT_MINUTES} minutes. Reverted to "
                "pending and reopened to other drivers.",
            )
            count += 1
        else:
            logger.warning(
                "Stale-accepted revert failed ride=%s: %s", ride.id, result
            )
    return count


def _sweep_started_too_long() -> int:
    """Case 3: a trip started and never got marked complete. Alert-only,
    generous window — a real cross-city delivery can legitimately take
    hours, and auto-cancelling an in-progress trip could be actively
    harmful if it's still genuinely underway."""
    cutoff = timezone.now() - timedelta(minutes=settings.STALE_STARTED_ALERT_MINUTES)
    stale = RideRequest.objects.filter(
        status="started", started_at__lte=cutoff, started_alert_sent_at__isnull=True
    )
    count = 0
    for ride in stale:
        _notify_admin_stale(
            ride,
            "still in progress",
            f"Ride #{ride.id} ({ride.current_location} → {ride.destination}) started "
            f"over {settings.STALE_STARTED_ALERT_MINUTES // 60} hours ago and still "
            "hasn't been marked complete.",
        )
        ride.started_alert_sent_at = timezone.now()
        ride.save(update_fields=["started_alert_sent_at"])
        count += 1
    return count


def _sweep_unpaid_completed() -> int:
    """Case 4: the trip finished but the rider never paid. One push nudge —
    they're blocked from booking again until it's settled (see
    fraud_checks.get_unpaid_completed_ride), so it's kinder to tell them
    than to let them find out when they next try to book."""
    cutoff = timezone.now() - timedelta(minutes=settings.UNPAID_REMINDER_MINUTES)
    unpaid = RideRequest.objects.filter(
        status="completed",
        payment_status__in=UNPAID_PAYMENT_STATUSES,
        completed_at__lte=cutoff,
        # Old, long-abandoned trips are left to admin — a burst of reminders
        # for weeks-old rides is noise, not a nudge.
        completed_at__gte=timezone.now() - timedelta(days=3),
        unpaid_reminder_sent_at__isnull=True,
    )
    count = 0
    for ride in unpaid:
        try:
            send_push_to_user(
                ride.passenger_id,
                "Trip payment due",
                f"Your ₦{float(ride.total_fare or 0):,.0f} trip is still unpaid. "
                "pay now to book your next ride.",
                data={"ride_id": ride.id},
            )
        except Exception:
            # A push failure must not stop the rest of the sweep.
            logger.exception("Unpaid-trip reminder failed ride=%s", ride.id)
        ride.unpaid_reminder_sent_at = timezone.now()
        ride.save(update_fields=["unpaid_reminder_sent_at"])
        count += 1
    return count


def sweep_stale_rides() -> dict:
    """Entry point for the scheduled sweep — see /internal/sweep-stale-rides."""
    unmatched_cancelled = _sweep_unmatched_pending()
    accepted_reverted = _sweep_accepted_timeout()
    started_alerted = _sweep_started_too_long()
    unpaid_reminded = _sweep_unpaid_completed()
    logger.info(
        "Stale-ride sweep: unmatched_cancelled=%s accepted_reverted=%s started_alerted=%s unpaid_reminded=%s",
        unmatched_cancelled, accepted_reverted, started_alerted, unpaid_reminded,
    )
    return {
        "unmatched_cancelled": unmatched_cancelled,
        "accepted_reverted": accepted_reverted,
        "started_alerted": started_alerted,
        "unpaid_reminded": unpaid_reminded,
    }
