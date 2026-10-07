from __future__ import annotations

import json
import logging

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt

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


def payment_success(request, ride_id):
    # Paystack's browser redirect lands here with no app session, so this
    # page can't require login. It's safe without one: handle_payment_callback
    # only marks a ride paid after Paystack itself confirms the ride's stored
    # reference succeeded, so a stranger hitting this URL changes nothing.
    paid = "payment=success" in handle_payment_callback(ride_id, request.GET)
    return HttpResponse(_payment_result_page(paid), content_type="text/html")


def _payment_result_page(paid: bool) -> str:
    if paid:
        title = "Payment received"
        message = "Your payment went through. Go back to the GoCab app, your ride status will update automatically."
        colour = "#1be451"
    else:
        title = "Payment not completed"
        message = "We could not confirm this payment. Go back to the GoCab app and try again, or contact support if money was debited."
        colour = "#f87171"
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title></head>
<body style="margin:0;background:#20241f;color:#fff;font-family:Arial,sans-serif;display:flex;align-items:center;justify-content:center;min-height:100vh;padding:24px;box-sizing:border-box;">
<div style="max-width:420px;text-align:center;">
<h1 style="color:{colour};font-size:26px;margin:0 0 16px;">{title}</h1>
<p style="font-size:16px;line-height:1.5;margin:0;">{message}</p>
</div></body></html>"""