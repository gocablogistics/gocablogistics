"""
Payment orchestration: fare estimation, Paystack checkout, and callback verification.
All Paystack HTTP logic lives here alongside the Django service functions.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import random
import secrets
import time
from decimal import Decimal

import requests
from django.conf import settings
from django.contrib.auth.models import User
from ..utils.mailer import send_admin_mail
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from ..models import Driver, Notification, PaymentDispute, RideRequest, Rider
from ..utils.fare_pricing import calculate_ride_fare, DRIVER_EARNINGS_RATE
from ..utils.distance_utils import google_distance
from ..services.ride_events import notify_rider, notify_driver_pool, notify_notification_count
from ..services.payout_service import create_payout_for_ride, handle_transfer_webhook_event
from ..services.push_service import send_push_to_user
from ..services.cash_debt_service import charge_cash_commission

logger = logging.getLogger(__name__)

# ── Paystack constants ────────────────────────────────────────────────────────

_INIT_URL   = "https://api.paystack.co/transaction/initialize"
_VERIFY_URL = "https://api.paystack.co/transaction/verify/{}"
_REFUND_URL = "https://api.paystack.co/refund"
_TIMEOUT    = 30
_REF_PREFIX = "RIDE"

CASH_CONFIRMATION_MAX_ATTEMPTS = 5


class PaymentError(Exception):
    """Paystack or transport-level failure."""


# ── Internal Paystack helpers ─────────────────────────────────────────────────

def _passenger_email(ride: RideRequest) -> str:
    email = ride.passenger.email
    if not email:
        try:
            email = Rider.objects.get(user=ride.passenger).email
        except Rider.DoesNotExist:
            pass
    if not email:
        raise PaymentError(f"No email found for passenger on ride {ride.id}")
    return email


def _reference(ride: RideRequest) -> str:
    return f"{_REF_PREFIX}_{ride.id}_{int(time.time())}_{random.randint(1000, 9999)}"


def _auth_header() -> dict:
    return {"Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}"}


def _create_payment_link(
    ride: RideRequest, callback_url: str | None = None, amount_override: Decimal | None = None
) -> str:
    """Call Paystack initialize; return authorization_url. Raises PaymentError on failure.

    amount_override is what actually gets charged through Paystack — used by
    initiate_checkout_for_ride to charge total_fare minus any wallet credit
    the rider has (see _wallet_credit_to_apply). ride.total_fare itself is
    never changed; it stays the ride's real value for history/payout math."""
    amount = amount_override if amount_override is not None else ride.total_fare
    if not amount or amount <= 0:
        raise PaymentError(f"Invalid fare ₦{amount} for ride {ride.id}")

    email     = _passenger_email(ride)
    reference = _reference(ride)

    payload = {
        "email":        email,
        "amount":       int(amount * 100),  # kobo
        "reference":    reference,
        "callback_url": callback_url or f"{settings.BASE_URL}/payment/success/{ride.id}/",
        "metadata": {
            "ride_id":      ride.id,
            "passenger_id": ride.passenger.id,
            "driver_id":    ride.driver.id if ride.driver else None,
        },
    }

    try:
        response = requests.post(_INIT_URL, headers=_auth_header(), json=payload, timeout=_TIMEOUT)
    except requests.RequestException as e:
        raise PaymentError(f"Paystack request failed: {e}") from e

    if response.status_code != 200:
        raise PaymentError(f"Paystack returned HTTP {response.status_code}")

    data = response.json()
    url  = data.get("data", {}).get("authorization_url")
    if not (data.get("status") and url):
        raise PaymentError(f"Paystack init failed: {data}")

    ride.payment_reference = reference
    ride.save(update_fields=["payment_reference"])
    return url


def _auto_resolve_nonpayment_dispute(ride: RideRequest) -> None:
    """A driver's non-payment report (report_nonpayment) sets payment_status
    to "reported" — which, since fraud_checks.UNPAID_PAYMENT_STATUSES now
    includes it, holds the rider exactly like a plain unpaid ride until they
    actually pay. Once they do, there's nothing left to adjudicate: close
    the report out automatically rather than leaving it sitting "open"
    forever needing an admin to notice and dismiss it by hand. Scoped to
    driver-initiated (non-payment) reports specifically — a rider's conduct
    complaint about the driver (report_driver) is a separate, unrelated
    concern that paying the fare doesn't resolve."""
    updated = PaymentDispute.objects.filter(
        ride=ride, status="open", driver_statement__gt="",
    ).update(
        status="resolved", resolved_at=timezone.now(),
        resolution_note="Auto-resolved, rider paid in full.",
    )
    if updated:
        logger.info("Auto-resolved non-payment dispute(s) for ride=%s", ride.id)


