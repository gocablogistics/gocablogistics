from __future__ import annotations

import logging

from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from django.contrib.auth.models import User

from ..models import Notification, RideRequest
from ..services.pickup_eta_service import compute_pickup_eta
from ..utils.names import display_name
from ..services.ride_events import (
    notify_driver_pool,
    notify_notification_count,
    notify_rider,
)

logger = logging.getLogger(__name__)


def _driver_info(instance: RideRequest) -> dict:
    u = instance.driver
    d = u.driver
    return {
        "name":          display_name(u, "driver", "Your driver"),
        "rating":        float(d.rating) if getattr(d, "rating", None) else 4.5,
        "car_model":     getattr(d, "vehicle_model",  None) or "Unknown",
        "license_plate": getattr(d, "license_plate",  None) or "N/A",
    }


@receiver(pre_save, sender=RideRequest)
def _stash_previous_status(sender, instance: RideRequest, **kwargs):
    """post_save doesn't get the pre-update value, so stash it here — the
    status-change blocks below must only fire on an actual transition, not
    on every unrelated save() of a ride already sitting in that status
    (e.g. a cash-confirmation-code retry saving payment_status on an
    already-completed ride would otherwise re-send a duplicate "ride
    completed" notification each time). Mirrors driver_signals.py's
    _stash_previous_approval."""
    if not instance.pk:
        instance._previous_status = None
        return
    try:
        instance._previous_status = RideRequest.objects.only("status").get(pk=instance.pk).status
    except RideRequest.DoesNotExist:
        instance._previous_status = None


@receiver(post_save, sender=RideRequest)
def ride_request_update(sender, instance: RideRequest, created: bool, **kwargs):
    if created:
        # Persist a notification too, not just the live blip — matches the
        # existing driver-pool broadcast's scope (all online drivers, not
        # distance-filtered; the /rides/nearby list is what applies the
        # actual proximity filter once they look).
        online_driver_users = list(User.objects.filter(
            driver__is_online=True, driver__is_approved=True
        ))
        notify_driver_pool(
            {"type": "new_ride_request", "ride_id": instance.id},
            push_to_user_ids=[u.id for u in online_driver_users],
        )
        Notification.objects.bulk_create(
            Notification(
                user=u,
                message=f"New ride request: {instance.current_location} → {instance.destination}",
                is_active=True,
            )
            for u in online_driver_users
        )
        for u in online_driver_users:
            count = Notification.objects.filter(user=u, is_active=True).count()
            notify_notification_count(u.id, count)
        return

    status = instance.status
    if status == getattr(instance, "_previous_status", None):
        # Some other field changed (payment_status, cash_confirmation_attempts,
        # etc.) on a ride already sitting in this status — not a real
        # transition, so none of the one-time notifications below should fire.
        return

    if status == "accepted":
        Notification.objects.filter(user=instance.passenger, is_active=True).delete()
        Notification.objects.create(
            user=instance.passenger,
            # User.get_full_name() is always empty in this app (accounts
            # never set first/last name) — the real name lives on the
            # Driver profile.
            message=f"Driver {instance.driver.driver.full_name} accepted your ride",
            is_active=True,
        )
        notify_notification_count(instance.passenger.id, 1)
        # Minutes until the driver reaches the PICKUP point (this used to be the
        # trip's own length, which isn't when the driver arrives). No Google call:
        # this runs inside the accept transaction, which must not wait on a network.
        driver_profile = instance.driver.driver
        pickup = compute_pickup_eta(
            instance, driver_profile.latitude, driver_profile.longitude, allow_google_call=False
        )
        notify_rider(instance.id, {
            "type":    "ride_update",
            "event":   "accepted",
            "ride_id": instance.id,
            "driver":  _driver_info(instance),
            "eta":     pickup["eta_min"] if pickup else None,
            "distance": f"{instance.distance_km:.1f} km" if instance.distance_km else None,
            "fare":    instance.total_fare,
        })
        

    elif status == "completed":
        Notification.objects.filter(user=instance.passenger, is_active=True).update(is_active=False)
        notify_notification_count(instance.passenger.id, 0)
        notify_rider(instance.id, {
            "type": "ride_update", "event": "completed",
            "ride_id": instance.id, "message": "Ride completed",
        })

    elif status in ("started", "cancelled"):
        notify_rider(instance.id, {
            "type": "ride_update", "event": status,
            "ride_id": instance.id, "message": f"Ride {status}",
        })
        if status == "cancelled" and instance.driver:
            notify_driver_pool({
                "type": "ride_cancelled", "ride_id": instance.id,
                "message": "Ride cancelled by passenger",
            })