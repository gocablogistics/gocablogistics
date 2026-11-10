"""Router-level coverage for POST /rides/request — the actual booking
endpoint a rider's app calls. driver_trip_service's own tests cover
accept/start/complete/cancel once a ride already exists; nothing
previously exercised the booking endpoint itself, including its five
separate guard rails (throttled, unpaid ride, flagged, already has an
active ride, missing recipient phone) or the real IntegrityError race
fix (see router.py's own comment on it).
"""
import datetime
import json
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.db import IntegrityError
from django.test import TestCase

from gocabapp.models import Rider, RideRequest


def _make_rider(suffix: str) -> Rider:
    user = User.objects.create_user(username=f"bookrider{suffix}", email=f"bookrider{suffix}@example.com")
    return Rider.objects.create(user=user, full_name=f"Rider {suffix}", phone_number=f"+23470000002{suffix}")


def _auth_header(rider: Rider) -> dict:
    from ninja_jwt.tokens import RefreshToken
    token = str(RefreshToken.for_user(rider.user).access_token)
    return {"HTTP_AUTHORIZATION": f"Bearer {token}"}


_ROUTE_PATCH_TARGET = "gocabapp.api.rides.router.route_with_coords"
_FAKE_ROUTE = (5.0, 12.0, {"lat": 6.5, "lng": 3.3}, {"lat": 6.6, "lng": 3.4})


class RequestRideTests(TestCase):
    def test_books_a_ride_with_a_real_looking_route(self):
        rider = _make_rider("1")
        with patch(_ROUTE_PATCH_TARGET, return_value=_FAKE_ROUTE):
            response = self.client.post(
                "/api/v1/rides/request",
                data=json.dumps({
                    "current_location": "A", "destination": "B",
                    "recipient_phone_number": "08011112222",
                }),
                content_type="application/json",
                **_auth_header(rider),
            )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("ride_id", body)
        ride = RideRequest.objects.get(id=body["ride_id"])
        self.assertEqual(ride.status, "pending")
        self.assertEqual(ride.passenger_id, rider.user_id)

    def test_cannot_book_a_second_ride_while_one_is_already_active(self):
        rider = _make_rider("2")
        RideRequest.objects.create(
            passenger=rider.user, current_location="X", destination="Y",
            status="pending", vehicle_type="Bike", total_fare=Decimal("500"),
        )
        with patch(_ROUTE_PATCH_TARGET, return_value=_FAKE_ROUTE):
            response = self.client.post(
                "/api/v1/rides/request",
                data=json.dumps({
                    "current_location": "A", "destination": "B",
                    "recipient_phone_number": "08011112222",
                }),
                content_type="application/json",
                **_auth_header(rider),
            )
        self.assertEqual(response.status_code, 409)

    def test_cannot_book_with_an_unpaid_completed_ride_outstanding(self):
        rider = _make_rider("3")
        RideRequest.objects.create(
            passenger=rider.user, current_location="X", destination="Y",
            status="completed", payment_status="pending", vehicle_type="Bike",
            total_fare=Decimal("500"), completed_at=datetime.datetime.now(datetime.timezone.utc),
        )
        with patch(_ROUTE_PATCH_TARGET, return_value=_FAKE_ROUTE):
            response = self.client.post(
                "/api/v1/rides/request",
                data=json.dumps({
                    "current_location": "A", "destination": "B",
                    "recipient_phone_number": "08011112222",
                }),
                content_type="application/json",
                **_auth_header(rider),
            )
        self.assertEqual(response.status_code, 402)

    def test_flagged_rider_cannot_book(self):
        rider = _make_rider("4")
        rider.is_flagged = True
        rider.save(update_fields=["is_flagged"])
        with patch(_ROUTE_PATCH_TARGET, return_value=_FAKE_ROUTE):
            response = self.client.post(
                "/api/v1/rides/request",
                data=json.dumps({
                    "current_location": "A", "destination": "B",
                    "recipient_phone_number": "08011112222",
                }),
                content_type="application/json",
                **_auth_header(rider),
            )
        self.assertEqual(response.status_code, 403)

    def test_missing_recipient_phone_is_rejected(self):
        rider = _make_rider("5")
        with patch(_ROUTE_PATCH_TARGET, return_value=_FAKE_ROUTE):
            response = self.client.post(
                "/api/v1/rides/request",
                data=json.dumps({
                    "current_location": "A", "destination": "B",
                    "recipient_phone_number": "",
                }),
                content_type="application/json",
                **_auth_header(rider),
            )
        self.assertEqual(response.status_code, 400)

    def test_ungeocodable_route_returns_a_clean_400_not_a_crash(self):
        rider = _make_rider("6")
        with patch(_ROUTE_PATCH_TARGET, return_value=(None, None, None, None)):
            response = self.client.post(
                "/api/v1/rides/request",
                data=json.dumps({
                    "current_location": "nowhere real", "destination": "also nowhere",
                    "recipient_phone_number": "08011112222",
                }),
                content_type="application/json",
                **_auth_header(rider),
            )
        self.assertEqual(response.status_code, 400)

    def test_duplicate_active_ride_race_is_a_clean_409_not_a_500(self):
        """Regression test for the IntegrityError guard: the .exists()
        pre-check has a small race window (two near-simultaneous requests
        can both pass it before either row exists), so the DB's own
        one_active_ride_per_rider constraint is the real backstop. Forces
        that exact path by making .create() itself raise, regardless of
        what the pre-check saw — the most faithful way to simulate the
        race without disturbing the other guard checks, which share the
        same RideRequest.objects manager."""
        rider = _make_rider("7")
        with patch(_ROUTE_PATCH_TARGET, return_value=_FAKE_ROUTE), patch(
            "gocabapp.api.rides.router.RideRequest.objects.create",
            side_effect=IntegrityError(),
        ):
            response = self.client.post(
                "/api/v1/rides/request",
                data=json.dumps({
                    "current_location": "A", "destination": "B",
                    "recipient_phone_number": "08011112222",
                }),
                content_type="application/json",
                **_auth_header(rider),
            )
        self.assertEqual(response.status_code, 409)
