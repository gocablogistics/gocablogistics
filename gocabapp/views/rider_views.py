from __future__ import annotations
from ..utils.names import display_name

import json
import logging

from django.contrib.auth.decorators import login_required
from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings

from ..models import Notification, RideRequest, Rider

from ..utils import (
    calculate_ride_fare,
    route_with_coords,       
)
from ..services.ride_events import notify_drivers_ride_cancelled

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_driver_info(driver_user) -> dict | None:
    """Return a serialisable dict for a driver user, or None."""
    if not driver_user or not hasattr(driver_user, "driver"):
        return None
    d = driver_user.driver
    return {
        "name": display_name(driver_user, "driver", "Your driver"),
        "car_model": getattr(d, "vehicle_model", None) or "Unknown",
        "license_plate": getattr(d, "license_plate", None) or "N/A",
        "phone": getattr(d, "phone_number", None) or "Not available",
        "rating": float(d.rating) if getattr(d, "rating", None) is not None else 4.5,
    }



def _save_ride_to_session(request, ride: RideRequest) -> None:
    """Persist only what the frontend needs into the session."""
    request.session["current_ride_id"] = str(ride.id)
    request.session["current_ride_status"] = ride.status

    if ride.status == "completed":
        request.session["completed_ride_fare"] = (
            float(ride.total_fare) if ride.total_fare is not None else 0.0
        )

    driver_info = _build_driver_info(ride.driver)
    if driver_info:
        request.session["current_driver"] = driver_info

    request.session.modified = True


def _clear_ride_session(request) -> None:
    for key in (
        "current_ride_id",
        "current_ride_status",
        "completed_ride_fare",
        "current_driver",
    ):
        request.session.pop(key, None)
    request.session.modified = True


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------

@login_required(login_url="home")
def rider_dashboard(request):
    COMPLETED_WINDOW_SECONDS = 600

    # Prefer an active ride; fall back to a recent completed one.
    active_ride = (
        RideRequest.objects
        .filter(passenger=request.user, status__in=["pending", "accepted", "started"])
        .select_related("driver__driver")
        .order_by("-requested_at")
        .first()
    )

    if active_ride:
        _save_ride_to_session(request, active_ride)
    else:
        _clear_ride_session(request)
        # Show payment card for up to 10 min after completion
        recent_completed = (
            RideRequest.objects
            .filter(
                passenger=request.user,
                status="completed",
                payment_status__in=["pending", "processing"],
            )
            .select_related("driver__driver")
            .order_by("-completed_at")
            .first()
        )
        if (
            recent_completed
            and recent_completed.completed_at
            and recent_completed.payment_status not in ("paid", "failed")
            and (timezone.now() - recent_completed.completed_at).total_seconds()
            < COMPLETED_WINDOW_SECONDS
        ):
            _save_ride_to_session(request, recent_completed)
            active_ride = recent_completed  # so the template can render it

    # Profile
    try:
        rider_profile = Rider.objects.get(user=request.user)
        address = getattr(rider_profile, "address", None) or "Address not set"
    except Rider.DoesNotExist:
        rider_profile = None
        address = "Address not set"

    # Stats
    all_rides = RideRequest.objects.filter(passenger=request.user)
    completed_qs = all_rides.filter(status="completed").select_related("driver")
    total_km = sum(
        float(r.distance_km) for r in completed_qs if r.distance_km is not None
    )
    total_spend = sum(
        float(r.total_fare) for r in completed_qs if r.total_fare is not None
    )

    

    # Recent rides (paginated)
    paginator = Paginator(completed_qs.order_by("-completed_at"), 5)
    try:
        recent_rides = paginator.page(request.GET.get("page", 1))
    except (PageNotAnInteger, EmptyPage):
        recent_rides = paginator.page(1)

    context = {
        "active_ride": active_ride,
        "is_rider": True,
        "rider_profile": rider_profile,
        "address": address,
        "total_rides": all_rides.count(),
        "completed_rides": completed_qs.count(),
        "total_spend": round(total_spend, 2),
        "total_miles": round(total_km, 1),
        "member_since": (
            request.user.date_joined.strftime("%B %Y")
            if request.user.date_joined
            else None
        ),
        "recent_rides": recent_rides,
        "notification_count": Notification.objects.filter(
            user=request.user, is_active=True
        ).count(),
        "GOOGLE_MAPS_API_KEY": getattr(settings, "GOOGLE_MAPS_API_KEY", "") or "",
        "is_dual_role": hasattr(request.user, "driver"),
    }
    return render(request, "rider-dashboard-2.html", context)


