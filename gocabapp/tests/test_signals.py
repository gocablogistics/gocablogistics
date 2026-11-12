"""Coverage for the post_save signal handlers in signals/driver_signals.py
and signals/ride_signals.py — previously exercised only incidentally by
other tests (as a side effect of creating a Driver/RideRequest), never
directly asserted on. Includes regression tests for the exact
re-trigger bug both files' own docstrings warn against: a save() that
doesn't actually change status/approval must not re-fire a one-time
notification.
"""
import datetime
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase

from gocabapp.models import Driver, Notification, Rider, RideRequest


def _make_rider(suffix: str) -> Rider:
    user = User.objects.create_user(username=f"sigrider{suffix}", email=f"sigrider{suffix}@example.com")
    return Rider.objects.create(user=user, full_name=f"Rider {suffix}")


def _make_driver(suffix: str, **extra) -> Driver:
    user = User.objects.create_user(username=f"sigdriver{suffix}", email=f"sigdriver{suffix}@example.com")
    extra.setdefault("is_approved", True)
    return Driver.objects.create(
        user=user, full_name=f"Driver {suffix}", phone_number=f"+23472300000{suffix}",
        date_of_birth=datetime.date(1995, 1, 1), vehicle_type="Bike",
        national_identification_number=f"SIGNIN{suffix}", bank_name="Test Bank",
        account_number=f"888335{suffix}0", account_holder_name=f"Driver {suffix}", **extra,
    )


class DriverApprovalSignalTests(TestCase):
    def test_approving_a_driver_notifies_them(self):
        driver = _make_driver("1", is_approved=False)
        driver.is_approved = True
        driver.save(update_fields=["is_approved"])
        self.assertTrue(
            Notification.objects.filter(user=driver.user, message__icontains="approved").exists()
        )

    def test_a_driver_created_already_approved_is_not_notified(self):
        """created=True short-circuits — this is a signup-time state, not
        a real "just got approved" transition."""
        driver = _make_driver("2", is_approved=True)
        self.assertFalse(Notification.objects.filter(user=driver.user).exists())

    def test_saving_an_already_approved_driver_again_does_not_re_notify(self):
        driver = _make_driver("3", is_approved=True)
        driver.is_approved = True
        driver.vehicle_color = "Red"
        driver.save(update_fields=["is_approved", "vehicle_color"])
        self.assertFalse(Notification.objects.filter(user=driver.user).exists())

    def test_un_approving_a_driver_does_not_notify(self):
        driver = _make_driver("4", is_approved=True)
        driver.is_approved = False
        driver.save(update_fields=["is_approved"])
        self.assertFalse(Notification.objects.filter(user=driver.user).exists())


class NewRideSignalTests(TestCase):
    def test_a_new_pending_ride_notifies_every_online_approved_driver(self):
        online_driver = _make_driver("5", is_online=True, is_approved=True)
        offline_driver = _make_driver("6", is_online=False, is_approved=True)
        unapproved_driver = _make_driver("7", is_online=True, is_approved=False)
        rider = _make_rider("1")

        RideRequest.objects.create(
            passenger=rider.user, current_location="A", destination="B",
            status="pending", vehicle_type="Bike", total_fare=Decimal("1000"),
        )
        self.assertTrue(
            Notification.objects.filter(user=online_driver.user, message__icontains="New ride request").exists()
        )
        self.assertFalse(Notification.objects.filter(user=offline_driver.user).exists())
        self.assertFalse(Notification.objects.filter(user=unapproved_driver.user).exists())

    def test_no_online_drivers_creates_no_notifications_and_does_not_crash(self):
        rider = _make_rider("2")
        RideRequest.objects.create(
            passenger=rider.user, current_location="A", destination="B",
            status="pending", vehicle_type="Bike", total_fare=Decimal("1000"),
        )
        self.assertEqual(Notification.objects.count(), 0)


class RideStatusTransitionSignalTests(TestCase):
    def _make_ride(self, rider, driver=None, status="pending") -> RideRequest:
        return RideRequest.objects.create(
            passenger=rider.user, driver=driver.user if driver else None,
            current_location="A", destination="B", status=status,
            vehicle_type="Bike", total_fare=Decimal("1000"),
        )

    def test_accepting_a_ride_notifies_the_passenger_with_the_driver_name(self):
        rider = _make_rider("3")
        driver = _make_driver("8")
        ride = self._make_ride(rider, status="pending")

        ride.driver = driver.user
        ride.status = "accepted"
        ride.save()

        self.assertTrue(
            Notification.objects.filter(
                user=rider.user, message__icontains="Driver 8 accepted your ride", is_active=True,
            ).exists()
        )

    def test_a_cash_confirmation_retry_on_an_accepted_ride_does_not_re_notify(self):
        """Regression test for exactly what ride_signals.py's own
        docstring warns about: payment_status (or any other field)
        changing on a ride that's already "accepted" must not re-fire
        the one-time acceptance notification."""
        rider = _make_rider("4")
        driver = _make_driver("9")
        ride = self._make_ride(rider, driver, status="accepted")
        Notification.objects.filter(user=rider.user).delete()  # clear the one from the transition above

        ride.cash_confirmation_attempts = 1
        ride.save(update_fields=["cash_confirmation_attempts"])

        self.assertFalse(Notification.objects.filter(user=rider.user).exists())

    def test_completing_a_ride_deactivates_the_passengers_notifications(self):
        rider = _make_rider("5")
        driver = _make_driver("10")
        ride = self._make_ride(rider, driver, status="started")
        Notification.objects.create(user=rider.user, message="still active", is_active=True)

        ride.status = "completed"
        ride.save()

        self.assertFalse(Notification.objects.filter(user=rider.user, is_active=True).exists())

    def test_starting_and_cancelling_do_not_touch_notification_rows(self):
        """These two only send a live WS blip, no persisted Notification —
        confirms that's still true and neither path crashes."""
        rider = _make_rider("6")
        driver = _make_driver("11")
        ride = self._make_ride(rider, driver, status="accepted")
        Notification.objects.filter(user=rider.user).delete()

        ride.status = "started"
        ride.save()
        self.assertEqual(Notification.objects.filter(user=rider.user).count(), 0)

        ride.status = "cancelled"
        ride.cancelled_at = None
        ride.save()
        self.assertEqual(Notification.objects.filter(user=rider.user).count(), 0)
