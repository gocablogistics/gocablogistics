from __future__ import annotations

import json
import logging

from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import redirect
from django.views.decorators.csrf import csrf_exempt

from ..models import RideRequest
from ..services.payment_service import (
    estimate_fare_from_locations,
    handle_payment_callback,
    initiate_checkout_for_ride,
)

logger = logging.getLogger(__name__)


@csrf_exempt
def estimate_fare(request):
    if request.method != "POST":
        return JsonResponse({"error": "Only POST allowed"}, status=405)
    try:
        data = (
            json.loads(request.body)
            if request.content_type == "application/json"
            else request.POST
        )
        pickup      = (data.get("pickup") or data.get("current_location", "")).strip()
        destination = data.get("destination", "").strip()
        body, status = estimate_fare_from_locations(pickup, destination)
        return JsonResponse(body, status=status)
    except Exception:
        logger.exception("estimate_fare view error")
        return JsonResponse({"error": "Internal server error"}, status=500)


@csrf_exempt
@login_required
def initiate_payment(request, ride_id):
    if request.method != "POST":
        return JsonResponse({"status": "error", "error": "Method not allowed"}, status=405)
    body, status = initiate_checkout_for_ride(request.user, ride_id)
    return JsonResponse(body, status=status)


@login_required
def payment_success(request, ride_id):
    # This URL is Paystack's browser-redirect target, so it's reachable
    # by anyone in the sense that the URL isn't secret — but it must never
    # let a caller mark a ride they don't own as paid. Ownership check first,
    # unrelated to handle_payment_callback's own reference/amount checks.
    if not RideRequest.objects.filter(id=ride_id, passenger=request.user).exists():
        return HttpResponseForbidden("Not your ride.")
    url = handle_payment_callback(ride_id, request.GET)
    return redirect(url)