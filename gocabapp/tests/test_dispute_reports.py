"""Tests against the documented rules in payment_service.report_nonpayment
and report_driver: either side can open a PaymentDispute on a ride, but
since it's one shared slot per ride, one side's complaint must never
block the other side's completely separate complaint from being filed.
Regression coverage for a real production bug (ride 433): a rider's
conduct report about the driver silently rejected the driver's own,
unrelated non-payment report as "already reported"."""
import datetime
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase

from gocabapp.models import Driver, PaymentDispute, RideRequest
from gocabapp.services.payment_service import report_driver, report_nonpayment


def _make_driver(suffix: str) -> Driver:
    user = User.objects.create_user(username=f"repdriver{suffix}", email=f"repdriver{suffix}@example.com")
    return Driver.objects.create(
        user=user, full_name=f"Driver {suffix}", phone_number=f"+23477000000{suffix}",
        date_of_birth=datetime.date(1995, 1, 1), vehicle_type="Bike",
        national_identification_number=f"REPNIN{suffix}", bank_name="Test Bank",
        account_number=f"444444{suffix}0", account_holder_name=f"Driver {suffix}",
        is_approved=True,
    )


def _make_ride(driver: Driver, rider: User) -> RideRequest:
    return RideRequest.objects.create(
        passenger=rider, driver=driver.user, current_location="A", destination="B",
        status="completed", vehicle_type="Bike", total_fare=Decimal("1000"),
    )


class ReportNonpaymentTests(TestCase):
    def test_successful_report_opens_a_dispute_and_marks_the_ride_reported(self):
        driver = _make_driver("1")
        rider = User.objects.create_user(username="reprider1", email="reprider1@example.com")
        ride = _make_ride(driver, rider)
        body, status = report_nonpayment(driver.user, ride.id, reason="never paid")
        self.assertEqual(status, 200)
        ride.refresh_from_db()
        self.assertEqual(ride.payment_status, "reported")
        self.assertEqual(ride.dispute.driver_statement, "never paid")

    def test_blocked_if_ride_not_completed(self):
        driver = _make_driver("2")
        rider = User.objects.create_user(username="reprider2", email="reprider2@example.com")
        ride = RideRequest.objects.create(
            passenger=rider, driver=driver.user, current_location="A", destination="B",
            status="started", vehicle_type="Bike", total_fare=Decimal("1000"),
        )
        body, status = report_nonpayment(driver.user, ride.id)
        self.assertEqual(status, 400)

    def test_duplicate_nonpayment_report_is_rejected(self):
        driver = _make_driver("3")
        rider = User.objects.create_user(username="reprider3", email="reprider3@example.com")
        ride = _make_ride(driver, rider)
        report_nonpayment(driver.user, ride.id, reason="first report")
        body, status = report_nonpayment(driver.user, ride.id, reason="second report")
        self.assertEqual(status, 400)
        ride.refresh_from_db()
        self.assertEqual(ride.dispute.driver_statement, "first report")  # untouched

    def test_an_unrelated_conduct_complaint_does_not_block_a_nonpayment_report(self):
        """Regression test for the real ride-433 bug: filing a conduct
        report first must not make the driver's later, unrelated
        non-payment report get rejected as "already reported"."""
        driver = _make_driver("4")
        rider = User.objects.create_user(username="reprider4", email="reprider4@example.com")
        ride = _make_ride(driver, rider)
        report_driver(rider, ride.id, reason="he is annoying")

        body, status = report_nonpayment(driver.user, ride.id, reason="never paid")
        self.assertEqual(status, 200)
        ride.refresh_from_db()
        self.assertEqual(ride.payment_status, "reported")
        self.assertEqual(ride.dispute.driver_statement, "never paid")
        self.assertEqual(ride.dispute.rider_statement, "he is annoying")  # untouched


class ReportDriverTests(TestCase):
    def test_successful_report_opens_a_dispute(self):
        driver = _make_driver("5")
        rider = User.objects.create_user(username="reprider5", email="reprider5@example.com")
        ride = _make_ride(driver, rider)
        body, status = report_driver(rider, ride.id, reason="rude")
        self.assertEqual(status, 200)
        ride.refresh_from_db()
        self.assertEqual(ride.dispute.rider_statement, "rude")

    def test_blocked_without_a_reason(self):
        driver = _make_driver("6")
        rider = User.objects.create_user(username="reprider6", email="reprider6@example.com")
        ride = _make_ride(driver, rider)
        body, status = report_driver(rider, ride.id, reason="   ")
        self.assertEqual(status, 400)

    def test_duplicate_conduct_report_is_rejected(self):
        driver = _make_driver("7")
        rider = User.objects.create_user(username="reprider7", email="reprider7@example.com")
        ride = _make_ride(driver, rider)
        report_driver(rider, ride.id, reason="first complaint")
        body, status = report_driver(rider, ride.id, reason="second complaint")
        self.assertEqual(status, 400)
        ride.refresh_from_db()
        self.assertEqual(ride.dispute.rider_statement, "first complaint")  # untouched

    def test_an_unrelated_nonpayment_report_does_not_block_a_conduct_report(self):
        """Same regression, other direction."""
        driver = _make_driver("8")
        rider = User.objects.create_user(username="reprider8", email="reprider8@example.com")
        ride = _make_ride(driver, rider)
        report_nonpayment(driver.user, ride.id, reason="never paid")

        body, status = report_driver(rider, ride.id, reason="he is annoying")
        self.assertEqual(status, 200)
        ride.refresh_from_db()
        self.assertEqual(ride.dispute.rider_statement, "he is annoying")
        self.assertEqual(ride.dispute.driver_statement, "never paid")  # untouched
