"""Coverage for POST /rides/location (driver) and /rides/rider-location —
neither had any test before this. Driver-side is the more interesting
one: it's also where the "driver arrived at pickup" notification fires,
exactly once, only while the ride is still "accepted" (not once started).
"""
import datetime
import json
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from ninja_jwt.tokens import RefreshToken

from gocabapp.models import Driver, Notification, Rider, RideRequest

PICKUP_LAT, PICKUP_LNG = 6.3350, 5.6037
# Comfortably inside pickup_eta_service.ARRIVED_KM (0.08km) of the pickup
# point above — close enough to trigger the "arrived" path without a
# real Google Maps call (compute_pickup_eta returns eta_min=0 for
# anything this close, before ever reaching the network-calling branch).
VERY_CLOSE_LAT, VERY_CLOSE_LNG = 6.33505, 5.60375
# Nowhere near the pickup point or any real road network — used only
# where pickup coordinates are deliberately left unset, so
# compute_pickup_eta short-circuits on None coordinates rather than
# hitting the network.
FAR_LAT, FAR_LNG = 9.0765, 7.3986


def _make_rider(suffix: str) -> Rider:
    user = User.objects.create_user(username=f"locrider{suffix}", email=f"locrider{suffix}@example.com")
    return Rider.objects.create(user=user, full_name=f"Rider {suffix}")


def _make_driver(suffix: str, **extra) -> Driver:
    user = User.objects.create_user(username=f"locdriver{suffix}", email=f"locdriver{suffix}@example.com")
    extra.setdefault("vehicle_type", "Bike")
    extra.setdefault("is_approved", True)
    return Driver.objects.create(
        user=user, full_name=f"Driver {suffix}", phone_number=f"+23470200000{suffix}",
        date_of_birth=datetime.date(1995, 1, 1),
        national_identification_number=f"LOCNIN{suffix}", bank_name="Test Bank",
        account_number=f"888885{suffix}0", account_holder_name=f"Driver {suffix}",
        **extra,
    )


def _auth_header(user: User) -> dict:
    token = str(RefreshToken.for_user(user).access_token)
    return {"HTTP_AUTHORIZATION": f"Bearer {token}"}


class DriverLocationUpdateTests(TestCase):
    def test_requires_a_driver_profile(self):
        rider = _make_rider("1")
        response = self.client.post(
            "/api/v1/rides/location",
            data=json.dumps({"latitude": 1.0, "longitude": 2.0}),
            content_type="application/json",
            **_auth_header(rider.user),
        )
        self.assertEqual(response.status_code, 403)

    def test_updates_the_drivers_stored_location(self):
        driver = _make_driver("1")
        response = self.client.post(
            "/api/v1/rides/location",
            data=json.dumps({"latitude": FAR_LAT, "longitude": FAR_LNG, "address": "Somewhere"}),
            content_type="application/json",
            **_auth_header(driver.user),
        )
        self.assertEqual(response.status_code, 200)
        driver.refresh_from_db()
        self.assertEqual(driver.latitude, FAR_LAT)
        self.assertEqual(driver.longitude, FAR_LNG)
        self.assertEqual(driver.current_address, "Somewhere")

    def test_with_no_active_ride_just_updates_location_without_error(self):
        driver = _make_driver("2")
        response = self.client.post(
            "/api/v1/rides/location",
            data=json.dumps({"latitude": FAR_LAT, "longitude": FAR_LNG}),
            content_type="application/json",
            **_auth_header(driver.user),
        )
        self.assertEqual(response.status_code, 200)

    def test_arriving_at_pickup_while_accepted_notifies_the_rider_once(self):
        driver = _make_driver("3")
        rider = _make_rider("2")
        ride = RideRequest.objects.create(
            passenger=rider.user, driver=driver.user, current_location="A", destination="B",
            status="accepted", vehicle_type="Bike", total_fare=Decimal("1000"),
            pickup_latitude=PICKUP_LAT, pickup_longitude=PICKUP_LNG,
        )
        response = self.client.post(
            "/api/v1/rides/location",
            data=json.dumps({"latitude": VERY_CLOSE_LAT, "longitude": VERY_CLOSE_LNG}),
            content_type="application/json",
            **_auth_header(driver.user),
        )
        self.assertEqual(response.status_code, 200)
        ride.refresh_from_db()
        self.assertIsNotNone(ride.arrival_notified_at)
        self.assertTrue(
            Notification.objects.filter(
                user=rider.user, message__icontains="driver has arrived", is_active=True,
            ).exists()
        )

    def test_a_second_ping_at_pickup_does_not_re_notify(self):
        driver = _make_driver("4")
        rider = _make_rider("3")
        ride = RideRequest.objects.create(
            passenger=rider.user, driver=driver.user, current_location="A", destination="B",
            status="accepted", vehicle_type="Bike", total_fare=Decimal("1000"),
            pickup_latitude=PICKUP_LAT, pickup_longitude=PICKUP_LNG,
        )
        for _ in range(2):
            response = self.client.post(
                "/api/v1/rides/location",
                data=json.dumps({"latitude": VERY_CLOSE_LAT, "longitude": VERY_CLOSE_LNG}),
                content_type="application/json",
                **_auth_header(driver.user),
            )
            self.assertEqual(response.status_code, 200)
        self.assertEqual(
            Notification.objects.filter(user=rider.user, message__icontains="driver has arrived").count(),
            1,
        )

    def test_arriving_once_the_trip_has_started_does_not_fire_the_arrival_notification(self):
        """The arrival check only makes sense pre-pickup — once status is
        "started" the driver is already past that point, so this must not
        fire again even if the coordinates still happen to be close."""
        driver = _make_driver("5")
        rider = _make_rider("4")
        ride = RideRequest.objects.create(
            passenger=rider.user, driver=driver.user, current_location="A", destination="B",
            status="started", vehicle_type="Bike", total_fare=Decimal("1000"),
            pickup_latitude=PICKUP_LAT, pickup_longitude=PICKUP_LNG,
        )
        response = self.client.post(
            "/api/v1/rides/location",
            data=json.dumps({"latitude": VERY_CLOSE_LAT, "longitude": VERY_CLOSE_LNG}),
            content_type="application/json",
            **_auth_header(driver.user),
        )
        self.assertEqual(response.status_code, 200)
        ride.refresh_from_db()
        self.assertIsNone(ride.arrival_notified_at)
        self.assertFalse(Notification.objects.filter(user=rider.user).exists())


class RiderLocationUpdateTests(TestCase):
    def test_requires_a_rider_profile(self):
        driver = _make_driver("6")
        response = self.client.post(
            "/api/v1/rides/rider-location",
            data=json.dumps({"latitude": 1.0, "longitude": 2.0}),
            content_type="application/json",
            **_auth_header(driver.user),
        )
        self.assertEqual(response.status_code, 403)

    def test_updates_the_riders_stored_location(self):
        rider = _make_rider("5")
        response = self.client.post(
            "/api/v1/rides/rider-location",
            data=json.dumps({"latitude": FAR_LAT, "longitude": FAR_LNG}),
            content_type="application/json",
            **_auth_header(rider.user),
        )
        self.assertEqual(response.status_code, 200)
        rider.refresh_from_db()
        self.assertEqual(rider.latitude, FAR_LAT)
        self.assertEqual(rider.longitude, FAR_LNG)