def _apply_verified_online_payment(ride: RideRequest, reference: str, amount_kobo: int) -> bool:
    """Marks a ride paid from a Paystack-confirmed transaction — used by
    both the browser callback and the webhook, so both paths enforce the
    exact same checks. Returns False (and marks nothing) if the amount
    doesn't match what this ride actually costs, which is what stops a
    valid-but-unrelated reference (e.g. a cheap transaction reused against
    an expensive ride) from underpaying a ride. Idempotent: calling this
    twice for an already-paid ride is a safe no-op.

    Expects total_fare minus wallet_credit_applied (see
    _wallet_credit_to_apply/initiate_checkout_for_ride) — a rider with
    credit on their account was only ever charged the discounted amount
    through Paystack in the first place.
    """
    discounted = (ride.total_fare or 0) - (ride.wallet_credit_applied or 0)
    expected_amount = int(discounted * 100) if ride.total_fare else None
    if expected_amount is None or amount_kobo != expected_amount:
        logger.error(
            "Payment amount mismatch ride_id=%s reference=%s expected=%s got=%s",
            ride.id, reference, expected_amount, amount_kobo,
        )
        return False

    applied = False
    with transaction.atomic():
        locked = RideRequest.objects.select_for_update().get(id=ride.id)
        if locked.payment_status != "paid":
            locked.payment_reference = reference
            locked.payment_status = "paid"
            locked.paid_at = timezone.now()
            locked.save()
            applied = True
            _consume_wallet_credit(ride, locked.wallet_credit_applied)
            logger.info("Ride %s marked paid via reference=%s", ride.id, reference)

    if applied:
        ride.refresh_from_db()
        _notify_payment_completed(ride)
        _auto_resolve_nonpayment_dispute(ride)
        create_payout_for_ride(ride)
        _maybe_credit_referral_reward(ride)
    return True


def _wallet_credit_to_apply(ride: RideRequest) -> Decimal:
    """How much of the passenger's Rider.wallet_credit_balance to knock off
    this ride's fare, capped at the fare itself. Zero if the passenger has
    no Rider profile (shouldn't happen — only riders book rides) or no
    credit."""
    if not ride.total_fare or ride.total_fare <= 0:
        return Decimal("0")
    try:
        balance = ride.passenger.rider.wallet_credit_balance or Decimal("0")
    except Rider.DoesNotExist:
        return Decimal("0")
    return min(balance, ride.total_fare)


def _consume_wallet_credit(ride: RideRequest, credit_amount: Decimal | None) -> None:
    """Deducts a ride's already-snapshotted wallet_credit_applied from the
    rider's live balance — called exactly once, from inside the same
    payment_status="paid" idempotency guard every other payment-completion
    side effect here already sits behind. Safe as a plain F() update (no
    select_for_update needed): the one-active-ride-per-rider DB constraint
    already means a rider can never have two rides consuming their wallet
    balance at once."""
    if not credit_amount:
        return
    try:
        rider = ride.passenger.rider
    except Rider.DoesNotExist:
        return
    Rider.objects.filter(pk=rider.pk).update(
        wallet_credit_balance=F("wallet_credit_balance") - credit_amount
    )


def _apply_wallet_only_payment(ride: RideRequest, credit_amount: Decimal) -> bool:
    """Marks a ride paid entirely from wallet credit, with no Paystack
    transaction at all — used when a rider's credit balance fully covers
    the fare (see initiate_checkout_for_ride). Same idempotency guard as
    _apply_verified_online_payment."""
    applied = False
    with transaction.atomic():
        locked = RideRequest.objects.select_for_update().get(id=ride.id)
        if locked.payment_status != "paid":
            locked.payment_reference = "WALLET_CREDIT"
            locked.payment_status = "paid"
            locked.paid_at = timezone.now()
            locked.wallet_credit_applied = credit_amount
            locked.save()
            applied = True
            _consume_wallet_credit(ride, credit_amount)
            logger.info("Ride %s marked paid entirely via wallet credit (₦%s)", ride.id, credit_amount)

    if applied:
        ride.refresh_from_db()
        _notify_payment_completed(ride)
        _auto_resolve_nonpayment_dispute(ride)
        create_payout_for_ride(ride)
        _maybe_credit_referral_reward(ride)
    return applied


