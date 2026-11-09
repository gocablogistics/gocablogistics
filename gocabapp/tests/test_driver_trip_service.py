"""Tests against the documented ride lifecycle in driver_trip_service.py:
accept, start, complete, cancel. Covers the state-transition guards (can't
skip or repeat a step, can't touch another driver's ride) and the two
real gaps found while reading this module: run_accept_ride didn't check
is_cash_debt_blocked/is_driver_flagged at all (an admin flagging an
already-online driver mid-shift never actually stopped them from
accepting new rides), and run_complete_trip silently created a real,
unused Paystack transaction on every single completion.
"""
import datetime
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from gocabapp.models import Driver, DriverCancellation, RideRequest
from gocabapp.services.driver_trip_service import (
    run_accept_ride,
    run_complete_trip,
    run_driver_cancel_ride,
    run_start_trip,
)


def _make_driver(suffix: str, is_flagged=False, cash_debt=0) -> Driver:
    user = User.objects.create_user(username=f"tripdriver{suffix}", email=f"tripdriver{suffix}@example.com")
    return Driver.objects.create(
        user=user, full_name=f"Driver {suffix}", phone_number=f"+23478000000{suffix}",
        date_of_birth=datetime.date(1995, 1, 1), vehicle_type="Bike",
        national_identification_number=f"TRIPNIN{suffix}", bank_name="Test Bank",
        account_number=f"555555{suffix}0", account_holder_name=f"Driver {suffix}",
        is_approved=True, is_flagged=is_flagged, cash_debt=Decimal(str(cash_debt)),
    )


def _make_pending_ride(rider_suffix: str) -> RideRequest:
    rider = User.objects.create_user(username=f"triprider{rider_suffix}", email=f"triprider{rider_suffix}@example.com")
    return RideRequest.objects.create(
        passenger=rider, current_location="A", destination="B",
        status="pending", vehicle_type="Bike", total_fare=Decimal("1000"),
    )


class RunAcceptRideTests(TestCase):
    def test_accepts_a_pending_ride_and_marks_the_driver_busy(self):
        driver = _make_driver("1")
        ride = _make_pending_ride("1")
        body, status = run_accept_ride(driver.user, ride.id)
        self.assertEqual(status, 200)
        ride.refresh_from_db()
        self.assertEqual(ride.status, "accepted")
        self.assertEqual(ride.driver_id, driver.user.id)
        driver.refresh_from_db()
        self.assertTrue(driver.is_busy)
        self.assertEqual(driver.current_ride_id, ride.id)

    def test_cannot_accept_with_an_existing_active_ride(self):
        driver = _make_driver("2")
        first = _make_pending_ride("2a")
        run_accept_ride(driver.user, first.id)
        second = _make_pending_ride("2b")
        body, status = run_accept_ride(driver.user, second.id)
        self.assertEqual(status, 400)
        second.refresh_from_db()
        self.assertEqual(second.status, "pending")

    def test_a_ride_someone_else_already_accepted_is_not_available(self):
        driver_a = _make_driver("3a")
        driver_b = _make_driver("3b")
        ride = _make_pending_ride("3")
        run_accept_ride(driver_a.user, ride.id)
        body, status = run_accept_ride(driver_b.user, ride.id)
        self.assertEqual(status, 404)

    @override_settings(CASH_DEBT_BLOCK_THRESHOLD=5000)
    def test_blocked_when_cash_debt_is_at_the_threshold(self):
        driver = _make_driver("4", cash_debt=5000)
        ride = _make_pending_ride("4")
        body, status = run_accept_ride(driver.user, ride.id)
        self.assertEqual(status, 402)
        ride.refresh_from_db()
        self.assertEqual(ride.status, "pending")

    def test_blocked_when_driver_is_flagged(self):
        driver = _make_driver("5", is_flagged=True)
        ride = _make_pending_ride("5")
        body, status = run_accept_ride(driver.user, ride.id)
        self.assertEqual(status, 403)
        ride.refresh_from_db()
        self.assertEqual(ride.status, "pending")


