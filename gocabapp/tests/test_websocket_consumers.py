"""Coverage for the WebSocket layer — ws_auth.py's JWTAuthMiddleware and
the three consumers in consumers.py — none of which had any test before
this, despite being the real-time backbone for chat, ride-status updates,
driver dispatch, and live notification counts.

Built against a test-local ASGI app (JWTAuthMiddlewareStack wrapping the
real URLRouter from routing.py) rather than Gocabservices.asgi.application,
since that module hardcodes settings.production at import time — this
way the test runs under settings.test's in-memory channel layer instead.
"""
import asyncio
import datetime
from decimal import Decimal

from channels.db import database_sync_to_async
from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator
from django.contrib.auth.models import User
from django.test import TestCase
from ninja_jwt.tokens import RefreshToken

import gocabapp.routing
from gocabapp.models import Driver, Notification, Rider, RideRequest
from gocabapp.services.ride_events import notify_driver_pool, notify_notification_count, notify_rider
from gocabapp.ws_auth import JWTAuthMiddlewareStack

application = JWTAuthMiddlewareStack(URLRouter(gocabapp.routing.websocket_urlpatterns))


def _make_rider(suffix: str) -> Rider:
    user = User.objects.create_user(username=f"wsrider{suffix}", email=f"wsrider{suffix}@example.com")
    return Rider.objects.create(user=user, full_name=f"Rider {suffix}")


def _make_driver(suffix: str, **extra) -> Driver:
    user = User.objects.create_user(username=f"wsdriver{suffix}", email=f"wsdriver{suffix}@example.com")
    return Driver.objects.create(
        user=user, full_name=f"Driver {suffix}", phone_number=f"+23471100000{suffix}",
        date_of_birth=datetime.date(1995, 1, 1), vehicle_type="Bike",
        national_identification_number=f"WSNIN{suffix}", bank_name="Test Bank",
        account_number=f"666115{suffix}0", account_holder_name=f"Driver {suffix}", is_approved=True,
        **extra,
    )


def _token(user: User) -> str:
    # RefreshToken.for_user writes an OutstandingToken row — a real DB
    # write, so this (like every other fixture helper here) can only run
    # via database_sync_to_async from inside an async test method.
    return str(RefreshToken.for_user(user).access_token)


async def _amake_rider(suffix: str) -> Rider:
    return await database_sync_to_async(_make_rider)(suffix)


async def _amake_driver(suffix: str, **extra) -> Driver:
    return await database_sync_to_async(_make_driver)(suffix, **extra)


async def _atoken(user: User) -> str:
    return await database_sync_to_async(_token)(user)


class JWTAuthMiddlewareTests(TestCase):
    async def test_a_valid_token_connects_as_the_right_user(self):
        rider = await _amake_rider("1")
        token = await _atoken(rider.user)
        comm = WebsocketCommunicator(application, f"/ws/notifications/?token={token}")
        connected, _ = await comm.connect()
        self.assertTrue(connected)
        await comm.disconnect()

    async def test_no_token_at_all_is_rejected(self):
        comm = WebsocketCommunicator(application, "/ws/notifications/")
        connected, _ = await comm.connect()
        self.assertFalse(connected)

    async def test_a_garbage_token_is_rejected(self):
        comm = WebsocketCommunicator(application, "/ws/notifications/?token=not-a-real-token")
        connected, _ = await comm.connect()
        self.assertFalse(connected)

    async def test_an_inactive_users_still_valid_token_is_rejected(self):
        """Regression test for the exact bug ws_auth.py's own comment
        describes: a banned/deleted account must not be able to keep a
        socket open (or open a new one) just because its access token
        hasn't technically expired yet."""
        rider = await _amake_rider("2")
        token = await _atoken(rider.user)  # minted while still active
        rider.user.is_active = False
        await database_sync_to_async(rider.user.save)(update_fields=["is_active"])

        comm = WebsocketCommunicator(application, f"/ws/notifications/?token={token}")
        connected, _ = await comm.connect()
        self.assertFalse(connected)


