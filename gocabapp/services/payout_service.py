"""Turns a card-paid ride into a DriverPayout row, then attempts to actually
send the driver their share via Paystack Transfers — falling back to an
admin sending it manually (see DriverPayoutAdmin) only if that automated
attempt can't complete. Cash rides never come through here: the driver
already holds that money in hand."""
from __future__ import annotations

import logging
import re
import time
from datetime import timedelta
from decimal import Decimal

import requests
from django.conf import settings
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.utils import timezone

from django.db.models import Sum

from ..models import Driver, DriverPayout, Notification, RideRequest, WeeklyPayoutBatch
from ..utils.fare_pricing import DRIVER_EARNINGS_RATE
from ..utils.mailer import send_admin_mail
from .push_service import send_push_to_user
from .ride_events import notify_notification_count

logger = logging.getLogger(__name__)

# ── Paystack Transfers constants ────────────────────────────────────────────
# Deliberately not shared with payment_service.py's own Paystack helpers —
# that module already imports create_payout_for_ride from this one, so
# importing back from it here would create a circular import. A few lines
# of duplicated HTTP plumbing is the smaller cost.

_BANK_LIST_URL      = "https://api.paystack.co/bank"
_RECIPIENT_URL      = "https://api.paystack.co/transferrecipient"
_TRANSFER_URL       = "https://api.paystack.co/transfer"
_TIMEOUT            = 30
_BANK_LIST_CACHE_KEY = "paystack_bank_list"
_BANK_LIST_CACHE_TTL = 60 * 60 * 24  # bank codes don't change day to day


def _auth_header() -> dict:
    return {"Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}"}


def _list_banks() -> list[dict]:
    cached = cache.get(_BANK_LIST_CACHE_KEY)
    if cached is not None:
        return cached
    try:
        response = requests.get(
            _BANK_LIST_URL, headers=_auth_header(),
            params={"country": "nigeria"}, timeout=_TIMEOUT,
        )
        response.raise_for_status()
        banks = response.json().get("data", [])
    except requests.RequestException:
        logger.exception("Failed to fetch Paystack bank list")
        return []
    cache.set(_BANK_LIST_CACHE_KEY, banks, _BANK_LIST_CACHE_TTL)
    return banks


def list_bank_options() -> list[dict]:
    """Public, trimmed-down version of _list_banks() for the driver signup
    form's bank dropdown — just {name, code}, sorted for display. Capturing
    the exact Paystack bank_code at signup time (instead of a free-text bank
    name) is what lets payout_service skip _resolve_bank_code's fuzzy
    matching entirely for any driver who signs up through it."""
    banks = [
        {"name": b.get("name"), "code": b.get("code")}
        for b in _list_banks()
        if b.get("name") and b.get("code")
    ]
    return sorted(banks, key=lambda b: b["name"])


_BANK_NAME_NOISE = ("bank", "plc", "nigeria", "limited", "ltd", "mfb", "microfinance")


def _normalize_bank_name(name: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]", "", name.lower())
    for word in _BANK_NAME_NOISE:
        cleaned = cleaned.replace(word, "")
    return cleaned


def _resolve_bank_code(bank_name: str) -> str | None:
    """Drivers typed bank_name freehand at signup — match it against
    Paystack's own bank list rather than trusting it to already be an exact
    Paystack name. Deliberately conservative: an ambiguous or unmatched name
    returns None (payout fails safely for an admin to fix by hand) rather
    than risking a transfer to the wrong bank on a bad guess — common
    abbreviations (GTBank, UBA, FCMB, etc.) generally won't auto-resolve and
    need the driver's paystack_bank_code set once in Django admin."""
    target = _normalize_bank_name(bank_name)
    if not target:
        return None
    matches = []
    for bank in _list_banks():
        name = _normalize_bank_name(bank.get("name") or "")
        if name and (name == target or target in name or name in target):
            matches.append(bank)
    if len(matches) == 1:
        return matches[0].get("code")
    if len(matches) > 1:
        logger.warning(
            "Ambiguous bank name match for %r: %s — resolve bank_code manually",
            bank_name, [m.get("name") for m in matches],
        )
    return None