def _maybe_credit_referral_reward(ride: RideRequest) -> None:
    """First-paid-ride referral bonus (settings.REFERRAL_REWARD_AMOUNT) —
    called after any ride of the referred rider's is confirmed paid, online,
    wallet-credit, or cash. Rider.referral_reward_credited guards this to
    firing exactly once per referred rider, no matter which of their rides
    trips it first or how many get paid afterwards."""
    try:
        rider = ride.passenger.rider
    except Rider.DoesNotExist:
        return
    if rider.referred_by_id is None or rider.referral_reward_credited:
        return

    reward = Decimal(str(settings.REFERRAL_REWARD_AMOUNT))
    with transaction.atomic():
        locked = Rider.objects.select_for_update().get(pk=rider.pk)
        if locked.referral_reward_credited or locked.referred_by_id is None:
            return
        referrer = Rider.objects.select_for_update().get(pk=locked.referred_by_id)
        referrer.wallet_credit_balance = referrer.wallet_credit_balance + reward
        referrer.save(update_fields=["wallet_credit_balance"])
        locked.referral_reward_credited = True
        locked.save(update_fields=["referral_reward_credited"])

    if not referrer.user_id:
        return
    message = (
        f"Your referral just completed their first paid ride. "
        f"₦{reward:.2f} credit has been added to your GoCab wallet."
    )
    Notification.objects.create(user_id=referrer.user_id, message=message, is_active=True)
    notify_notification_count(referrer.user_id, 1)
    send_push_to_user(referrer.user_id, "Referral bonus credited", message)
    logger.info(
        "Referral reward credited: referrer_rider_id=%s referred_rider_id=%s amount=%s",
        referrer.id, locked.id, reward,
    )


def verify_paystack_signature(raw_body: bytes, signature_header: str | None) -> bool:
    """Paystack signs webhook payloads with HMAC-SHA512 over the raw request
    body, keyed with your secret key — this is the only thing that should
    ever be trusted to say "this webhook really came from Paystack"."""
    if not signature_header or not settings.PAYSTACK_SECRET_KEY:
        return False
    computed = hmac.new(
        settings.PAYSTACK_SECRET_KEY.encode("utf-8"), raw_body, hashlib.sha512
    ).hexdigest()
    return hmac.compare_digest(computed, signature_header)


def handle_paystack_webhook(event: dict) -> None:
    """Server-to-server notification from Paystack — the reliable source of
    truth for payment status, since it doesn't depend on the rider's
    browser completing a redirect (closed tab, dropped connection, etc. all
    leave the client-driven callback below never firing, even though
    Paystack successfully charged the card)."""
    event_type = event.get("event")
    if event_type and event_type.startswith("transfer."):
        handle_transfer_webhook_event(event)
        return
    if event_type != "charge.success":
        return

    data = event.get("data") or {}
    reference = data.get("reference")
    amount = data.get("amount")
    if not reference or amount is None:
        logger.error("Paystack webhook missing reference/amount: %s", event)
        return

    try:
        ride = RideRequest.objects.get(payment_reference=reference)
    except RideRequest.DoesNotExist:
        # Every tap on Pay mints a new reference and overwrites the stored
        # one, so a payment made through an earlier link (the rider tapped
        # twice, or a slow network) arrives with a reference the ride no
        # longer remembers. The ride id we put in the checkout metadata is
        # signed by Paystack's webhook signature, so it's safe to use —
        # and the amount check in _apply_verified_online_payment still
        # decides whether the ride really gets marked paid.
        ride = None
        ride_id = (data.get("metadata") or {}).get("ride_id")
        if ride_id:
            ride = RideRequest.objects.filter(id=ride_id).first()
        if ride is None:
            logger.error("Paystack webhook: no ride found for reference=%s", reference)
            return
        logger.info(
            "Paystack webhook: matched ride_id=%s from metadata (reference=%s was superseded)",
            ride.id, reference,
        )

    _apply_verified_online_payment(ride, reference, amount)


