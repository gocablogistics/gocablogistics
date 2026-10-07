from __future__ import annotations

import logging
from typing import Optional

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.http import JsonResponse
from django.utils import timezone
from ninja import Router
from ninja.errors import HttpError
from ninja_jwt.authentication import JWTAuth

from ...models import DriverPayout, Notification, Rating, RideRequest, Rider

logger = logging.getLogger(__name__)
from ...services.driver_trip_service import (
    run_accept_ride,
    run_complete_trip,
    run_driver_cancel_ride,
    run_start_trip,
)
from ...utils.fare_quote import make_fare_quote, resolve_fare
from ...utils.payment_confirm import make_payment_confirm_token, payment_confirm_token_matches
from ...utils.tracking_token import make_tracking_token, resolve_tracking_ride_id
from ...services.fraud_checks import (
    get_unpaid_completed_ride,
    has_disputed_unpaid_ride,
    is_cash_debt_blocked,
    is_driver_flagged,
    is_driver_throttled,
    is_rider_flagged,
    is_rider_throttled,
)
from ...services.payment_service import (
    confirm_cash_payment,
    driver_respond_to_dispute,
    estimate_fare_from_locations,
    handle_payment_callback,
    initiate_cash_payment,
    initiate_checkout_for_ride,
    report_driver,
    report_nonpayment,
    respond_to_dispute,
)
from ...services.messaging_service import get_ride_for_participant, list_messages, send_message
from ...services.rating_service import submit_rating
from ...services.pickup_eta_service import compute_pickup_eta
from ...utils.names import display_name
from ...services.ride_events import notify_drivers_ride_cancelled, notify_notification_count, notify_rider
from ...utils import calculate_ride_fare, route_with_coords
from ...utils.distance_utils import get_nearby_rides
from ...utils.fare_pricing import DRIVER_EARNINGS_RATE
from ...services.payout_service import get_driver_wallet_balance, initiate_instant_cashout
from ...utils.ngrok import resolve_frontend_base_url
from ..auth.schemas import MessageOut
from ..auth.throttle import throttle
from ..auth.utils import get_client_ip
from .schemas import (
    ActiveRideOut,
    AvailabilityIn,
    AvailabilityOut,
    ConfirmCashIn,
    DisputeResponseIn,
    DriverActiveRideOut,
    DriverSummaryOut,
    FareEstimateIn,
    FareEstimateOut,
    LocationIn,
    NearbyRideOut,
    PaymentCallbackOut,
    PayoutOut,
    RateRideIn,
    ReferralOut,
    ReferralSummaryOut,
    ReportNonPaymentIn,
    RequestRideIn,
    RequestRideOut,
    RideHistoryOut,
    RideMessageOut,
    SendMessageIn,
    TrackingOut,
)

router = Router(tags=["rides"])


def _passenger_name(user) -> str:
    return display_name(user, "rider", "Rider")


def _passenger_phone(user) -> str:
    if hasattr(user, "rider") and user.rider.phone_number:
        return user.rider.phone_number
    return "Not available"


def _passenger_rating(user) -> float:
    if hasattr(user, "rider") and user.rider.rating:
        return float(user.rider.rating)
    return 5.0


def _passenger_location(user):
    if hasattr(user, "rider"):
        return user.rider.latitude, user.rider.longitude
    return None, None


@router.post("/estimate-fare", response=FareEstimateOut)
def estimate_fare(request, payload: FareEstimateIn):
    # Deliberately public — same as the legacy payment_views.estimate_fare
    # view, which has no @login_required either. A visitor needs to see a
    # price before we ask them to sign up. But public + calling a paid
    # Google API per request needs a throttle, unlike the rest of this
    # file's auth-gated endpoints (a logged-in user hammering their own
    # account is a much smaller exposure than anyone on the internet
    # hammering a free endpoint that costs you money per call).
    throttle(
        f"throttle:estimate-fare:ip:{get_client_ip(request)}",
        settings.FARE_ESTIMATE_THROTTLE_LIMIT,
        settings.FARE_ESTIMATE_THROTTLE_WINDOW_SECONDS,
        message="Too many fare estimate requests. Please wait a moment and try again.",
    )
    body, status = estimate_fare_from_locations(
        payload.pickup.strip(), payload.destination.strip(), payload.vehicle_type
    )
    if status != 200:
        raise HttpError(status, body.get("error", "Could not estimate fare"))
    body["quote"] = make_fare_quote(
        payload.pickup.strip(), payload.destination.strip(), body["total_fare"], payload.vehicle_type
    )
    return body