def _get_or_create_recipient(driver: Driver) -> str | None:
    if driver.paystack_recipient_code:
        return driver.paystack_recipient_code

    bank_code = driver.paystack_bank_code or _resolve_bank_code(driver.bank_name)
    if not bank_code:
        logger.error(
            "Could not resolve Paystack bank code for driver_id=%s bank_name=%r",
            driver.id, driver.bank_name,
        )
        return None

    payload = {
        "type": "nuban",
        "name": driver.account_holder_name,
        "account_number": driver.account_number,
        "bank_code": bank_code,
        "currency": "NGN",
    }
    try:
        response = requests.post(
            _RECIPIENT_URL, headers=_auth_header(), json=payload, timeout=_TIMEOUT,
        )
    except requests.RequestException:
        logger.exception("Paystack recipient creation request failed driver_id=%s", driver.id)
        return None

    data = response.json() if response.content else {}
    if response.status_code != 201 or not data.get("status"):
        logger.error(
            "Paystack recipient creation failed driver_id=%s status=%s body=%s",
            driver.id, response.status_code, data,
        )
        return None

    recipient_code = data["data"]["recipient_code"]
    driver.paystack_bank_code = bank_code
    driver.paystack_recipient_code = recipient_code
    driver.save(update_fields=["paystack_bank_code", "paystack_recipient_code"])
    return recipient_code


def _claim_payout_for_transfer(payout_id: int) -> DriverPayout | None:
    """Atomically flips pending/failed -> processing and returns the payout
    only if this call is the one that won that transition — the row lock
    closes the window where the automatic call from create_payout_for_ride
    and an admin's "Retry transfer" click (or two rapid retry clicks) could
    otherwise both pass a plain status check and both fire a real transfer
    for the same payout."""
    with transaction.atomic():
        payout = DriverPayout.objects.select_for_update().get(id=payout_id)
        if payout.status not in ("pending", "failed"):
            return None
        payout.status = "processing"
        payout.save(update_fields=["status"])
    return payout


def _send_transfer(driver: Driver, amount, reference: str, reason: str) -> tuple[bool, dict]:
    """The actual Paystack Transfer call, shared by the per-ride path (now
    only used for an admin's off-cycle manual retry) and the weekly batch
    path below. Returns (ok, response_data) — never raises; the caller owns
    updating whatever row (DriverPayout or WeeklyPayoutBatch) this was for."""
    recipient_code = _get_or_create_recipient(driver)
    if not recipient_code:
        return False, {}

    payload = {
        "source": "balance",
        "amount": int(round(float(amount) * 100)),  # kobo
        "recipient": recipient_code,
        "reference": reference,
        "reason": reason,
    }
    try:
        response = requests.post(_TRANSFER_URL, headers=_auth_header(), json=payload, timeout=_TIMEOUT)
    except requests.RequestException:
        logger.exception("Paystack transfer request failed reference=%s", reference)
        return False, {}

    data = response.json() if response.content else {}
    if response.status_code not in (200, 201) or not data.get("status"):
        logger.error("Paystack transfer failed reference=%s status=%s body=%s", reference, response.status_code, data)
        return False, data
    return True, data


def initiate_transfer_for_payout(payout: DriverPayout) -> None:
    """Off-cycle manual path only now (admin's "Retry transfer" action on one
    payout) — the normal path for a new payout is the weekly batch below.
    Best-effort — never raises; a failure here just leaves the payout
    "failed" for an admin to retry or send manually."""
    payout = _claim_payout_for_transfer(payout.id)
    if payout is None:
        return

    try:
        reference = f"PAYOUT_{payout.id}_{int(time.time())}"
        ok, _data = _send_transfer(
            payout.driver, payout.amount, reference, f"GoCab payout, ride #{payout.ride_id}",
        )
        if not ok:
            payout.status = "failed"
            payout.save(update_fields=["status"])
            return

        # Paystack's transfer status here is typically "otp" or "pending"
        # (or "success" outright for some accounts) — not final either way;
        # the transfer.success/transfer.failed webhook is what actually
        # confirms it landed. Status is already "processing" from the claim
        # above; just record the reference the webhook will match against.
        payout.paystack_reference = reference
        payout.save(update_fields=["paystack_reference"])
        logger.info("Transfer initiated payout_id=%s reference=%s", payout.id, reference)

    except Exception:
        logger.exception("Unexpected error initiating transfer for payout_id=%s", payout.id)
        payout.status = "failed"
        payout.save(update_fields=["status"])


