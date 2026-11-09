"""Tests against the documented rules in payment_service.py's cash-payment
functions and the /rides/availability gate in rides/router.py: cash is
fully disabled by settings.CASH_PAYMENTS_ENABLED until GoCab chooses to
turn it back on, the confirmation code can't be brute-forced, and a driver
who owes cash-ride commission can't go back online."""
import datetime
import json
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from ninja_jwt.tokens import RefreshToken

from gocabapp.models import CashDebtEntry, Driver, RideRequest
from gocabapp.services.payment_service import (
    CASH_CONFIRMATION_MAX_ATTEMPTS,
    confirm_cash_payment,
    initiate_cash_payment,
)


def _make_driver(suffix: str, cash_debt=0, is_online=False) -> Driver:
    user = User.objects.create_user(username=f"cpdriver{suffix}", email=f"cpdriver{suffix}@example.com")
    return Driver.objects.create(
        user=user, full_name=f"Driver {suffix}", phone_number=f"+23476000000{suffix}",
        date_of_birth=datetime.date(1995, 1, 1), vehicle_type="Bike",
        national_identification_number=f"CPNIN{suffix}", bank_name="Test Bank",
        account_number=f"333333{suffix}0", account_holder_name=f"Driver {suffix}",
        is_approved=True, cash_debt=Decimal(str(cash_debt)), is_online=is_online,
    )


def _make_completed_ride(driver: Driver, rider: User, total_fare=1000) -> RideRequest:
    return RideRequest.objects.create(
        passenger=rider, driver=driver.user, current_location="A", destination="B",
        status="completed", total_fare=Decimal(str(total_fare)), vehicle_type="Bike",
    )


def _auth_header(user: User) -> dict:
    token = str(RefreshToken.for_user(user).access_token)
    return {"HTTP_AUTHORIZATION": f"Bearer {token}"}


@override_settings(CASH_PAYMENTS_ENABLED=True)
class InitiateCashPaymentTests(TestCase):
    def test_generates_a_four_digit_code_and_sets_payment_method(self):
        driver = _make_driver("1")
        rider = User.objects.create_user(username="cprider1", email="cprider1@example.com")
        ride = _make_completed_ride(driver, rider)
        body, status = initiate_cash_payment(rider, ride.id)
        self.assertEqual(status, 200)
        self.assertRegex(body["code"], r"^\d{4}$")
        ride.refresh_from_db()
        self.assertEqual(ride.payment_method, "cash")
        self.assertEqual(ride.cash_confirmation_code, body["code"])
        self.assertEqual(ride.cash_confirmation_attempts, 0)

    def test_blocked_if_ride_is_not_completed(self):
        driver = _make_driver("2")
        rider = User.objects.create_user(username="cprider2", email="cprider2@example.com")
        ride = RideRequest.objects.create(
            passenger=rider, driver=driver.user, current_location="A", destination="B",
            status="started", total_fare=Decimal("1000"), vehicle_type="Bike",
        )
        body, status = initiate_cash_payment(rider, ride.id)
        self.assertEqual(status, 400)

    def test_blocked_if_already_paid(self):
        driver = _make_driver("3")
        rider = User.objects.create_user(username="cprider3", email="cprider3@example.com")
        ride = _make_completed_ride(driver, rider)
        ride.payment_status = "paid"
        ride.save(update_fields=["payment_status"])
        body, status = initiate_cash_payment(rider, ride.id)
        self.assertEqual(status, 400)


class InitiateCashPaymentDisabledTests(TestCase):
    def test_disabled_by_default_returns_a_clean_error_not_a_crash(self):
        """settings.CASH_PAYMENTS_ENABLED is False by default — cash is a
        switch GoCab hasn't flipped on yet, not a removed feature."""
        driver = _make_driver("4")
        rider = User.objects.create_user(username="cprider4", email="cprider4@example.com")
        ride = _make_completed_ride(driver, rider)
        body, status = initiate_cash_payment(rider, ride.id)
        self.assertEqual(status, 403)


