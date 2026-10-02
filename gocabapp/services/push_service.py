"""Firebase Cloud Messaging push notifications.

Fully no-op-safe until Firebase credentials exist (see FCM_CREDENTIALS_PATH /
FCM_CREDENTIALS_JSON in settings) — every function here checks
is_push_configured() first, so this module is mergeable and callable well
before any Firebase project exists. Once a token starts failing with an
"unregistered"-type error (app uninstalled, token rotated), the offending
DeviceToken row is flipped inactive rather than retried.
"""
from __future__ import annotations

import json
import logging

from django.conf import settings

from ..models import DeviceToken, RideRequest

logger = logging.getLogger(__name__)

_firebase_app = None
_init_attempted = False


def is_push_configured() -> bool:
    return bool(settings.FCM_CREDENTIALS_PATH or settings.FCM_CREDENTIALS_JSON)


def _get_app():
    """Lazy, once-only firebase_admin init. Returns None (and logs) on any
    failure — callers treat that exactly like "not configured"."""
    global _firebase_app, _init_attempted
    if _firebase_app is not None or _init_attempted:
        return _firebase_app
    _init_attempted = True

    if not is_push_configured():
        return None

    try:
        import firebase_admin
        from firebase_admin import credentials
    except ImportError:
        logger.error("firebase-admin not installed — push notifications disabled")
        return None

    try:
        if settings.FCM_CREDENTIALS_JSON:
            cred = credentials.Certificate(json.loads(settings.FCM_CREDENTIALS_JSON))
        else:
            cred = credentials.Certificate(settings.FCM_CREDENTIALS_PATH)
        _firebase_app = firebase_admin.initialize_app(cred)
        logger.info("firebase_admin initialized for push notifications")
    except Exception:
        logger.exception("Failed to initialize firebase_admin — push notifications disabled")
        _firebase_app = None

    return _firebase_app


def send_push_to_users(user_ids: list[int], title: str, body: str, data: dict | None = None) -> None:
    if not user_ids or _get_app() is None:
        return

    from firebase_admin import messaging

    tokens = list(
        DeviceToken.objects.filter(user_id__in=user_ids, is_active=True).values_list("id", "token")
    )
    if not tokens:
        return

    str_data = {k: str(v) for k, v in (data or {}).items()}
    stale_ids = []

    for token_id, token in tokens:
        message = messaging.Message(
            notification=messaging.Notification(title=title, body=body),
            data=str_data,
            token=token,
        )
        try:
            messaging.send(message)
        except messaging.UnregisteredError:
            stale_ids.append(token_id)
        except Exception:
            logger.exception("Push send failed token_id=%s", token_id)

    if stale_ids:
        DeviceToken.objects.filter(id__in=stale_ids).update(is_active=False)


def send_push_to_user(user_id: int, title: str, body: str, data: dict | None = None) -> None:
    send_push_to_users([user_id], title, body, data=data)


def _text(value, message: dict) -> str:
    return value(message) if callable(value) else value


# Keyed by (message["type"], message.get("event")) exactly as broadcast by
# ride_events.notify_rider / notify_driver_pool. An event absent from this
# table is a deliberate no-op (e.g. driver_location, which fires every
# ~15s) — new event types opt in here explicitly rather than being pushed
# by default.
PUSH_TEMPLATES: dict[tuple[str, str | None], dict] = {
    ("ride_update", "accepted"): {
        "target": "passenger",
        "title": "Ride accepted",
        "body": lambda m: (
            f"{(m.get('driver') or {}).get('name') or 'Your driver'} accepted your ride and is on the way"
            + (f", about {m['eta']} min away" if m.get("eta") else "")
        ),
    },
    ("ride_update", "started"): {
        "target": "passenger", "title": "Ride started", "body": "Your ride has started",
    },
    ("ride_update", "driver_arrived"): {
        "target": "passenger", "title": "Driver arrived",
        "body": "Your driver has arrived at the pickup point",
    },
    ("ride_update", "completed"): {
        "target": "passenger", "title": "Ride completed", "body": "Your ride is complete",
    },
    ("ride_update", "cancelled"): {
        "target": "passenger", "title": "Ride cancelled", "body": "Your ride was cancelled",
    },
    ("ride_update", "driver_cancelled"): {
        "target": "passenger", "title": "Driver cancelled",
        "body": "Your driver cancelled. We're finding you another one",
    },
    ("ride_update", "payment_disputed"): {
        "target": "passenger", "title": "Account flagged",
        "body": lambda m: m.get("message") or "Your account was flagged pending a payment dispute.",
    },
    ("ride_update", "payment_completed"): {
        "target": "passenger", "title": "Dispute resolved",
        "body": lambda m: m.get("message") or "Your payment dispute was resolved.",
    },
    ("ride_update", "payment_reported"): {
        "target": "passenger", "title": "Payment reported",
        "body": lambda m: m.get("message") or "Your driver reported this ride as unpaid.",
    },
    ("ride_update", "payment_refunded"): {
        "target": "passenger", "title": "Payment refunded",
        "body": lambda m: m.get("message") or "Your payment was refunded.",
    },
    ("ride_accepted", None): {
        "target": "passenger", "title": "Ride accepted", "body": "A driver accepted your ride",
    },
    ("chat_message", None): {
        "target": "other_participant", "title": "New message",
        "body": lambda m: (m.get("text") or "")[:120],
    },
    ("new_ride_request", None): {
        "target": "explicit", "title": "New ride request", "body": "A ride is available near you",
    },
}


def push_for_event(ride_id: int | None, message: dict, target_user_ids: list[int] | None = None) -> None:
    """Best-effort push hook called by ride_events after every WS broadcast.
    Never raises — a push failure must never take down the WS send it
    piggybacks on."""
    if not is_push_configured():
        return

    template = PUSH_TEMPLATES.get((message.get("type"), message.get("event")))
    if not template:
        return

    title = _text(template["title"], message)
    body = _text(template["body"], message)
    target = template["target"]
    data = {"ride_id": str(ride_id)} if ride_id is not None else {}

    if target == "explicit":
        if target_user_ids:
            send_push_to_users(target_user_ids, title, body, data=data)
        return

    if ride_id is None:
        return

    if target == "passenger":
        try:
            passenger_id = RideRequest.objects.only("passenger_id").get(id=ride_id).passenger_id
        except RideRequest.DoesNotExist:
            return
        send_push_to_user(passenger_id, title, body, data=data)

    elif target == "other_participant":
        try:
            ride = RideRequest.objects.only("passenger_id", "driver_id").get(id=ride_id)
        except RideRequest.DoesNotExist:
            return
        sender_id = message.get("sender_id")
        recipient_id = ride.driver_id if sender_id == ride.passenger_id else ride.passenger_id
        if recipient_id:
            send_push_to_user(recipient_id, title, body, data=data)