def _notify_payment_completed(ride: RideRequest) -> None:
    """Shared by both the online (Paystack) and cash confirmation paths —
    the notification doesn't care which method was used."""
    # Whole naira (2026-10-02, client request) — just the figure shown in
    # the "payment received" push to the driver pool; the real payout
    # amount is computed separately in payout_service.create_payout_for_ride.
    earnings = round(float(ride.total_fare) * DRIVER_EARNINGS_RATE)

    notify_rider(ride.id, {
        "type":    "ride_update",
        "event":   "payment_completed",
        "ride_id": ride.id,
        "message": "Payment completed! Thank you for your ride.",
    })

    if ride.driver:
        notify_driver_pool({
            "type":     "ride_update",
            "event":    "payment_received",
            "ride_id":  ride.id,
            "message":  "Rider payment completed!",
            "earnings": earnings,
        })


# ── Public service functions ──────────────────────────────────────────────────

def estimate_fare_from_locations(pickup: str, destination: str, vehicle_type: str = "Bike") -> tuple[dict, int]:
    if not pickup or not destination:
        return {"error": "Both pickup and destination are required"}, 400
    distance_km, duration_min = google_distance(pickup, destination)
    if distance_km is None:
        return {"error": "Could not calculate route. Check addresses"}, 400
    return calculate_ride_fare(distance_km, duration_min, vehicle_type), 200


def initiate_checkout_for_ride(
    passenger: User, ride_id: int, callback_url: str | None = None
) -> tuple[dict, int]:
    try:
        ride = RideRequest.objects.get(id=ride_id, passenger=passenger)
    except RideRequest.DoesNotExist:
        return {"status": "error", "error": "Ride not found"}, 404

    if ride.status != "completed":
        return {"status": "error", "error": f"Ride must be completed before payment (status: {ride.status})"}, 400
    if ride.payment_status == "paid":
        return {"status": "error", "error": "Payment already completed"}, 400

    credit_to_apply = _wallet_credit_to_apply(ride)
    if credit_to_apply > 0 and credit_to_apply >= ride.total_fare:
        # Wallet credit covers the fare in full — no Paystack transaction
        # needed at all.
        _apply_wallet_only_payment(ride, credit_to_apply)
        return {
            "status": "success",
            "paid_via_wallet_credit": True,
            "ride_id": ride.id,
            "wallet_credit_applied": str(credit_to_apply),
        }, 200

    if credit_to_apply > 0:
        ride.wallet_credit_applied = credit_to_apply
        ride.save(update_fields=["wallet_credit_applied"])

    try:
        amount_due = ride.total_fare - credit_to_apply
        url = _create_payment_link(ride, callback_url=callback_url, amount_override=amount_due)
        logger.info("Payment link created ride_id=%s wallet_credit_applied=%s", ride.id, credit_to_apply)
        return {
            "status": "success",
            "payment_url": url,
            "ride_id": ride.id,
            "wallet_credit_applied": str(credit_to_apply),
        }, 200
    except PaymentError as e:
        logger.error("Payment link failed ride_id=%s: %s", ride_id, e)
        return {"status": "error", "error": str(e)}, 500


def handle_payment_callback(ride_id: int, query_params) -> str:
    """
    Verify Paystack callback, mark ride paid, notify via WebSocket.
    Returns a redirect path string.

    Deliberately ignores any `reference` the caller supplies (e.g. a URL
    query param) — that value is attacker-controllable, and trusting it
    would let someone reuse a valid, cheap Paystack reference of their own
    to "verify" a much more expensive ride. The only reference ever looked
    up is the one this ride's own checkout generated and stored server-side
    in _create_payment_link.
    """
    fail = "/rider-dashboard/?payment=failed"

    try:
        ride      = RideRequest.objects.get(id=ride_id)
        reference = ride.payment_reference

        if not reference:
            return f"{fail}&error=no_reference"

        try:
            response = requests.get(
                _VERIFY_URL.format(reference),
                headers=_auth_header(),
                timeout=_TIMEOUT,
            )
        except requests.RequestException as e:
            logger.error("Paystack verify request failed: %s", e)
            return f"{fail}&error=request_failed"

        if response.status_code != 200:
            return f"{fail}&error=http_{response.status_code}"

        data            = response.json()
        paystack_status = data.get("data", {}).get("status")

        if not (data.get("status") and paystack_status == "success"):
            logger.error("Paystack verification failed status=%s", paystack_status)
            return f"{fail}&error=paystack_{paystack_status}"

        amount = data.get("data", {}).get("amount")
        if not _apply_verified_online_payment(ride, reference, amount):
            return f"{fail}&error=amount_mismatch"

        ride.refresh_from_db()
        return f"/rider-dashboard/?payment=success&amount={ride.total_fare}&ride_id={ride.id}"

    except RideRequest.DoesNotExist:
        logger.error("handle_payment_callback: ride %s not found", ride_id)
        return f"{fail}&error=ride_not_found"
    except Exception:
        logger.exception("handle_payment_callback unexpected error ride_id=%s", ride_id)
        return f"{fail}&error=unexpected"


