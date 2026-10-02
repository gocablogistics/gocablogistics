from __future__ import annotations

import json
import logging
from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from ..models import RideRequest
from ..utils.distance_utils import get_nearby_rides
from ..utils.pagination import json_partial_html, paginate_request_page
from ..services.driver_trip_service import (
    run_accept_ride,
    run_complete_trip,
    run_driver_cancel_ride,
    run_start_trip,
)

logger = logging.getLogger(__name__)


def _require_driver(request):
    """Return driver instance or None. Caller redirects if None."""
    return getattr(request.user, "driver", None)


# ── Dashboard ─────────────────────────────────────────────────────────────────

@login_required(login_url="home")
def driver_dashboard(request):
    if not _require_driver(request):
        return redirect("home")

    driver = request.user.driver

    active_ride = (
        RideRequest.objects
        .filter(driver=request.user, status__in=["accepted", "started"])
        .order_by("-accepted_at")
        .first()
    )

    
    assigned_qs   = RideRequest.objects.filter(driver=request.user)
    completed_qs  = assigned_qs.filter(status="completed")
    total_assigned  = assigned_qs.count()
    total_completed = completed_qs.count()

    completion_rate = round((total_completed / total_assigned) * 100, 1) if total_assigned else 0

    
    paid_completed = completed_qs.filter(payment_status="paid").count()
    payment_rate   = round((paid_completed / total_completed) * 100, 1) if total_completed else 0

    today = timezone.now().date()
    todays_completed  = completed_qs.filter(completed_at__date=today)
    total_fare_today  = todays_completed.aggregate(total=Sum('total_fare'))['total'] or 0
    todays_earnings   = float(total_fare_today) * 0.8

    context = {
        "driver":           driver,
        "active_ride":      active_ride,
        "available_rides": (
            RideRequest.objects.filter(status="pending", driver__isnull=True)
            .order_by("-requested_at")
            if not active_ride and driver.can_accept_ride() else None
        ),
        "completed_rides":  completed_qs.order_by("-completed_at")[:10],
        "completed_trips":  total_completed,
        "completion_rate":  completion_rate,
        "payment_rate":     payment_rate,
        "todays_earnings":  todays_earnings,
        "is_driver":        True,
        "is_dual_role":     hasattr(request.user, "rider"),
    }
    return render(request, "driver-dashboard-2.html", context)


# ── Partial-HTML endpoints (HTMX / fetch) ────────────────────────────────────

@login_required
def pending_rides(request):
    # Prune stale pending rides older than 1 hour
    stale = RideRequest.objects.filter(
        status="pending", requested_at__lt=timezone.now() - timedelta(hours=1)
    )
    if stale.exists():
        count = stale.count()
        stale.delete()
        logger.info("Pruned %s stale pending rides", count)

    driver      = request.user.driver
    driver_lat  = getattr(driver, "latitude",  None)
    driver_lng  = getattr(driver, "longitude", None)
    has_location = bool(driver_lat and driver_lng)

    if has_location:
        from ..utils.distance_utils import city_limits, detect_city
        city         = detect_city(driver_lat, driver_lng)
        max_distance = city_limits(driver_lat, driver_lng)["max_pickup_distance"]
        rides_list   = get_nearby_rides(driver_lat, driver_lng)
    else:
        city = "unknown"
        max_distance = 6
        rides_list = list(
            RideRequest.objects.filter(status="pending", driver__isnull=True)
            .select_related("passenger")
            .order_by("-requested_at")
        )

    rides = paginate_request_page(request, rides_list, 4)
    for ride in rides:
        if not hasattr(ride, "passenger_phone"):
            ride.passenger_phone = (
                ride.passenger.rider.phone_number
                if hasattr(ride.passenger, "rider") else "No phone number"
            )

    return json_partial_html(
        request, "partials/_pending_rides.html",
        {"pending_rides": rides, "has_location": has_location,
         "max_distance": max_distance, "city": city},
    )