@router.post("/request", response=RequestRideOut, auth=JWTAuth())
def request_ride(request, payload: RequestRideIn):
    if is_rider_throttled(request.user):
        raise HttpError(
            429,
            "Too many cancelled rides recently. Please try again later or contact support.",
        )
    if has_disputed_unpaid_ride(request.user):
        raise HttpError(
            402,
            "You have an unpaid ride on your account. Please pay it before booking another.",
        )
    if is_rider_flagged(request.user):
        raise HttpError(
            403,
            "Your account has been flagged pending review. Contact support before booking again.",
        )
    if RideRequest.objects.filter(
        passenger=request.user, status__in=["pending", "accepted", "started"]
    ).exists():
        raise HttpError(
            409,
            "You already have an active ride. Finish or cancel it before booking another.",
        )
    unpaid = get_unpaid_completed_ride(request.user)
    if unpaid:
        raise HttpError(
            402,
            f"Your last trip (₦{float(unpaid.total_fare or 0):,.0f}) hasn't been paid yet. "
            "please pay it before booking another.",
        )

    pickup = payload.current_location.strip()
    destination = payload.destination.strip()
    if not pickup or not destination:
        raise HttpError(400, "Both locations are required")

    recipient_phone = (payload.recipient_phone_number or "").strip()
    if not recipient_phone:
        raise HttpError(400, "Recipient phone number is required")
    if not recipient_phone.isdigit() or len(recipient_phone) > 11:
        raise HttpError(400, "Recipient phone number must be at most 11 digits")

    distance_km, duration_min, pickup_coords, dest_coords = route_with_coords(
        pickup, destination
    )
    if not distance_km:
        raise HttpError(400, "Could not calculate route")

    fare = calculate_ride_fare(distance_km, duration_min, payload.vehicle_type)
    if not fare:
        raise HttpError(400, "Could not calculate the fare for this route")
    total_fare = resolve_fare(
        payload.fare_quote, pickup, destination, payload.vehicle_type, fare["total_fare"]
    )

    payment_method = payload.payment_method if payload.payment_method in ("online", "cash") else "online"
    if payment_method == "cash" and not settings.CASH_PAYMENTS_ENABLED:
        payment_method = "online"

    try:
        ride = RideRequest.objects.create(
            passenger=request.user,
            current_location=pickup,
            destination=destination,
            distance_km=distance_km,
            duration_min=duration_min,
            total_fare=total_fare,
            # The surge in effect when this ride was actually priced — kept
            # separate from total_fare, which may instead reflect a locked
            # earlier quote (see resolve_fare above). Was never being saved
            # at all before this; silently stuck at the model default (1.0)
            # regardless of the real fare.
            surge_multiplier=fare["surge_multiplier"],
            status="pending",
            pickup_latitude=pickup_coords["lat"] if pickup_coords else None,
            pickup_longitude=pickup_coords["lng"] if pickup_coords else None,
            destination_latitude=dest_coords["lat"] if dest_coords else None,
            destination_longitude=dest_coords["lng"] if dest_coords else None,
            recipient_phone_number=recipient_phone,
            payment_method=payment_method,
            vehicle_type=payload.vehicle_type,
        )
    except IntegrityError:
        # The check above has a small race window (two near-simultaneous
        # requests can both pass it before either row exists) — the DB's
        # one_active_ride_per_rider constraint is the real backstop; this
        # just turns that into the same clean error instead of a 500.
        raise HttpError(
            409,
            "You already have an active ride. Finish or cancel it before booking another.",
        )
    # NOTE: post_save signal handles driver broadcast — mirrors rider_views.request_ride.

    return {
        "ride_id": ride.id,
        "status": ride.status,
        "fare": float(ride.total_fare),
        "distance_km": distance_km,
        "duration_min": duration_min,
    }


@router.post("/{ride_id}/cancel", response=MessageOut, auth=JWTAuth())
def cancel_ride(request, ride_id: int):
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
            ride.save()

            if had_driver and hasattr(ride.driver, "driver"):
                ride.driver.driver.set_available()
    except RideRequest.DoesNotExist:
        raise HttpError(404, "Ride not found")

    notify_drivers_ride_cancelled(ride.id, had_driver)
    return {"detail": "Ride cancelled"}


