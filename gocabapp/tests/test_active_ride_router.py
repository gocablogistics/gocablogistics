"""Coverage for GET /rides/active (rider) and /rides/driver/active
(driver) — the screens both apps poll to resume tracking after a reload.
Neither had any test before this."""
import datetime
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone
from ninja_jwt.tokens import RefreshToken

from gocabapp.models import Driver, PaymentDispute, Rider, RideRequest


def _make_rider(suffix: str) -> Rider:
    user = User.objects.create_user(username=f"activerider{suffix}", email=f"activerider{suffix}@example.com")
    return Rider.objects.create(user=user, full_name=f"Rider {suffix}")


def _make_driver(suffix: str, **extra) -> Driver:
    user = User.objects.create_user(username=f"activedriver{suffix}", email=f"activedriver{suffix}@example.com")
    extra.setdefault("vehicle_type", "Bike")
    extra.setdefault("is_approved", True)
    extra.setdefault("vehicle_model", "Honda")
    extra.setdefault("license_plate", "ABC-123")
    return Driver.objects.create(
        user=user, full_name=f"Driver {suffix}", phone_number=f"+23479000000{suffix}",
        date_of_birth=datetime.date(1995, 1, 1),
        national_identification_number=f"ACTNIN{suffix}", bank_name="Test Bank",
        account_number=f"666665{suffix}0", account_holder_name=f"Driver {suffix}",
        **extra,
    )


def _auth_header(user: User) -> dict:
    token = str(RefreshToken.for_user(user).access_token)
    return {"HTTP_AUTHORIZATION": f"Bearer {token}"}


class RiderActiveRideTests(TestCase):
    def test_no_active_ride_is_a_404(self):
        rider = _make_rider("1")
        response = self.client.get("/api/v1/rides/active", **_auth_header(rider.user))
        self.assertEqual(response.status_code, 404)

    def test_returns_the_pending_ride_with_no_driver_yet(self):
        rider = _make_rider("2")
        ride = RideRequest.objects.create(
            passenger=rider.user, current_location="A", destination="B",
            status="pending", vehicle_type="Bike", total_fare=Decimal("1000"),
        )
        response = self.client.get("/api/v1/rides/active", **_auth_header(rider.user))
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["ride_id"], ride.id)
        self.assertIsNone(body["driver"])

    def test_returns_driver_info_once_accepted(self):
        rider = _make_rider("3")
        driver = _make_driver("3")
        RideRequest.objects.create(
            passenger=rider.user, driver=driver.user, current_location="A", destination="B",
            status="accepted", vehicle_type="Bike", total_fare=Decimal("1000"),
        )
        response = self.client.get("/api/v1/rides/active", **_auth_header(rider.user))
        driver_out = response.json()["driver"]
        self.assertEqual(driver_out["name"], "Driver 3")
        self.assertEqual(driver_out["car_model"], "Honda")
        self.assertEqual(driver_out["license_plate"], "ABC-123")

    def test_pickup_eta_only_present_while_accepted_not_once_started(self):
        rider = _make_rider("4")
        driver = _make_driver("4", latitude=6.3350, longitude=5.6037)
        ride = RideRequest.objects.create(
            passenger=rider.user, driver=driver.user, current_location="A", destination="B",
            status="started", vehicle_type="Bike", total_fare=Decimal("1000"),
            pickup_latitude=6.3350, pickup_longitude=5.6037,
        )
        response = self.client.get("/api/v1/rides/active", **_auth_header(rider.user))
        body = response.json()
        self.assertEqual(body["status"], "started")
        self.assertIsNone(body["pickup_eta_min"])

    def test_falls_back_to_an_unpaid_completed_ride_with_no_age_limit(self):
        rider = _make_rider("5")
        old_unpaid = RideRequest.objects.create(
            passenger=rider.user, current_location="A", destination="B",
            status="completed", vehicle_type="Bike", total_fare=Decimal("1000"),
            payment_status="pending",
            completed_at=timezone.now() - datetime.timedelta(days=30),
        )
        response = self.client.get("/api/v1/rides/active", **_auth_header(rider.user))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["ride_id"], old_unpaid.id)

    def test_falls_back_to_a_disputed_ride_over_a_merely_unpaid_one(self):
        """Both an unpaid-but-undisputed ride and a disputed one could
        match — the disputed one takes priority since it's the one
        actually blocking new bookings (see fraud_checks.has_disputed_unpaid_ride)."""
        rider = _make_rider("6")
        RideRequest.objects.create(
            passenger=rider.user, current_location="A", destination="B",
            status="completed", vehicle_type="Bike", total_fare=Decimal("1000"),
            payment_status="pending", completed_at=timezone.now() - datetime.timedelta(days=1),
        )
        disputed = RideRequest.objects.create(
            passenger=rider.user, current_location="A", destination="B",
            status="completed", vehicle_type="Bike", total_fare=Decimal("1000"),
            payment_status="disputed", completed_at=timezone.now() - datetime.timedelta(hours=1),
        )
        response = self.client.get("/api/v1/rides/active", **_auth_header(rider.user))
        self.assertEqual(response.json()["ride_id"], disputed.id)

    def test_a_paid_completed_ride_is_not_an_active_ride(self):
        rider = _make_rider("7")
        RideRequest.objects.create(
            passenger=rider.user, current_location="A", destination="B",
            status="completed", vehicle_type="Bike", total_fare=Decimal("1000"),
            payment_status="paid", completed_at=timezone.now(),
        )
        response = self.client.get("/api/v1/rides/active", **_auth_header(rider.user))
        self.assertEqual(response.status_code, 404)