def refund_ride_payment(ride: RideRequest, reason: str = "") -> tuple[dict, int]:
    """Issues a real refund through Paystack for a ride that was genuinely
    paid online — "refunded" existed only as a status label until now;
    nothing actually issued one. Cash never touches Paystack, so there's
    nothing here to refund automatically — that has to be handled directly
    with the rider, same as any other cash dispute."""
    if ride.payment_method != "online":
        return {
            "status": "error",
            "error": "Only online (card) payments can be refunded automatically. "
                     "settle a cash ride directly with the rider.",
        }, 400
    if ride.payment_status != "paid":
        return {"status": "error", "error": f"Ride isn't marked paid (status: {ride.payment_status})"}, 400
    if not ride.payment_reference:
        return {"status": "error", "error": "No payment reference on this ride"}, 400

    payload = {"transaction": ride.payment_reference}
    if reason:
        payload["customer_note"] = reason[:180]  # Paystack's own field length limit

    try:
        response = requests.post(_REFUND_URL, headers=_auth_header(), json=payload, timeout=_TIMEOUT)
    except requests.RequestException as e:
        logger.error("Refund request failed ride_id=%s: %s", ride.id, e)
        return {"status": "error", "error": "Could not reach Paystack"}, 502

    data = response.json() if response.content else {}
    if response.status_code not in (200, 201) or not data.get("status"):
        logger.error(
            "Paystack refund failed ride_id=%s status=%s body=%s", ride.id, response.status_code, data,
        )
        return {"status": "error", "error": data.get("message") or "Refund failed"}, 502

    ride.payment_status = "refunded"
    ride.save(update_fields=["payment_status"])
    logger.info("Ride %s refunded via Paystack reference=%s", ride.id, ride.payment_reference)
    return {"status": "success", "message": "Refund initiated"}, 200


def initiate_cash_payment(passenger: User, ride_id: int) -> tuple[dict, int]:
    """Rider chooses to pay cash — generates a code only they can see, to
    be disclosed to the driver in person once cash is handed over."""
    if not settings.CASH_PAYMENTS_ENABLED:
        return {"status": "error", "error": "Cash payments aren't available right now. Please pay online."}, 403
    try:
        ride = RideRequest.objects.get(id=ride_id, passenger=passenger)
    except RideRequest.DoesNotExist:
        return {"status": "error", "error": "Ride not found"}, 404

    if ride.status != "completed":
        return {"status": "error", "error": f"Ride must be completed before payment (status: {ride.status})"}, 400
    if ride.payment_status == "paid":
        return {"status": "error", "error": "Payment already completed"}, 400

    code = f"{secrets.randbelow(10_000):04d}"
    ride.payment_method = "cash"
    ride.cash_confirmation_code = code
    ride.cash_confirmation_attempts = 0
    ride.save(update_fields=["payment_method", "cash_confirmation_code", "cash_confirmation_attempts"])
    logger.info("Cash payment code generated ride_id=%s", ride.id)
    return {"status": "success", "code": code, "ride_id": ride.id}, 200