class NotificationConsumerTests(TestCase):
    async def test_connect_immediately_sends_the_current_unread_count(self):
        rider = await _amake_rider("3")
        await database_sync_to_async(Notification.objects.create)(
            user=rider.user, message="hello", is_active=True,
        )
        token = await _atoken(rider.user)
        comm = WebsocketCommunicator(application, f"/ws/notifications/?token={token}")
        connected, _ = await comm.connect()
        self.assertTrue(connected)
        message = await comm.receive_json_from()
        self.assertEqual(message, {"type": "counter", "count": 1})
        await comm.disconnect()

    async def test_receives_a_live_count_update(self):
        rider = await _amake_rider("4")
        token = await _atoken(rider.user)
        comm = WebsocketCommunicator(application, f"/ws/notifications/?token={token}")
        await comm.connect()
        await comm.receive_json_from()  # the initial counter on connect

        await database_sync_to_async(notify_notification_count)(rider.user.id, 3)
        message = await comm.receive_json_from()
        self.assertEqual(message, {"type": "counter", "count": 3})
        await comm.disconnect()

    async def test_does_not_receive_another_users_count_update(self):
        rider = await _amake_rider("5")
        other = await _amake_rider("6")
        token = await _atoken(rider.user)
        comm = WebsocketCommunicator(application, f"/ws/notifications/?token={token}")
        await comm.connect()
        await comm.receive_json_from()

        await database_sync_to_async(notify_notification_count)(other.user.id, 7)
        self.assertTrue(await comm.receive_nothing(timeout=0.2))
        await comm.disconnect()


class RideUpdatesConsumerTests(TestCase):
    async def _make_ride(self, rider: Rider, driver: Driver = None) -> RideRequest:
        return await database_sync_to_async(RideRequest.objects.create)(
            passenger=rider.user, driver=driver.user if driver else None,
            current_location="A", destination="B", status="accepted",
            vehicle_type="Bike", total_fare=Decimal("1000"),
        )

    async def test_anonymous_connection_is_rejected(self):
        comm = WebsocketCommunicator(application, "/ws/ride/updates/")
        connected, _ = await comm.connect()
        self.assertFalse(connected)

    async def test_subscribing_to_your_own_ride_receives_its_updates(self):
        rider = await _amake_rider("7")
        driver = await _amake_driver("1")
        ride = await self._make_ride(rider, driver)
        token = await _atoken(rider.user)

        comm = WebsocketCommunicator(application, f"/ws/ride/updates/?token={token}")
        await comm.connect()
        await comm.send_json_to({"action": "subscribe", "ride_id": ride.id})
        # Lets the consumer's own async subscribe handling (the
        # permission check + channel_layer.group_add) actually finish
        # before this test fires a group message at it — send_json_to
        # only enqueues the frame, it doesn't wait for the consumer to
        # finish processing it.
        await asyncio.sleep(0.05)

        await database_sync_to_async(notify_rider)(ride.id, {
            "type": "ride_update", "event": "driver_arrived", "ride_id": ride.id,
        })
        message = await comm.receive_json_from()
        self.assertEqual(message["type"], "ride_update")
        self.assertEqual(message["event"], "driver_arrived")
        await comm.disconnect()

    async def test_the_assigned_driver_can_also_subscribe_to_the_same_ride(self):
        rider = await _amake_rider("8")
        driver = await _amake_driver("2")
        ride = await self._make_ride(rider, driver)
        token = await _atoken(driver.user)

        comm = WebsocketCommunicator(application, f"/ws/ride/updates/?token={token}")
        await comm.connect()
        await comm.send_json_to({"action": "subscribe", "ride_id": ride.id})
        # Lets the consumer's own async subscribe handling (the
        # permission check + channel_layer.group_add) actually finish
        # before this test fires a group message at it — send_json_to
        # only enqueues the frame, it doesn't wait for the consumer to
        # finish processing it.
        await asyncio.sleep(0.05)

        await database_sync_to_async(notify_rider)(ride.id, {
            "type": "ride_update", "event": "something_happened", "ride_id": ride.id,
        })
        message = await comm.receive_json_from()
        self.assertEqual(message["event"], "something_happened")
        await comm.disconnect()

    async def test_cannot_subscribe_to_a_ride_you_are_not_part_of(self):
        rider = await _amake_rider("9")
        stranger = await _amake_rider("10")
        ride = await self._make_ride(rider)
        token = await _atoken(stranger.user)

        comm = WebsocketCommunicator(application, f"/ws/ride/updates/?token={token}")
        await comm.connect()
        await comm.send_json_to({"action": "subscribe", "ride_id": ride.id})
        # Lets the consumer's own async subscribe handling (the
        # permission check + channel_layer.group_add) actually finish
        # before this test fires a group message at it — send_json_to
        # only enqueues the frame, it doesn't wait for the consumer to
        # finish processing it.
        await asyncio.sleep(0.05)

        await database_sync_to_async(notify_rider)(ride.id, {
            "type": "ride_update", "event": "should_not_arrive", "ride_id": ride.id,
        })
        # Silently ignored by the consumer (see RideUpdatesConsumer.receive) —
        # the connection itself stays open, it just never joins the group.
        self.assertTrue(await comm.receive_nothing(timeout=0.2))
        await comm.disconnect()

    async def test_unsubscribing_stops_further_messages(self):
        rider = await _amake_rider("11")
        ride = await self._make_ride(rider)
        token = await _atoken(rider.user)

        comm = WebsocketCommunicator(application, f"/ws/ride/updates/?token={token}")
        await comm.connect()
        await comm.send_json_to({"action": "subscribe", "ride_id": ride.id})
        # Lets the consumer's own async subscribe handling (the
        # permission check + channel_layer.group_add) actually finish
        # before this test fires a group message at it — send_json_to
        # only enqueues the frame, it doesn't wait for the consumer to
        # finish processing it.
        await asyncio.sleep(0.05)
        await comm.send_json_to({"action": "unsubscribe"})
        await asyncio.sleep(0.05)

        await database_sync_to_async(notify_rider)(ride.id, {
            "type": "ride_update", "event": "too_late", "ride_id": ride.id,
        })
        self.assertTrue(await comm.receive_nothing(timeout=0.2))
        await comm.disconnect()

    async def test_a_chat_message_relays_with_the_real_shape(self):
        rider = await _amake_rider("12")
        driver = await _amake_driver("3")
        ride = await self._make_ride(rider, driver)
        token = await _atoken(rider.user)

        comm = WebsocketCommunicator(application, f"/ws/ride/updates/?token={token}")
        await comm.connect()
        await comm.send_json_to({"action": "subscribe", "ride_id": ride.id})
        # Lets the consumer's own async subscribe handling (the
        # permission check + channel_layer.group_add) actually finish
        # before this test fires a group message at it — send_json_to
        # only enqueues the frame, it doesn't wait for the consumer to
        # finish processing it.
        await asyncio.sleep(0.05)

        await database_sync_to_async(notify_rider)(ride.id, {
            "type": "chat_message", "id": 1, "ride_id": ride.id,
            "sender_id": driver.user.id, "sender_role": "driver",
            "text": "On my way", "created_at": "2026-01-01T00:00:00Z",
        })
        message = await comm.receive_json_from()
        self.assertEqual(message["type"], "chat_message")
        self.assertEqual(message["text"], "On my way")
        await comm.disconnect()


