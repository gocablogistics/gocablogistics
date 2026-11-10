"""Coverage for POST /rides/{id}/rate and the rating_service it calls —
had zero tests before, including the auto-flag-on-low-rating mechanism
(ratings existed but nothing ever consumed them until this was built: a
driver could sit at a 1.8 average forever with no consequence).
"""
import datetime
import json
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from gocabapp.models import Driver, Rating, RideRequest


def _make_driver(suffix: str) -> Driver:
    user = User.objects.create_user(username=f"ratedriver{suffix}", email=f"ratedriver{suffix}@example.com")
    return Driver.objects.create(
        user=user, full_name=f"Driver {suffix}", phone_number=f"+23470000004{suffix}",
        date_of_birth=datetime.date(1995, 1, 1), vehicle_type="Bike",
        national_identification_number=f"RATENIN{suffix}", is_approved=True,
    )


def _make_completed_ride(rider_suffix: str, driver: Driver) -> RideRequest:
    rider = User.objects.create_user(username=f"raterider{rider_suffix}", email=f"raterider{rider_suffix}@example.com")
    return RideRequest.objects.create(
        passenger=rider, driver=driver.user, current_location="A", destination="B",
        status="completed", vehicle_type="Bike", total_fare=Decimal("1000"),
    )


def _auth_header(user: User) -> dict:
    from ninja_jwt.tokens import RefreshToken
    token = str(RefreshToken.for_user(user).access_token)
    return {"HTTP_AUTHORIZATION": f"Bearer {token}"}


class SubmitRatingTests(TestCase):
    def test_rider_rates_the_driver(self):
        driver = _make_driver("1")
        ride = _make_completed_ride("1", driver)
        response = self.client.post(
            f"/api/v1/rides/{ride.id}/rate",
            data=json.dumps({"stars": 5, "comment": "Great trip"}),
            content_type="application/json",
            **_auth_header(ride.passenger),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Rating.objects.filter(ride=ride, ratee=driver.user).count(), 1)

    def test_stars_out_of_range_is_rejected(self):
        driver = _make_driver("2")
        ride = _make_completed_ride("2", driver)
        response = self.client.post(
            f"/api/v1/rides/{ride.id}/rate",
            data=json.dumps({"stars": 6}),
            content_type="application/json",
            **_auth_header(ride.passenger),
        )
        self.assertEqual(response.status_code, 400)

    def test_cannot_rate_the_same_ride_twice(self):
        driver = _make_driver("3")
        ride = _make_completed_ride("3", driver)
        self.client.post(
            f"/api/v1/rides/{ride.id}/rate",
            data=json.dumps({"stars": 4}),
            content_type="application/json",
            **_auth_header(ride.passenger),
        )
        second = self.client.post(
            f"/api/v1/rides/{ride.id}/rate",
            data=json.dumps({"stars": 2}),
            content_type="application/json",
            **_auth_header(ride.passenger),
        )
        self.assertEqual(second.status_code, 400)
        self.assertEqual(Rating.objects.filter(ride=ride).count(), 1)

    def test_someone_not_on_the_ride_cannot_rate_it(self):
        driver = _make_driver("4")
        ride = _make_completed_ride("4", driver)
        stranger = User.objects.create_user(username="ratestranger4", email="ratestranger4@example.com")
        response = self.client.post(
            f"/api/v1/rides/{ride.id}/rate",
            data=json.dumps({"stars": 3}),
            content_type="application/json",
            **_auth_header(stranger),
        )
        self.assertEqual(response.status_code, 403)

    @override_settings(RATING_AUTO_FLAG_MIN_COUNT=2, RATING_AUTO_FLAG_THRESHOLD=3.0)
    def test_driver_gets_auto_flagged_once_average_falls_below_threshold(self):
        driver = _make_driver("5")
        ride_a = _make_completed_ride("5a", driver)
        ride_b = _make_completed_ride("5b", driver)

        self.client.post(
            f"/api/v1/rides/{ride_a.id}/rate", data=json.dumps({"stars": 1}),
            content_type="application/json", **_auth_header(ride_a.passenger),
        )
        driver.refresh_from_db()
        self.assertFalse(driver.is_flagged, "one bad rating under the minimum count shouldn't flag yet")

        self.client.post(
            f"/api/v1/rides/{ride_b.id}/rate", data=json.dumps({"stars": 1}),
            content_type="application/json", **_auth_header(ride_b.passenger),
        )
        driver.refresh_from_db()
        self.assertTrue(driver.is_flagged)
