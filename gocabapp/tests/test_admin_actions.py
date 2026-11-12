"""Coverage for admin.py's custom admin actions — real moderation and
money-movement logic (ban/flag accounts, resolve disputes, settle cash
debt, retry payouts), not just Django admin UI glue, and previously
completely untested. Actions are called directly (the standard,
lightweight way to test a ModelAdmin action) rather than through the
full admin HTTP changelist UI.
"""
import datetime
import itertools
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.contrib.messages.storage.fallback import FallbackStorage
from django.core import mail
from django.test import RequestFactory, TestCase, override_settings

from gocabapp.admin import (
    CashDebtEntryAdmin,
    DriverAdmin,
    DriverPayoutAdmin,
    PaymentDisputeAdmin,
    RideRequestAdmin,
    RiderPaymentInstrumentAdmin,
    WeeklyPayoutBatchAdmin,
)
from gocabapp.models import (
    CashDebtEntry,
    Driver,
    DriverPayout,
    Notification,
    PaymentDispute,
    Rider,
    RideRequest,
    RiderPaymentInstrument,
    WeeklyPayoutBatch,
)

_SEND_TRANSFER_PATCH_TARGET = "gocabapp.services.payout_service._send_transfer"
_REFUND_POST_PATCH_TARGET = "gocabapp.services.payment_service.requests.post"


_admin_user_counter = itertools.count(1)


def _admin_request(post_data=None):
    request = RequestFactory().post("/admin/", data=post_data or {})
    n = next(_admin_user_counter)
    request.user = User.objects.create_superuser(
        username=f"adminuser{n}", email=f"admin-test{n}@example.com", password="x",
    )
    setattr(request, "session", {})
    messages = FallbackStorage(request)
    setattr(request, "_messages", messages)
    return request


def _make_rider(suffix: str, **extra) -> Rider:
    user = User.objects.create_user(username=f"adminrider{suffix}", email=f"adminrider{suffix}@example.com")
    return Rider.objects.create(user=user, full_name=f"Rider {suffix}", **extra)


def _make_driver(suffix: str, **extra) -> Driver:
    user = User.objects.create_user(username=f"admindriver{suffix}", email=f"admindriver{suffix}@example.com")
    extra.setdefault("is_approved", True)
    return Driver.objects.create(
        user=user, full_name=f"Driver {suffix}", phone_number=f"+23472200000{suffix}",
        date_of_birth=datetime.date(1995, 1, 1), vehicle_type="Bike",
        national_identification_number=f"ADMNIN{suffix}", bank_name="Test Bank",
        account_number=f"777225{suffix}0", account_holder_name=f"Driver {suffix}",
        **extra,
    )


def _make_ride(rider: Rider, driver: Driver = None, **extra) -> RideRequest:
    extra.setdefault("status", "completed")
    return RideRequest.objects.create(
        passenger=rider.user, driver=driver.user if driver else None,
        current_location="A", destination="B",
        vehicle_type="Bike", total_fare=Decimal("1000"), **extra,
    )


class DriverAdminActionsTests(TestCase):
    def setUp(self):
        self.admin = DriverAdmin(Driver, None)

    def test_settle_cash_debt_clears_balance_and_notifies(self):
        driver = _make_driver("1", cash_debt=Decimal("500"))
        self.admin.settle_cash_debt(_admin_request(), Driver.objects.filter(id=driver.id))
        driver.refresh_from_db()
        self.assertEqual(driver.cash_debt, Decimal("0"))
        self.assertTrue(CashDebtEntry.objects.filter(driver=driver, entry_type="settlement").exists())
        self.assertTrue(Notification.objects.filter(user=driver.user, message__icontains="settled").exists())

    def test_settle_cash_debt_skips_a_driver_with_nothing_owed(self):
        driver = _make_driver("2", cash_debt=Decimal("0"))
        self.admin.settle_cash_debt(_admin_request(), Driver.objects.filter(id=driver.id))
        self.assertFalse(CashDebtEntry.objects.filter(driver=driver).exists())

    def test_approve_drivers_clears_rejection_state(self):
        driver = _make_driver(
            "3", is_approved=False, needs_reverification=True, rejection_reason="blurry photo",
        )
        self.admin.approve_drivers(_admin_request(), Driver.objects.filter(id=driver.id))
        driver.refresh_from_db()
        self.assertTrue(driver.is_approved)
        self.assertFalse(driver.needs_reverification)
        self.assertEqual(driver.rejection_reason, "")

    def test_mark_not_verified_sets_reason_and_emails_the_driver(self):
        driver = _make_driver("4", is_approved=True)
        request = _admin_request({"reason": "License photo unreadable"})
        self.admin.mark_not_verified(request, Driver.objects.filter(id=driver.id))
        driver.refresh_from_db()
        self.assertFalse(driver.is_approved)
        self.assertTrue(driver.needs_reverification)
        self.assertEqual(driver.rejection_reason, "License photo unreadable")
        self.assertTrue(any("documents need another look" in m.subject for m in mail.outbox))

    def test_make_available_resets_busy_state(self):
        driver = _make_driver("5", is_busy=True)
        self.admin.make_available(_admin_request(), Driver.objects.filter(id=driver.id))
        driver.refresh_from_db()
        self.assertFalse(driver.is_busy)
        self.assertIsNone(driver.current_ride_id)