class DriverUpdatesConsumerTests(TestCase):
    async def test_a_rider_is_accepted_then_immediately_closed(self):
        """The consumer calls accept() before it can check for a driver
        profile (it needs the socket open to call close() on), so connect()
        itself reports True — the real access-control signal is the
        websocket.close frame that follows right behind it."""
        rider = await _amake_rider("13")
        token = await _atoken(rider.user)
        comm = WebsocketCommunicator(application, f"/ws/driver/updates/?token={token}")
        connected, _ = await comm.connect()
        self.assertTrue(connected)
        output = await comm.receive_output(timeout=1)
        self.assertEqual(output["type"], "websocket.close")

    async def test_a_driver_receives_a_pool_wide_broadcast(self):
        driver = await _amake_driver("4")
        token = await _atoken(driver.user)
        comm = WebsocketCommunicator(application, f"/ws/driver/updates/?token={token}")
        connected, _ = await comm.connect()
        self.assertTrue(connected)
        # connect() returning True only confirms accept() ran — the
        # consumer's own driver-profile check and group_add calls run
        # afterward in the same coroutine and need a moment to finish.
        await asyncio.sleep(0.05)

        await database_sync_to_async(notify_driver_pool)(
            {"type": "new_ride_request", "ride_id": 42, "message": "New ride!"},
        )
        message = await comm.receive_json_from()
        self.assertEqual(message["type"], "new_ride_request")
        self.assertEqual(message["ride_id"], 42)
        await comm.disconnect()