def _notify_payout_result(driver: Driver, amount, success: bool, label: str) -> None:
    """Until now, a driver only ever found out a transfer actually landed
    (or didn't) by checking their own bank app — this module updated the
    DriverPayout/WeeklyPayoutBatch row but never told them either way.
    label distinguishes the three cases in the message text: "payout"
    (single off-cycle ride), "weekly payout" (the normal batch), or
    "instant cash-out" (see initiate_instant_cashout)."""
    if success:
        title = "Payout received"
        message = f"Your {label} of ₦{float(amount):,.2f} has been paid to your bank account."
    else:
        title = "Payout failed"
        message = (
            f"Your {label} of ₦{float(amount):,.2f} could not be completed. "
            "We're looking into it, contact support if this continues."
        )
    Notification.objects.create(user=driver.user, message=message, is_active=True)
    count = Notification.objects.filter(user=driver.user, is_active=True).count()
    notify_notification_count(driver.user_id, count)
    send_push_to_user(driver.user_id, title, message)


def handle_transfer_webhook_event(event: dict) -> None:
    """Paystack's authoritative word on whether a transfer actually landed —
    matches the reference this module generated, whether that was a single
    off-cycle payout (initiate_transfer_for_payout) or a weekly batch
    (initiate_transfer_for_batch)."""
    event_type = event.get("event")
    if event_type not in ("transfer.success", "transfer.failed", "transfer.reversed"):
        return

    data = event.get("data") or {}
    reference = data.get("reference")
    if not reference:
        return

    payout = DriverPayout.objects.filter(paystack_reference=reference).first()
    if payout:
        success = event_type == "transfer.success"
        if success:
            payout.status = "paid"
            payout.paid_at = timezone.now()
            payout.save(update_fields=["status", "paid_at"])
            logger.info("Payout confirmed paid payout_id=%s", payout.id)
        else:
            payout.status = "failed"
            payout.save(update_fields=["status"])
            logger.warning("Payout transfer %s payout_id=%s", event_type, payout.id)
        _notify_payout_result(payout.driver, payout.amount, success, "payout")
        return

    batch = WeeklyPayoutBatch.objects.filter(paystack_reference=reference).first()
    if batch:
        success = event_type == "transfer.success"
        label = "instant cash-out" if batch.cashout_fee else "weekly payout"
        if success:
            batch.status = "paid"
            batch.paid_at = timezone.now()
            batch.save(update_fields=["status", "paid_at"])
            # Cascade to every ride-level row this batch covered, so each
            # ride's own payout record reflects reality too, not just the
            # aggregate — a driver/admin looking at one ride shouldn't see
            # "pending" forever once the week that actually paid it lands.
            batch.payouts.update(status="paid", paid_at=batch.paid_at)
            logger.info("Weekly payout batch confirmed paid batch_id=%s", batch.id)
        else:
            batch.status = "failed"
            batch.save(update_fields=["status"])
            batch.payouts.update(status="failed")
            logger.warning("Weekly payout batch transfer %s batch_id=%s", event_type, batch.id)
        _notify_payout_result(batch.driver, batch.amount, success, label)
        return

    logger.warning("Transfer webhook for unknown reference=%s", reference)


def create_payout_for_ride(ride: RideRequest) -> DriverPayout | None:
    if not ride.driver_id or not ride.total_fare or not hasattr(ride.driver, "driver"):
        return None

    # Whole naira, not kobo (2026-10-02, client request) — easier to
    # reconcile by hand, and means the Paystack transfer this eventually
    # becomes is always a round amount. amount + platform_fee still sums
    # back to the (already whole) total_fare exactly, since platform_fee is
    # derived as the remainder rather than independently rounded.
    amount = round(float(ride.total_fare) * DRIVER_EARNINGS_RATE)
    platform_fee = round(float(ride.total_fare) - amount)

    try:
        payout = DriverPayout.objects.create(
            driver=ride.driver.driver,
            ride=ride,
            amount=amount,
            platform_fee=platform_fee,
        )
    except IntegrityError:
        # A DriverPayout already exists for this ride — the OneToOneField
        # is exactly the guard for a duplicate webhook delivery racing the
        # first one past the payment_status check in _apply_verified_online_payment.
        logger.info("Payout already exists for ride=%s, skipping", ride.id)
        return None

    logger.info(
        "Payout created ride=%s driver_id=%s amount=%s platform_fee=%s — earned, awaiting weekly payout",
        ride.id, ride.driver_id, amount, platform_fee,
    )
    # No transfer fires here anymore — a driver used to get paid the
    # instant each ride's payment confirmed; that's now batched into one
    # transfer per driver per week (see run_weekly_payouts below). This row
    # just records what they've earned until that next run picks it up.
    return payout


