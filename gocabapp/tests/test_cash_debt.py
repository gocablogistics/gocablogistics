"""Tests against the documented rules in cash_debt_service.py: GoCab never
collects its commission on a cash ride directly, so it's tracked as debt
and enforced by taking a driver offline once they cross
settings.CASH_DEBT_BLOCK_THRESHOLD. Covers charge_cash_commission,
settle_cash_debt, and the fraud_checks.is_cash_debt_blocked read side.
"""
import datetime
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from gocabapp.models import CashDebtEntry, Driver, RideRequest
from gocabapp.services.cash_debt_service import charge_cash_commission, settle_cash_debt
from gocabapp.services.fraud_checks import is_cash_debt_blocked


def _make_driver(suffix: str, cash_debt=0, is_online=False) -> Driver:
    user = User.objects.create_user(username=f"cashdriver{suffix}", email=f"cashdriver{suffix}@example.com")
    return Driver.objects.create(
        user=user, full_name=f"Driver {suffix}", phone_number=f"+23475000000{suffix}",
        date_of_birth=datetime.date(1995, 1, 1), vehicle_type="Bike",
        national_identification_number=f"CASHNIN{suffix}", bank_name="Test Bank",
        account_number=f"222222{suffix}0", account_holder_name=f"Driver {suffix}",
        is_approved=True, cash_debt=Decimal(str(cash_debt)), is_online=is_online,
    )


def _make_ride(driver: Driver, total_fare) -> RideRequest:
    return RideRequest.objects.create(
        passenger=driver.user, driver=driver.user, current_location="A", destination="B",
        status="completed", total_fare=Decimal(str(total_fare)), vehicle_type="Bike",
    )


class ChargeCashCommissionTests(TestCase):
    def test_commission_is_twenty_percent_of_the_fare(self):
        driver = _make_driver("1")
        ride = _make_ride(driver, 1000)
        entry = charge_cash_commission(ride)
        self.assertEqual(entry.amount, 200)
        driver.refresh_from_db()
        self.assertEqual(driver.cash_debt, 200)

    def test_commission_accumulates_across_multiple_rides(self):
        driver = _make_driver("2")
        charge_cash_commission(_make_ride(driver, 1000))
        charge_cash_commission(_make_ride(driver, 500))
        driver.refresh_from_db()
        self.assertEqual(driver.cash_debt, 300)

    def test_no_charge_without_a_driver_or_fare(self):
        driver = _make_driver("3")
        rideless = RideRequest.objects.create(
            passenger=driver.user, current_location="A", destination="B",
            status="pending", total_fare=None, vehicle_type="Bike",
        )
        self.assertIsNone(charge_cash_commission(rideless))
        driver.refresh_from_db()
        self.assertEqual(driver.cash_debt, 0)

    def test_duplicate_charge_for_the_same_ride_is_rejected(self):
        driver = _make_driver("4")
        ride = _make_ride(driver, 1000)
        first = charge_cash_commission(ride)
        second = charge_cash_commission(ride)
        self.assertIsNotNone(first)
        self.assertIsNone(second)
        driver.refresh_from_db()
        self.assertEqual(driver.cash_debt, 200)  # not double-charged
        self.assertEqual(CashDebtEntry.objects.filter(ride=ride, entry_type="charge").count(), 1)

    @override_settings(CASH_DEBT_BLOCK_THRESHOLD=5000)
    def test_crossing_the_threshold_while_online_takes_the_driver_offline(self):
        driver = _make_driver("5", cash_debt=4900, is_online=True)
        charge_cash_commission(_make_ride(driver, 1000))  # +200 → 5100, crosses 5000
        driver.refresh_from_db()
        self.assertEqual(driver.cash_debt, 5100)
        self.assertFalse(driver.is_online)

    @override_settings(CASH_DEBT_BLOCK_THRESHOLD=5000)
    def test_crossing_the_threshold_while_already_offline_does_not_error(self):
        """newly_blocked only fires the "taken offline" notification when the
        driver was actually online — already-offline shouldn't crash or
        double-notify, just keep tracking the balance."""
        driver = _make_driver("6", cash_debt=4900, is_online=False)
        charge_cash_commission(_make_ride(driver, 1000))
        driver.refresh_from_db()
        self.assertEqual(driver.cash_debt, 5100)
        self.assertFalse(driver.is_online)

    @override_settings(CASH_DEBT_BLOCK_THRESHOLD=5000)
    def test_staying_under_the_threshold_leaves_driver_online(self):
        driver = _make_driver("7", cash_debt=0, is_online=True)
        charge_cash_commission(_make_ride(driver, 1000))
        driver.refresh_from_db()
        self.assertEqual(driver.cash_debt, 200)
        self.assertTrue(driver.is_online)


class SettleCashDebtTests(TestCase):
    def test_settling_clears_the_balance_and_records_an_entry(self):
        driver = _make_driver("8", cash_debt=1200)
        entry = settle_cash_debt(driver, note="Paid via bank transfer")
        self.assertEqual(entry.amount, 1200)
        self.assertEqual(entry.entry_type, "settlement")
        driver.refresh_from_db()
        self.assertEqual(driver.cash_debt, 0)

    def test_settling_a_zero_balance_is_a_no_op(self):
        driver = _make_driver("9", cash_debt=0)
        self.assertIsNone(settle_cash_debt(driver))
        self.assertEqual(CashDebtEntry.objects.filter(driver=driver).count(), 0)


class IsCashDebtBlockedTests(TestCase):
    @override_settings(CASH_DEBT_BLOCK_THRESHOLD=5000)
    def test_blocked_at_or_above_threshold(self):
        driver = _make_driver("10", cash_debt=5000)
        self.assertTrue(is_cash_debt_blocked(driver.user))

    @override_settings(CASH_DEBT_BLOCK_THRESHOLD=5000)
    def test_not_blocked_below_threshold(self):
        driver = _make_driver("11", cash_debt=4999)
        self.assertFalse(is_cash_debt_blocked(driver.user))

    def test_a_user_with_no_driver_profile_is_never_blocked(self):
        rider_user = User.objects.create_user(username="plainrider", email="plainrider@example.com")
        self.assertFalse(is_cash_debt_blocked(rider_user))
