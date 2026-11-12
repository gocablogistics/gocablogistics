"""HTTP-layer coverage for the ride-lifecycle endpoints. The underlying
service functions (run_accept_ride, run_start_trip, run_complete_trip,
run_driver_cancel_ride) already have direct unit coverage in
test_driver_trip_service.py — this file is specifically for what only
exists at the router layer: the throttle/cash-debt/flagged guards in
front of /accept, and the rider's own /{ride_id}/cancel endpoint, which
had no coverage anywhere before this.
"""
import datetime
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.utils import timezone
from ninja_jwt.tokens import RefreshToken

from gocabapp.models import Driver, DriverCancellation, Rider, RideRequest


def _make_rider(suffix: str) -> Rider:
    user = User.objects.create_user(username=f"lcrider{suffix}", email=f"lcrider{suffix}@example.com")
    return Rider.objects.create(user=user, full_name=f"Rider {suffix}")


def _make_driver(suffix: str, **extra) -> Driver:
    user = User.objects.create_user(username=f"lcdriver{suffix}", email=f"lcdriver{suffix}@example.com")
    extra.setdefault("vehicle_type", "Bike")
    extra.setdefault("is_approved", True)
    return Driver.objects.create(
        user=user, full_name=f"Driver {suffix}", phone_number=f"+23470400000{suffix}",
        date_of_birth=datetime.date(1995, 1, 1),
        national_identification_number=f"LCNIN{suffix}", bank_name="Test Bank",
        account_number=f"111105{suffix}0", account_holder_name=f"Driver {suffix}",
        **extra,
    )


def _auth_header(user: User) -> dict:
    token = str(RefreshToken.for_user(user).access_token)
    return {"HTTP_AUTHORIZATION": f"Bearer {token}"}


def _pending_ride(rider: Rider) -> RideRequest:
    return RideRequest.objects.create(
        passenger=rider.user, current_location="A", destination="B",
        status="pending", vehicle_type="Bike", total_fare=Decimal("1000"),
    )


class AcceptRideRouterGuardsTests(TestCase):
    @override_settings(DRIVER_CANCELLATION_LIMIT=2)
    def test_a_driver_over_the_cancellation_limit_is_throttled(self):
        driver = _make_driver("1")
        rider = _make_rider("1")
        ride = _pending_ride(rider)
        for _ in range(2):
            DriverCancellation.objects.create(driver=driver.user)

        response = self.client.post(f"/api/v1/rides/{ride.id}/accept", **_auth_header(driver.user))
        self.assertEqual(response.status_code, 429)
        ride.refresh_from_db()
        self.assertEqual(ride.status, "pending")  # never actually accepted

    @override_settings(CASH_DEBT_BLOCK_THRESHOLD=5000)
    def test_a_driver_with_too_much_cash_debt_cannot_accept(self):
        driver = _make_driver("2", cash_debt=Decimal("6000"))
        rider = _make_rider("2")
        ride = _pending_ride(rider)

        response = self.client.post(f"/api/v1/rides/{ride.id}/accept", **_auth_header(driver.user))
        self.assertEqual(response.status_code, 402)

    def test_a_flagged_driver_cannot_accept(self):
        driver = _make_driver("3", is_flagged=True)
        rider = _make_rider("3")
        ride = _pending_ride(rider)

        response = self.client.post(f"/api/v1/rides/{ride.id}/accept", **_auth_header(driver.user))
        self.assertEqual(response.status_code, 403)

    def test_a_clean_driver_can_actually_accept(self):
        driver = _make_driver("4")
        rider = _make_rider("4")
        ride = _pending_ride(rider)

        response = self.client.post(f"/api/v1/rides/{ride.id}/accept", **_auth_header(driver.user))
        self.assertEqual(response.status_code, 200)
        ride.refresh_from_db()
        self.assertEqual(ride.status, "accepted")
        self.assertEqual(ride.driver_id, driver.user.id)


