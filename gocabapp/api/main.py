import json
import secrets
import logging

from django.conf import settings
from django.http import HttpResponse
from ninja import NinjaAPI
from ninja_extra.exceptions import APIException

from .auth.router import router as auth_router
from .notifications.router import router as notifications_router
from .rides.router import router as rides_router
from ..services.payment_service import handle_paystack_webhook, verify_paystack_signature
from ..services.payout_service import list_bank_options, run_weekly_payouts, send_weekly_payout_reminder
from ..services.stale_ride_service import sweep_stale_rides

logger = logging.getLogger(__name__)

api = NinjaAPI(
    title="GoCab API",
    version="1.0.0",
    description="Shared API for the GoCab web app, Android and iOS clients.",
    urls_namespace="api_v1",
)


@api.get("/config/maps-key")
def maps_key(request):
    # Public on purpose — Maps JS API keys are inherently client-exposed
    # (security is HTTP-referrer restriction in Google Cloud Console, not
    # secrecy). The legacy rider-dashboard-2.html already ships this same
    # key to the browser the same way.
    return {"key": settings.GOOGLE_MAPS_API_KEY or ""}


@api.get("/config/flags")
def feature_flags(request):
    # Public — the booking/payment UI needs this before (and regardless of)
    # auth to decide whether to even show a cash option.
    return {
        "cash_payments_enabled": settings.CASH_PAYMENTS_ENABLED,
        "no_drivers_message_minutes": settings.NO_DRIVERS_MESSAGE_MINUTES,
        "support_phone_number": settings.SUPPORT_PHONE_NUMBER,
        "instant_cashout_fee": settings.INSTANT_CASHOUT_FEE,
        "instant_cashout_min_balance": settings.INSTANT_CASHOUT_MIN_BALANCE,
    }


@api.get("/config/banks")
def banks(request):
    # Public, same as /config/maps-key — the driver signup form needs this
    # list before the driver has an account/token to authenticate with.
    return {"banks": list_bank_options()}


@api.post("/webhooks/paystack")
def paystack_webhook(request):
    # Server-to-server only — Paystack can't send our JWT, so this endpoint
    # is intentionally unauthenticated. Its ONLY real protection is the
    # signature check below; do not add logic here that trusts the payload
    # before that check passes.
    signature = request.headers.get("x-paystack-signature")
    if not verify_paystack_signature(request.body, signature):
        logger.warning("Rejected Paystack webhook with invalid/missing signature")
        return HttpResponse(status=401)

    try:
        event = json.loads(request.body)
    except json.JSONDecodeError:
        return HttpResponse(status=400)

    try:
        handle_paystack_webhook(event)
    except Exception:
        logger.exception("Unhandled error processing Paystack webhook")
        # Still 200 — Paystack retries on non-2xx, and retrying a payload
        # that fails the same way every time just wastes their retry budget.
        # The error is logged for us to investigate directly.
    return HttpResponse(status=200)


@api.post("/internal/sweep-stale-rides")
def sweep_stale_rides_endpoint(request):
    # Server-to-server only, hit on a schedule by a GitHub Actions cron job
    # regardless of where the app itself ends up hosted. No user/JWT to
    # authenticate as, so this is checked the same way the Paystack webhook
    # checks its signature — a missing/unset secret always 401s, it never
    # silently allows an unauthenticated call through.
    provided = request.headers.get("x-sweep-secret")
    if not settings.STALE_SWEEP_SECRET or provided != settings.STALE_SWEEP_SECRET:
        return HttpResponse(status=401)
    return sweep_stale_rides()


@api.post("/internal/run-weekly-payouts")
def run_weekly_payouts_endpoint(request):
    # Same server-to-server pattern as the sweep above. A GitHub Actions
    # cron hits this weekly regardless of where the app is hosted. Reuses
    # STALE_SWEEP_SECRET rather than adding a second secret to manage; both
    # endpoints are equally "trusted internal cron caller", not two
    # different trust levels that need separating.
    #
    # Not actually on the schedule right now (see weekly-driver-payouts.yml,
    # which calls the reminder endpoint below instead) — automated payouts
    # move real money on a codebase that's still changing fast, so the
    # scheduled cron only reminds a human to review and click this
    # themselves in Django admin. This endpoint stays live for that manual
    # click, and for whenever you're ready to let the cron call it directly.
    provided = request.headers.get("x-sweep-secret")
    if not settings.STALE_SWEEP_SECRET or provided != settings.STALE_SWEEP_SECRET:
        return HttpResponse(status=401)
    return run_weekly_payouts()


@api.post("/internal/send-weekly-payout-reminder")
def send_weekly_payout_reminder_endpoint(request):
    # What the Monday cron actually calls. See send_weekly_payout_reminder's
    # own docstring for why this stops short of running the real payout.
    provided = request.headers.get("x-sweep-secret")
    if not settings.STALE_SWEEP_SECRET or provided != settings.STALE_SWEEP_SECRET:
        return HttpResponse(status=401)
    return send_weekly_payout_reminder()


@api.exception_handler(APIException)
def handle_api_exception(request, exc: APIException):
    """Renders ninja-jwt's DRF-style exceptions (invalid/expired/blacklisted
    token, auth failures) as clean JSON instead of django-ninja's default
    str(exc) fallback."""
    return api.create_response(request, exc.detail, status=exc.status_code)


@api.exception_handler(Exception)
def handle_unexpected_exception(request, exc: Exception):
    """Last resort for anything genuinely unhandled (a real bug, a DB
    outage, whatever) — every HttpError raised throughout this API (by far
    the common case: validation, "already registered", throttling, ...)
    has its own specific message and status and is handled by Ninja's own
    built-in HttpError dispatch before this ever runs; this only fires for
    an exception type nothing else recognizes.

    Reports to Sentry (a no-op if SENTRY_DSN isn't set — see settings/base.py)
    and hands back its event id, so "our servers are busy" on screen comes
    with a code support can look up immediately instead of needing someone
    to screenshot a stack trace that was never shown to them anyway."""
    event_id = None
    if settings.SENTRY_DSN:
        import sentry_sdk

        event_id = sentry_sdk.capture_exception(exc)
    error_code = f"GC-{(event_id or secrets.token_hex(4)).upper()[:8]}"
    logger.exception(
        "Unhandled exception [%s] in API request: %s %s", error_code, request.method, request.path
    )
    return api.create_response(
        request,
        {
            "detail": "Something went wrong on our end. Please try again in a few moments.",
            "error_id": error_code,
        },
        status=500,
    )


api.add_router("/auth", auth_router)
api.add_router("/rides", rides_router)
api.add_router("/notifications", notifications_router)