def confirm_cash_payment(driver: User, ride_id: int, code: str) -> tuple[dict, int]:
    """Driver enters the code the rider disclosed to them. Doesn't prove
    cash physically changed hands — but does mean neither party can
    unilaterally mark the ride paid without the other's participation."""
    try:
        ride = RideRequest.objects.get(id=ride_id, driver=driver)
    except RideRequest.DoesNotExist:
        return {"status": "error", "error": "Ride not found"}, 404

    if ride.payment_method != "cash" or not ride.cash_confirmation_code:
        return {"status": "error", "error": "This ride isn't set up for cash payment yet"}, 400
    if ride.payment_status == "paid":
        return {"status": "error", "error": "Payment already completed"}, 400
    if ride.cash_confirmation_attempts >= CASH_CONFIRMATION_MAX_ATTEMPTS:
        return {"status": "error", "error": "Too many incorrect attempts. Ask the rider for a new code"}, 429

    if code.strip() != ride.cash_confirmation_code:
        ride.cash_confirmation_attempts += 1
        ride.save(update_fields=["cash_confirmation_attempts"])
        remaining = CASH_CONFIRMATION_MAX_ATTEMPTS - ride.cash_confirmation_attempts
        return {"status": "error", "error": f"Incorrect code. {max(remaining, 0)} attempt(s) left"}, 400

    with transaction.atomic():
        locked = RideRequest.objects.select_for_update().get(id=ride.id)
        if locked.payment_status != "paid":
            locked.payment_status = "paid"
            locked.paid_at = timezone.now()
            locked.save(update_fields=["payment_status", "paid_at"])

    ride.refresh_from_db()
    _notify_payment_completed(ride)
    _auto_resolve_nonpayment_dispute(ride)
    charge_cash_commission(ride)
    _maybe_credit_referral_reward(ride)
    logger.info("Cash payment confirmed ride_id=%s", ride.id)
    return {"status": "success", "message": "Cash payment confirmed", "ride_id": ride.id}, 200


def _notify_admin_of_dispute(dispute: PaymentDispute, event: str) -> None:
    """Emails whoever handles support (ADMIN_NOTIFICATION_EMAIL) so a human
    picks up the phone/WhatsApp conversation — resolving a payment dispute
    is a judgment call software shouldn't make unsupervised. Silently
    no-ops if no address is configured; the dispute is still fully visible
    in Django admin either way."""
    if not settings.ADMIN_NOTIFICATION_EMAIL:
        return

    ride = dispute.ride
    driver_phone = getattr(getattr(ride.driver, "driver", None), "phone_number", None) if ride.driver else None
    rider_phone = getattr(getattr(ride.passenger, "rider", None), "phone_number", None)
    admin_url = f"{settings.BASE_URL}/admin/gocabapp/paymentdispute/{dispute.id}/change/"

    try:
        send_admin_mail(
            subject=f"GoCab payment dispute, ride #{ride.id} ({event})",
            message=(
                f"Ride #{ride.id}: {ride.current_location} → {ride.destination}\n"
                f"Fare: ₦{ride.total_fare}\n\n"
                f"Driver: {ride.driver.driver.full_name if ride.driver and hasattr(ride.driver, 'driver') else 'Unknown'} "
                f"({driver_phone or 'no phone on file'})\n"
                f"Rider: {ride.passenger.rider.full_name if hasattr(ride.passenger, 'rider') else 'Unknown'} "
                f"({rider_phone or 'no phone on file'})\n\n"
                f"Driver's statement: {dispute.driver_statement or '(none given)'}\n"
                f"Rider's statement: {dispute.rider_statement or '(none given)'}\n\n"
                f"Review and resolve: {admin_url}"
            ),
            recipient_list=[settings.ADMIN_NOTIFICATION_EMAIL],
        )
    except Exception:
        # Never let a notification failure block the actual report/response.
        logger.exception("Failed to email admin about dispute on ride %s", ride.id)


def _maybe_auto_flag_rider_for_nonpayment(rider_user: User) -> None:
    """Repeat non-payment is a trust problem, not a one-off — a rider who's
    been reported this many times before (lifetime count) gets flagged the
    same way an admin manually flagging one does, so it takes a human to
    clear rather than just paying off whichever ride happens to be open
    right now. See fraud_checks.is_rider_flagged / RIDER_NONPAYMENT_AUTO_FLAG_COUNT."""
    if not hasattr(rider_user, "rider") or rider_user.rider.is_flagged:
        return
    report_count = PaymentDispute.objects.filter(
        ride__passenger=rider_user,
    ).exclude(driver_statement="").count()
    if report_count < settings.RIDER_NONPAYMENT_AUTO_FLAG_COUNT:
        return

    rider = rider_user.rider
    rider.is_flagged = True
    rider.flagged_reason = f"Auto-flagged: reported for non-payment {report_count} times."
    rider.save(update_fields=["is_flagged", "flagged_reason"])

    message = "Your account has been flagged after repeated non-payment reports. Contact support to continue booking."
    Notification.objects.filter(user=rider_user, is_active=True).delete()
    Notification.objects.create(user=rider_user, message=message, is_active=True)
    notify_notification_count(rider_user.id, 1)
    send_push_to_user(rider_user.id, "Account flagged", message)
    logger.warning("Rider auto-flagged for repeat non-payment: user_id=%s count=%s", rider_user.id, report_count)