class FlagActionsTests(TestCase):
    def setUp(self):
        self.admin = PaymentDisputeAdmin(PaymentDispute, None)

    def test_flag_rider_disputes_the_ride_and_flags_the_account(self):
        rider = _make_rider("1")
        driver = _make_driver("6")
        ride = _make_ride(rider, driver, payment_status="reported")
        dispute = PaymentDispute.objects.create(ride=ride, status="open", driver_statement="never paid")

        self.admin.flag_rider(_admin_request(), PaymentDispute.objects.filter(id=dispute.id))
        ride.refresh_from_db()
        rider.refresh_from_db()
        self.assertEqual(ride.payment_status, "disputed")
        self.assertTrue(rider.is_flagged)
        self.assertEqual(rider.flagged_reason, "never paid")

    def test_flag_rider_skips_an_already_resolved_dispute(self):
        rider = _make_rider("2")
        ride = _make_ride(rider, payment_status="reported")
        dispute = PaymentDispute.objects.create(ride=ride, status="resolved", driver_statement="never paid")

        self.admin.flag_rider(_admin_request(), PaymentDispute.objects.filter(id=dispute.id))
        rider.refresh_from_db()
        self.assertFalse(rider.is_flagged)

    def test_flag_driver_flags_the_account_and_notifies(self):
        rider = _make_rider("3")
        driver = _make_driver("7")
        ride = _make_ride(rider, driver)
        dispute = PaymentDispute.objects.create(ride=ride, status="open", rider_statement="he was rude")

        self.admin.flag_driver(_admin_request(), PaymentDispute.objects.filter(id=dispute.id))
        driver.refresh_from_db()
        self.assertTrue(driver.is_flagged)
        self.assertEqual(driver.flagged_reason, "he was rude")
        self.assertTrue(Notification.objects.filter(user=driver.user, message__icontains="flagged").exists())

    def test_flag_driver_is_a_no_op_when_the_ride_has_no_driver(self):
        rider = _make_rider("4")
        ride = _make_ride(rider)
        dispute = PaymentDispute.objects.create(ride=ride, status="open", rider_statement="whatever")
        # Must not raise despite ride.driver being None.
        self.admin.flag_driver(_admin_request(), PaymentDispute.objects.filter(id=dispute.id))