COMPLETED_PAYMENT_WINDOW_SECONDS = 600


@router.get("/active", response=ActiveRideOut, auth=JWTAuth())
def active_ride(request):
    """The rider's current in-progress ride, if any — lets the SPA resume
    tracking after a page reload. Also returns a finished-but-unpaid trip
    (no time limit) so it can always be paid."""
    ride = (
        RideRequest.objects.filter(
            passenger=request.user, status__in=["pending", "accepted", "started"]
        )
        .order_by("-requested_at")
        .first()
    )
    if not ride:
        # A disputed ride has no time limit — the rider is blocked from
        # booking again until it's resolved, so they need to be able to
        # find and pay it whenever they come back, not just within a
        # 10-minute window.
        ride = (
            RideRequest.objects.filter(passenger=request.user, payment_status="disputed")
            .order_by("-completed_at")
            .first()
        )

    if not ride:
        # A finished trip stays payable however long ago it ended — new
        # bookings are held until it's paid (see request_ride), so it has to
        # stay findable here rather than expiring off the screen.
        ride = get_unpaid_completed_ride(request.user)

    if not ride:
        raise HttpError(404, "No active ride")

    driver = None
    if ride.driver_id and hasattr(ride.driver, "driver"):
        d = ride.driver.driver
        driver = {
            "id": ride.driver.id,
            "name": display_name(ride.driver, "driver", "Your driver"),
            "phone": d.phone_number or "Not available",
            "car_model": d.vehicle_model or "Unknown",
            "license_plate": d.license_plate or "N/A",
            "rating": float(d.rating) if d.rating else 4.5,
            "photo": d.passport_photo.url if d.passport_photo else None,
            "latitude": d.latitude,
            "longitude": d.longitude,
        }

    pickup_eta_min = driver_distance_km = None
    if ride.status == "accepted" and driver:
        eta = compute_pickup_eta(ride, driver["latitude"], driver["longitude"])
        if eta:
            pickup_eta_min, driver_distance_km = eta["eta_min"], eta["distance_km"]

    # Only for a trip still actually in flight — tracking a long-finished
    # (or finished-but-unpaid) ride isn't meaningful, and this function
    # also serves those as a fallback above.
    tracking_url = None
    if ride.status in ("pending", "accepted", "started"):
        token = make_tracking_token(ride.id)
        tracking_url = f"{resolve_frontend_base_url()}/track/{token}"

    return {
        "ride_id": ride.id,
        "status": ride.status,
        "requested_at": ride.requested_at,
        "current_location": ride.current_location,
        "destination": ride.destination,
        "pickup_latitude": ride.pickup_latitude,
        "pickup_longitude": ride.pickup_longitude,
        "destination_latitude": ride.destination_latitude,
        "destination_longitude": ride.destination_longitude,
        "total_fare": float(ride.total_fare) if ride.total_fare else None,
        "payment_status": ride.payment_status,
        "payment_method": ride.payment_method,
        "driver": driver,
        "pickup_eta_min": pickup_eta_min,
        "tracking_url": tracking_url,
        "driver_distance_km": driver_distance_km,
    }


@router.get("/track/{token}", response=TrackingOut)
def track_ride(request, token: str):
    # Public, unauthenticated by design — see utils/tracking_token.py and
    # TrackingOut's own docstring for exactly what this deliberately does
    # and doesn't expose. Same "don't leak which case it is" shape as
    # other token-based lookups in this file: an invalid/expired/tampered
    # token and a nonexistent ride both just 404.
    ride_id = resolve_tracking_ride_id(token)
    if ride_id is None:
        raise HttpError(404, "This tracking link is invalid or has expired.")
    try:
        ride = RideRequest.objects.get(id=ride_id)
    except RideRequest.DoesNotExist:
        raise HttpError(404, "This tracking link is invalid or has expired.")

    driver_name = driver_photo = None
    driver_latitude = driver_longitude = None
    pickup_eta_min = None
    if ride.driver_id and hasattr(ride.driver, "driver"):
        d = ride.driver.driver
        driver_name = display_name(ride.driver, "driver", "Your driver")
        driver_photo = d.passport_photo.url if d.passport_photo else None
        driver_latitude, driver_longitude = d.latitude, d.longitude
        if ride.status == "accepted":
            eta = compute_pickup_eta(ride, d.latitude, d.longitude)
            if eta:
                pickup_eta_min = eta["eta_min"]

    return {
        "status": ride.status,
        "destination": ride.destination,
        "vehicle_type": ride.vehicle_type,
        "driver_name": driver_name,
        "driver_photo": driver_photo,
        "driver_latitude": driver_latitude,
        "driver_longitude": driver_longitude,
        "destination_latitude": ride.destination_latitude,
        "destination_longitude": ride.destination_longitude,
        "pickup_eta_min": pickup_eta_min,
    }