def get_driver_wallet_balance(driver: Driver) -> Decimal:
    """What a driver could cash out right now — every card-ride earning not
    yet part of any batch (weekly or instant). Deliberately never stored as
    its own column: this is always computed fresh from the DriverPayout
    ledger, the same rows send_weekly_payout_reminder/run_weekly_payouts
    already sum, so there's only ever one source of truth for "what's
    owed" rather than a running balance that could drift out of sync with it."""
    total = DriverPayout.objects.filter(
        driver=driver, batch__isnull=True, status__in=["pending", "failed"],
    ).aggregate(total=Sum("amount"))["total"]
    return total or Decimal("0")


def initiate_instant_cashout(driver: Driver) -> tuple[dict, int]:
    """A driver pulling their current balance out right now instead of
    waiting for the free weekly batch — same model as Uber's Flex Pay in
    Nigeria: a flat fee (settings.INSTANT_CASHOUT_FEE) comes off the top,
    the driver gets the rest immediately, GoCab doesn't eat the cost of the
    extra off-cycle Paystack transfer itself.

    The underlying DriverPayout rows keep their full, un-discounted amount
    (that's still exactly what was earned per ride) — only this batch's own
    amount is net of the fee, recorded separately via cashout_fee so it's
    visible in Django admin, not silently absorbed into a smaller number."""
    fee = Decimal(str(settings.INSTANT_CASHOUT_FEE))
    min_balance = Decimal(str(settings.INSTANT_CASHOUT_MIN_BALANCE))

    with transaction.atomic():
        # Locks the driver's unbatched payouts for the duration of this
        # claim, same reasoning as _claim_payout_for_transfer/
        # _claim_batch_for_transfer — closes the window where tapping
        # "Cash out now" twice in quick succession could otherwise claim
        # the same earnings into two separate batches.
        payout_ids = list(
            DriverPayout.objects.select_for_update()
            .filter(driver=driver, batch__isnull=True, status__in=["pending", "failed"])
            .values_list("id", flat=True)
        )
        total = DriverPayout.objects.filter(id__in=payout_ids).aggregate(total=Sum("amount"))["total"] or Decimal("0")

        # min_balance (₦210 by default) already implies > fee (₦100) at the
        # default settings, but both are checked explicitly in case either
        # one is ever reconfigured independently of the other.
        if not payout_ids or total <= fee or total < min_balance:
            return {
                "status": "error",
                "error": (
                    f"Your balance (₦{total:,.2f}) must be at least ₦{min_balance:,.2f} "
                    f"to cash out instantly (₦{fee:,.2f} fee applies)."
                ),
            }, 400

        now = timezone.now()
        batch = WeeklyPayoutBatch.objects.create(
            driver=driver, period_start=now, period_end=now,
            amount=total - fee, cashout_fee=fee,
        )
        DriverPayout.objects.filter(id__in=payout_ids).update(batch=batch)

    initiate_transfer_for_batch(batch)
    return {
        "status": "success",
        "amount": float(batch.amount),
        "fee": float(fee),
        "batch_id": batch.id,
    }, 200


def _claim_batch_for_transfer(batch_id: int) -> WeeklyPayoutBatch | None:
    """Same race-condition guard as _claim_payout_for_transfer, for a batch
    instead of a single payout."""
    with transaction.atomic():
        batch = WeeklyPayoutBatch.objects.select_for_update().get(id=batch_id)
        if batch.status not in ("pending", "failed"):
            return None
        batch.status = "processing"
        batch.save(update_fields=["status"])
    return batch