class RunStartTripTests(TestCase):
    def test_starts_an_accepted_ride(self):
        driver = _make_driver("6")
        ride = _make_pending_ride("6")
        run_accept_ride(driver.user, ride.id)
        body, status = run_start_trip(driver.user, ride.id)
        self.assertEqual(status, 200)
        ride.refresh_from_db()
        self.assertEqual(ride.status, "started")
        self.assertIsNotNone(ride.started_at)

    def test_cannot_start_a_ride_not_assigned_to_this_driver(self):
        driver_a = _make_driver("7a")
        driver_b = _make_driver("7b")
        ride = _make_pending_ride("7")
        run_accept_ride(driver_a.user, ride.id)
        body, status = run_start_trip(driver_b.user, ride.id)
        self.assertEqual(status, 404)

    def test_cannot_start_a_ride_still_pending(self):
        driver = _make_driver("8")
        ride = _make_pending_ride("8")
        body, status = run_start_trip(driver.user, ride.id)
        self.assertEqual(status, 404)


class RunCompleteTripTests(TestCase):
    def test_completes_a_started_ride_and_frees_the_driver(self):
        driver = _make_driver("9")
        ride = _make_pending_ride("9")
        run_accept_ride(driver.user, ride.id)
        run_start_trip(driver.user, ride.id)
        body, status = run_complete_trip(driver.user, ride.id)
        self.assertEqual(status, 200)
        ride.refresh_from_db()
        self.assertEqual(ride.status, "completed")
        self.assertEqual(ride.payment_status, "pending")
        driver.refresh_from_db()
        self.assertFalse(driver.is_busy)
        self.assertIsNone(driver.current_ride_id)

    def test_does_not_create_a_premature_payment_reference(self):
        """Regression test: completing a trip must not silently create a
        real Paystack transaction before the rider has even chosen to
        pay — that reference would only get overwritten anyway once they
        actually tap Pay, so creating it here was pure dead weight (and,
        in production, left a confusing phantom "abandoned" transaction
        behind on every single completed ride)."""
        driver = _make_driver("10")
        ride = _make_pending_ride("10")
        run_accept_ride(driver.user, ride.id)
        run_start_trip(driver.user, ride.id)
        run_complete_trip(driver.user, ride.id)
        ride.refresh_from_db()
        self.assertIsNone(ride.payment_reference)

    def test_cannot_complete_a_ride_not_yet_started(self):
        driver = _make_driver("11")
        ride = _make_pending_ride("11")
        run_accept_ride(driver.user, ride.id)
        body, status = run_complete_trip(driver.user, ride.id)
        self.assertEqual(status, 400)


class RunDriverCancelRideTests(TestCase):
    def test_reopens_the_ride_to_pending_and_records_a_cancellation(self):
        driver = _make_driver("12")
        ride = _make_pending_ride("12")
        run_accept_ride(driver.user, ride.id)
        body, status = run_driver_cancel_ride(driver.user, ride.id)
        self.assertEqual(status, 200)
        ride.refresh_from_db()
        self.assertEqual(ride.status, "pending")
        self.assertIsNone(ride.driver_id)
        self.assertIsNone(ride.accepted_at)
        self.assertEqual(DriverCancellation.objects.filter(driver=driver.user, ride=ride).count(), 1)
        driver.refresh_from_db()
        self.assertFalse(driver.is_busy)

    def test_cannot_cancel_a_ride_already_started(self):
        driver = _make_driver("13")
        ride = _make_pending_ride("13")
        run_accept_ride(driver.user, ride.id)
        run_start_trip(driver.user, ride.id)
        body, status = run_driver_cancel_ride(driver.user, ride.id)
        self.assertEqual(status, 404)
        ride.refresh_from_db()
        self.assertEqual(ride.status, "started")
