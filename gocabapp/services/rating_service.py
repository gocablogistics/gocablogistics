"""Post-trip ratings — either direction (rider rates driver, driver rates
rider) go through the same function; which one happens is decided by
whether the caller is the ride's passenger or its driver."""
from __future__ import annotations

import logging

from django.conf import settings
from django.contrib.auth.models import User
from django.db import IntegrityError
from django.db.models import Avg, Count

from ..models import Notification, Rating, RideRequest

logger = logging.getLogger(__name__)

DEFAULT_RATING = 5.0


def _recompute_average(user: User) -> tuple[float, int]:
    agg = Rating.objects.filter(ratee=user).aggregate(avg=Avg("stars"), n=Count("id"))
    avg = round(agg["avg"], 2) if agg["avg"] is not None else DEFAULT_RATING
    return avg, agg["n"]


def _maybe_auto_flag_driver(driver_user: User, average: float, count: int) -> None:
    """Ratings existed but nothing ever consumed them — a driver could sit
    at a 1.8 average forever with zero consequence. Requires a minimum
    number of ratings first (RATING_AUTO_FLAG_MIN_COUNT) so one bad rating
    can't instantly block a driver who's barely started; below the
    threshold with enough ratings behind it, this blocks going online the
    same way a payment-dispute flag does — an admin still has to review and
    clear it (PaymentDisputeAdmin's dismiss_dispute action), same as any
    other flag, not an automatic ban."""
    if count < settings.RATING_AUTO_FLAG_MIN_COUNT or average >= settings.RATING_AUTO_FLAG_THRESHOLD:
        return
    driver = driver_user.driver
    if driver.is_flagged:
        return
    driver.is_flagged = True
    driver.flagged_reason = (
        f"Auto-flagged: average rating {average} fell below "
        f"{settings.RATING_AUTO_FLAG_THRESHOLD} over {count} ratings."
    )
    driver.save(update_fields=["is_flagged", "flagged_reason"])

    # Same notify pattern as PaymentDisputeAdmin.flag_driver, so a flagged
    # driver finds out why instead of just discovering "Go online" is gone.
    from .ride_events import notify_notification_count
    from .push_service import send_push_to_user
    message = (
        f"Your rating ({average}★ over {count} rides) has fallen below our "
        "minimum. Contact support before going online again."
    )
    Notification.objects.filter(user=driver_user, is_active=True).delete()
    Notification.objects.create(user=driver_user, message=message, is_active=True)
    notify_notification_count(driver_user.id, 1)
    send_push_to_user(driver_user.id, "Account flagged", message)

    logger.warning(
        "Driver auto-flagged for low rating: user_id=%s average=%s count=%s",
        driver_user.id, average, count,
    )


def submit_rating(rater: User, ride_id: int, stars: int, comment: str = "") -> tuple[dict, int]:
    if not isinstance(stars, int) or stars < 1 or stars > 5:
        return {"status": "error", "error": "Rating must be between 1 and 5 stars"}, 400

    try:
        ride = RideRequest.objects.get(id=ride_id)
    except RideRequest.DoesNotExist:
        return {"status": "error", "error": "Ride not found"}, 404

    if rater.id == ride.passenger_id:
        ratee = ride.driver
    elif ride.driver_id and rater.id == ride.driver_id:
        ratee = ride.passenger
    else:
        return {"status": "error", "error": "You weren't part of this ride"}, 403

    if not ratee:
        return {"status": "error", "error": "No one to rate on this ride yet"}, 400
    if ride.status != "completed":
        return {"status": "error", "error": "You can only rate a completed ride"}, 400

    try:
        Rating.objects.create(
            ride=ride, rater=rater, ratee=ratee, stars=stars, comment=comment.strip()
        )
    except IntegrityError:
        return {"status": "error", "error": "You've already rated this ride"}, 400

    new_average, rating_count = _recompute_average(ratee)
    rating_str = str(new_average)
    # Same CharField-of-a-stringified-float every existing call site already
    # reads via float(x.rating) if x.rating else 4.5 — see models.py.
    if hasattr(ratee, "driver"):
        ratee.driver.rating = rating_str
        ratee.driver.save(update_fields=["rating"])
        _maybe_auto_flag_driver(ratee, new_average, rating_count)
    elif hasattr(ratee, "rider"):
        ratee.rider.rating = rating_str
        ratee.rider.save(update_fields=["rating"])

    logger.info(
        "Rating recorded: ride=%s rater=%s ratee=%s stars=%s", ride_id, rater.id, ratee.id, stars
    )
    return {"status": "success", "average_rating": new_average}, 200
