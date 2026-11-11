"""Coverage for POST /rides/{id}/dispute/respond (rider) and
/rides/{id}/dispute/driver-respond (driver) — the counterpart to
report_nonpayment/report_driver (already tested in test_dispute_reports.py)
that had zero coverage of its own before this."""
import datetime
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from ninja_jwt.tokens import RefreshToken

from gocabapp.models import Driver, PaymentDispute, Rider, RideRequest


def _make_rider(suffix: str) -> Rider:
    user = User.objects.create_user(username=f"disprider{suffix}", email=f"disprider{suffix}@example.com")
    return Rider.objects.create(user=user, full_name=f"Rider {suffix}")


def _make_driver(suffix: str) -> Driver:
    user = User.objects.create_user(username=f"dispdriver{suffix}", email=f"dispdriver{suffix}@example.com")
    return Driver.objects.create(
        user=user, full_name=f"Driver {suffix}", phone_number=f"+23470600000{suffix}",
        date_of_birth=datetime.date(1995, 1, 1), vehicle_type="Bike",
        national_identification_number=f"DISPNIN{suffix}", bank_name="Test Bank",
        account_number=f"333305{suffix}0", account_holder_name=f"Driver {suffix}", is_approved=True,
    )


def _make_ride_with_dispute(rider: Rider, driver: Driver, dispute_status="open", **dispute_kwargs) -> RideRequest:
    ride = RideRequest.objects.create(
        passenger=rider.user, driver=driver.user, current_location="A", destination="B",
        status="completed", vehicle_type="Bike", total_fare=Decimal("1000"),
    )
    PaymentDispute.objects.create(ride=ride, status=dispute_status, **dispute_kwargs)
    return ride


def _auth_header(user: User) -> dict:
    token = str(RefreshToken.for_user(user).access_token)
    return {"HTTP_AUTHORIZATION": f"Bearer {token}"}


class RiderRespondToDisputeTests(TestCase):
    def test_rider_can_respond_to_a_driver_filed_dispute(self):
        rider = _make_rider("1")
        driver = _make_driver("1")
        ride = _make_ride_with_dispute(rider, driver, driver_statement="never paid")

        response = self.client.post(
            f"/api/v1/rides/{ride.id}/dispute/respond",
            data='{"statement": "I paid in cash, ask him again"}',
            content_type="application/json",
            **_auth_header(rider.user),
        )
        self.assertEqual(response.status_code, 200)
        ride.dispute.refresh_from_db()
        self.assertEqual(ride.dispute.rider_statement, "I paid in cash, ask him again")
        self.assertIsNotNone(ride.dispute.rider_responded_at)

    def test_someone_not_on_the_ride_cannot_respond(self):
        rider = _make_rider("2")
        driver = _make_driver("2")
        stranger = _make_rider("3")
        ride = _make_ride_with_dispute(rider, driver, driver_statement="never paid")

        response = self.client.post(
            f"/api/v1/rides/{ride.id}/dispute/respond",
            data='{"statement": "whatever"}', content_type="application/json",
            **_auth_header(stranger.user),
        )
        self.assertEqual(response.status_code, 404)

    def test_responding_when_no_dispute_exists_is_rejected(self):
        rider = _make_rider("4")
        ride = RideRequest.objects.create(
            passenger=rider.user, current_location="A", destination="B",
            status="completed", vehicle_type="Bike", total_fare=Decimal("1000"),
        )
        response = self.client.post(
            f"/api/v1/rides/{ride.id}/dispute/respond",
            data='{"statement": "huh?"}', content_type="application/json",
            **_auth_header(rider.user),
        )
        self.assertEqual(response.status_code, 404)

    def test_an_empty_statement_is_rejected(self):
        rider = _make_rider("5")
        driver = _make_driver("3")
        ride = _make_ride_with_dispute(rider, driver, driver_statement="never paid")

        response = self.client.post(
            f"/api/v1/rides/{ride.id}/dispute/respond",
            data='{"statement": "   "}', content_type="application/json",
            **_auth_header(rider.user),
        )
        self.assertEqual(response.status_code, 400)

    def test_responding_to_an_already_resolved_dispute_is_rejected(self):
        rider = _make_rider("6")
        driver = _make_driver("4")
        ride = _make_ride_with_dispute(rider, driver, dispute_status="resolved", driver_statement="never paid")

        response = self.client.post(
            f"/api/v1/rides/{ride.id}/dispute/respond",
            data='{"statement": "too late"}', content_type="application/json",
            **_auth_header(rider.user),
        )
        self.assertEqual(response.status_code, 400)


class DriverRespondToDisputeTests(TestCase):
    def test_driver_can_respond_to_a_rider_filed_dispute(self):
        rider = _make_rider("7")
        driver = _make_driver("5")
        ride = _make_ride_with_dispute(rider, driver, rider_statement="he was rude")

        response = self.client.post(
            f"/api/v1/rides/{ride.id}/dispute/driver-respond",
            data='{"statement": "that is not true"}', content_type="application/json",
            **_auth_header(driver.user),
        )
        self.assertEqual(response.status_code, 200)
        ride.dispute.refresh_from_db()
        self.assertEqual(ride.dispute.driver_statement, "that is not true")
        self.assertIsNotNone(ride.dispute.driver_responded_at)

    def test_a_different_driver_cannot_respond(self):
        rider = _make_rider("8")
        driver = _make_driver("6")
        other_driver = _make_driver("7")
        ride = _make_ride_with_dispute(rider, driver, rider_statement="he was rude")

        response = self.client.post(
            f"/api/v1/rides/{ride.id}/dispute/driver-respond",
            data='{"statement": "whatever"}', content_type="application/json",
            **_auth_header(other_driver.user),
        )
        self.assertEqual(response.status_code, 404)