class StartCompleteDriverCancelRouterTests(TestCase):
    def test_start_requires_a_driver_profile(self):
        rider = _make_rider("5")
        response = self.client.post("/api/v1/rides/999/start", **_auth_header(rider.user))
        self.assertEqual(response.status_code, 403)

    def test_start_moves_an_accepted_ride_to_started(self):
        driver = _make_driver("5")
        rider = _make_rider("5")
        ride = RideRequest.objects.create(
            passenger=rider.user, driver=driver.user, current_location="A", destination="B",
            status="accepted", vehicle_type="Bike", total_fare=Decimal("1000"),
        )
        response = self.client.post(f"/api/v1/rides/{ride.id}/start", **_auth_header(driver.user))
        self.assertEqual(response.status_code, 200)
        ride.refresh_from_db()
        self.assertEqual(ride.status, "started")

    def test_complete_requires_a_driver_profile(self):
        rider = _make_rider("6")
        response = self.client.post("/api/v1/rides/999/complete", **_auth_header(rider.user))
        self.assertEqual(response.status_code, 403)

    def test_complete_moves_a_started_ride_to_completed(self):
        driver = _make_driver("6")
        rider = _make_rider("7")
        ride = RideRequest.objects.create(
            passenger=rider.user, driver=driver.user, current_location="A", destination="B",
            status="started", vehicle_type="Bike", total_fare=Decimal("1000"),
        )
        response = self.client.post(f"/api/v1/rides/{ride.id}/complete", **_auth_header(driver.user))
        self.assertEqual(response.status_code, 200)
        ride.refresh_from_db()
        self.assertEqual(ride.status, "completed")
        self.assertEqual(ride.payment_status, "pending")

    def test_driver_cancel_reopens_the_ride_for_other_drivers(self):
        driver = _make_driver("7", is_busy=True)
        rider = _make_rider("8")
        ride = RideRequest.objects.create(
            passenger=rider.user, driver=driver.user, current_location="A", destination="B",
            status="accepted", vehicle_type="Bike", total_fare=Decimal("1000"),
        )
        response = self.client.post(f"/api/v1/rides/{ride.id}/driver-cancel", **_auth_header(driver.user))
        self.assertEqual(response.status_code, 200)
        ride.refresh_from_db()
        self.assertEqual(ride.status, "pending")
        self.assertIsNone(ride.driver_id)
        driver.refresh_from_db()
        self.assertFalse(driver.is_busy)
        self.assertTrue(DriverCancellation.objects.filter(driver=driver.user, ride=ride).exists())

    def test_driver_cancel_for_a_non_driver_user_is_a_404_not_a_403(self):
        """Documents an existing inconsistency: unlike /start, /complete
        and /accept (which all check hasattr(user, "driver") and return
        403), run_driver_cancel_ride has no such guard — a non-driver
        user just never matches the driver=user filter, so this comes
        back as a plain "ride not found" 404 instead. Not unsafe (a rider
        still can't cancel anything this way), just a less specific
        error message than the sibling endpoints give."""
        rider = _make_rider("9")
        response = self.client.post("/api/v1/rides/999/driver-cancel", **_auth_header(rider.user))
        self.assertEqual(response.status_code, 404)


class RiderCancelRideRouterTests(TestCase):
    def test_cancelling_someone_elses_ride_is_a_404(self):
        rider = _make_rider("10")
        other_rider = _make_rider("11")
        ride = _pending_ride(other_rider)
        response = self.client.post(f"/api/v1/rides/{ride.id}/cancel", **_auth_header(rider.user))
        self.assertEqual(response.status_code, 404)
        ride.refresh_from_db()
        self.assertEqual(ride.status, "pending")

    def test_cancelling_a_started_ride_is_rejected(self):
        """Only pending/accepted can be rider-cancelled — once the trip
        has actually started, a cancellation has to go through
        report/dispute channels instead, not a plain cancel."""
        rider = _make_rider("12")
        driver = _make_driver("8")
        ride = RideRequest.objects.create(
            passenger=rider.user, driver=driver.user, current_location="A", destination="B",
            status="started", vehicle_type="Bike", total_fare=Decimal("1000"),
        )
        response = self.client.post(f"/api/v1/rides/{ride.id}/cancel", **_auth_header(rider.user))
        self.assertEqual(response.status_code, 404)
        ride.refresh_from_db()
        self.assertEqual(ride.status, "started")

    def test_cancelling_a_pending_ride_with_no_driver_yet_succeeds(self):
        rider = _make_rider("13")
        ride = _pending_ride(rider)
        response = self.client.post(f"/api/v1/rides/{ride.id}/cancel", **_auth_header(rider.user))
        self.assertEqual(response.status_code, 200)
        ride.refresh_from_db()
        self.assertEqual(ride.status, "cancelled")
        self.assertIsNotNone(ride.cancelled_at)

    def test_cancelling_an_accepted_ride_frees_the_assigned_driver(self):
        rider = _make_rider("14")
        driver = _make_driver("9", is_busy=True)
        ride = RideRequest.objects.create(
            passenger=rider.user, driver=driver.user, current_location="A", destination="B",
            status="accepted", vehicle_type="Bike", total_fare=Decimal("1000"),
        )
        response = self.client.post(f"/api/v1/rides/{ride.id}/cancel", **_auth_header(rider.user))
        self.assertEqual(response.status_code, 200)
        ride.refresh_from_db()
        self.assertEqual(ride.status, "cancelled")
        driver.refresh_from_db()
        self.assertFalse(driver.is_busy)