RIDE_HISTORY_LIMIT = 100


@router.get("/history", response=list[RideHistoryOut], auth=JWTAuth())
def ride_history(request):
    rides = (
        RideRequest.objects.filter(passenger=request.user)
        .select_related("driver__driver")
        .exclude(status__in=["pending", "accepted", "started"])
        .order_by("-requested_at")[:RIDE_HISTORY_LIMIT]
    )
    rides = list(rides)
    rated_ride_ids = set(
        Rating.objects.filter(rater=request.user, ride_id__in=[r.id for r in rides])
        .values_list("ride_id", flat=True)
    )
    return [
        {
            "ride_id": r.id,
            "current_location": r.current_location,
            "destination": r.destination,
            "status": r.status,
            "payment_status": r.payment_status,
            "payment_method": r.payment_method,
            "total_fare": float(r.total_fare) if r.total_fare else None,
            "distance_km": float(r.distance_km) if r.distance_km else None,
            "requested_at": r.requested_at,
            "completed_at": r.completed_at,
            "other_party_name": display_name(r.driver, "driver", "Driver") if r.driver_id else None,
            "my_rating_submitted": r.id in rated_ride_ids,
        }
        for r in rides
    ]


@router.get("/driver/history", response=list[RideHistoryOut], auth=JWTAuth())
def driver_ride_history(request):
    if not hasattr(request.user, "driver"):
        raise HttpError(403, "Driver profile not found")
    rides = (
        RideRequest.objects.filter(driver=request.user)
        .exclude(status__in=["pending", "accepted", "started"])
        .order_by("-requested_at")[:RIDE_HISTORY_LIMIT]
    )
    rides = list(rides)
    rated_ride_ids = set(
        Rating.objects.filter(rater=request.user, ride_id__in=[r.id for r in rides])
        .values_list("ride_id", flat=True)
    )
    return [
        {
            "ride_id": r.id,
            "current_location": r.current_location,
            "destination": r.destination,
            "status": r.status,
            "payment_status": r.payment_status,
            "payment_method": r.payment_method,
            "total_fare": float(r.total_fare) if r.total_fare else None,
            "distance_km": float(r.distance_km) if r.distance_km else None,
            "requested_at": r.requested_at,
            "completed_at": r.completed_at,
            "other_party_name": _passenger_name(r.passenger),
            "my_rating_submitted": r.id in rated_ride_ids,
        }
        for r in rides
    ]


@router.get("/{ride_id}/messages", response=list[RideMessageOut], auth=JWTAuth())
def get_messages(request, ride_id: int):
    try:
        ride = get_ride_for_participant(request.user, ride_id)
    except RideRequest.DoesNotExist:
        raise HttpError(404, "Ride not found")
    except PermissionError:
        raise HttpError(403, "Not part of this ride")
    return list_messages(ride)


@router.post("/{ride_id}/messages", response=RideMessageOut, auth=JWTAuth())
def post_message(request, ride_id: int, payload: SendMessageIn):
    try:
        ride = get_ride_for_participant(request.user, ride_id)
    except RideRequest.DoesNotExist:
        raise HttpError(404, "Ride not found")
    except PermissionError:
        raise HttpError(403, "Not part of this ride")
    try:
        return send_message(request.user, ride, payload.text)
    except ValueError as e:
        raise HttpError(400, str(e))


@router.post("/{ride_id}/pay", auth=JWTAuth())
def initiate_payment(request, ride_id: int):
    # Points Paystack's redirect at the SPA instead of the legacy Django
    # template flow _create_payment_link defaults to. resolve_frontend_base_url
    # transparently swaps in a live ngrok URL instead of FRONTEND_BASE_URL
    # when demoing to a client through a tunnel — see gocabapp/utils/ngrok.py.
    callback_url = f"{settings.BASE_URL}/payment/success/{ride_id}/"
    body, status = initiate_checkout_for_ride(request.user, ride_id, callback_url=callback_url)
    return JsonResponse(body, status=status)


