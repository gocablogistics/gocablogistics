"""Tests against the documented rules in payment_service.maybe_credit_referral_reward
and Rider.referral_reward_credited: the first paid ride of a referred
rider credits settings.REFERRAL_REWARD_AMOUNT to whoever referred them,
exactly once per referred rider — no matter how many of their rides get
paid afterwards, and regardless of which payment method confirmed it."""
from decimal import Decimal
from typing import Optional

from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from gocabapp.models import RideRequest, Rider
from gocabapp.services.payment_service import (
    apply_verified_online_payment,
    maybe_credit_referral_reward,
    confirm_cash_payment,
    initiate_cash_payment,
)


def _make_rider(suffix: str, referred_by: Optional[Rider] = None) -> Rider:
    user = User.objects.create_user(username=f"refrider{suffix}", email=f"refrider{suffix}@example.com")
    return Rider.objects.create(user=user, full_name=f"Rider {suffix}", referred_by=referred_by)


def _make_paid_ride(rider: Rider, total_fare=1000) -> RideRequest:
    return RideRequest.objects.create(
        passenger=rider.user, current_location="A", destination="B",
        status="completed", vehicle_type="Bike", total_fare=Decimal(str(total_fare)),
    )


@override_settings(REFERRAL_REWARD_AMOUNT=500.0)
class MaybeCreditReferralRewardTests(TestCase):
    def test_credits_the_referrer_the_configured_amount(self):
        referrer = _make_rider("1")
        referred = _make_rider("2", referred_by=referrer)
        ride = _make_paid_ride(referred)
        maybe_credit_referral_reward(ride)
        referrer.refresh_from_db()
        self.assertEqual(referrer.wallet_credit_balance, Decimal("500.00"))
        referred.refresh_from_db()
        self.assertTrue(referred.referral_reward_credited)

    def test_does_not_credit_again_on_a_second_paid_ride(self):
        referrer = _make_rider("3")
        referred = _make_rider("4", referred_by=referrer)
        maybe_credit_referral_reward(_make_paid_ride(referred))
        maybe_credit_referral_reward(_make_paid_ride(referred))
        referrer.refresh_from_db()
        self.assertEqual(referrer.wallet_credit_balance, Decimal("500.00"))  # not 1000

    def test_calling_it_twice_for_the_same_ride_does_not_double_credit(self):
        referrer = _make_rider("5")
        referred = _make_rider("6", referred_by=referrer)
        ride = _make_paid_ride(referred)
        maybe_credit_referral_reward(ride)
        maybe_credit_referral_reward(ride)
        referrer.refresh_from_db()
        self.assertEqual(referrer.wallet_credit_balance, Decimal("500.00"))

    def test_a_rider_with_no_referrer_credits_nobody(self):
        referred = _make_rider("7", referred_by=None)
        maybe_credit_referral_reward(_make_paid_ride(referred))
        referred.refresh_from_db()
        self.assertFalse(referred.referral_reward_credited)

    def test_referrers_own_rides_do_not_trigger_their_own_reward(self):
        """referred_by is only ever set on the REFERRED rider — a
        referrer paying for their own ride has no referred_by at all, so
        this must never fire for them regardless of how many rides they
        pay for themselves."""
        referrer = _make_rider("8")
        maybe_credit_referral_reward(_make_paid_ride(referrer))
        referrer.refresh_from_db()
        self.assertEqual(referrer.wallet_credit_balance, Decimal("0"))


@override_settings(REFERRAL_REWARD_AMOUNT=500.0)
class ReferralRewardWiredIntoRealPaymentFlowsTests(TestCase):
    def test_online_payment_confirmation_credits_the_referrer(self):
        referrer = _make_rider("9")
        referred = _make_rider("10", referred_by=referrer)
        ride = _make_paid_ride(referred)
        ride.payment_reference = "REF_ONLINE"
        ride.save(update_fields=["payment_reference"])
        result = apply_verified_online_payment(ride, "REF_ONLINE", amount_kobo=100_000)
        self.assertTrue(result)
        referrer.refresh_from_db()
        self.assertEqual(referrer.wallet_credit_balance, Decimal("500.00"))

    @override_settings(CASH_PAYMENTS_ENABLED=True)
    def test_cash_payment_confirmation_credits_the_referrer(self):
        from gocabapp.models import Driver
        import datetime

        driver_user = User.objects.create_user(username="refdriver1", email="refdriver1@example.com")
        Driver.objects.create(
            user=driver_user, full_name="Ref Driver", phone_number="+2347900000001",
            date_of_birth=datetime.date(1995, 1, 1), vehicle_type="Bike",
            national_identification_number="REFNIN1", bank_name="Test Bank",
            account_number="6666660", account_holder_name="Ref Driver", is_approved=True,
        )
        referrer = _make_rider("11")
        referred = _make_rider("12", referred_by=referrer)
        ride = RideRequest.objects.create(
            passenger=referred.user, driver=driver_user, current_location="A", destination="B",
            status="completed", vehicle_type="Bike", total_fare=Decimal("1000"),
        )
        initiate_cash_payment(referred.user, ride.id)
        ride.refresh_from_db()
        body, status = confirm_cash_payment(driver_user, ride.id, ride.cash_confirmation_code)
        self.assertEqual(status, 200)
        referrer.refresh_from_db()
        self.assertEqual(referrer.wallet_credit_balance, Decimal("500.00"))
