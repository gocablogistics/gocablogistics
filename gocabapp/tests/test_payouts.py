"""Tests against the stated rules in payout_service.py's own docstrings:
the driver/platform split must never create or lose money, and instant
cash-out must enforce its fee and minimum-balance rules exactly.
Paystack's own network calls are mocked out everywhere — these tests
check GoCab's own business logic, not whether Paystack is reachable."""
import datetime
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase

from gocabapp.models import Driver, DriverPayout, RideRequest
from gocabapp.services.payout_service import create_payout_for_ride, initiate_instant_cashout


def _make_driver(suffix: str) -> Driver:
    user = User.objects.create_user(username=f"driver{suffix}", email=f"driver{suffix}@example.com")
    return Driver.objects.create(
        user=user, full_name=f"Driver {suffix}", phone_number=f"+23470000000{suffix}",
        date_of_birth=datetime.date(1995, 1, 1), vehicle_type="Bike",
        national_identification_number=f"NIN{suffix}", bank_name="Test Bank",
        account_number=f"000000{suffix}0", account_holder_name=f"Driver {suffix}",
        is_approved=True,
    )


def _make_ride(driver: Driver, total_fare) -> RideRequest:
    return RideRequest.objects.create(
        passenger=driver.user, driver=driver.user, current_location="A", destination="B",
        status="completed", total_fare=Decimal(str(total_fare)), vehicle_type="Bike",
    )


class PayoutSplitTests(TestCase):
    def test_driver_and_platform_cut_always_sum_to_the_full_fare(self):
        """Money must never be created or lost in the split — whatever
        isn't the driver's amount must be exactly the platform fee,
        for every fare value, not just round ones."""
        driver = _make_driver("1")
        for fare in (500, 1000, 1951, 3193, 7497, 12345):
            ride = _make_ride(driver, fare)
            payout = create_payout_for_ride(ride)
            self.assertEqual(payout.amount + payout.platform_fee, fare)

    def test_driver_gets_roughly_eighty_percent(self):
        driver = _make_driver("2")
        ride = _make_ride(driver, 1000)
        payout = create_payout_for_ride(ride)
        self.assertEqual(payout.amount, 800)
        self.assertEqual(payout.platform_fee, 200)

    def test_no_payout_without_a_driver_or_fare(self):
        """Documented guard at the top of create_payout_for_ride — a ride
        with no assigned driver or no fare must not create a payout."""
        driver = _make_driver("3")
        ride = RideRequest.objects.create(
            passenger=driver.user, current_location="A", destination="B",
            status="pending", total_fare=None, vehicle_type="Bike",
        )
        self.assertIsNone(create_payout_for_ride(ride))

    def test_duplicate_payout_for_the_same_ride_is_rejected(self):
        """DriverPayout.ride is a one-to-one field — a ride can only ever
        generate one payout, calling this twice must not double-pay."""
        driver = _make_driver("4")
        ride = _make_ride(driver, 1000)
        first = create_payout_for_ride(ride)
        second = create_payout_for_ride(ride)
        self.assertIsNotNone(first)
        self.assertIsNone(second)
        self.assertEqual(DriverPayout.objects.filter(ride=ride).count(), 1)


class InstantCashoutTests(TestCase):
    def setUp(self):
        self.driver = _make_driver("5")
        # Mocks only the actual Paystack network call (_send_transfer), not
        # the whole initiate_transfer_for_batch — that function's own real
        # logic (claiming the batch, setting status="processing") must
        # still run for real, since initiate_instant_cashout's success
        # path now checks batch.status == "processing" afterward (added
        # this session: it used to report success unconditionally, even
        # when the real transfer silently failed to even start). Mocking
        # the whole function out, like this used to, would make that check
        # always see the batch's un-advanced default status and 502 —
        # exactly what broke the first time this ran for real.
        patcher = patch("gocabapp.services.payout_service._send_transfer", return_value=(True, {}))
        self.mock_transfer = patcher.start()
        self.addCleanup(patcher.stop)

    def _give_driver_balance(self, amount) -> None:
        ride = _make_ride(self.driver, amount / Decimal("0.8"))
        create_payout_for_ride(ride)

    def test_zero_balance_is_rejected(self):
        body, status = initiate_instant_cashout(self.driver)
        self.assertEqual(status, 400)
        self.mock_transfer.assert_not_called()

    def test_balance_at_or_below_the_fee_is_rejected(self):
        """A cash-out that would net the driver ₦0 or less must be
        blocked — settings.INSTANT_CASHOUT_FEE is ₦100 by default."""
        from django.conf import settings
        self._give_driver_balance(Decimal(str(settings.INSTANT_CASHOUT_FEE)))
        body, status = initiate_instant_cashout(self.driver)
        self.assertEqual(status, 400)
        self.mock_transfer.assert_not_called()

    def test_balance_above_fee_but_below_minimum_is_rejected(self):
        """settings.INSTANT_CASHOUT_MIN_BALANCE (₦210 by default, matching
        Uber's real Nigeria Flex Pay minimum) must be enforced even when
        the balance clears the fee on its own."""
        from django.conf import settings
        mid = (Decimal(str(settings.INSTANT_CASHOUT_FEE)) + Decimal(str(settings.INSTANT_CASHOUT_MIN_BALANCE))) / 2
        self._give_driver_balance(mid)
        body, status = initiate_instant_cashout(self.driver)
        self.assertEqual(status, 400)
        self.mock_transfer.assert_not_called()

    def test_balance_above_minimum_succeeds_and_fee_is_deducted_correctly(self):
        from django.conf import settings
        self._give_driver_balance(Decimal("1000"))
        body, status = initiate_instant_cashout(self.driver)
        self.assertEqual(status, 200)
        self.assertEqual(body["fee"], settings.INSTANT_CASHOUT_FEE)
        self.assertEqual(body["amount"], 1000 - settings.INSTANT_CASHOUT_FEE)
        self.mock_transfer.assert_called_once()
