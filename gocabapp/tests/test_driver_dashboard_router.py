"""Coverage for the driver dashboard's read endpoints and /rides/availability's
flagged-driver gate (the cash-debt gate on the same endpoint already had
coverage in test_cash_payment.py; is_driver_flagged did not)."""
import datetime
import json
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone
from ninja_jwt.tokens import RefreshToken

from gocabapp.models import Driver, DriverPayout, Rider, RideRequest


def _make_rider(suffix: str) -> Rider:
    user = User.objects.create_user(username=f"dashrider{suffix}", email=f"dashrider{suffix}@example.com")
    return Rider.objects.create(user=user, full_name=f"Rider {suffix}")


def _make_driver(suffix: str, **extra) -> Driver:
    user = User.objects.create_user(username=f"dashdriver{suffix}", email=f"dashdriver{suffix}@example.com")
    extra.setdefault("vehicle_type", "Bike")
    extra.setdefault("is_approved", True)
    return Driver.objects.create(
        user=user, full_name=f"Driver {suffix}", phone_number=f"+23470100000{suffix}",
        date_of_birth=datetime.date(1995, 1, 1),
        national_identification_number=f"DASHNIN{suffix}", bank_name="Test Bank",
        account_number=f"777775{suffix}0", account_holder_name=f"Driver {suffix}",
        **extra,
    )


def _auth_header(user: User) -> dict:
    token = str(RefreshToken.for_user(user).access_token)
    return {"HTTP_AUTHORIZATION": f"Bearer {token}"}


class AvailabilityTests(TestCase):
    def test_get_requires_a_driver_profile(self):
        rider = _make_rider("1")
        response = self.client.get("/api/v1/rides/availability", **_auth_header(rider.user))
        self.assertEqual(response.status_code, 403)

    def test_get_reflects_the_drivers_current_state(self):
        driver = _make_driver("1", is_online=True, is_busy=True)
        response = self.client.get("/api/v1/rides/availability", **_auth_header(driver.user))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"is_online": True, "is_busy": True})

    def test_flagged_driver_cannot_go_online(self):
        driver = _make_driver("2", is_flagged=True, is_online=False)
        response = self.client.post(
            "/api/v1/rides/availability",
            data=json.dumps({"is_online": True}),
            content_type="application/json",
            **_auth_header(driver.user),
        )
        self.assertEqual(response.status_code, 403)
        driver.refresh_from_db()
        self.assertFalse(driver.is_online)

    def test_flagged_driver_can_still_go_offline(self):
        driver = _make_driver("3", is_flagged=True, is_online=True)
        response = self.client.post(
            "/api/v1/rides/availability",
            data=json.dumps({"is_online": False}),
            content_type="application/json",
            **_auth_header(driver.user),
        )
        self.assertEqual(response.status_code, 200)
        driver.refresh_from_db()
        self.assertFalse(driver.is_online)


class DriverSummaryTests(TestCase):
    def test_requires_a_driver_profile(self):
        rider = _make_rider("4")
        response = self.client.get("/api/v1/rides/driver/summary", **_auth_header(rider.user))
        self.assertEqual(response.status_code, 403)

    def test_completion_rate_and_earnings_match_the_real_rides(self):
        driver = _make_driver("4", cash_debt=Decimal("150"))
        rider = _make_rider("5")
        RideRequest.objects.create(
            passenger=rider.user, driver=driver.user, current_location="A", destination="B",
            status="completed", vehicle_type="Bike", total_fare=Decimal("1000"),
            completed_at=timezone.now(),
        )
        RideRequest.objects.create(
            passenger=rider.user, driver=driver.user, current_location="A", destination="B",
            status="cancelled", vehicle_type="Bike", total_fare=Decimal("500"),
        )

        response = self.client.get("/api/v1/rides/driver/summary", **_auth_header(driver.user))
        body = response.json()
        self.assertEqual(body["completed_trips"], 1)
        self.assertEqual(body["completion_rate"], 50.0)  # 1 of 2 assigned rides completed
        self.assertEqual(body["total_earnings"], 800)  # 1000 * 0.80
        self.assertEqual(body["todays_earnings"], 800)
        self.assertEqual(body["cash_debt"], 150.0)

    def test_no_rides_at_all_does_not_divide_by_zero(self):
        driver = _make_driver("6")
        response = self.client.get("/api/v1/rides/driver/summary", **_auth_header(driver.user))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["completion_rate"], 0.0)


class DriverPayoutsTests(TestCase):
    def test_requires_a_driver_profile(self):
        rider = _make_rider("7")
        response = self.client.get("/api/v1/rides/driver/payouts", **_auth_header(rider.user))
        self.assertEqual(response.status_code, 403)

    def test_lists_only_this_drivers_own_payouts_newest_first(self):
        driver = _make_driver("7")
        other_driver = _make_driver("8")
        rider = _make_rider("9")

        def _ride(d):
            return RideRequest.objects.create(
                passenger=rider.user, driver=d.user, current_location="A", destination="B",
                status="completed", vehicle_type="Bike", total_fare=Decimal("1000"),
            )

        older = DriverPayout.objects.create(
            driver=driver, ride=_ride(driver), amount=Decimal("800"), platform_fee=Decimal("200"),
        )
        newer = DriverPayout.objects.create(
            driver=driver, ride=_ride(driver), amount=Decimal("400"), platform_fee=Decimal("100"),
            status="paid",
        )
        DriverPayout.objects.create(
            driver=other_driver, ride=_ride(other_driver), amount=Decimal("300"), platform_fee=Decimal("75"),
        )

        response = self.client.get("/api/v1/rides/driver/payouts", **_auth_header(driver.user))
        body = response.json()
        self.assertEqual([p["id"] for p in body], [newer.id, older.id])
        self.assertEqual(body[0]["status"], "paid")
        self.assertEqual(body[0]["amount"], 400.0)


class DriverCashoutRouterTests(TestCase):
    def test_requires_a_driver_profile(self):
        rider = _make_rider("10")
        response = self.client.post("/api/v1/rides/driver/cashout", **_auth_header(rider.user))
        self.assertEqual(response.status_code, 403)

    def test_zero_balance_is_rejected_through_the_real_endpoint(self):
        """Full business-rule coverage for initiate_instant_cashout already
        lives in test_payouts.py — this just confirms the router actually
        wires request.user.driver into it and returns its (body, status)
        unchanged."""
        driver = _make_driver("11")
        response = self.client.post("/api/v1/rides/driver/cashout", **_auth_header(driver.user))
        self.assertEqual(response.status_code, 400)