@login_required
def ride_status(request, ride_id):
    """Lightweight polling endpoint — returns current ride state as JSON."""
    try:
        ride = get_object_or_404(RideRequest, id=ride_id, passenger=request.user)

        if not ride:
            _clear_ride_session(request)
            return JsonResponse({"status": "not_found"}, status=404)

        if ride.status in ("completed", "cancelled"):
            _clear_ride_session(request)

        return JsonResponse(
            {
                "status": ride.status,
                "fare": float(ride.total_fare) if ride.total_fare else 0,
                "ride_id": ride.id,
                "driver": _build_driver_info(ride.driver),
                "current_location": ride.current_location,
                "destination": ride.destination,
                "last_updated": ride.requested_at.isoformat(),
                "payment_status": ride.payment_status,
            }
        )
    except Exception:
        logger.exception("ride_status failed for ride_id=%s", ride_id)
        return JsonResponse({"error": "Could not fetch ride status"}, status=500)


@csrf_exempt
@login_required
def request_ride(request):
    if request.method != "POST":
        return JsonResponse({"error": "Only POST allowed"}, status=405)

    try:
        data = (
            json.loads(request.body)
            if request.content_type == "application/json"
            else request.POST
        )
        pickup = data.get("current_location", "").strip()
        destination = data.get("destination", "").strip()

        if not pickup or not destination:
            return JsonResponse({"error": "Both locations required"}, status=400)

        distance_km, duration_min, pickup_coords, dest_coords = (
            route_with_coords(pickup, destination)
        )
        if not distance_km:
            return JsonResponse({"error": "Could not calculate route"}, status=400)

        fare = calculate_ride_fare(distance_km, duration_min)

        ride = RideRequest.objects.create(
            passenger=request.user,
            current_location=pickup,
            destination=destination,
            distance_km=distance_km,
            duration_min=duration_min,
            total_fare=fare["total_fare"],
            surge_multiplier=fare["surge_multiplier"],
            status="pending",
            pickup_latitude=pickup_coords["lat"] if pickup_coords else None,
            pickup_longitude=pickup_coords["lng"] if pickup_coords else None,
            destination_latitude=dest_coords["lat"] if dest_coords else None,
            destination_longitude=dest_coords["lng"] if dest_coords else None,
        )
        # NOTE: post_save signal handles driver broadcast — no manual call needed.
        _save_ride_to_session(request, ride)
        logger.info("Ride %s created for user %s", ride.id, request.user)

        return JsonResponse(
            {
                "status": "success",
                "ride_id": ride.id,
                "fare": ride.total_fare,
                "distance": distance_km,
                "duration": duration_min,
            }
        )
    except Exception:
        logger.exception("request_ride failed for user=%s", request.user)
        return JsonResponse({"error": "Could not create ride"}, status=500)


@csrf_exempt
@login_required
def cancel_ride(request, ride_id):
    """Rider cancels a pending or accepted ride."""
    try:
        with transaction.atomic():
            ride = RideRequest.objects.select_for_update().get(
                id=ride_id,
                passenger=request.user,
                status__in=["pending", "accepted"],
            )
            had_driver = ride.driver_id is not None
            ride.status = "cancelled"
            ride.cancelled_at = timezone.now()
            ride.cancelled_by = "rider"
            ride.save()

            if had_driver and hasattr(ride.driver, "driver"):
                ride.driver.driver.set_available()

        _clear_ride_session(request)
        notify_drivers_ride_cancelled(ride.id, had_driver)
        return JsonResponse({"status": "success", "message": "Ride cancelled"})

    except RideRequest.DoesNotExist:
        return JsonResponse({"error": "Ride not found"}, status=404)
    except Exception:
        logger.exception("cancel_ride failed ride_id=%s", ride_id)
        return JsonResponse({"error": "Failed to cancel ride"}, status=500)