@router.post("/{ride_id}/pay-cash", auth=JWTAuth())
def pay_cash(request, ride_id: int):
    body, status = initiate_cash_payment(request.user, ride_id)
    return JsonResponse(body, status=status)


@router.post("/{ride_id}/confirm-cash", auth=JWTAuth())
def confirm_cash(request, ride_id: int, payload: ConfirmCashIn):
    body, status = confirm_cash_payment(request.user, ride_id, payload.code)
    return JsonResponse(body, status=status)


@router.get("/referrals", response=ReferralSummaryOut, auth=JWTAuth())
def get_referrals(request):
    # Riders only — a driver account has no Rider profile/referral_code at
    # all (see Rider.referral_code / services/payment_service.py's referral
    # reward logic).
    try:
        rider = request.user.rider
    except Rider.DoesNotExist:
        raise HttpError(404, "No rider profile found for this account.")

    referred = rider.referrals.order_by("-id").all()
    return {
        "referral_code": rider.referral_code,
        "wallet_credit_balance": rider.wallet_credit_balance,
        "referral_reward_amount": settings.REFERRAL_REWARD_AMOUNT,
        "referrals": [
            {
                "full_name": r.full_name,
                "joined_at": r.created_at,
                "reward_earned": r.referral_reward_credited,
            }
            for r in referred
        ],
    }


@router.post("/{ride_id}/report-nonpayment", auth=JWTAuth())
def report_nonpayment_endpoint(request, ride_id: int, payload: ReportNonPaymentIn):
    body, status = report_nonpayment(request.user, ride_id, reason=payload.reason)
    return JsonResponse(body, status=status)


@router.post("/{ride_id}/report-driver", auth=JWTAuth())
def report_driver_endpoint(request, ride_id: int, payload: ReportNonPaymentIn):
    body, status = report_driver(request.user, ride_id, reason=payload.reason)
    return JsonResponse(body, status=status)


@router.post("/{ride_id}/rate", auth=JWTAuth())
def rate_ride(request, ride_id: int, payload: RateRideIn):
    body, status = submit_rating(request.user, ride_id, payload.stars, payload.comment)
    return JsonResponse(body, status=status)


@router.post("/{ride_id}/dispute/respond", auth=JWTAuth())
def respond_to_dispute_endpoint(request, ride_id: int, payload: DisputeResponseIn):
    body, status = respond_to_dispute(request.user, ride_id, payload.statement)
    return JsonResponse(body, status=status)


@router.post("/{ride_id}/dispute/driver-respond", auth=JWTAuth())
def driver_respond_to_dispute_endpoint(request, ride_id: int, payload: DisputeResponseIn):
    body, status = driver_respond_to_dispute(request.user, ride_id, payload.statement)
    return JsonResponse(body, status=status)


@router.get("/{ride_id}/payment-callback", response=PaymentCallbackOut, auth=JWTAuth())
def payment_callback(
    request, ride_id: int, reference: Optional[str] = None, confirm_token: Optional[str] = None,
):
    # `reference` is accepted for URL-compatibility with Paystack's redirect
    # (and so the SPA can pass through whatever it received) but is no
    # longer used for verification — handle_payment_callback only ever
    # trusts the reference this ride's own checkout generated server-side.
    #
    # `confirm_token` (signed, minted alongside the checkout link in
    # initiate_payment) is what actually proves this browser started this
    # specific payment — checked FIRST and, if it matches, bypasses the
    # passenger-must-equal-request.user check entirely. That check alone
    # used to gate this, which broke on real, already-successfully-paid
    # rides (277, 278, 281 — confirmed genuine on Paystack, logged 404
    # anyway) whenever a *different* tab of the same browser had logged
    # into another account in the meantime — the JWT active in this tab at
    # the moment Paystack's redirect reloads the page is no longer a
    # reliable way to know who actually paid.
    if confirm_token and payment_confirm_token_matches(confirm_token, ride_id):
        try:
            ride = RideRequest.objects.get(id=ride_id)
        except RideRequest.DoesNotExist:
            raise HttpError(404, "Ride not found")
    else:
        try:
            ride = RideRequest.objects.get(id=ride_id, passenger=request.user)
        except RideRequest.DoesNotExist:
            actual_owner = (
                RideRequest.objects.filter(id=ride_id).values_list("passenger_id", flat=True).first()
            )
            logger.error(
                "payment-callback 404: ride_id=%s requested by user_id=%s (%s) — %s",
                ride_id, request.user.id, request.user.username,
                "belongs to a different account (passenger_id=%s)" % actual_owner
                if actual_owner is not None else "no ride with this id exists",
            )
            raise HttpError(404, "Ride not found")

    handle_payment_callback(ride_id, {})  # verifies + updates the DB; redirect target unused here

    ride.refresh_from_db()
    return {
        "ride_id": ride.id,
        "payment_status": ride.payment_status,
        "total_fare": float(ride.total_fare) if ride.total_fare else None,
        "paid_at": ride.paid_at,
        "wallet_credit_applied": float(ride.wallet_credit_applied) if ride.wallet_credit_applied else None,
    }