def initiate_transfer_for_batch(batch: WeeklyPayoutBatch) -> None:
    """Best-effort — never raises. A failure leaves the batch "failed" for
    an admin to retry (or pay that driver manually) without blocking the
    rest of the week's run for every other driver."""
    batch = _claim_batch_for_transfer(batch.id)
    if batch is None:
        return

    try:
        reference = f"WEEKLY_{batch.id}_{int(time.time())}"
        ok, _data = _send_transfer(
            batch.driver, batch.amount, reference,
            f"GoCab weekly payout, {batch.period_start:%d %b} to {batch.period_end:%d %b}",
        )
        if not ok:
            batch.status = "failed"
            batch.save(update_fields=["status"])
            return

        batch.paystack_reference = reference
        batch.save(update_fields=["paystack_reference"])
        logger.info("Weekly transfer initiated batch_id=%s reference=%s", batch.id, reference)

    except Exception:
        logger.exception("Unexpected error initiating transfer for batch_id=%s", batch.id)
        batch.status = "failed"
        batch.save(update_fields=["status"])


def send_weekly_payout_reminder() -> dict:
    """What the Monday cron actually calls now, instead of run_weekly_payouts
    itself — automated payouts move real money on a codebase that's still
    changing fast, so this deliberately stops short of firing anything. It
    computes the exact same "who's owed what" the real run would use, emails
    it to ADMIN_NOTIFICATION_EMAIL so a human can sanity-check the numbers,
    and leaves the actual "Run this week's payout now" click (Django
    admin's Driver Payouts action, or run_weekly_payouts directly) to them.
    Safe to call as often as you like — it never creates a batch or touches
    a payout row."""
    unbatched = (
        DriverPayout.objects.filter(batch__isnull=True, status__in=["pending", "failed"])
        .values("driver_id", "driver__full_name")
        .annotate(total=Sum("amount"))
        .filter(total__gt=0)
        .order_by("-total")
    )
    rows = list(unbatched)

    if not settings.ADMIN_NOTIFICATION_EMAIL:
        logger.info("Weekly payout reminder: %s driver(s) owed, but no ADMIN_NOTIFICATION_EMAIL set", len(rows))
        return {"drivers_owed": len(rows)}

    if not rows:
        body = "No drivers have any un-paid earnings this week. Nothing to run."
    else:
        lines = [f"- {r['driver__full_name']}: ₦{r['total']:,.2f}" for r in rows]
        total = sum(r["total"] for r in rows)
        body = (
            f"{len(rows)} driver(s) have earnings waiting to be paid out this week, "
            f"totaling ₦{total:,.2f}.\n\n" + "\n".join(lines) +
            f"\n\nReview and run it from Django admin: {settings.BASE_URL}/admin/gocabapp/driverpayout/"
            "\n(select any one row, then choose \"Run this week's payout now\")"
        )

    send_admin_mail(
        subject=f"GoCab weekly payout review, {len(rows)} driver(s) owed",
        message=body,
        recipient_list=[settings.ADMIN_NOTIFICATION_EMAIL],
    )
    logger.info("Weekly payout reminder sent: %s driver(s) owed", len(rows))
    return {"drivers_owed": len(rows)}


def run_weekly_payouts(period_start=None, period_end=None) -> dict:
    """The actual weekly payday — entry point for /internal/run-weekly-payouts,
    triggered on a schedule the same way the stale-ride sweep is (see
    .github/workflows). Finds every DriverPayout row not yet part of a batch
    (earned since whenever the driver's last payout was, regardless of
    exactly which week each ride happened to fall in — a payout that
    somehow got missed one week still goes out the next, rather than being
    silently skipped), groups by driver, and fires one combined transfer
    per driver instead of one per ride."""
    period_end = period_end or timezone.now()
    period_start = period_start or (period_end - timedelta(days=7))

    unbatched = (
        DriverPayout.objects.filter(batch__isnull=True, status__in=["pending", "failed"])
        .values("driver_id")
        .annotate(total=Sum("amount"))
        .filter(total__gt=0)
    )

    batches_created = 0
    for row in unbatched:
        driver_id = row["driver_id"]
        amount = row["total"]
        batch = WeeklyPayoutBatch.objects.create(
            driver_id=driver_id, period_start=period_start, period_end=period_end, amount=amount,
        )
        DriverPayout.objects.filter(
            driver_id=driver_id, batch__isnull=True, status__in=["pending", "failed"],
        ).update(batch=batch)
        try:
            initiate_transfer_for_batch(batch)
        except Exception:
            logger.exception("Weekly transfer initiation crashed for batch_id=%s", batch.id)
        batches_created += 1

    logger.info("Weekly payout run: %s driver batch(es) created", batches_created)
    return {"batches_created": batches_created}
