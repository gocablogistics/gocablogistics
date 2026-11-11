"""Coverage for GET /rides/history and /rides/driver/history — previously
untested at the HTTP layer. Includes a regression test for a real bug
found while writing this: RideHistoryOut documents dispute_status and
my_statement_submitted (its own docstring explains exactly how they
should behave), but the endpoint never actually populated them, so a
rider or driver with an open dispute on a past ride always saw
dispute_status: null regardless of the real state. Fixed in router.py
alongside these tests.
"""
import datetime
import json
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from ninja_jwt.tokens import RefreshToken

from gocabapp.models import Driver, PaymentDispute, Rider, RideRequest


def _make_rider(suffix: str) -> Rider:
    user = User.objects.create_user(username=f"histrider{suffix}", email=f"histrider{suffix}@example.com")
    return Rider.objects.create(user=user, full_name=f"Rider {suffix}")


def _make_driver(suffix: str) -> Driver:
    user = User.objects.create_user(username=f"histdriver{suffix}", email=f"histdriver{suffix}@example.com")
    return Driver.objects.create(
        user=user, full_name=f"Driver {suffix}", phone_number=f"+23478000000{suffix}",
        date_of_birth=datetime.date(1995, 1, 1), vehicle_type="Bike",
        national_identification_number=f"HISTNIN{suffix}", bank_name="Test Bank",
        account_number=f"555555{suffix}0", account_holder_name=f"Driver {suffix}", is_approved=True,
    )


def _make_ride(rider: Rider, driver: Driver = None, status="completed") -> RideRequest:
    return RideRequest.objects.create(
        passenger=rider.user, driver=driver.user if driver else None,
        current_location="A", destination="B", status=status,
        vehicle_type="Bike", total_fare=Decimal("1000"),
    )


def _auth_header(user: User) -> dict:
    token = str(RefreshToken.for_user(user).access_token)
    return {"HTTP_AUTHORIZATION": f"Bearer {token}"}


class RiderHistoryTests(TestCase):
    def test_lists_only_finished_rides_newest_first(self):
        rider = _make_rider("1")
        driver = _make_driver("1")
        old = _make_ride(rider, driver)
        old.requested_at = old.requested_at - datetime.timedelta(days=1)
        old.save(update_fields=["requested_at"])
        new = _make_ride(rider, driver)
        _make_ride(rider, driver, status="pending")  # excluded — still active

        response = self.client.get("/api/v1/rides/history", **_auth_header(rider.user))
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual([r["ride_id"] for r in body], [new.id, old.id])

    def test_does_not_see_another_riders_history(self):
        rider = _make_rider("2")
        other = _make_rider("3")
        _make_ride(other)

        response = self.client.get("/api/v1/rides/history", **_auth_header(rider.user))
        self.assertEqual(response.json(), [])

    def test_dispute_status_and_my_statement_submitted_reflect_the_real_dispute(self):
        """Regression test for the bug this file's docstring describes —
        confirmed broken (always null/false) before the router.py fix."""
        rider = _make_rider("4")
        driver = _make_driver("4")
        ride = _make_ride(rider, driver)
        PaymentDispute.objects.create(ride=ride, status="open", driver_statement="never paid")

        response = self.client.get("/api/v1/rides/history", **_auth_header(rider.user))
        row = response.json()[0]
        self.assertEqual(row["dispute_status"], "open")
        # The rider hasn't responded yet — only the driver's side is filled in.
        self.assertFalse(row["my_statement_submitted"])

    def test_my_statement_submitted_is_true_once_the_rider_has_responded(self):
        rider = _make_rider("5")
        driver = _make_driver("5")
        ride = _make_ride(rider, driver)
        PaymentDispute.objects.create(
            ride=ride, status="open", driver_statement="never paid", rider_statement="I did pay",
        )

        response = self.client.get("/api/v1/rides/history", **_auth_header(rider.user))
        row = response.json()[0]
        self.assertTrue(row["my_statement_submitted"])

    def test_a_ride_with_no_dispute_reports_null_status(self):
        rider = _make_rider("6")
        _make_ride(rider)

        response = self.client.get("/api/v1/rides/history", **_auth_header(rider.user))
        row = response.json()[0]
        self.assertIsNone(row["dispute_status"])
        self.assertFalse(row["my_statement_submitted"])

    def test_my_rating_submitted_reflects_whether_this_rider_already_rated(self):
        rider = _make_rider("7")
        driver = _make_driver("7")
        ride = _make_ride(rider, driver)
        from gocabapp.models import Rating
        Rating.objects.create(ride=ride, rater=rider.user, ratee=driver.user, stars=5)

        response = self.client.get("/api/v1/rides/history", **_auth_header(rider.user))
        self.assertTrue(response.json()[0]["my_rating_submitted"])


class DriverHistoryTests(TestCase):
    def test_requires_a_driver_profile(self):
        rider = _make_rider("8")
        response = self.client.get("/api/v1/rides/driver/history", **_auth_header(rider.user))
        self.assertEqual(response.status_code, 403)

    def test_lists_only_this_drivers_finished_rides(self):
        driver = _make_driver("8")
        other_driver = _make_driver("9")
        rider = _make_rider("10")
        mine = _make_ride(rider, driver)
        _make_ride(rider, other_driver)  # someone else's — must not appear

        response = self.client.get("/api/v1/rides/driver/history", **_auth_header(driver.user))
        body = response.json()
        self.assertEqual([r["ride_id"] for r in body], [mine.id])

    def test_dispute_fields_are_scoped_to_the_drivers_own_statement(self):
        """Same bug/fix as the rider side, but checked against
        driver_statement instead of rider_statement — a driver who hasn't
        responded yet must see my_statement_submitted: false even though
        the rider already has."""
        driver = _make_driver("11")
        rider = _make_rider("12")
        ride = _make_ride(rider, driver)
        PaymentDispute.objects.create(
            ride=ride, status="open", rider_statement="he was rude",
        )

        response = self.client.get("/api/v1/rides/driver/history", **_auth_header(driver.user))
        row = response.json()[0]
        self.assertEqual(row["dispute_status"], "open")
        self.assertFalse(row["my_statement_submitted"])  # driver_statement still empty

    def test_other_party_name_is_the_passengers_name(self):
        driver = _make_driver("13")
        rider = _make_rider("14")
        _make_ride(rider, driver)

        response = self.client.get("/api/v1/rides/driver/history", **_auth_header(driver.user))
        self.assertEqual(response.json()[0]["other_party_name"], "Rider 14")