# ── Driver-side endpoints ────────────────────────────────────────────────────


@router.get("/availability", response=AvailabilityOut, auth=JWTAuth())
def get_availability(request):
    if not hasattr(request.user, "driver"):
        raise HttpError(403, "Driver profile not found")
    d = request.user.driver
    return {"is_online": d.is_online, "is_busy": d.is_busy}


@router.post("/availability", response=AvailabilityOut, auth=JWTAuth())
def set_availability(request, payload: AvailabilityIn):
    if not hasattr(request.user, "driver"):
        raise HttpError(403, "Driver profile not found")
    d = request.user.driver
    if payload.is_online and is_cash_debt_blocked(request.user):
        raise HttpError(
            402,
            f"You owe ₦{d.cash_debt:,.2f} in cash-ride commission. Settle up before going online again.",
        )
    if payload.is_online and is_driver_flagged(request.user):
        raise HttpError(
            403,
            "Your account has been flagged pending review. Contact support before going online again.",
        )
    d.is_online = payload.is_online
    d.save(update_fields=["is_online"])
    return {"is_online": d.is_online, "is_busy": d.is_busy}


@router.get("/nearby", response=list[NearbyRideOut], auth=JWTAuth())
def nearby_rides(request):
    if not hasattr(request.user, "driver"):
        raise HttpError(403, "Driver profile not found")

    driver = request.user.driver
    if not driver.is_online:
        return []

    if driver.latitude and driver.longitude:
        rides = get_nearby_rides(driver.latitude, driver.longitude, driver.vehicle_type)
    else:
        rides = list(
            RideRequest.objects.filter(
                status="pending", driver__isnull=True, vehicle_type=driver.vehicle_type
            )
            .select_related("passenger")
            .order_by("-requested_at")
        )

    return [
        {
            "id": ride.id,
            "current_location": ride.current_location,
            "destination": ride.destination,
            "pickup_latitude": ride.pickup_latitude,
            "pickup_longitude": ride.pickup_longitude,
            "destination_latitude": ride.destination_latitude,
            "destination_longitude": ride.destination_longitude,
            "total_fare": float(ride.total_fare) if ride.total_fare else None,
            "vehicle_type": ride.vehicle_type,
            "distance_from_driver": getattr(ride, "distance_from_driver", None),
            "estimated_pickup_time": getattr(ride, "estimated_pickup_time", None),
            "requested_at": ride.requested_at,
            "passenger_name": _passenger_name(ride.passenger),
            "passenger_phone": _passenger_phone(ride.passenger),
            "passenger_rating": _passenger_rating(ride.passenger),
        }
        for ride in rides
    ]


@router.post("/{ride_id}/accept", auth=JWTAuth())
def accept_ride(request, ride_id: int):
    if is_driver_throttled(request.user):
        return JsonResponse(
            {
                "status": "error",
                "message": "Too many cancelled trips recently. Accepting is paused. Contact support.",
            },
            status=429,
        )
    if is_cash_debt_blocked(request.user):
        return JsonResponse(
            {
                "status": "error",
                "message": "Outstanding cash-ride commission owed. Settle up before accepting new rides.",
            },
            status=402,
        )
    if is_driver_flagged(request.user):
        return JsonResponse(
            {
                "status": "error",
                "message": "Your account has been flagged pending review. Contact support.",
            },
            status=403,
        )
    body, status = run_accept_ride(request.user, ride_id)
    return JsonResponse(body, status=status)