class ResolveRefundDismissTests(TestCase):
    def setUp(self):
        self.admin = PaymentDisputeAdmin(PaymentDispute, None)

    def test_resolve_rider_paid_marks_the_ride_paid_and_creates_a_payout_for_online(self):
        rider = _make_rider("5")
        driver = _make_driver("8")
        ride = _make_ride(rider, driver, payment_status="reported", payment_method="online")
        dispute = PaymentDispute.objects.create(ride=ride, status="open", driver_statement="never paid")

        self.admin.resolve_rider_paid(_admin_request(), PaymentDispute.objects.filter(id=dispute.id))
        ride.refresh_from_db()
        dispute.refresh_from_db()
        self.assertEqual(ride.payment_status, "paid")
        self.assertIsNotNone(ride.paid_at)
        self.assertEqual(dispute.status, "resolved")
        self.assertTrue(DriverPayout.objects.filter(ride=ride).exists())

    def test_resolve_rider_paid_charges_cash_commission_for_cash_rides(self):
        rider = _make_rider("6")
        driver = _make_driver("9")
        ride = _make_ride(rider, driver, payment_status="reported", payment_method="cash")
        dispute = PaymentDispute.objects.create(ride=ride, status="open", driver_statement="never paid")

        self.admin.resolve_rider_paid(_admin_request(), PaymentDispute.objects.filter(id=dispute.id))
        self.assertTrue(CashDebtEntry.objects.filter(driver=driver, ride=ride, entry_type="charge").exists())

    def test_refund_rider_resolves_the_dispute_on_success(self):
        rider = _make_rider("7")
        ride = _make_ride(
            rider, payment_status="paid", payment_method="online", payment_reference="REF_ADMIN_1",
        )
        dispute = PaymentDispute.objects.create(ride=ride, status="open", rider_statement="never showed up")

        fake_response = type("R", (), {
            "status_code": 200, "content": b"{}",
            "json": lambda self: {"status": True},
        })()
        with patch(_REFUND_POST_PATCH_TARGET, return_value=fake_response):
            self.admin.refund_rider(_admin_request(), PaymentDispute.objects.filter(id=dispute.id))
        ride.refresh_from_db()
        dispute.refresh_from_db()
        self.assertEqual(ride.payment_status, "refunded")
        self.assertEqual(dispute.status, "resolved")

    def test_refund_rider_leaves_the_dispute_open_on_failure(self):
        """A cash ride can never be refunded via Paystack — confirms the
        admin action surfaces that failure instead of silently resolving
        the dispute anyway."""
        rider = _make_rider("8")
        ride = _make_ride(rider, payment_status="paid", payment_method="cash")
        dispute = PaymentDispute.objects.create(ride=ride, status="open", rider_statement="never showed up")

        self.admin.refund_rider(_admin_request(), PaymentDispute.objects.filter(id=dispute.id))
        dispute.refresh_from_db()
        ride.refresh_from_db()
        self.assertEqual(dispute.status, "open")
        self.assertEqual(ride.payment_status, "paid")

    def test_dismiss_dispute_rolls_back_a_reported_ride_and_clears_flags(self):
        rider = _make_rider("9", is_flagged=True)
        driver = _make_driver("10", is_flagged=True)
        ride = _make_ride(rider, driver, payment_status="disputed")
        dispute = PaymentDispute.objects.create(ride=ride, status="open", driver_statement="never paid")

        self.admin.dismiss_dispute(_admin_request(), PaymentDispute.objects.filter(id=dispute.id))
        ride.refresh_from_db()
        rider.refresh_from_db()
        driver.refresh_from_db()
        dispute.refresh_from_db()
        self.assertEqual(ride.payment_status, "pending")
        self.assertFalse(rider.is_flagged)
        self.assertFalse(driver.is_flagged)
        self.assertEqual(dispute.status, "dismissed")

    def test_dismiss_dispute_leaves_an_already_paid_ride_alone(self):
        """report_driver (pure conduct complaint) never touches
        payment_status — dismissing it must not incorrectly reset an
        already-paid ride back to pending."""
        rider = _make_rider("10")
        driver = _make_driver("11")
        ride = _make_ride(rider, driver, payment_status="paid")
        dispute = PaymentDispute.objects.create(ride=ride, status="open", rider_statement="he was rude")

        self.admin.dismiss_dispute(_admin_request(), PaymentDispute.objects.filter(id=dispute.id))
        ride.refresh_from_db()
        self.assertEqual(ride.payment_status, "paid")


