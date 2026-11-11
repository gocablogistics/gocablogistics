"""Tests against the documented rules in payment_service.py's
fingerprint_from_webhook_data / record_and_check_payment_instrument: a
rider flagged for non-payment who abandons that account and signs up
fresh should still be caught if the new account pays with the same card.
"""
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase

from gocabapp.models import RideRequest, Rider, RiderPaymentInstrument
from gocabapp.services.payment_service import (
    fingerprint_from_webhook_data,
    record_and_check_payment_instrument,
    handle_paystack_webhook,
)


def _make_rider(suffix: str, is_flagged=False) -> Rider:
    user = User.objects.create_user(username=f"fpuser{suffix}", email=f"fpuser{suffix}@example.com")
    return Rider.objects.create(user=user, full_name=f"Rider {suffix}", is_flagged=is_flagged)


def _make_ride(rider: Rider, reference: str = "") -> RideRequest:
    return RideRequest.objects.create(
        passenger=rider.user, current_location="A", destination="B",
        status="completed", vehicle_type="Bike", total_fare=Decimal("5000"),
        payment_reference=reference,
    )


class FingerprintFromWebhookDataTests(TestCase):
    def test_card_with_bin_and_last4_fingerprints_on_those(self):
        data = {"channel": "card", "authorization": {"bin": "408408", "last4": "4081"}}
        self.assertEqual(fingerprint_from_webhook_data(data), "card:408408:4081")

    def test_card_falls_back_to_authorization_code_without_bin_last4(self):
        data = {"channel": "card", "authorization": {"authorization_code": "AUTH_abc123"}}
        self.assertEqual(fingerprint_from_webhook_data(data), "auth:AUTH_abc123")

    def test_bank_transfer_is_not_fingerprinted(self):
        data = {"channel": "bank_transfer", "authorization": {}}
        self.assertIsNone(fingerprint_from_webhook_data(data))

    def test_card_with_no_usable_authorization_data_returns_none(self):
        data = {"channel": "card", "authorization": {}}
        self.assertIsNone(fingerprint_from_webhook_data(data))


class RecordAndCheckPaymentInstrumentTests(TestCase):
    def _card_data(self, bin_="408408", last4="4081"):
        return {"channel": "card", "authorization": {"bin": bin_, "last4": last4}}

    def test_logs_the_fingerprint_against_the_paying_rider(self):
        rider = _make_rider("1")
        ride = _make_ride(rider)
        record_and_check_payment_instrument(ride, self._card_data())
        self.assertTrue(
            RiderPaymentInstrument.objects.filter(rider=rider, fingerprint="card:408408:4081").exists()
        )

    def test_same_rider_paying_again_does_not_duplicate_or_flag(self):
        rider = _make_rider("2")
        ride = _make_ride(rider)
        record_and_check_payment_instrument(ride, self._card_data())
        record_and_check_payment_instrument(ride, self._card_data())
        self.assertEqual(RiderPaymentInstrument.objects.filter(rider=rider).count(), 1)
        rider.refresh_from_db()
        self.assertFalse(rider.is_flagged)

    def test_a_different_riders_card_does_not_trigger_a_flag(self):
        flagged_rider = _make_rider("3", is_flagged=True)
        RiderPaymentInstrument.objects.create(rider=flagged_rider, fingerprint="card:111111:9999")
        clean_rider = _make_rider("4")
        ride = _make_ride(clean_rider)
        record_and_check_payment_instrument(ride, self._card_data(bin_="222222", last4="8888"))
        clean_rider.refresh_from_db()
        self.assertFalse(clean_rider.is_flagged)

    def test_reusing_a_flagged_riders_card_auto_flags_the_new_account(self):
        flagged_rider = _make_rider("5", is_flagged=True)
        RiderPaymentInstrument.objects.create(rider=flagged_rider, fingerprint="card:408408:4081")
        evader = _make_rider("6")
        ride = _make_ride(evader)
        record_and_check_payment_instrument(ride, self._card_data())
        evader.refresh_from_db()
        self.assertTrue(evader.is_flagged)
        self.assertIn("matches another flagged account", evader.flagged_reason)

    def test_reusing_a_now_unflagged_riders_card_does_not_flag(self):
        """The check is dynamic (joins on rider.is_flagged at query time),
        not a static snapshot — once an admin clears the original rider,
        their card stops being a signal too."""
        cleared_rider = _make_rider("7", is_flagged=False)
        RiderPaymentInstrument.objects.create(rider=cleared_rider, fingerprint="card:408408:4081")
        other_rider = _make_rider("8")
        ride = _make_ride(other_rider)
        record_and_check_payment_instrument(ride, self._card_data())
        other_rider.refresh_from_db()
        self.assertFalse(other_rider.is_flagged)


class WebhookWiresInstrumentCheckTests(TestCase):
    def test_handle_paystack_webhook_flags_an_evading_account_on_a_rejected_charge(self):
        """The instrument check must run even when the amount doesn't
        match this ride (see apply_verified_online_payment) — a rejected
        charge still proves the card was genuinely used."""
        flagged_rider = _make_rider("9", is_flagged=True)
        RiderPaymentInstrument.objects.create(rider=flagged_rider, fingerprint="card:408408:4081")

        evader = _make_rider("10")
        ride = _make_ride(evader, reference="EVADE_REF")
        handle_paystack_webhook({
            "event": "charge.success",
            "data": {
                "reference": "EVADE_REF", "amount": 100_000,  # mismatched on purpose
                "channel": "card", "authorization": {"bin": "408408", "last4": "4081"},
            },
        })
        evader.refresh_from_db()
        self.assertTrue(evader.is_flagged)
        ride.refresh_from_db()
        self.assertEqual(ride.payment_status, "pending")  # the mismatch still correctly rejects payment