def report_nonpayment(driver: User, ride_id: int, reason: str = "") -> tuple[dict, int]:
    """Driver reports a completed ride never got paid — no code was
    disclosed, or the rider paid online and then didn't. Doesn't decide or
    block anything by itself: a report from either side of a ride can be
    false or retaliatory, so this only opens a PaymentDispute (with the
    driver's side of the story) and notifies an admin — the actual block
    (payment_status -> "disputed", see fraud_checks.has_disputed_unpaid_ride)
    only happens if an admin reviews it and chooses to flag the account via
    PaymentDisputeAdmin.flag_rider."""
    try:
        ride = RideRequest.objects.get(id=ride_id, driver=driver)
    except RideRequest.DoesNotExist:
        return {"status": "error", "error": "Ride not found"}, 404

    if ride.status != "completed":
        return {"status": "error", "error": f"Ride must be completed first (status: {ride.status})"}, 400
    if ride.payment_status == "paid":
        return {"status": "error", "error": "This ride is already paid"}, 400
    if hasattr(ride, "dispute") and ride.dispute.status == "open":
        return {"status": "error", "error": "Already reported"}, 400

    ride.payment_status = "reported"
    ride.save(update_fields=["payment_status"])
    dispute, _ = PaymentDispute.objects.update_or_create(
        ride=ride, defaults={"driver_statement": reason, "status": "open"}
    )
    _notify_admin_of_dispute(dispute, "driver report")

    Notification.objects.filter(user=ride.passenger, is_active=True).delete()
    Notification.objects.create(
        user=ride.passenger,
        message=f"Your driver reported ride #{ride.id} as unpaid. Pay it to keep booking. "
                "An admin will also review the report.",
        is_active=True,
    )
    notify_notification_count(ride.passenger.id, 1)
    notify_rider(ride.id, {
        "type": "ride_update", "event": "payment_reported",
        "ride_id": ride.id, "message": "Your driver reported this ride as unpaid. Pay it to keep booking.",
    })

    _maybe_auto_flag_rider_for_nonpayment(ride.passenger)
    logger.info("Ride %s reported unpaid by driver=%s", ride.id, driver.id)
    return {"status": "success", "message": "Reported", "ride_id": ride.id}, 200


def _maybe_auto_flag_driver_for_reports(driver_user: User) -> None:
    """Mirrors _maybe_auto_flag_rider_for_nonpayment, other direction — a
    driver reported for conduct this many times before (lifetime count) gets
    flagged the same way an admin manually flagging one does. Separate from
    (and in addition to) the low-rating auto-flag in rating_service.py: a
    driver can trip this one on report volume alone, before their average
    rating ever gets bad enough to trip the other."""
    if not hasattr(driver_user, "driver") or driver_user.driver.is_flagged:
        return
    report_count = PaymentDispute.objects.filter(
        ride__driver=driver_user,
    ).exclude(rider_statement="").count()
    if report_count < settings.DRIVER_REPORT_AUTO_FLAG_COUNT:
        return

    driver = driver_user.driver
    driver.is_flagged = True
    driver.flagged_reason = f"Auto-flagged: reported by riders {report_count} times."
    driver.save(update_fields=["is_flagged", "flagged_reason"])

    message = "Your account has been flagged after repeated rider reports. Contact support before going online again."
    Notification.objects.filter(user=driver_user, is_active=True).delete()
    Notification.objects.create(user=driver_user, message=message, is_active=True)
    notify_notification_count(driver_user.id, 1)
    send_push_to_user(driver_user.id, "Account flagged", message)
    logger.warning("Driver auto-flagged for repeat reports: user_id=%s count=%s", driver_user.id, report_count)