@login_required
def accepted_rides(request):
    rides = paginate_request_page(
        request,
        RideRequest.objects.filter(driver=request.user, status="accepted")
        .select_related("passenger__rider").order_by("-accepted_at"),
        1,
    )
    return json_partial_html(request, "partials/_accepted_rides.html", {"accepted_rides": rides})


@login_required
def active_rides(request):
    rides = paginate_request_page(
        request,
        RideRequest.objects.filter(driver=request.user, status="started")
        .select_related("passenger__rider").order_by("-started_at"),
        10,
    )
    return json_partial_html(request, "partials/_active_rides.html", {"active_rides": rides})


@login_required(login_url="home")
def completed_trips(request):
    try:
        rides = paginate_request_page(
            request,
            RideRequest.objects.filter(driver=request.user, status="completed")
            .order_by("-completed_at"),
            10,
        )
        return json_partial_html(request, "partials/_completed_rides.html", {"completed_rides": rides})
    except Exception:
        logger.exception("completed_trips view error")
        return JsonResponse({"error": "Could not load completed trips"}, status=500)


# ── Ride actions ──────────────────────────────────────────────────────────────

@csrf_exempt
@login_required
def accept_ride(request, ride_id):
    if request.method != "POST":
        return JsonResponse({"status": "error", "message": "POST only"}, status=405)
    body, status = run_accept_ride(request.user, ride_id)
    return JsonResponse(body, status=status)


@csrf_exempt
@login_required
def start_trip(request, ride_id):
    if request.method != "POST":
        return JsonResponse({"error": "POST only"}, status=405)
    body, status = run_start_trip(request.user, ride_id)
    return JsonResponse(body, status=status)


@csrf_exempt
@login_required
def complete_trip(request, ride_id):
    if request.method != "POST":
        return JsonResponse({"error": "POST only"}, status=405)
    body, status = run_complete_trip(request.user, ride_id)
    return JsonResponse(body, status=status)


@csrf_exempt
@login_required
def driver_cancel_ride(request, ride_id):
    if request.method != "POST":
        return JsonResponse({"status": "error", "message": "POST only"}, status=405)
    body, status = run_driver_cancel_ride(request.user, ride_id)
    return JsonResponse(body, status=status)


@csrf_exempt
@login_required
def update_driver_location(request):
    if request.method != "POST":
        return JsonResponse({"error": "POST only"}, status=405)
    try:
        data = json.loads(request.body)
        lat  = data.get("latitude")
        lng  = data.get("longitude")
        if not lat or not lng:
            return JsonResponse({"error": "latitude and longitude required"}, status=400)
        request.user.driver.update_location(lat, lng, data.get("address"))
        return JsonResponse({"status": "success"})
    except Exception:
        logger.exception("update_driver_location error")
        return JsonResponse({"error": "Server error"}, status=500)


# ── Profile / Earnings ────────────────────────────────────────────────────────

@login_required(login_url="home")
def driver_profile(request):
    if not _require_driver(request):
        return redirect("home")

    driver       = request.user.driver
    completed_qs = RideRequest.objects.filter(driver=request.user, status="completed")
    trip_count   = completed_qs.count()
    # DB-level aggregation instead of Python loop
    total_earnings = completed_qs.aggregate(
        total=Sum("driver_earnings")
    )["total"] or 0

    context = {
        "driver": {
            "full_name":  driver.full_name,
            "initials":   "".join(n[0] for n in driver.full_name.split()[:2]).upper(),
            "rating":     float(driver.rating) if driver.rating else 4.5,
            "trip_count": trip_count,
            "status":     "Online" if driver.is_approved else "Offline",
            "vehicle": {
                "model":         driver.vehicle_model,
                "type":          driver.vehicle_type,
                "license_plate": driver.license_plate or "Not Set",
            },
            "stats": {
                "total_earnings": total_earnings,
                "completed_trips": trip_count,
                "rating":         float(driver.rating) if driver.rating else 4.5,
                "online_hours":   "5h 42m",  # placeholder until you track this
            },
        }
    }
    return render(request, "driver-profile.html", context)


@login_required(login_url="home")
def driver_earnings(request):
    return render(request, "driver-earnings.html")