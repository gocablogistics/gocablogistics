"""Tests against the stated rules in payment_service.py's own docstrings
for the path that actually decides whether a ride gets marked paid —
arguably the single most consequential untested code in the app before
today. Covers: webhook signature verification (the only thing that
should ever be trusted as "this really came from Paystack"), the
fraud-prevention amount check (a cheap reference can't be reused to
underpay an expensive ride), wallet credit being correctly factored into
what's actually expected, and idempotency (a webhook firing twice must
not double-create a payout).
"""
import datetime
import hashlib
import hmac
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from gocabapp.models import Driver, DriverPayout, RideRequest
from gocabapp.services.payment_service import (
    apply_verified_online_payment,
    handle_paystack_webhook,
    verify_paystack_signature,
)


class SignatureVerificationTests(TestCase):
    @override_settings(PAYSTACK_SECRET_KEY="test-secret-key")
    def test_correct_signature_verifies(self):
        body = b'{"event": "charge.success"}'
        signature = hmac.new(b"test-secret-key", body, hashlib.sha512).hexdigest()
        self.assertTrue(verify_paystack_signature(body, signature))

    @override_settings(PAYSTACK_SECRET_KEY="test-secret-key")
    def test_wrong_signature_is_rejected(self):
        body = b'{"event": "charge.success"}'
        self.assertFalse(verify_paystack_signature(body, "not-the-real-signature"))

    @override_settings(PAYSTACK_SECRET_KEY="test-secret-key")
    def test_missing_signature_header_is_rejected(self):
        self.assertFalse(verify_paystack_signature(b"{}", None))

    @override_settings(PAYSTACK_SECRET_KEY="test-secret-key")
    def test_signature_for_different_body_is_rejected(self):
        """A signature computed over one payload must not verify against
        a different one — catches any form of payload tampering in
        transit, not just a missing/garbage signature."""
        real_body = b'{"event": "charge.success", "data": {"amount": 100000}}'
        signature = hmac.new(b"test-secret-key", real_body, hashlib.sha512).hexdigest()
        tampered_body = b'{"event": "charge.success", "data": {"amount": 999999}}'
        self.assertFalse(verify_paystack_signature(tampered_body, signature))


def _make_paid_ride(total_fare, wallet_credit=0, reference="RIDE_1_REF") -> RideRequest:
    rider = User.objects.create_user(username="rider1", email="rider1@example.com")
    driver_user = User.objects.create_user(username="driver1", email="driver1@example.com")
    Driver.objects.create(
        user=driver_user, full_name="Driver One", phone_number="+2347200000001",
        date_of_birth=datetime.date(1995, 1, 1), vehicle_type="Bike",
        national_identification_number="PAYNIN1", bank_name="Test Bank",
        account_number="1234567890", account_holder_name="Driver One", is_approved=True,
    )
    return RideRequest.objects.create(
        passenger=rider, driver=driver_user, current_location="A", destination="B",
        status="completed", vehicle_type="Bike",
        total_fare=Decimal(str(total_fare)), wallet_credit_applied=Decimal(str(wallet_credit)),
        payment_reference=reference, payment_status="pending",
    )


class ApplyVerifiedOnlinePaymentTests(TestCase):
    def test_correct_amount_marks_the_ride_paid_and_creates_a_payout(self):
        ride = _make_paid_ride(total_fare=1000)
        result = apply_verified_online_payment(ride, "RIDE_1_REF", amount_kobo=100_000)
        self.assertTrue(result)
        ride.refresh_from_db()
        self.assertEqual(ride.payment_status, "paid")
        self.assertEqual(DriverPayout.objects.filter(ride=ride).count(), 1)

    def test_mismatched_amount_does_not_mark_the_ride_paid(self):
        """The fraud-prevention check this function exists for: a
        cheaper, genuinely-paid reference can't be replayed to mark a
        more expensive ride as paid."""
        ride = _make_paid_ride(total_fare=5000)
        result = apply_verified_online_payment(ride, "RIDE_1_REF", amount_kobo=100_000)  # only ₦1000 paid
        self.assertFalse(result)
        ride.refresh_from_db()
        self.assertEqual(ride.payment_status, "pending")
        self.assertEqual(DriverPayout.objects.filter(ride=ride).count(), 0)

    def test_wallet_credit_reduces_the_amount_actually_expected(self):
        """A rider with ₦200 wallet credit on a ₦1000 ride was only ever
        charged ₦800 through Paystack — the expected amount must reflect
        that discount, not the full fare."""
        ride = _make_paid_ride(total_fare=1000, wallet_credit=200)
        underpaid_as_if_full_fare = apply_verified_online_payment(ride, "RIDE_1_REF", amount_kobo=100_000)
        self.assertFalse(underpaid_as_if_full_fare)
        ride.refresh_from_db()
        self.assertEqual(ride.payment_status, "pending")

        correctly_discounted = apply_verified_online_payment(ride, "RIDE_1_REF", amount_kobo=80_000)
        self.assertTrue(correctly_discounted)
        ride.refresh_from_db()
        self.assertEqual(ride.payment_status, "paid")

    def test_applying_twice_does_not_create_a_second_payout(self):
        """Idempotency — a webhook retry or a race between the webhook
        and the browser callback must not double-pay a driver."""
        ride = _make_paid_ride(total_fare=1000)
        apply_verified_online_payment(ride, "RIDE_1_REF", amount_kobo=100_000)
        ride.refresh_from_db()
        second_call_result = apply_verified_online_payment(ride, "RIDE_1_REF", amount_kobo=100_000)
        self.assertTrue(second_call_result)  # documented as a safe no-op, not a failure
        self.assertEqual(DriverPayout.objects.filter(ride=ride).count(), 1)


class HandlePaystackWebhookTests(TestCase):
    def test_charge_success_with_correct_amount_marks_the_ride_paid(self):
        ride = _make_paid_ride(total_fare=1000, reference="WEBHOOK_REF_1")
        handle_paystack_webhook({
            "event": "charge.success",
            "data": {"reference": "WEBHOOK_REF_1", "amount": 100_000},
        })
        ride.refresh_from_db()
        self.assertEqual(ride.payment_status, "paid")

    def test_charge_success_with_wrong_amount_does_not_mark_paid(self):
        ride = _make_paid_ride(total_fare=5000, reference="WEBHOOK_REF_2")
        handle_paystack_webhook({
            "event": "charge.success",
            "data": {"reference": "WEBHOOK_REF_2", "amount": 100_000},
        })
        ride.refresh_from_db()
        self.assertEqual(ride.payment_status, "pending")

    def test_unknown_reference_with_no_ride_id_metadata_does_not_crash(self):
        """A reference the DB no longer remembers (see the comment this
        tests: a rider tapped Pay twice) and no ride_id metadata to fall
        back on must be logged and ignored, not raise."""
        handle_paystack_webhook({
            "event": "charge.success",
            "data": {"reference": "NEVER_SEEN_REF", "amount": 100_000, "metadata": {}},
        })  # must not raise

    def test_unrelated_event_types_are_ignored(self):
        ride = _make_paid_ride(total_fare=1000, reference="WEBHOOK_REF_3")
        handle_paystack_webhook({"event": "customer.created", "data": {}})
        ride.refresh_from_db()
        self.assertEqual(ride.payment_status, "pending")
