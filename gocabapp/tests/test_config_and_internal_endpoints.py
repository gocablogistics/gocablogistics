"""Coverage for the public /config/* endpoints and the internal,
secret-gated cron endpoints (/internal/run-weekly-payouts,
/internal/send-weekly-payout-reminder) — none of these had any test
before this. sweep-stale-rides, the third endpoint in this same
"trusted internal cron caller" family, already has its own auth-guard
coverage in test_unpaid_ride_escalation.py."""
import datetime
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from gocabapp.models import Driver, DriverPayout, RideRequest

_LIST_BANKS_PATCH_TARGET = "gocabapp.services.payout_service._list_banks"
_SEND_TRANSFER_PATCH_TARGET = "gocabapp.services.payout_service._send_transfer"


class ConfigEndpointsTests(TestCase):
    def test_maps_key_is_public_and_returns_the_configured_key(self):
        with override_settings(GOOGLE_MAPS_API_KEY="AIzaTestKeyForThisAssertionOnly00"):
            response = self.client.get("/api/v1/config/maps-key")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["key"], "AIzaTestKeyForThisAssertionOnly00")

    @override_settings(CASH_PAYMENTS_ENABLED=True, SUPPORT_PHONE_NUMBER="+2341234567890")
    def test_flags_reflects_current_settings(self):
        response = self.client.get("/api/v1/config/flags")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["cash_payments_enabled"])
        self.assertEqual(body["support_phone_number"], "+2341234567890")

    def test_banks_is_public_and_wraps_list_bank_options(self):
        with patch(_LIST_BANKS_PATCH_TARGET, return_value=[{"name": "GTBank", "code": "058"}]):
            response = self.client.get("/api/v1/config/banks")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"banks": [{"name": "GTBank", "code": "058"}]})


@override_settings(STALE_SWEEP_SECRET="test-internal-secret")
class InternalPayoutCronEndpointsTests(TestCase):
    def _make_driver(self, suffix: str) -> Driver:
        user = User.objects.create_user(username=f"introndriver{suffix}", email=f"introndriver{suffix}@example.com")
        return Driver.objects.create(
            user=user, full_name=f"Driver {suffix}", phone_number=f"+23470700000{suffix}",
            date_of_birth=datetime.date(1995, 1, 1), vehicle_type="Bike",
            national_identification_number=f"INTRONNIN{suffix}", bank_name="Test Bank",
            account_number=f"444405{suffix}0", account_holder_name=f"Driver {suffix}",
            is_approved=True, paystack_recipient_code=f"RCP_{suffix}",
        )

    def test_run_weekly_payouts_requires_the_secret(self):
        response = self.client.post("/api/v1/internal/run-weekly-payouts")
        self.assertEqual(response.status_code, 401)

    def test_run_weekly_payouts_rejects_the_wrong_secret(self):
        response = self.client.post(
            "/api/v1/internal/run-weekly-payouts", HTTP_X_SWEEP_SECRET="wrong",
        )
        self.assertEqual(response.status_code, 401)

    def test_run_weekly_payouts_batches_an_owed_drivers_payouts(self):
        driver = self._make_driver("1")
        rider_user = User.objects.create_user(username="intronrider1", email="intronrider1@example.com")
        ride = RideRequest.objects.create(
            passenger=rider_user, driver=driver.user, current_location="A", destination="B",
            status="completed", vehicle_type="Bike", total_fare=Decimal("1000"),
        )
        DriverPayout.objects.create(driver=driver, ride=ride, amount=Decimal("800"), platform_fee=Decimal("200"))

        with patch(_SEND_TRANSFER_PATCH_TARGET, return_value=(True, {})):
            response = self.client.post(
                "/api/v1/internal/run-weekly-payouts", HTTP_X_SWEEP_SECRET="test-internal-secret",
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["batches_created"], 1)

    def test_send_weekly_payout_reminder_requires_the_secret(self):
        response = self.client.post("/api/v1/internal/send-weekly-payout-reminder")
        self.assertEqual(response.status_code, 401)

    def test_send_weekly_payout_reminder_never_touches_any_payout_row(self):
        """Its whole reason to exist instead of just calling
        run_weekly_payouts directly — confirms it's genuinely read-only."""
        driver = self._make_driver("2")
        rider_user = User.objects.create_user(username="intronrider2", email="intronrider2@example.com")
        ride = RideRequest.objects.create(
            passenger=rider_user, driver=driver.user, current_location="A", destination="B",
            status="completed", vehicle_type="Bike", total_fare=Decimal("1000"),
        )
        payout = DriverPayout.objects.create(
            driver=driver, ride=ride, amount=Decimal("800"), platform_fee=Decimal("200"),
        )

        response = self.client.post(
            "/api/v1/internal/send-weekly-payout-reminder", HTTP_X_SWEEP_SECRET="test-internal-secret",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["drivers_owed"], 1)
        payout.refresh_from_db()
        self.assertIsNone(payout.batch_id)
        self.assertEqual(payout.status, "pending")
