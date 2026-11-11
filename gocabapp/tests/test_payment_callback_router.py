"""Coverage for GET /rides/{id}/payment-callback — specifically the
confirm_token bypass logic documented in utils/payment_confirm.py: a
real production bug (rides 277, 278, 281) where a genuinely paid ride
404'd because a different tab of the same browser had logged into
another account by the time Paystack's redirect reloaded the page.
handle_payment_callback's own Paystack-verification logic is mocked out
here — this file is only about the router's ownership/token check in
front of it, not re-proving Paystack verification itself."""
import datetime
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from ninja_jwt.tokens import RefreshToken

from gocabapp.models import Rider, RideRequest
from gocabapp.utils.payment_confirm import make_payment_confirm_token

_CALLBACK_PATCH_TARGET = "gocabapp.api.rides.router.handle_payment_callback"


def _make_rider(suffix: str) -> Rider:
    user = User.objects.create_user(username=f"pcbrider{suffix}", email=f"pcbrider{suffix}@example.com")
    return Rider.objects.create(user=user, full_name=f"Rider {suffix}")


def _make_ride(rider: Rider, payment_status="paid") -> RideRequest:
    return RideRequest.objects.create(
        passenger=rider.user, current_location="A", destination="B",
        status="completed", vehicle_type="Bike", total_fare=Decimal("1000"),
        payment_status=payment_status,
    )


def _auth_header(user: User) -> dict:
    token = str(RefreshToken.for_user(user).access_token)
    return {"HTTP_AUTHORIZATION": f"Bearer {token}"}


class PaymentCallbackOwnershipTests(TestCase):
    def test_the_actual_owner_can_check_their_own_ride_with_no_token(self):
        rider = _make_rider("1")
        ride = _make_ride(rider)
        with patch(_CALLBACK_PATCH_TARGET, return_value="/anything"):
            response = self.client.get(
                f"/api/v1/rides/{ride.id}/payment-callback", **_auth_header(rider.user),
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["ride_id"], ride.id)

    def test_a_different_logged_in_account_with_no_token_gets_404(self):
        """The exact pre-fix behavior for rides 277/278/281 — this is what
        must stay blocked for anyone who genuinely isn't this ride's
        owner and has no valid confirm_token."""
        rider = _make_rider("2")
        stranger = _make_rider("3")
        ride = _make_ride(rider)
        with patch(_CALLBACK_PATCH_TARGET, return_value="/anything"):
            response = self.client.get(
                f"/api/v1/rides/{ride.id}/payment-callback", **_auth_header(stranger.user),
            )
        self.assertEqual(response.status_code, 404)

    def test_a_valid_confirm_token_bypasses_the_logged_in_account_mismatch(self):
        """The actual fix: the browser that started this payment proves it
        via the signed token, regardless of which account is logged into
        this tab by the time Paystack redirects back."""
        rider = _make_rider("4")
        stranger = _make_rider("5")
        ride = _make_ride(rider)
        token = make_payment_confirm_token(ride.id)
        with patch(_CALLBACK_PATCH_TARGET, return_value="/anything"):
            response = self.client.get(
                f"/api/v1/rides/{ride.id}/payment-callback?confirm_token={token}",
                **_auth_header(stranger.user),
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["ride_id"], ride.id)

    def test_a_confirm_token_minted_for_a_different_ride_does_not_bypass_anything(self):
        rider = _make_rider("6")
        stranger = _make_rider("7")
        ride = _make_ride(rider)
        other_ride = _make_ride(rider)
        token_for_other_ride = make_payment_confirm_token(other_ride.id)
        with patch(_CALLBACK_PATCH_TARGET, return_value="/anything"):
            response = self.client.get(
                f"/api/v1/rides/{ride.id}/payment-callback?confirm_token={token_for_other_ride}",
                **_auth_header(stranger.user),
            )
        self.assertEqual(response.status_code, 404)

    def test_a_garbage_confirm_token_falls_back_to_the_ownership_check(self):
        rider = _make_rider("8")
        ride = _make_ride(rider)
        with patch(_CALLBACK_PATCH_TARGET, return_value="/anything"):
            response = self.client.get(
                f"/api/v1/rides/{ride.id}/payment-callback?confirm_token=not-a-real-token",
                **_auth_header(rider.user),
            )
        # Falls through to the ownership check, which the real owner still passes.
        self.assertEqual(response.status_code, 200)

    def test_nonexistent_ride_is_a_404_even_with_a_token(self):
        rider = _make_rider("9")
        token = make_payment_confirm_token(999999)
        with patch(_CALLBACK_PATCH_TARGET, return_value="/anything"):
            response = self.client.get(
                "/api/v1/rides/999999/payment-callback?confirm_token=" + token,
                **_auth_header(rider.user),
            )
        self.assertEqual(response.status_code, 404)