class BanActionsTests(TestCase):
    def setUp(self):
        self.admin = PaymentDisputeAdmin(PaymentDispute, None)

    def test_ban_rider_deactivates_the_account(self):
        rider = _make_rider("11")
        ride = _make_ride(rider, payment_status="reported")
        dispute = PaymentDispute.objects.create(ride=ride, status="open", driver_statement="never paid")

        self.admin.ban_rider(_admin_request(), PaymentDispute.objects.filter(id=dispute.id))
        rider.user.refresh_from_db()
        dispute.refresh_from_db()
        self.assertFalse(rider.user.is_active)
        self.assertEqual(dispute.status, "resolved")

    def test_ban_rider_cancels_their_other_active_rides(self):
        rider = _make_rider("12")
        driver = _make_driver("12", is_busy=True)
        disputed_ride = _make_ride(rider, payment_status="reported")
        other_ride = RideRequest.objects.create(
            passenger=rider.user, driver=driver.user, current_location="A", destination="B",
            status="accepted", vehicle_type="Bike", total_fare=Decimal("500"),
        )
        dispute = PaymentDispute.objects.create(ride=disputed_ride, status="open", driver_statement="never paid")

        self.admin.ban_rider(_admin_request(), PaymentDispute.objects.filter(id=dispute.id))
        other_ride.refresh_from_db()
        driver.refresh_from_db()
        self.assertEqual(other_ride.status, "cancelled")
        self.assertFalse(driver.is_busy)

    def test_ban_driver_deactivates_the_account_and_clears_the_rider_block(self):
        rider = _make_rider("13")
        driver = _make_driver("13")
        ride = _make_ride(rider, driver, payment_status="disputed")
        dispute = PaymentDispute.objects.create(ride=ride, status="open", rider_statement="he was rude")

        self.admin.ban_driver(_admin_request(), PaymentDispute.objects.filter(id=dispute.id))
        driver.user.refresh_from_db()
        ride.refresh_from_db()
        dispute.refresh_from_db()
        self.assertFalse(driver.user.is_active)
        self.assertEqual(ride.payment_status, "pending")
        self.assertEqual(dispute.status, "resolved")

    def test_ban_driver_reopens_an_accepted_other_ride_for_a_new_driver(self):
        rider = _make_rider("14")
        driver = _make_driver("14")
        other_rider = _make_rider("15")
        disputed_ride = _make_ride(rider, driver)
        other_ride = RideRequest.objects.create(
            passenger=other_rider.user, driver=driver.user, current_location="A", destination="B",
            status="accepted", vehicle_type="Bike", total_fare=Decimal("500"),
        )
        dispute = PaymentDispute.objects.create(ride=disputed_ride, status="open", rider_statement="scary driving")

        self.admin.ban_driver(_admin_request(), PaymentDispute.objects.filter(id=dispute.id))
        other_ride.refresh_from_db()
        self.assertEqual(other_ride.status, "pending")
        self.assertIsNone(other_ride.driver_id)

    def test_ban_driver_cancels_a_started_other_ride_outright(self):
        """A started ride can't safely hand off to a stranger mid-trip —
        confirmed this ends it instead of reopening it like an accepted one."""
        rider = _make_rider("16")
        driver = _make_driver("15")
        other_rider = _make_rider("17")
        disputed_ride = _make_ride(rider, driver)
        other_ride = RideRequest.objects.create(
            passenger=other_rider.user, driver=driver.user, current_location="A", destination="B",
            status="started", vehicle_type="Bike", total_fare=Decimal("500"),
        )
        dispute = PaymentDispute.objects.create(ride=disputed_ride, status="open", rider_statement="scary driving")

        self.admin.ban_driver(_admin_request(), PaymentDispute.objects.filter(id=dispute.id))
        other_ride.refresh_from_db()
        self.assertEqual(other_ride.status, "cancelled")


