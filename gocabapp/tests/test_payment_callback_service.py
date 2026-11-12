"""Coverage for payment_service.handle_payment_callback's own Paystack
verification logic — previously only ever mocked away wholesale in
test_payment_callback_router.py (which exists specifically to test the
router's confirm_token/ownership logic in front of it, not this).
Nothing in the suite had ever exercised the real verify-and-mark-paid
behavior directly. requests.get is the one genuine external boundary
mocked here; everything else runs for real."""
import json
from decimal import Decimal
from unittest.mock import patch

import requests
from django.contrib.auth.models import User
from django.test import TestCase

from gocabapp.models import Rider, RideRequest
from gocabapp.services.payment_service import handle_payment_callback

_GET_PATCH_TARGET = "gocabapp.services.payment_service.requests.get"


def _make_rider(suffix: str) -> Rider:
    user = User.objects.create_user(username=f"cbrider{suffix}", email=f"cbrider{suffix}@example.com")
    return Rider.objects.create(user=user, full_name=f"Rider {suffix}")


def _make_ride(rider: Rider, **extra) -> RideRequest:
    extra.setdefault("total_fare", Decimal("1000"))
    extra.setdefault("payment_status", "pending")
    return RideRequest.objects.create(
        passenger=rider.user, current_location="A", destination="B",
        status="completed", vehicle_type="Bike", **extra,
    )


def _fake_response(status_code=200, body=None):
    response = requests.Response()
    response.status_code = status_code
    response._content = json.dumps(body if body is not None else {}).encode()
    return response


class HandlePaymentCallbackTests(TestCase):
    def test_a_nonexistent_ride_redirects_with_ride_not_found(self):
        result = handle_payment_callback(999999, {})
        self.assertIn("error=ride_not_found", result)

    def test_a_ride_with_no_payment_reference_redirects_with_no_reference(self):
        rider = _make_rider("1")
        ride = _make_ride(rider, payment_reference="")
        result = handle_payment_callback(ride.id, {})
        self.assertIn("error=no_reference", result)

    def test_a_network_failure_talking_to_paystack_redirects_with_request_failed(self):
        rider = _make_rider("2")
        ride = _make_ride(rider, payment_reference="REF_1")
        with patch(_GET_PATCH_TARGET, side_effect=requests.RequestException("timeout")):
            result = handle_payment_callback(ride.id, {})
        self.assertIn("error=request_failed", result)

    def test_a_non_200_from_paystack_redirects_with_the_http_status(self):
        rider = _make_rider("3")
        ride = _make_ride(rider, payment_reference="REF_2")
        with patch(_GET_PATCH_TARGET, return_value=_fake_response(status_code=500)):
            result = handle_payment_callback(ride.id, {})
        self.assertIn("error=http_500", result)
        ride.refresh_from_db()
        self.assertEqual(ride.payment_status, "pending")

    def test_a_failed_paystack_transaction_redirects_with_the_paystack_status(self):
        rider = _make_rider("4")
        ride = _make_ride(rider, payment_reference="REF_3")
        body = {"status": True, "data": {"status": "failed", "amount": 100000}}
        with patch(_GET_PATCH_TARGET, return_value=_fake_response(body=body)):
            result = handle_payment_callback(ride.id, {})
        self.assertIn("error=paystack_failed", result)
        ride.refresh_from_db()
        self.assertEqual(ride.payment_status, "pending")

    def test_a_successful_verification_marks_the_ride_paid(self):
        rider = _make_rider("5")
        ride = _make_ride(rider, payment_reference="REF_4", total_fare=Decimal("1000"))
        body = {"status": True, "data": {"status": "success", "amount": 100000}}  # ₦1000 in kobo
        with patch(_GET_PATCH_TARGET, return_value=_fake_response(body=body)):
            result = handle_payment_callback(ride.id, {})
        self.assertIn("payment=success", result)
        ride.refresh_from_db()
        self.assertEqual(ride.payment_status, "paid")

    def test_a_verified_but_short_amount_redirects_with_amount_mismatch(self):
        """apply_verified_online_payment's own fraud check — a reference
        that's genuinely valid on Paystack but for less than this ride's
        fare must not mark it paid."""
        rider = _make_rider("6")
        ride = _make_ride(rider, payment_reference="REF_5", total_fare=Decimal("1000"))
        body = {"status": True, "data": {"status": "success", "amount": 50000}}  # only ₦500
        with patch(_GET_PATCH_TARGET, return_value=_fake_response(body=body)):
            result = handle_payment_callback(ride.id, {})
        self.assertIn("error=amount_mismatch", result)
        ride.refresh_from_db()
        self.assertEqual(ride.payment_status, "pending")

    def test_a_malformed_paystack_response_body_does_not_crash(self):
        """response.json() raising (not valid JSON) is still an
        unexpected error, not an unhandled 500 — the except Exception
        catch-all at the bottom covers it."""
        rider = _make_rider("7")
        ride = _make_ride(rider, payment_reference="REF_6")
        broken_response = requests.Response()
        broken_response.status_code = 200
        broken_response._content = b"not json"
        with patch(_GET_PATCH_TARGET, return_value=broken_response):
            result = handle_payment_callback(ride.id, {})
        self.assertIn("error=unexpected", result)
