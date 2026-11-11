"""Tests against the three safeguards update_bank_details is supposed to
enforce (see the function's own docstring): a fresh one-time code is
required, Paystack re-verifies the account server-side regardless of
what the client claims, and a bank account already registered to
another driver must be rejected cleanly, not crash. All of this was
proven live against the real server at build time — these are the
repeatable regression versions of those same checks, with Paystack's
own network calls mocked out.
"""
import datetime
import json
import re
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core import mail
from django.core.cache import cache
from django.test import TestCase, override_settings
from ninja_jwt.tokens import RefreshToken

from gocabapp.api.auth import otp
from gocabapp.models import Driver


def _make_driver(suffix: str, email: bool = True) -> Driver:
    user = User.objects.create_user(
        username=f"driver{suffix}", email=f"driver{suffix}@example.com" if email else "",
    )
    return Driver.objects.create(
        user=user, full_name=f"Driver {suffix}", phone_number=f"+23471000000{suffix}",
        date_of_birth=datetime.date(1995, 1, 1), vehicle_type="Bike",
        national_identification_number=f"BDNIN{suffix}", bank_name="Old Bank",
        account_number=f"111111{suffix}0", account_holder_name=f"Driver {suffix}",
        paystack_recipient_code=f"RCP_{suffix}", is_approved=True,
    )


def _auth_header(driver: Driver) -> dict:
    token = str(RefreshToken.for_user(driver.user).access_token)
    return {"HTTP_AUTHORIZATION": f"Bearer {token}"}


def _real_code(email: str) -> str:
    """Pulls the code out of the actual email sent, same as test_otp.py —
    send_code never returns the code, only emails it, and reading the
    real outbox keeps this independent of otp.py's internal storage."""
    otp.send_code(email)
    body = mail.outbox[-1].body
    match = re.search(r"\b\d{6}\b", body)
    if not match:
        raise AssertionError(f"no 6-digit code found in sent email body: {body!r}")
    return match.group()


class UpdateBankDetailsTests(TestCase):
    def setUp(self):
        cache.clear()
        mail.outbox = []

    def test_duplicate_bank_account_is_rejected_cleanly_not_a_500(self):
        """Regression test for the real bug a code review caught the same
        day this endpoint was built: saving a (bank, account number)
        combo another driver already has must return a clean 400, the
        existing Driver.Meta unique constraint shouldn't surface as a
        raw, unhandled IntegrityError."""
        existing = _make_driver("A")
        existing.bank_name = "Access Bank"
        existing.account_number = "0011122233"
        existing.save()

        mover = _make_driver("B")
        code = _real_code(mover.user.email)

        with patch(
            "gocabapp.api.rides.router.resolve_account_name",
            return_value="Driver B",
        ):
            response = self.client.post(
                "/api/v1/rides/driver/update-bank-details",
                data=json.dumps({"bank_code": "044", "account_number": "0011122233", "code": code}),
                content_type="application/json",
                **_auth_header(mover),
            )
        self.assertEqual(response.status_code, 400)
        self.assertIn("already registered", response.json()["detail"])

    def test_successful_change_clears_the_cached_paystack_recipient(self):
        """Documented requirement: changing bank details must force the
        next payout to create a fresh Paystack recipient, not reuse one
        tied to the old account."""
        driver = _make_driver("C")
        self.assertTrue(driver.paystack_recipient_code)
        code = _real_code(driver.user.email)

        with patch(
            "gocabapp.api.rides.router.resolve_account_name",
            return_value="Driver C",
        ), patch(
            "gocabapp.api.rides.router.list_bank_options",
            return_value=[{"name": "GTBank", "code": "058"}],
        ):
            response = self.client.post(
                "/api/v1/rides/driver/update-bank-details",
                data=json.dumps({"bank_code": "058", "account_number": "9988776655", "code": code}),
                content_type="application/json",
                **_auth_header(driver),
            )
        self.assertEqual(response.status_code, 200)
        driver.refresh_from_db()
        self.assertEqual(driver.paystack_recipient_code, "")
        self.assertEqual(driver.account_number, "9988776655")
        self.assertEqual(driver.account_holder_name, "Driver C")

    @override_settings(ADMIN_NOTIFICATION_EMAIL="admin@example.com")
    def test_admin_gets_alerted_on_a_successful_change(self):
        driver = _make_driver("D")
        code = _real_code(driver.user.email)
        with patch(
            "gocabapp.api.rides.router.resolve_account_name",
            return_value="Driver D",
        ), patch(
            "gocabapp.api.rides.router.list_bank_options",
            return_value=[{"name": "GTBank", "code": "058"}],
        ):
            self.client.post(
                "/api/v1/rides/driver/update-bank-details",
                data=json.dumps({"bank_code": "058", "account_number": "9988776656", "code": code}),
                content_type="application/json",
                **_auth_header(driver),
            )
        # The OTP code itself also sends a real email via _real_code(),
        # so the outbox legitimately has more than just the alert —
        # check the alert exists, not that it's alone in the outbox.
        alerts = [m for m in mail.outbox if "changed their payout bank details" in m.subject]
        self.assertEqual(len(alerts), 1)

    def test_wrong_code_is_rejected_and_nothing_saves(self):
        driver = _make_driver("E")
        original_account = driver.account_number
        _real_code(driver.user.email)  # sent, but we'll submit a wrong one
        with patch(
            "gocabapp.api.rides.router.resolve_account_name",
            return_value="Driver E",
        ):
            response = self.client.post(
                "/api/v1/rides/driver/update-bank-details",
                data=json.dumps({"bank_code": "058", "account_number": "9988776657", "code": "000000"}),
                content_type="application/json",
                **_auth_header(driver),
            )
        self.assertEqual(response.status_code, 400)
        driver.refresh_from_db()
        self.assertEqual(driver.account_number, original_account)

    def test_driver_with_no_email_gets_a_clean_error_not_a_crash(self):
        driver = _make_driver("F", email=False)
        response = self.client.post(
            "/api/v1/rides/driver/update-bank-details",
            data=json.dumps({"bank_code": "058", "account_number": "9988776658", "code": "123456"}),
            content_type="application/json",
            **_auth_header(driver),
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("email", response.json()["detail"].lower())

    def test_unresolvable_account_is_rejected_on_the_preview_endpoint(self):
        driver = _make_driver("G")
        with patch(
            "gocabapp.api.rides.router.resolve_account_name",
            return_value=None,
        ):
            response = self.client.post(
                "/api/v1/rides/driver/resolve-bank-account",
                data=json.dumps({"bank_code": "058", "account_number": "0000000000"}),
                content_type="application/json",
                **_auth_header(driver),
            )
        self.assertEqual(response.status_code, 400)