def report_driver(rider: User, ride_id: int, reason: str) -> tuple[dict, int]:
    """Rider's counterpart to report_nonpayment — a conduct complaint about
    the driver, not a payment issue, so it never touches ride.payment_status.
    Same principle applies in this direction too: filing the report alone
    doesn't restrict the driver's account (drivers.is_flagged stays False)
    — it opens a PaymentDispute (with the rider's side of the story) and
    notifies an admin, who decides whether to flag the driver via
    PaymentDisputeAdmin.flag_driver."""
    try:
        ride = RideRequest.objects.get(id=ride_id, passenger=rider)
    except RideRequest.DoesNotExist:
        return {"status": "error", "error": "Ride not found"}, 404

    if not ride.driver_id:
        return {"status": "error", "error": "This ride has no driver to report"}, 400
    if not reason.strip():
        return {"status": "error", "error": "Describe what happened before submitting"}, 400
    if hasattr(ride, "dispute") and ride.dispute.status == "open":
        return {"status": "error", "error": "Already reported"}, 400

    dispute, _ = PaymentDispute.objects.update_or_create(
        ride=ride, defaults={"rider_statement": reason.strip(), "status": "open"}
    )
    _notify_admin_of_dispute(dispute, "rider report")

    if hasattr(ride.driver, "driver"):
        report_message = f"A rider reported ride #{ride.id}. An admin will review it."
        Notification.objects.filter(user=ride.driver, is_active=True).delete()
        Notification.objects.create(user=ride.driver, message=report_message, is_active=True)
        notify_notification_count(ride.driver.id, 1)
        send_push_to_user(ride.driver.id, "Ride reported", report_message)

    if hasattr(ride.driver, "driver"):
        _maybe_auto_flag_driver_for_reports(ride.driver)

    logger.info("Ride %s driver reported by rider=%s", ride.id, rider.id)
    return {"status": "success", "message": "Reported", "ride_id": ride.id}, 200


def respond_to_dispute(passenger: User, ride_id: int, statement: str) -> tuple[dict, int]:
    """Rider's side of an open dispute — e.g. 'I did pay in cash'. Doesn't
    clear the block by itself (a rider could otherwise always click this to
    instantly undo it); an admin reads both sides and resolves it."""
    try:
        ride = RideRequest.objects.get(id=ride_id, passenger=passenger)
    except RideRequest.DoesNotExist:
        return {"status": "error", "error": "Ride not found"}, 404

    try:
        dispute = ride.dispute
    except PaymentDispute.DoesNotExist:
        return {"status": "error", "error": "No dispute exists for this ride"}, 404

    if dispute.status != "open":
        return {"status": "error", "error": "This dispute has already been resolved"}, 400
    if not statement.strip():
        return {"status": "error", "error": "Enter a response before submitting"}, 400

    dispute.rider_statement = statement.strip()
    dispute.rider_responded_at = timezone.now()
    dispute.save(update_fields=["rider_statement", "rider_responded_at"])
    _notify_admin_of_dispute(dispute, "rider response")
    logger.info("Rider responded to dispute on ride %s", ride.id)
    return {"status": "success", "message": "Your response has been recorded for admin review"}, 200


def driver_respond_to_dispute(driver: User, ride_id: int, statement: str) -> tuple[dict, int]:
    """Driver's side of an open dispute — the counterpart to respond_to_dispute,
    for when a rider filed the report (report_driver) rather than the driver
    reporting non-payment. Same reasoning: doesn't resolve anything by
    itself, just adds the driver's statement for an admin to read alongside
    the rider's before picking an outcome in PaymentDisputeAdmin."""
    try:
        ride = RideRequest.objects.get(id=ride_id, driver=driver)
    except RideRequest.DoesNotExist:
        return {"status": "error", "error": "Ride not found"}, 404

    try:
        dispute = ride.dispute
    except PaymentDispute.DoesNotExist:
        return {"status": "error", "error": "No dispute exists for this ride"}, 404

    if dispute.status != "open":
        return {"status": "error", "error": "This dispute has already been resolved"}, 400
    if not statement.strip():
        return {"status": "error", "error": "Enter a response before submitting"}, 400

    dispute.driver_statement = statement.strip()
    dispute.driver_responded_at = timezone.now()
    dispute.save(update_fields=["driver_statement", "driver_responded_at"])
    _notify_admin_of_dispute(dispute, "driver response")
    logger.info("Driver responded to dispute on ride %s", ride.id)
    return {"status": "success", "message": "Your response has been recorded for admin review"}, 200