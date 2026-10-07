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

# ── Partial-HTML endpoints (HTMX / fetch) ────────────────────────────────────

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