class DriverActiveRideTests(TestCase):
    def test_requires_a_driver_profile(self):
        rider = _make_rider("8")
        response = self.client.get("/api/v1/rides/driver/active", **_auth_header(rider.user))
        self.assertEqual(response.status_code, 403)

    def test_no_active_ride_is_a_404(self):
        driver = _make_driver("8")
        response = self.client.get("/api/v1/rides/driver/active", **_auth_header(driver.user))
        self.assertEqual(response.status_code, 404)

    def test_returns_the_accepted_ride_with_passenger_info(self):
        driver = _make_driver("9")
        rider = _make_rider("9")
        ride = RideRequest.objects.create(
            passenger=rider.user, driver=driver.user, current_location="A", destination="B",
            status="accepted", vehicle_type="Bike", total_fare=Decimal("1000"),
        )
        response = self.client.get("/api/v1/rides/driver/active", **_auth_header(driver.user))
        body = response.json()
        self.assertEqual(body["ride_id"], ride.id)
        self.assertEqual(body["passenger"]["name"], "Rider 9")

    def test_a_just_completed_unpaid_ride_still_shows_within_the_grace_window(self):
        driver = _make_driver("10")
        rider = _make_rider("10")
        ride = RideRequest.objects.create(
            passenger=rider.user, driver=driver.user, current_location="A", destination="B",
            status="completed", vehicle_type="Bike", total_fare=Decimal("1000"),
            payment_status="pending", completed_at=timezone.now(),
        )
        response = self.client.get("/api/v1/rides/driver/active", **_auth_header(driver.user))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["ride_id"], ride.id)

    def test_a_completed_unpaid_ride_disappears_after_the_grace_window(self):
        driver = _make_driver("11")
        rider = _make_rider("11")
        RideRequest.objects.create(
            passenger=rider.user, driver=driver.user, current_location="A", destination="B",
            status="completed", vehicle_type="Bike", total_fare=Decimal("1000"),
            payment_status="pending",
            completed_at=timezone.now() - datetime.timedelta(seconds=601),
        )
        response = self.client.get("/api/v1/rides/driver/active", **_auth_header(driver.user))
        self.assertEqual(response.status_code, 404)

    def test_a_paid_completed_ride_is_never_shown_even_within_the_window(self):
        driver = _make_driver("12")
        rider = _make_rider("12")
        RideRequest.objects.create(
            passenger=rider.user, driver=driver.user, current_location="A", destination="B",
            status="completed", vehicle_type="Bike", total_fare=Decimal("1000"),
            payment_status="paid", completed_at=timezone.now(),
        )
        response = self.client.get("/api/v1/rides/driver/active", **_auth_header(driver.user))
        self.assertEqual(response.status_code, 404)

    def test_another_drivers_ride_never_shows_up(self):
        driver = _make_driver("13")
        other_driver = _make_driver("14")
        rider = _make_rider("13")
        RideRequest.objects.create(
            passenger=rider.user, driver=other_driver.user, current_location="A", destination="B",
            status="accepted", vehicle_type="Bike", total_fare=Decimal("1000"),
        )
        response = self.client.get("/api/v1/rides/driver/active", **_auth_header(driver.user))
        self.assertEqual(response.status_code, 404)
