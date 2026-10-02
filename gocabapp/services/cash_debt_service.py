"""Tracks the platform commission GoCab is owed on cash rides but never
actually collects at payment time (the cash goes straight from rider to
driver). See models.CashDebtEntry / Driver.cash_debt and
fraud_checks.is_cash_debt_blocked for the enforcement side."""
from __future__ import annotations

import logging
from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.db import IntegrityError, transaction

from ..models import CashDebtEntry, Driver, Notification, RideRequest
from ..utils.fare_pricing import DRIVER_EARNINGS_RATE
from .push_service import send_push_to_user
from .ride_events import notify_notification_count

logger = logging.getLogger(__name__)

# total_fare is a DecimalField — do this arithmetic in Decimal throughout
# rather than mixing in the float DRIVER_EARNINGS_RATE, which raises
# TypeError the moment it meets a Decimal in a + or * expression.
_CASH_COMMISSION_RATE = Decimal("1") - Decimal(str(DRIVER_EARNINGS_RATE))


def charge_cash_commission(ride: RideRequest) -> CashDebtEntry | None:
    """Called once a cash ride is confirmed paid — records the commission
    GoCab is owed on it and adds it to the driver's running balance. If
    that balance crosses the block threshold, the driver is taken offline
    immediately rather than waiting for their next go-online attempt."""
    if not ride.driver_id or not ride.total_fare or not hasattr(ride.driver, "driver"):
        return None

    # Whole naira, not kobo (2026-10-02, client request) — matches the same
    # rounding now applied to the fare itself and to card-paid payouts.
    commission = (ride.total_fare * _CASH_COMMISSION_RATE).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP
    )
    driver = ride.driver.driver

    try:
        with transaction.atomic():
            entry = CashDebtEntry.objects.create(
                driver=driver, ride=ride, entry_type="charge", amount=commission,
            )
            locked = Driver.objects.select_for_update().get(id=driver.id)
            locked.cash_debt = locked.cash_debt + commission
            newly_blocked = (
                locked.cash_debt >= settings.CASH_DEBT_BLOCK_THRESHOLD and locked.is_online
            )
            if newly_blocked:
                locked.is_online = False
                locked.save(update_fields=["cash_debt", "is_online"])
            else:
                locked.save(update_fields=["cash_debt"])
    except IntegrityError:
        # Already charged for this ride — one_cash_debt_charge_per_ride is
        # exactly the guard for a duplicate cash-confirmation call.
        logger.info("Cash debt already charged for ride=%s, skipping", ride.id)
        return None

    logger.info(
        "Cash debt charged ride=%s driver_id=%s amount=%s new_balance=%s",
        ride.id, driver.id, commission, locked.cash_debt,
    )

    if newly_blocked:
        debt_message = (
            f"You've been taken offline. ₦{locked.cash_debt:,.2f} in cash-ride "
            "commission is owed. Settle up to go back online."
        )
        Notification.objects.create(user=driver.user, message=debt_message, is_active=True)
        count = Notification.objects.filter(user=driver.user, is_active=True).count()
        notify_notification_count(driver.user_id, count)
        send_push_to_user(driver.user_id, "Taken offline", debt_message)

    return entry


def settle_cash_debt(driver: Driver, note: str = "") -> CashDebtEntry | None:
    """Admin-confirmed settlement — clears the driver's full outstanding
    balance and unblocks them. Partial settlement isn't supported; a driver
    pays the amount an admin tells them and it's cleared in one go."""
    with transaction.atomic():
        locked = Driver.objects.select_for_update().get(id=driver.id)
        if locked.cash_debt <= 0:
            return None

        entry = CashDebtEntry.objects.create(
            driver=locked, entry_type="settlement", amount=locked.cash_debt,
            note=note or "Settled by admin",
        )
        locked.cash_debt = 0
        locked.save(update_fields=["cash_debt"])

    logger.info("Cash debt settled driver_id=%s amount=%s", driver.id, entry.amount)
    return entry
