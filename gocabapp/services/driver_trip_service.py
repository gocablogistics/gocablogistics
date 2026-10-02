"""Driver-side ride lifecycle: accept, start, complete, cancel."""
from __future__ import annotations

import logging
from typing import Any

from django.contrib.auth.models import User
from django.db import transaction
from django.utils import timezone

from ..models import DriverCancellation, RideRequest
from ..utils.names import display_name
from ..services.ride_events import (
    build_trip_payload,
    notify_driver_pool,
    notify_rider,
)
from ..services.payment_service import _create_payment_link

logger = logging.getLogger(__name__)
JsonDict = dict[str, Any]


def _driver_ws_info(user: User) -> dict:
    d = user.driver
    return {
        "id":            user.id,
        "name":          display_name(user, "driver", "Your driver"),
        "phone":         getattr(d, "phone_number", None) or "Not available",
        "car_model":     getattr(d, "vehicle_model",  None) or "Unknown",
        "license_plate": getattr(d, "license_plate",  None) or "N/A",
        "rating":        float(d.rating) if getattr(d, "rating", None) else 4.5,
        "photo":         d.passport_photo.url if getattr(d, "passport_photo", None) else None,
    }


def run_accept_ride(user: User, ride_id: int) -> tuple[JsonDict, int]:
    if not hasattr(user, "driver"):
        return {"status": "error", "message": "Driver profile not found"}, 403

    try:
        with transaction.atomic():
            active = RideRequest.objects.filter(
                driver=user, status__in=["accepted", "started"]
            ).select_for_update()
            if active.exists():
                return {
                    "status": "error",
                    "message": f"You have {active.count()} active ride(s). Complete them first.",
                }, 400

            try:
                ride = RideRequest.objects.select_for_update().get(
                    id=ride_id, status="pending", driver__isnull=True
                )
            except RideRequest.DoesNotExist:
                return {
                    "status": "error",
                    "message": "Ride no longer available. Another driver may have accepted it.",
                }, 404

            ride.driver     = user
            ride.status     = "accepted"
            ride.accepted_at = timezone.now()
            ride.save()
            user.driver.set_busy(ride)

        # Tell all other drivers this ride is gone
        notify_driver_pool({
            "type":    "ride_accepted_by_other",
            "ride_id": ride.id,
        })

        notify_rider(ride.id, {
            "type":    "ride_accepted",
            "ride_id": ride.id,
            "message": "Ride accepted",
        })

        logger.info("Ride %s accepted by driver %s", ride_id, user)
        return {"status": "success", "message": "Ride accepted", "ride_id": ride.id}, 200

    except Exception:
        logger.exception("run_accept_ride failed user=%s ride=%s", user, ride_id)
        try:
            user.driver.set_available()
        except Exception:
            pass
        return {"status": "error", "message": "Unable to accept ride. Please try again."}, 500


def run_start_trip(user: User, ride_id: int) -> tuple[JsonDict, int]:
    if not hasattr(user, "driver"):
        return {"error": "Driver profile not found"}, 403

    try:
        with transaction.atomic():
            ride = RideRequest.objects.select_for_update().get(
                id=ride_id, driver=user, status="accepted"
            )
            ride.status     = "started"
            ride.started_at = timezone.now()
            ride.save()

        payload = build_trip_payload(ride, user)

        notify_rider(ride.id, {
            "type": "ride_update", "event": "started",
            "ride_id": ride.id, "message": "Your ride has started", "data": payload,
        })
        notify_driver_pool({
            "type": "ride_update", "event": "started",
            "ride_id": ride.id, "message": "Trip started", "data": payload,
        })

        return {"status": "success", "ride_id": ride.id, "message": "Trip started", "data": payload}, 200

    except RideRequest.DoesNotExist:
        return {"error": "Ride not found or not assigned to you"}, 404
    except Exception:
        logger.exception("run_start_trip failed ride=%s", ride_id)
        return {"error": "Server error"}, 500


def run_complete_trip(user: User, ride_id: int) -> tuple[JsonDict, int]:
    if not hasattr(user, "driver"):
        return {"status": "error", "error": "Driver profile not found"}, 403

    try:
        with transaction.atomic():
            ride = RideRequest.objects.select_for_update().get(id=ride_id, driver=user)
            if ride.status != "started":
                return {
                    "status": "error",
                    "error": f"Ride must be started first (current: {ride.status})",
                }, 400
            ride.status         = "completed"
            ride.completed_at   = timezone.now()
            ride.payment_status = "pending"
            ride.save()
            user.driver.set_available()

        ride.refresh_from_db()
        payload = build_trip_payload(ride, user)

        try:
            _create_payment_link(ride)
        except Exception:
            logger.exception("Payment link creation failed ride=%s", ride_id)

        notify_rider(ride.id, {
            "type": "ride_update", "event": "completed",
            "ride_id": ride.id, "message": "Your ride is complete", "data": payload,
        })
        notify_driver_pool({
            "type": "ride_update", "event": "completed",
            "ride_id": ride.id, "message": "Trip completed", "data": payload,
        })

        return {"status": "success", "ride_id": ride.id, "message": "Trip completed", "data": payload}, 200

    except RideRequest.DoesNotExist:
        return {"status": "error", "error": "Trip not found or already completed"}, 404
    except Exception:
        logger.exception("run_complete_trip failed ride=%s", ride_id)
        return {"status": "error", "error": "Server error"}, 500


def run_driver_cancel_ride(user: User, ride_id: int) -> tuple[JsonDict, int]:
    try:
        with transaction.atomic():
            ride = RideRequest.objects.select_for_update().get(
                id=ride_id, driver=user, status="accepted"
            )
            ride.driver      = None
            ride.status      = "pending"
            ride.accepted_at = None
            # This ride is genuinely reopened — clear any earlier
            # unmatched-too-long alert so the stale-ride sweep can alert
            # again if it goes stale a second time instead of staying
            # permanently silenced by the first alert.
            ride.pending_alert_sent_at = None
            ride.save()
            user.driver.set_available()
            DriverCancellation.objects.create(driver=user, ride=ride)

        notify_rider(ride.id, {
            "type": "ride_update", "event": "driver_cancelled",
            "ride_id": ride.id, "message": "Driver cancelled the ride",
        })
        online_driver_ids = list(
            User.objects.filter(
                driver__is_online=True, driver__is_approved=True
            ).values_list("id", flat=True)
        )
        notify_driver_pool(
            {"type": "new_ride_request", "ride_id": ride.id, "message": "A ride is now available"},
            push_to_user_ids=online_driver_ids,
        )

        return {"status": "success", "message": "Ride cancelled"}, 200

    except RideRequest.DoesNotExist:
        return {"status": "error", "message": "Ride not found"}, 404
    except Exception:
        logger.exception("run_driver_cancel_ride failed ride=%s", ride_id)
        return {"status": "error", "message": "Server error"}, 500