@router.post("/{ride_id}/start", auth=JWTAuth())
def start_trip(request, ride_id: int):
    body, status = run_start_trip(request.user, ride_id)
    return JsonResponse(body, status=status)


@router.post("/{ride_id}/complete", auth=JWTAuth())
def complete_trip(request, ride_id: int):
    body, status = run_complete_trip(request.user, ride_id)
    return JsonResponse(body, status=status)


@router.post("/{ride_id}/driver-cancel", auth=JWTAuth())
def driver_cancel_ride(request, ride_id: int):
    body, status = run_driver_cancel_ride(request.user, ride_id)
    return JsonResponse(body, status=status)


@router.post("/location", response=MessageOut, auth=JWTAuth())
def update_driver_location(request, payload: LocationIn):
    if not hasattr(request.user, "driver"):
        raise HttpError(403, "Driver profile not found")
    request.user.driver.update_location(payload.latitude, payload.longitude, payload.address)

    active_ride = RideRequest.objects.filter(
        driver=request.user, status__in=["accepted", "started"]
    ).first()
    if active_ride:
        message = {
            "type": "driver_location",
            "ride_id": active_ride.id,
            "lat": payload.latitude,
            "lng": payload.longitude,
        }
        # Only while the driver is still heading to the pickup point — once the
        # trip has started, "arrives in N min" no longer means anything.
        if active_ride.status == "accepted":
            eta = compute_pickup_eta(active_ride, payload.latitude, payload.longitude)
            if eta:
                message["eta_min"] = eta["eta_min"]
                message["distance_km"] = eta["distance_km"]
                # eta_min == 0 is compute_pickup_eta's own "within
                # ARRIVED_KM" signal. One-time per ride, guarded by
                # arrival_notified_at — otherwise a driver sitting at the
                # pickup point would re-trigger this on every ~15s ping.
                if eta["eta_min"] == 0 and active_ride.arrival_notified_at is None:
                    active_ride.arrival_notified_at = timezone.now()
                    active_ride.save(update_fields=["arrival_notified_at"])
                    notify_rider(active_ride.id, {
                        "type": "ride_update", "event": "driver_arrived",
                        "ride_id": active_ride.id,
                        "message": "Your driver has arrived at the pickup point.",
                    })
                    Notification.objects.create(
                        user=active_ride.passenger,
                        message="Your driver has arrived at the pickup point.",
                        is_active=True,
                    )
                    count = Notification.objects.filter(user=active_ride.passenger, is_active=True).count()
                    notify_notification_count(active_ride.passenger_id, count)
        notify_rider(active_ride.id, message)

    return {"detail": "Location updated"}


@router.post("/rider-location", response=MessageOut, auth=JWTAuth())
def update_rider_location(request, payload: LocationIn):
    """Rider's counterpart to /rides/location — lets the driver see where
    the rider actually is pre-pickup (e.g. they've moved to another
    entrance), rather than only the fixed address typed at booking time.
    Deliberately just persists rather than also pushing over a websocket:
    the driver dashboard has no live socket connection today (Phase 8 chose
    polling), so it's picked up via the existing /rides/driver/active poll
    instead of adding a connection nothing else there uses yet."""
    if not hasattr(request.user, "rider"):
        raise HttpError(403, "Rider profile not found")
    request.user.rider.update_location(payload.latitude, payload.longitude)
    return {"detail": "Location updated"}