@override_settings(CASH_PAYMENTS_ENABLED=True)
class ConfirmCashPaymentTests(TestCase):
    def _ride_with_code(self, driver, rider, total_fare=1000):
        ride = _make_completed_ride(driver, rider, total_fare)
        initiate_cash_payment(rider, ride.id)
        ride.refresh_from_db()
        return ride

    def test_wrong_code_increments_attempts_and_does_not_mark_paid(self):
        driver = _make_driver("5")
        rider = User.objects.create_user(username="cprider5", email="cprider5@example.com")
        ride = self._ride_with_code(driver, rider)
        body, status = confirm_cash_payment(driver.user, ride.id, "0000")
        self.assertEqual(status, 400)
        ride.refresh_from_db()
        self.assertEqual(ride.payment_status, "pending")
        self.assertEqual(ride.cash_confirmation_attempts, 1)

    def test_correct_code_marks_paid_and_charges_cash_commission(self):
        driver = _make_driver("6")
        rider = User.objects.create_user(username="cprider6", email="cprider6@example.com")
        ride = self._ride_with_code(driver, rider, total_fare=1000)
        body, status = confirm_cash_payment(driver.user, ride.id, ride.cash_confirmation_code)
        self.assertEqual(status, 200)
        ride.refresh_from_db()
        self.assertEqual(ride.payment_status, "paid")
        driver.refresh_from_db()
        self.assertEqual(driver.cash_debt, 200)  # 20% commission on ₦1000

    def test_too_many_wrong_attempts_locks_out_even_the_correct_code(self):
        driver = _make_driver("7")
        rider = User.objects.create_user(username="cprider7", email="cprider7@example.com")
        ride = self._ride_with_code(driver, rider)
        real_code = ride.cash_confirmation_code
        for _ in range(CASH_CONFIRMATION_MAX_ATTEMPTS):
            confirm_cash_payment(driver.user, ride.id, "9999")
        body, status = confirm_cash_payment(driver.user, ride.id, real_code)
        self.assertEqual(status, 429)
        ride.refresh_from_db()
        self.assertEqual(ride.payment_status, "pending")

    def test_already_paid_ride_is_rejected(self):
        driver = _make_driver("8")
        rider = User.objects.create_user(username="cprider8", email="cprider8@example.com")
        ride = self._ride_with_code(driver, rider)
        confirm_cash_payment(driver.user, ride.id, ride.cash_confirmation_code)
        body, status = confirm_cash_payment(driver.user, ride.id, ride.cash_confirmation_code)
        self.assertEqual(status, 400)

    def test_a_different_driver_cannot_confirm_this_ride(self):
        driver = _make_driver("9")
        other_driver = _make_driver("10")
        rider = User.objects.create_user(username="cprider9", email="cprider9@example.com")
        ride = self._ride_with_code(driver, rider)
        body, status = confirm_cash_payment(other_driver.user, ride.id, ride.cash_confirmation_code)
        self.assertEqual(status, 404)
        ride.refresh_from_db()
        self.assertEqual(ride.payment_status, "pending")


class SetAvailabilityCashDebtGateTests(TestCase):
    @override_settings(CASH_DEBT_BLOCK_THRESHOLD=5000)
    def test_going_online_is_blocked_once_cash_debt_reaches_the_threshold(self):
        driver = _make_driver("11", cash_debt=5000, is_online=False)
        response = self.client.post(
            "/api/v1/rides/availability",
            data=json.dumps({"is_online": True}),
            content_type="application/json",
            **_auth_header(driver.user),
        )
        self.assertEqual(response.status_code, 402)
        driver.refresh_from_db()
        self.assertFalse(driver.is_online)

    @override_settings(CASH_DEBT_BLOCK_THRESHOLD=5000)
    def test_going_online_is_allowed_below_the_threshold(self):
        driver = _make_driver("12", cash_debt=4999, is_online=False)
        response = self.client.post(
            "/api/v1/rides/availability",
            data=json.dumps({"is_online": True}),
            content_type="application/json",
            **_auth_header(driver.user),
        )
        self.assertEqual(response.status_code, 200)
        driver.refresh_from_db()
        self.assertTrue(driver.is_online)

    @override_settings(CASH_DEBT_BLOCK_THRESHOLD=5000)
    def test_going_offline_is_always_allowed_even_while_blocked(self):
        """The debt gate only ever applies to going online — a blocked
        driver must still be able to take themselves offline."""
        driver = _make_driver("13", cash_debt=9000, is_online=True)
        response = self.client.post(
            "/api/v1/rides/availability",
            data=json.dumps({"is_online": False}),
            content_type="application/json",
            **_auth_header(driver.user),
        )
        self.assertEqual(response.status_code, 200)
        driver.refresh_from_db()
        self.assertFalse(driver.is_online)
