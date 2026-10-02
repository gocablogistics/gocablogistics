from __future__ import annotations

import json
import logging

from asgiref.sync import async_to_sync
from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from django.core.serializers.json import DjangoJSONEncoder
from django.db.models import Q

from ..models import Notification, RideRequest
from ..utils import DjangoSafeJSONEncoder

logger = logging.getLogger(__name__)


class RideUpdatesConsumer(AsyncWebsocketConsumer):
    """Per-ride WebSocket: subscribes to a single ride group. Originally
    rider-only, now also used by the driver's dashboard for live chat
    (see chat_message below) — subscribe is authorized per-ride so this
    being usable by either side doesn't let an unrelated user eavesdrop
    on someone else's ride."""

    async def connect(self):
        self.ride_group: str | None = None
        if self.scope["user"].is_anonymous:
            await self.close()
            return
        self.user = self.scope["user"]
        await self.accept()
        logger.info("RideUpdates connected user=%s", self.user.id)

    async def disconnect(self, close_code):
        if self.ride_group:
            await self.channel_layer.group_discard(self.ride_group, self.channel_name)

    async def receive(self, text_data):
        try:
            data = json.loads(text_data)
        except json.JSONDecodeError:
            return

        action = data.get("action")
        ride_id = data.get("ride_id")

        if action == "subscribe" and ride_id:
            if not await self._can_access_ride(ride_id):
                logger.warning(
                    "User %s tried to subscribe to ride %s they're not part of",
                    self.user.id, ride_id,
                )
                return
            # Leave previous group if re-subscribing
            if self.ride_group:
                await self.channel_layer.group_discard(
                    self.ride_group, self.channel_name
                )
            self.ride_group = f"ride_{ride_id}"
            await self.channel_layer.group_add(self.ride_group, self.channel_name)
            logger.info("User %s subscribed to %s", self.user.id, self.ride_group)

        elif action == "unsubscribe" and self.ride_group:
            await self.channel_layer.group_discard(self.ride_group, self.channel_name)
            self.ride_group = None

    async def ride_update(self, event):
        """Relay a ride_update group message to the WebSocket client. Some
        senders (driver_trip_service's run_start_trip/run_complete_trip)
        already build the full trip payload via ride_events.build_trip_payload
        and put it under "data" — pass that through as-is rather than
        discarding it and reconstructing a mostly-null object from top-level
        keys that only ride_signals.py's "accepted" event actually sets."""
        if event.get("data") is not None:
            data = event["data"]
        else:
            data = {
                "status": event.get("event"),
                "driver": event.get("driver"),
                "eta": event.get("eta"),
                "fare": _to_float(event.get("fare")),
                "distance": _to_float(event.get("distance")),
            }
        payload = {
            "type": "ride_update",
            "event": event.get("event"),
            "ride_id": event.get("ride_id"),
            "data": data,
        }
        await self.send(text_data=json.dumps(payload, cls=DjangoJSONEncoder))

    async def ride_accepted(self, event):
        """driver_trip_service.run_accept_ride sends this type — needs its
        own handler since Channels dispatches by the group message's exact
        `type`, not through ride_update."""
        payload = {
            "type": "ride_accepted",
            "ride_id": event.get("ride_id"),
            "message": event.get("message"),
        }
        await self.send(text_data=json.dumps(payload, cls=DjangoJSONEncoder))

    async def driver_location(self, event):
        """Live position for the map — deliberately its own message type
        rather than another (status, event) pair crammed into ride_update,
        since that channel already overloads "event" with several non-status
        strings (payment_completed, driver_cancelled, payment_disputed)."""
        payload = {
            "type": "driver_location",
            "ride_id": event.get("ride_id"),
            "lat": event.get("lat"),
            "lng": event.get("lng"),
            "eta_min": event.get("eta_min"),
            "distance_km": event.get("distance_km"),
        }
        await self.send(text_data=json.dumps(payload, cls=DjangoJSONEncoder))

    async def chat_message(self, event):
        """A message sent via POST /rides/{id}/messages, relayed live to
        whichever side (rider or driver) is subscribed to this ride's group
        and isn't the sender — the sender's own UI updates optimistically
        from the POST response instead of waiting for this echo."""
        payload = {
            "type": "chat_message",
            "id": event.get("id"),
            "ride_id": event.get("ride_id"),
            "sender_id": event.get("sender_id"),
            "sender_role": event.get("sender_role"),
            "text": event.get("text"),
            "created_at": event.get("created_at"),
        }
        await self.send(text_data=json.dumps(payload, cls=DjangoJSONEncoder))

    @database_sync_to_async
    def _can_access_ride(self, ride_id) -> bool:
        return RideRequest.objects.filter(
            Q(passenger_id=self.user.id) | Q(driver_id=self.user.id), id=ride_id
        ).exists()


