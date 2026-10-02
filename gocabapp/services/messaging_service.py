"""In-ride chat between the passenger and driver, delivered live over the
same ride_{id} channel-layer group RideUpdatesConsumer already relays
status/location events through (see ride_events.notify_rider)."""
from __future__ import annotations

import logging

from django.contrib.auth.models import User

from ..models import RideMessage, RideRequest
from .ride_events import notify_rider

logger = logging.getLogger(__name__)

MAX_MESSAGE_LENGTH = 1000


def _sender_role(ride: RideRequest, sender_id: int) -> str:
    return "driver" if sender_id == ride.driver_id else "rider"


def _serialize(message: RideMessage, ride: RideRequest) -> dict:
    return {
        "id": message.id,
        "ride_id": ride.id,
        "sender_id": message.sender_id,
        "sender_role": _sender_role(ride, message.sender_id),
        "text": message.text,
        # ISO string, not a raw datetime — the channel layer's own
        # serializer (msgpack/json, depending on backend) can't encode a
        # datetime object, and Ninja's response schema parses an ISO
        # string into its `created_at: datetime` field just fine anyway.
        "created_at": message.created_at.isoformat(),
    }


def get_ride_for_participant(user: User, ride_id: int) -> RideRequest:
    """Raises RideRequest.DoesNotExist / PermissionError — callers translate
    those to 404 / 403."""
    ride = RideRequest.objects.get(id=ride_id)
    if user.id not in (ride.passenger_id, ride.driver_id):
        raise PermissionError("Not part of this ride")
    return ride


def list_messages(ride: RideRequest) -> list[dict]:
    return [_serialize(m, ride) for m in ride.messages.all()]


def send_message(user: User, ride: RideRequest, text: str) -> dict:
    text = text.strip()
    if not text:
        raise ValueError("Message can't be empty")
    if len(text) > MAX_MESSAGE_LENGTH:
        raise ValueError(f"Message must be under {MAX_MESSAGE_LENGTH} characters")

    message = RideMessage.objects.create(ride=ride, sender=user, text=text)
    payload = _serialize(message, ride)

    notify_rider(ride.id, {"type": "chat_message", **payload})
    logger.info("Message sent ride_id=%s sender_id=%s", ride.id, user.id)
    return payload
