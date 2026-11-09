"""Tests against the documented rules in payment_service.auto_escalate_unpaid_ride
and stale_ride_service._sweep_unpaid_too_long: a completed ride that sits
unpaid for settings.UNPAID_RIDE_AUTO_DISPUTE_DAYS gets escalated by the
system itself, exactly like a driver's own non-payment report, closing
the gap where nobody ever bothers to tap "report"."""
import datetime
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.utils import timezone

from gocabapp.models import PaymentDispute, RideRequest, Rider
from gocabapp.services.payment_service import auto_escalate_unpaid_ride
from gocabapp.services.stale_ride_service import _sweep_unpaid_too_long


def _make_rider(suffix: str) -> Rider:
    user = User.objects.create_user(username=f"escrider{suffix}", email=f"escrider{suffix}@example.com")
    return Rider.objects.create(user=user, full_name=f"Rider {suffix}")


def _make_unpaid_ride(rider: Rider, completed_at=None, payment_status="pending") -> RideRequest:
    return RideRequest.objects.create(
        passenger=rider.user, current_location="A", destination="B",
        status="completed", vehicle_type="Bike", total_fare=Decimal("1000"),
        payment_status=payment_status, completed_at=completed_at or timezone.now(),
    )


class AutoEscalateUnpaidRideTests(TestCase):
    def test_opens_a_dispute_and_marks_the_ride_reported(self):
        rider = _make_rider("1")
        ride = _make_unpaid_ride(rider)
        auto_escalate_unpaid_ride(ride)
        ride.refresh_from_db()
        self.assertEqual(ride.payment_status, "reported")
        dispute = PaymentDispute.objects.get(ride=ride)
        self.assertEqual(dispute.status, "open")
        self.assertIn("Auto-reported", dispute.driver_statement)

    def test_a_paid_ride_is_left_alone(self):
        rider = _make_rider("2")
        ride = _make_unpaid_ride(rider, payment_status="paid")
        auto_escalate_unpaid_ride(ride)
        self.assertFalse(PaymentDispute.objects.filter(ride=ride).exists())

    def test_a_ride_with_an_existing_nonpayment_dispute_is_not_re_escalated(self):
        """Even a resolved/dismissed dispute counts — an admin already
        looked at this one, so the system shouldn't second-guess them."""
        rider = _make_rider("3")
        ride = _make_unpaid_ride(rider)
        PaymentDispute.objects.create(ride=ride, status="dismissed", driver_statement="original report")
        auto_escalate_unpaid_ride(ride)
        dispute = PaymentDispute.objects.get(ride=ride)
        self.assertEqual(dispute.status, "dismissed")  # untouched
        self.assertEqual(dispute.driver_statement, "original report")

    def test_an_unrelated_rider_conduct_complaint_does_not_block_escalation(self):
        """Regression test for a real production case (ride 433): the
        rider had already filed an unrelated conduct complaint about the
        driver (rider_statement set, driver_statement empty) — that must
        not be mistaken for "already escalated for non-payment" and
        silently swallow this ride forever."""
        rider = _make_rider("3b")
        ride = _make_unpaid_ride(rider)
        PaymentDispute.objects.create(ride=ride, status="open", rider_statement="he is annoying")
        escalated = auto_escalate_unpaid_ride(ride)
        self.assertTrue(escalated)
        dispute = PaymentDispute.objects.get(ride=ride)
        self.assertIn("Auto-reported", dispute.driver_statement)
        self.assertEqual(dispute.rider_statement, "he is annoying")  # untouched
        ride.refresh_from_db()
        self.assertEqual(ride.payment_status, "reported")

    @override_settings(RIDER_NONPAYMENT_AUTO_FLAG_COUNT=2)
    def test_two_auto_escalations_on_different_rides_flags_the_rider(self):
        rider = _make_rider("4")
        auto_escalate_unpaid_ride(_make_unpaid_ride(rider))
        rider.refresh_from_db()
        self.assertFalse(rider.is_flagged)  # only one so far

        auto_escalate_unpaid_ride(_make_unpaid_ride(rider))
        rider.refresh_from_db()
        self.assertTrue(rider.is_flagged)


class SweepUnpaidTooLongTests(TestCase):
    @override_settings(UNPAID_RIDE_AUTO_DISPUTE_DAYS=3)
    def test_escalates_rides_past_the_cutoff(self):
        rider = _make_rider("5")
        old_enough = timezone.now() - datetime.timedelta(days=4)
        ride = _make_unpaid_ride(rider, completed_at=old_enough)
        count = _sweep_unpaid_too_long()
        self.assertEqual(count, 1)
        ride.refresh_from_db()
        self.assertEqual(ride.payment_status, "reported")

    @override_settings(UNPAID_RIDE_AUTO_DISPUTE_DAYS=3)
    def test_does_not_escalate_rides_not_old_enough_yet(self):
        rider = _make_rider("6")
        too_recent = timezone.now() - datetime.timedelta(days=1)
        ride = _make_unpaid_ride(rider, completed_at=too_recent)
        count = _sweep_unpaid_too_long()
        self.assertEqual(count, 0)
        ride.refresh_from_db()
        self.assertEqual(ride.payment_status, "pending")

    @override_settings(UNPAID_RIDE_AUTO_DISPUTE_DAYS=3)
    def test_does_not_re_escalate_a_ride_that_already_has_a_dispute(self):
        rider = _make_rider("7")
        old_enough = timezone.now() - datetime.timedelta(days=10)
        ride = _make_unpaid_ride(rider, completed_at=old_enough, payment_status="reported")
        PaymentDispute.objects.create(ride=ride, status="open", driver_statement="driver reported it")
        count = _sweep_unpaid_too_long()
        self.assertEqual(count, 0)

    @override_settings(UNPAID_RIDE_AUTO_DISPUTE_DAYS=3)
    def test_does_not_touch_a_paid_ride(self):
        rider = _make_rider("8")
        old_enough = timezone.now() - datetime.timedelta(days=10)
        _make_unpaid_ride(rider, completed_at=old_enough, payment_status="paid")
        count = _sweep_unpaid_too_long()
        self.assertEqual(count, 0)