@router.get("/driver/active", response=DriverActiveRideOut, auth=JWTAuth())
def driver_active_ride(request):
    """Mirrors the rider-side /active endpoint for the driver's own
    currently accepted/started trip — including the same post-completion
    grace window, so a driver can still see and confirm a cash payment
    right after completing the trip, before it disappears."""
    if not hasattr(request.user, "driver"):
        raise HttpError(403, "Driver profile not found")

    ride = (
        RideRequest.objects.filter(driver=request.user, status__in=["accepted", "started"])
        .order_by("-accepted_at")
        .first()
    )
    if not ride:
        recent_completed = (
            RideRequest.objects.filter(
                driver=request.user,
                status="completed",
                payment_status__in=["pending", "processing", "disputed"],
            )
            .order_by("-completed_at")
            .first()
        )
        if (
            recent_completed
            and recent_completed.completed_at
            and (timezone.now() - recent_completed.completed_at).total_seconds()
            < COMPLETED_PAYMENT_WINDOW_SECONDS
        ):
            ride = recent_completed

    if not ride:
        raise HttpError(404, "No active ride")

    rider_lat, rider_lng = _passenger_location(ride.passenger)

    # Same calculation (and the same cached Google reading) the rider sees, so
    # both screens show matching numbers without extra Google calls.
    pickup_eta_min = pickup_distance_km = None
    if ride.status == "accepted":
        driver_profile = request.user.driver
        eta = compute_pickup_eta(ride, driver_profile.latitude, driver_profile.longitude)
        if eta:
            pickup_eta_min, pickup_distance_km = eta["eta_min"], eta["distance_km"]

    return {
        "ride_id": ride.id,
        "status": ride.status,
        "current_location": ride.current_location,
        "destination": ride.destination,
        "pickup_latitude": ride.pickup_latitude,
        "pickup_longitude": ride.pickup_longitude,
        "destination_latitude": ride.destination_latitude,
        "destination_longitude": ride.destination_longitude,
        "total_fare": float(ride.total_fare) if ride.total_fare else None,
        "payment_status": ride.payment_status,
        "payment_method": ride.payment_method,
        "pickup_eta_min": pickup_eta_min,
        "pickup_distance_km": pickup_distance_km,
        "passenger": {
            "name": _passenger_name(ride.passenger),
            "phone": _passenger_phone(ride.passenger),
            "rating": _passenger_rating(ride.passenger),
            "latitude": rider_lat,
            "longitude": rider_lng,
        },
    }


@router.get("/driver/summary", response=DriverSummaryOut, auth=JWTAuth())
def driver_summary(request):
    """Aggregate the real total_fare field, then apply the driver's cut."""
    if not hasattr(request.user, "driver"):
        raise HttpError(403, "Driver profile not found")

    assigned_qs = RideRequest.objects.filter(driver=request.user)
    completed_qs = assigned_qs.filter(status="completed")
    total_assigned = assigned_qs.count()
    total_completed = completed_qs.count()
    completion_rate = round((total_completed / total_assigned) * 100, 1) if total_assigned else 0.0

    today = timezone.now().date()
    todays_fare = completed_qs.filter(completed_at__date=today).aggregate(total=Sum("total_fare"))["total"] or 0
    total_fare = completed_qs.aggregate(total=Sum("total_fare"))["total"] or 0

    return {
        "completed_trips": total_completed,
        "completion_rate": completion_rate,
        # Whole naira (2026-10-02, client request) — matches the actual
        # per-ride payout amounts (see payout_service.create_payout_for_ride),
        # which are each already rounded before this sums them.
        "todays_earnings": round(float(todays_fare) * DRIVER_EARNINGS_RATE),
        "total_earnings": round(float(total_fare) * DRIVER_EARNINGS_RATE),
        "cash_debt": float(request.user.driver.cash_debt),
        "cash_debt_blocked": is_cash_debt_blocked(request.user),
        "is_flagged": is_driver_flagged(request.user),
        "wallet_balance": float(get_driver_wallet_balance(request.user.driver)),
    }


@router.post("/driver/cashout", auth=JWTAuth())
def driver_cashout(request):
    """Driver-requested instant cash-out of their current wallet balance —
    see payout_service.initiate_instant_cashout for the fee/claim logic.
    Same JsonResponse-not-a-typed-schema pattern as the other action
    endpoints here (pay, pay-cash, ...)."""
    if not hasattr(request.user, "driver"):
        raise HttpError(403, "Driver profile not found")
    body, status = initiate_instant_cashout(request.user.driver)
    return JsonResponse(body, status=status)


@router.get("/driver/payouts", response=list[PayoutOut], auth=JWTAuth())
def driver_payouts(request):
    """Payout ledger for card-paid rides only — cash rides never generate a
    row here since the driver already holds that cash directly (see
    services/payout_service.py). Status moves pending -> paid once an admin
    has actually sent the bank transfer."""
    if not hasattr(request.user, "driver"):
        raise HttpError(403, "Driver profile not found")

    payouts = DriverPayout.objects.filter(driver=request.user.driver).order_by("-created_at")
    return [
        {
            "id": p.id,
            "ride_id": p.ride_id,
            "amount": float(p.amount),
            "status": p.status,
            "created_at": p.created_at,
            "paid_at": p.paid_at,
        }
        for p in payouts
    ]