class DriverPayoutAdminActionsTests(TestCase):
    def setUp(self):
        self.admin = DriverPayoutAdmin(DriverPayout, None)

    def _make_payout(self, driver, status="pending"):
        rider = _make_rider(f"p{RideRequest.objects.count()}")
        ride = _make_ride(rider, driver)
        return DriverPayout.objects.create(
            driver=driver, ride=ride, amount=Decimal("800"), platform_fee=Decimal("200"), status=status,
        )

    def test_retry_transfer_only_acts_on_pending_or_failed(self):
        driver = _make_driver("16", paystack_recipient_code="RCP_1")
        pending = self._make_payout(driver, status="pending")
        paid = self._make_payout(driver, status="paid")

        with patch(_SEND_TRANSFER_PATCH_TARGET, return_value=(True, {})) as mock_transfer:
            self.admin.retry_transfer(
                _admin_request(), DriverPayout.objects.filter(id__in=[pending.id, paid.id]),
            )
        mock_transfer.assert_called_once()

    def test_mark_as_paid_sets_status_and_timestamp(self):
        driver = _make_driver("17")
        payout = self._make_payout(driver, status="processing")
        self.admin.mark_as_paid(_admin_request(), DriverPayout.objects.filter(id=payout.id))
        payout.refresh_from_db()
        self.assertEqual(payout.status, "paid")
        self.assertIsNotNone(payout.paid_at)

    def test_mark_as_failed_excludes_already_paid(self):
        driver = _make_driver("18")
        paid = self._make_payout(driver, status="paid")
        self.admin.mark_as_failed(_admin_request(), DriverPayout.objects.filter(id=paid.id))
        paid.refresh_from_db()
        self.assertEqual(paid.status, "paid")  # untouched

    def test_run_weekly_payout_now_batches_owed_drivers(self):
        driver = _make_driver("19")
        self._make_payout(driver, status="pending")
        with patch(_SEND_TRANSFER_PATCH_TARGET, return_value=(True, {})):
            self.admin.run_weekly_payout_now(_admin_request(), DriverPayout.objects.none())
        self.assertTrue(WeeklyPayoutBatch.objects.filter(driver=driver).exists())


class WeeklyPayoutBatchAdminActionsTests(TestCase):
    def setUp(self):
        self.admin = WeeklyPayoutBatchAdmin(WeeklyPayoutBatch, None)

    def test_mark_as_paid_cascades_to_its_payouts(self):
        driver = _make_driver("20")
        batch = WeeklyPayoutBatch.objects.create(
            driver=driver, period_start=datetime.date(2026, 1, 1), period_end=datetime.date(2026, 1, 7),
            amount=Decimal("800"),
        )
        rider = _make_rider("18")
        ride = _make_ride(rider, driver)
        payout = DriverPayout.objects.create(
            driver=driver, ride=ride, amount=Decimal("800"), platform_fee=Decimal("200"),
            status="processing", batch=batch,
        )

        self.admin.mark_as_paid(_admin_request(), WeeklyPayoutBatch.objects.filter(id=batch.id))
        batch.refresh_from_db()
        payout.refresh_from_db()
        self.assertEqual(batch.status, "paid")
        self.assertEqual(payout.status, "paid")
        self.assertEqual(payout.paid_at, batch.paid_at)


class ReadOnlyAdminPermissionsTests(TestCase):
    def test_cash_debt_entry_admin_is_fully_read_only(self):
        admin = CashDebtEntryAdmin(CashDebtEntry, None)
        self.assertFalse(admin.has_add_permission(_admin_request()))
        self.assertFalse(admin.has_change_permission(_admin_request()))

    def test_rider_payment_instrument_admin_is_fully_read_only(self):
        admin = RiderPaymentInstrumentAdmin(RiderPaymentInstrument, None)
        self.assertFalse(admin.has_add_permission(_admin_request()))
        self.assertFalse(admin.has_change_permission(_admin_request()))


class RideRequestAdminActionsTests(TestCase):
    def setUp(self):
        self.admin = RideRequestAdmin(RideRequest, None)

    def test_mark_as_completed_bulk_updates(self):
        rider = _make_rider("19")
        ride = _make_ride(rider, status="started")
        self.admin.mark_as_completed(_admin_request(), RideRequest.objects.filter(id=ride.id))
        ride.refresh_from_db()
        self.assertEqual(ride.status, "completed")
        self.assertIsNotNone(ride.completed_at)

    def test_cleanup_old_rides_deletes_only_old_cancelled_ones(self):
        rider = _make_rider("20")
        old_cancelled = _make_ride(rider, status="cancelled")
        old_cancelled.requested_at = old_cancelled.requested_at - datetime.timedelta(days=10)
        old_cancelled.save(update_fields=["requested_at"])
        recent_cancelled = _make_ride(rider, status="cancelled")

        self.admin.cleanup_old_rides(_admin_request(), RideRequest.objects.none())
        self.assertFalse(RideRequest.objects.filter(id=old_cancelled.id).exists())
        self.assertTrue(RideRequest.objects.filter(id=recent_cancelled.id).exists())