class DriverUpdatesConsumer(AsyncWebsocketConsumer):
    """Driver-side WebSocket: joins the shared driver_updates pool."""

    DRIVER_GROUP = "driver_updates"

    async def connect(self):
        user = self.scope["user"]

        if user.is_anonymous:
            await self.close()
            return
        
        await self.accept()
    
        if not await self._is_driver(user):
            logger.warning("DriverUpdates rejected non-driver: user=%s", user.id)
            await self.close()
            return
        self.user = user
        self.personal_group = f"driver_{user.id}"
        await self.channel_layer.group_add(self.DRIVER_GROUP, self.channel_name)
        await self.channel_layer.group_add(self.personal_group, self.channel_name)
        logger.info("Driver %s joined %s", self.user.id, self.DRIVER_GROUP)

    async def disconnect(self, close_code):
        if hasattr(self, "user"):
            await self.channel_layer.group_discard(self.DRIVER_GROUP, self.channel_name)
            if hasattr(self, "personal_group"):
                await self.channel_layer.group_discard(self.personal_group, self.channel_name)

    async def receive(self, text_data):
        try:
            data = json.loads(text_data)
        except json.JSONDecodeError:
            return
        if data.get("type") == "heartbeat":
            await self.send(text_data=json.dumps({"type": "heartbeat_ack"}))

    # ---- channel-layer event handlers ----

    async def new_ride_request(self, event):
        await self._send(
            {
                "type": "new_ride_request",
                "event": "new_ride_request",
                "ride_id": event.get("ride_id"),
                "message": event.get("message", "New ride request available"),
            }
        )

    async def ride_accepted(self, event):
        await self._send(
            {
                "type": "ride_accepted",
                "event": "ride_accepted",
                "ride": event.get("ride"),
                "message": "Ride accepted successfully",
            }
        )

    async def ride_update(self, event):
        await self._send(
            {
                "type": "ride_update",
                "event": event.get("event"),
                "ride_id": event.get("ride_id"),
                "message": event.get("message"),
                "data": event.get("data"),
            }
        )

    async def ride_accepted_by_other(self, event):
        await self._send(
            {
                "type": "ride_accepted_by_other",
                "ride_id": event.get("ride_id"),
                "message": "This ride was accepted by another driver",
            }
        )

    async def ride_cancelled(self, event):
        await self._send(
            {
                "type": "ride_update",
                "event": "ride_cancelled",
                "ride_id": event.get("ride_id"),
                "message": "Ride was cancelled by passenger",
            }
        )

    async def driver_update(self, event):
        await self._send(dict(event))

    # ---- helpers ----

    async def _send(self, payload: dict):
        """Serialise and send; log on failure instead of silently swallowing."""
        try:
            await self.send(text_data=json.dumps(payload, cls=DjangoSafeJSONEncoder))
        except Exception:
            logger.exception(
                "DriverUpdatesConsumer._send failed for driver %s payload=%s",
                getattr(self, "user", {}).id if hasattr(self, "user") else "?",
                payload.get("type"),
            )

    @database_sync_to_async
    def _is_driver(self, user) -> bool:
        return hasattr(user, "driver")


class NotificationConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        user = self.scope["user"]
        if user.is_anonymous:
            await self.close()
            return
        self.user = user
        self.group = f"notifications_{user.id}"
        await self.channel_layer.group_add(self.group, self.channel_name)
        count = await self._notification_count()
        await self.accept()
        await self.send(text_data=json.dumps({"type": "counter", "count": count}))

    async def notification_update(self, event):
        """Forward a live notification-count change to the client. Same
        {"type": "counter", ...} shape as the initial connect message, so
        the frontend only needs to handle one shape."""
        await self.send(text_data=json.dumps({
            "type": "counter",
            "count": event.get("count", 0),
        }, cls=DjangoJSONEncoder))

    async def disconnect(self, close_code):
        if hasattr(self, "group"):
            await self.channel_layer.group_discard(self.group, self.channel_name)

    @database_sync_to_async
    def _notification_count(self) -> int:
        return Notification.objects.filter(user=self.user, is_active=True).count()


# ---- module-level util ----

def _to_float(value) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None