"""Router-level coverage for GET/POST /rides/{id}/messages — had zero
tests despite a real production bug fixed this session (the first message
from a driver was lost to a subscribe/broadcast race, and reconnects
dropped history). These don't test the websocket race itself (that fix
was a frontend refetch-on-reconnect, not backend-testable), but they do
lock in the two things the backend is actually responsible for: only
ride participants can read/send, and messages persist and come back in
order regardless of the live broadcast.
"""
import json
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase

from gocabapp.models import Rider, RideRequest


def _make_rider_and_driver_on_a_ride(suffix: str) -> tuple[User, User, RideRequest]:
    rider_user = User.objects.create_user(username=f"chatrider{suffix}", email=f"chatrider{suffix}@example.com")
    Rider.objects.create(user=rider_user, full_name=f"Rider {suffix}", phone_number=f"+23470000003{suffix}")
    driver_user = User.objects.create_user(username=f"chatdriver{suffix}", email=f"chatdriver{suffix}@example.com")
    ride = RideRequest.objects.create(
        passenger=rider_user, driver=driver_user, current_location="A", destination="B",
        status="accepted", vehicle_type="Bike", total_fare=Decimal("1000"),
    )
    return rider_user, driver_user, ride


def _auth_header(user: User) -> dict:
    from ninja_jwt.tokens import RefreshToken
    token = str(RefreshToken.for_user(user).access_token)
    return {"HTTP_AUTHORIZATION": f"Bearer {token}"}


class ChatMessagesTests(TestCase):
    def test_driver_can_send_and_rider_can_read_it_back(self):
        rider_user, driver_user, ride = _make_rider_and_driver_on_a_ride("1")

        send_response = self.client.post(
            f"/api/v1/rides/{ride.id}/messages",
            data=json.dumps({"text": "On my way"}),
            content_type="application/json",
            **_auth_header(driver_user),
        )
        self.assertEqual(send_response.status_code, 200)
        self.assertEqual(send_response.json()["sender_role"], "driver")

        read_response = self.client.get(f"/api/v1/rides/{ride.id}/messages", **_auth_header(rider_user))
        self.assertEqual(read_response.status_code, 200)
        messages = read_response.json()
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]["text"], "On my way")
        self.assertEqual(messages[0]["sender_role"], "driver")

    def test_a_stranger_to_the_ride_cannot_read_messages(self):
        _, _, ride = _make_rider_and_driver_on_a_ride("2")
        stranger = User.objects.create_user(username="chatstranger2", email="chatstranger2@example.com")
        response = self.client.get(f"/api/v1/rides/{ride.id}/messages", **_auth_header(stranger))
        self.assertEqual(response.status_code, 403)

    def test_a_stranger_to_the_ride_cannot_send_messages(self):
        _, _, ride = _make_rider_and_driver_on_a_ride("3")
        stranger = User.objects.create_user(username="chatstranger3", email="chatstranger3@example.com")
        response = self.client.post(
            f"/api/v1/rides/{ride.id}/messages",
            data=json.dumps({"text": "Hi"}),
            content_type="application/json",
            **_auth_header(stranger),
        )
        self.assertEqual(response.status_code, 403)

    def test_an_empty_message_is_rejected(self):
        _, driver_user, ride = _make_rider_and_driver_on_a_ride("4")
        response = self.client.post(
            f"/api/v1/rides/{ride.id}/messages",
            data=json.dumps({"text": "   "}),
            content_type="application/json",
            **_auth_header(driver_user),
        )
        self.assertEqual(response.status_code, 400)

    def test_messages_for_a_nonexistent_ride_is_a_404(self):
        rider = User.objects.create_user(username="chatrider5", email="chatrider5@example.com")
        response = self.client.get("/api/v1/rides/999999/messages", **_auth_header(rider))
        self.assertEqual(response.status_code, 404)

    def test_multiple_messages_come_back_in_order(self):
        rider_user, driver_user, ride = _make_rider_and_driver_on_a_ride("6")
        for text in ["first", "second", "third"]:
            self.client.post(
                f"/api/v1/rides/{ride.id}/messages",
                data=json.dumps({"text": text}),
                content_type="application/json",
                **_auth_header(rider_user),
            )
        response = self.client.get(f"/api/v1/rides/{ride.id}/messages", **_auth_header(driver_user))
        self.assertEqual([m["text"] for m in response.json()], ["first", "second", "third"])
