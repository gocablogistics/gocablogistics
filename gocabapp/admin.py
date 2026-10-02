import logging

from django import forms
from django.conf import settings
from django.contrib import admin
from .models import *
from django.contrib import admin
from django.contrib.admin.helpers import ActionForm
from django.core.mail import send_mail
from django.utils import timezone
from django.utils.html import format_html

from django.contrib import messages
from django.contrib.auth.models import User

from .services.ride_events import notify_driver_pool, notify_notification_count, notify_rider
from .services.payment_service import refund_ride_payment
from .services.cash_debt_service import charge_cash_commission, settle_cash_debt
from .services.payout_service import create_payout_for_ride, initiate_transfer_for_payout, initiate_transfer_for_batch, run_weekly_payouts
from .services.push_service import send_push_to_user

logger = logging.getLogger(__name__)


class DriverReviewActionForm(ActionForm):
    reason = forms.CharField(
        required=False,
        label="Reason (used by 'Mark as not verified')",
        widget=forms.TextInput(attrs={"style": "width: 320px"}),
    )


# Register your models here.


admin.site.register(Rider)
admin.site.register(Notification)


@admin.register(Driver)
class DriverAdmin(admin.ModelAdmin):
    list_display = [
        "user",
        "is_busy",
        "current_ride",
        "verification_status",
        "vehicle_model",
        "cash_debt_display",
        "documents_links",
    ]
    list_filter = ["is_busy", "is_approved", "needs_reverification", "vehicle_type"]
    readonly_fields = ["is_busy", "current_ride"]
    action_form = DriverReviewActionForm
    actions = ["make_available", "approve_drivers", "mark_not_verified", "settle_cash_debt"]

    def verification_status(self, obj):
        if obj.is_approved:
            color, label = "#2a2", "Approved"
        elif obj.needs_reverification:
            color, label = "crimson", "Needs re-check"
        else:
            color, label = "#cc8400", "Pending review"
        return format_html('<span style="color: {}; font-weight: bold;">{}</span>', color, label)

    verification_status.short_description = "Status"

    def cash_debt_display(self, obj):
        if obj.cash_debt <= 0:
            return "N/A"
        color = "crimson" if obj.cash_debt >= settings.CASH_DEBT_BLOCK_THRESHOLD else "#cc8400"
        return format_html('<span style="color: {}; font-weight: bold;">₦{}</span>', color, obj.cash_debt)

    cash_debt_display.short_description = "Cash debt"

    def settle_cash_debt(self, request, queryset):
        settled = 0
        for driver in queryset:
            entry = settle_cash_debt(driver)
            if entry:
                settled += 1
                settle_message = f"Your cash-ride commission balance (₦{entry.amount:,.2f}) has been settled. You can go online again."
                Notification.objects.create(user=driver.user, message=settle_message, is_active=True)
                count = Notification.objects.filter(user=driver.user, is_active=True).count()
                notify_notification_count(driver.user_id, count)
                send_push_to_user(driver.user_id, "Cash debt settled", settle_message)
        self.message_user(request, f"Settled cash debt for {settled} driver(s) with an outstanding balance.")

    settle_cash_debt.short_description = "Settle cash debt (clears balance, unblocks driver)"

    def documents_links(self, obj):
        fields = [
            ("License", obj.drivers_license),
            ("Selfie", obj.passport_photo),
            ("NIN slip", obj.nin_slip_photo),
            ("Vehicle photo", obj.vehicle_picture),
        ]
        parts = [
            f'<a href="{f.url}" target="_blank">{label}</a>' if f else f'<span style="color:#999">{label}</span>'
            for label, f in fields
        ]
        return format_html(" | ".join(parts))

    documents_links.short_description = "Documents"

    def make_available(self, request, queryset):
        """Admin action to force set drivers as available"""
        updated = 0
        for driver in queryset:
            try:
                driver.is_busy = False
                driver.current_ride = None
                driver.save()
                updated += 1
            except Exception as e:
                self.message_user(
                    request, f"Error updating driver {driver}: {e}", level="error"
                )

        self.message_user(request, f"Successfully made {updated} drivers available.")

    make_available.short_description = "Mark selected drivers as available"

    def approve_drivers(self, request, queryset):
        # .update() would bypass save() and skip the post_save signal that
        # notifies the driver they've been approved — save() individually
        # instead (the queryset here is admin-selected, so always small).
        updated = 0
        for driver in queryset:
            driver.is_approved = True
            driver.needs_reverification = False
            driver.rejection_reason = ""
            driver.save(update_fields=["is_approved", "needs_reverification", "rejection_reason"])
            updated += 1
        self.message_user(request, f"Approved {updated} driver(s).")

    approve_drivers.short_description = "Approve selected drivers"

    def mark_not_verified(self, request, queryset):
        reason = (request.POST.get("reason") or "").strip()
        updated = 0
        for driver in queryset:
            driver.is_approved = False
            driver.needs_reverification = True
            driver.rejection_reason = reason
            driver.save(update_fields=["is_approved", "needs_reverification", "rejection_reason"])
            updated += 1
            if driver.user.email:
                try:
                    send_mail(
                        subject="GoCab: your driver documents need another look",
                        message=(
                            f"Hi {driver.full_name},\n\n"
                            "We reviewed your driver application and found an issue with "
                            "what you uploaded"
                            + (f":\n\n{reason}\n\n" if reason else ".\n\n")
                            + "Please check your documents and reach out to support to resubmit. "
                            "Once corrected, log back in to try again."
                        ),
                        from_email=None,
                        recipient_list=[driver.user.email],
                    )
                except Exception:
                    logger.exception("Failed to email driver id=%s about rejection", driver.id)
        self.message_user(request, f"Marked {updated} driver(s) as needing re-verification.")

    mark_not_verified.short_description = "Mark as not verified (uses the Reason box above)"

    def get_queryset(self, request):
        
        return super().get_queryset(request).select_related("user", "current_ride")

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        
        if db_field.name == "current_ride":
            kwargs["queryset"] = RideRequest.objects.filter(
                status__in=["accepted", "started"]
            )
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


@admin.register(RideRequest)
class RideRequestAdmin(admin.ModelAdmin):

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        
        qs = qs.select_related("passenger", "driver")
        return qs.using('default')
    
    list_display = [
        "id",
        "passenger_info",
        "driver_info",
        "current_location_short",
        "destination_short",
        "status_badge",
        "payment_status_badge",
        "total_fare",
        "requested_at_short",
        "ride_duration",
    ]

    
    list_filter = ["status", "payment_status", "requested_at", "driver"]

    
    search_fields = [
        "passenger__username",
        "passenger__email",
        "driver__username",
        "current_location",
        "destination",
        "payment_reference",
    ]

    
    readonly_fields = [
        "requested_at",
        "accepted_at",
        "started_at",
        "completed_at",
        "cancelled_at",
        "paid_at",
        "driver_earnings_display",
    ]

    # Fieldsets for detailed view
    fieldsets = (
        (
            "Ride Information",
            {
                "fields": (
                    "passenger",
                    "driver",
                    "status",
                    ("requested_at", "accepted_at"),
                    ("started_at", "completed_at"),
                    "cancelled_at",
                )
            },
        ),
        (
            "Location Details",
            {
                "fields": (
                    "current_location",
                    ("pickup_latitude", "pickup_longitude"),
                    "destination",
                    ("destination_latitude", "destination_longitude"),
                )
            },
        ),
        (
            "Payment Information",
            {
                "fields": (
                    "payment_status",
                    "payment_reference",
                    "paid_at",
                    ("base_fare", "surge_multiplier"),
                    ("distance_fare", "time_fare"),
                    "total_fare",
                    "driver_earnings_display",
                )
            },
        ),
        (
            "Ride Metrics",
            {"fields": (("distance_km", "duration_min"),), "classes": ("collapse",)},
        ),
    )

    # Custom methods for display
    def passenger_info(self, obj):
        return f"{obj.passenger.username} ({obj.passenger.email})"

    passenger_info.short_description = "Passenger"

    def driver_info(self, obj):
        if obj.driver:
            return f"{obj.driver.username} ({obj.driver.email})"
        return "No driver assigned"

    driver_info.short_description = "Driver"

    def current_location_short(self, obj):
        return (
            obj.current_location[:30] + "..."
            if len(obj.current_location) > 30
            else obj.current_location
        )

    current_location_short.short_description = "Pickup"

    def destination_short(self, obj):
        return (
            obj.destination[:30] + "..."
            if len(obj.destination) > 30
            else obj.destination
        )

    destination_short.short_description = "Destination"

    def status_badge(self, obj):
        colors = {
            "pending": "orange",
            "accepted": "blue",
            "started": "green",
            "completed": "gray",
            "cancelled": "red",
        }
        return format_html(
            '<span style="background: {}; color: white; padding: 3px 8px; border-radius: 10px; font-size: 12px;">{}</span>',
            colors.get(obj.status, "gray"),
            obj.get_status_display().upper(),
        )

    status_badge.short_description = "Status"

    def payment_status_badge(self, obj):
        colors = {
            "pending": "orange",
            "paid": "green",
            "failed": "red",
            "refunded": "blue",
        }
        return format_html(
            '<span style="background: {}; color: white; padding: 3px 8px; border-radius: 10px; font-size: 12px;">{}</span>',
            colors.get(obj.payment_status, "gray"),
            obj.get_payment_status_display().upper(),
        )

    def requested_at_short(self, obj):
        return obj.requested_at.strftime("%b %d, %H:%M")

    requested_at_short.short_description = "Requested"

    def ride_duration(self, obj):
        if obj.started_at and obj.completed_at:
            duration = obj.completed_at - obj.started_at
            minutes = duration.total_seconds() / 60
            return f"{int(minutes)} min"
        return "-"

    ride_duration.short_description = "Duration"

    def driver_earnings_display(self, obj):
        return f"₦{obj.driver_earnings:,.2f}"

    driver_earnings_display.short_description = "Driver Earnings"

    # Admin actions
    actions = ["mark_as_completed", "mark_as_cancelled", "cleanup_old_rides"]

    def mark_as_completed(self, request, queryset):
        updated = queryset.update(status="completed", completed_at=timezone.now())
        self.message_user(request, f"{updated} rides marked as completed.")

    mark_as_completed.short_description = "Mark selected rides as completed"

    def mark_as_cancelled(self, request, queryset):
        updated = queryset.update(status="cancelled", cancelled_at=timezone.now())
        self.message_user(request, f"{updated} rides marked as cancelled.")

    mark_as_cancelled.short_description = "Mark selected rides as cancelled"

    def cleanup_old_rides(self, request, queryset):
        deleted_count = RideRequest.cleanup_canceled_rides(days_old=7)
        self.message_user(request, f"Cleaned up {deleted_count} old cancelled rides.")

    cleanup_old_rides.short_description = "Clean up old cancelled rides (7+ days)"

    # Configuration
    list_per_page = 25
    date_hierarchy = "requested_at"
    ordering = ["-requested_at"]


@admin.register(PaymentDispute)
class PaymentDisputeAdmin(admin.ModelAdmin):
    """Both sides' statements land here — a driver's non-payment report
    (report_nonpayment) or a rider's conduct report about the driver
    (report_driver), plus whatever the other side adds via respond_to_dispute
    (ADMIN_NOTIFICATION_EMAIL gets emailed on each). A fresh report
    ("Awaiting review" below) does NOT restrict anyone — either side could
    file one falsely, so nothing happens to either account until a human
    looks at it here and explicitly picks "Flag rider" or "Flag driver"
    below. Resolving is a human judgment call: read both statements, follow
    up by phone/WhatsApp using the numbers shown, then pick an outcome.
    Nothing here auto-decides in either party's favor."""

    list_display = ["id", "ride", "rider_name", "driver_name", "status", "rider_account_status", "driver_account_status", "created_at", "rider_responded_at"]
    list_filter = ["status"]
    readonly_fields = ["ride", "created_at", "rider_responded_at", "resolved_at"]
    actions = ["flag_rider", "flag_driver", "resolve_rider_paid", "refund_rider", "dismiss_dispute", "ban_rider", "ban_driver"]

    def rider_name(self, obj):
        return getattr(getattr(obj.ride.passenger, "rider", None), "full_name", None) or obj.ride.passenger.username

    def driver_name(self, obj):
        if not obj.ride.driver:
            return "N/A"
        return getattr(getattr(obj.ride.driver, "driver", None), "full_name", None) or obj.ride.driver.username

    def rider_account_status(self, obj):
        if obj.ride.payment_status == "disputed":
            return format_html('<span style="color: crimson; font-weight: bold;">Flagged, blocked</span>')
        if obj.ride.payment_status == "reported":
            return format_html('<span style="color: #cc8400;">Awaiting review</span>')
        return "N/A"

    rider_account_status.short_description = "Rider account"

    def driver_account_status(self, obj):
        driver_profile = getattr(obj.ride.driver, "driver", None) if obj.ride.driver else None
        if driver_profile and driver_profile.is_flagged:
            return format_html('<span style="color: crimson; font-weight: bold;">Flagged, blocked</span>')
        if obj.rider_statement and obj.status == "open":
            return format_html('<span style="color: #cc8400;">Awaiting review</span>')
        return "N/A"

    driver_account_status.short_description = "Driver account"

    def flag_rider(self, request, queryset):
        flagged = 0
        for dispute in queryset.filter(status="open"):
            ride = dispute.ride
            if ride.payment_status != "disputed":
                ride.payment_status = "disputed"
                ride.save(update_fields=["payment_status"])
            # Also flags the account itself (mirrors flag_driver) rather
            # than just this one ride — an admin deliberately stepping in
            # is already a serious call, so it should stick to the account,
            # not clear itself the moment this specific ride gets paid.
            rider_profile = getattr(ride.passenger, "rider", None)
            if rider_profile and not rider_profile.is_flagged:
                rider_profile.is_flagged = True
                rider_profile.flagged_reason = dispute.driver_statement or "Flagged by admin"
                rider_profile.save(update_fields=["is_flagged", "flagged_reason"])
            notify_rider(ride.id, {
                "type": "ride_update", "event": "payment_disputed",
                "ride_id": ride.id,
                "message": "An admin reviewed your driver's report and flagged your account. "
                           "Pay or respond to the dispute to continue booking rides.",
            })
            flagged += 1
        self.message_user(request, f"Flagged {flagged} rider account(s), blocked from booking until resolved.")

    flag_rider.short_description = "Flag rider (block from booking pending resolution)"

    def flag_driver(self, request, queryset):
        flagged = 0
        for dispute in queryset.filter(status="open"):
            ride = dispute.ride
            driver_user = ride.driver
            if not driver_user or not hasattr(driver_user, "driver"):
                continue
            driver_profile = driver_user.driver
            if driver_profile.is_flagged:
                continue
            driver_profile.is_flagged = True
            driver_profile.flagged_reason = dispute.rider_statement or "Flagged by admin"
            driver_profile.save(update_fields=["is_flagged", "flagged_reason"])

            flag_message = ("An admin reviewed a rider's report and flagged your account. "
                            "Contact support before going online again.")
            Notification.objects.filter(user=driver_user, is_active=True).delete()
            Notification.objects.create(user=driver_user, message=flag_message, is_active=True)
            notify_notification_count(driver_user.id, 1)
            send_push_to_user(driver_user.id, "Account flagged", flag_message)
            flagged += 1
        self.message_user(request, f"Flagged {flagged} driver account(s), blocked from going online until resolved.")

    flag_driver.short_description = "Flag driver (block from going online pending resolution)"

    def resolve_rider_paid(self, request, queryset):
        updated = 0
        for dispute in queryset.filter(status="open"):
            ride = dispute.ride
            ride.payment_status = "paid"
            if not ride.paid_at:
                ride.paid_at = timezone.now()
            ride.save(update_fields=["payment_status", "paid_at"])

            dispute.status = "resolved"
            dispute.resolved_at = timezone.now()
            dispute.resolution_note = dispute.resolution_note or "Resolved by admin, marked paid."
            dispute.save(update_fields=["status", "resolved_at", "resolution_note"])

            notify_rider(ride.id, {
                "type": "ride_update", "event": "payment_completed",
                "ride_id": ride.id, "message": "Your payment dispute was resolved. Thank you.",
            })
            # report_nonpayment doesn't restrict itself to cash rides (a
            # rider could also dispute an online payment that never went
            # through) — route the money-owed side accordingly rather than
            # assuming cash.
            if ride.payment_method == "cash":
                charge_cash_commission(ride)
            else:
                create_payout_for_ride(ride)
            updated += 1
        self.message_user(request, f"Resolved {updated} dispute(s), ride(s) marked paid, rider(s) unblocked.")

    resolve_rider_paid.short_description = "Resolve: mark ride paid (unblocks rider)"

    def refund_rider(self, request, queryset):
        """For the opposite case from resolve_rider_paid — the rider already
        paid, but the dispute is being resolved in *their* favor (driver
        never showed, wrong item, etc.), so the money goes back instead of
        being kept."""
        refunded = 0
        failed = 0
        for dispute in queryset.filter(status="open"):
            ride = dispute.ride
            body, status_code = refund_ride_payment(
                ride, reason=dispute.rider_statement or "Dispute resolved in rider's favor"
            )
            if status_code != 200:
                failed += 1
                self.message_user(
                    request, f"Dispute #{dispute.id}: refund failed. {body.get('error')}",
                    level=messages.ERROR,
                )
                continue

            dispute.status = "resolved"
            dispute.resolved_at = timezone.now()
            dispute.resolution_note = dispute.resolution_note or "Resolved by admin, rider refunded."
            dispute.save(update_fields=["status", "resolved_at", "resolution_note"])

            notify_rider(ride.id, {
                "type": "ride_update", "event": "payment_refunded", "ride_id": ride.id,
                "message": "Your payment was refunded.",
            })
            refunded += 1
        self.message_user(request, f"Refunded {refunded} ride(s)." + (f" {failed} failed, see above." if failed else ""))

    refund_rider.short_description = "Refund rider's payment via Paystack"

    def dismiss_dispute(self, request, queryset):
        updated = 0
        for dispute in queryset.filter(status="open"):
            ride = dispute.ride
            # Only roll back payment_status if the (non-)payment report path
            # actually set it — a pure conduct report (report_driver) never
            # touches it, so a ride that's genuinely "paid" must stay that
            # way here rather than being incorrectly reset to "pending".
            if ride.payment_status in ("reported", "disputed"):
                ride.payment_status = "pending"
                ride.save(update_fields=["payment_status"])

            driver_profile = getattr(ride.driver, "driver", None) if ride.driver else None
            if driver_profile and driver_profile.is_flagged:
                driver_profile.is_flagged = False
                driver_profile.flagged_reason = ""
                driver_profile.save(update_fields=["is_flagged", "flagged_reason"])
                count = Notification.objects.filter(user=ride.driver, is_active=True).count()
                notify_notification_count(ride.driver.id, count)

            rider_profile = getattr(ride.passenger, "rider", None)
            if rider_profile and rider_profile.is_flagged:
                rider_profile.is_flagged = False
                rider_profile.flagged_reason = ""
                rider_profile.save(update_fields=["is_flagged", "flagged_reason"])

            dispute.status = "dismissed"
            dispute.resolved_at = timezone.now()
            dispute.resolution_note = dispute.resolution_note or "Dismissed by admin, report did not hold up."
            dispute.save(update_fields=["status", "resolved_at", "resolution_note"])

            count = Notification.objects.filter(user=ride.passenger, is_active=True).count()
            notify_notification_count(ride.passenger.id, count)
            updated += 1
        self.message_user(request, f"Dismissed {updated} dispute(s). Any block/flag cleared, ride(s) left as-is.")

    dismiss_dispute.short_description = "Dismiss: clear any block/flag without changing payment"

    def _cancel_other_active_rides(self, user, exclude_ride_id):
        """A banned account might have a completely different ride in
        progress right now, with the other party waiting on it — banning
        only ever touched the disputed ride itself, silently stranding
        anything else that account had going."""
        others = RideRequest.objects.filter(
            passenger=user, status__in=["pending", "accepted", "started"]
        ).exclude(id=exclude_ride_id)
        for ride in others:
            had_driver = ride.driver_id is not None
            ride.status = "cancelled"
            ride.cancelled_at = timezone.now()
            ride.save(update_fields=["status", "cancelled_at"])
            if had_driver and hasattr(ride.driver, "driver"):
                ride.driver.driver.set_available()
            notify_rider(ride.id, {
                "type": "ride_update", "event": "cancelled", "ride_id": ride.id,
                "message": "This ride was cancelled. The passenger's account was suspended.",
            })

    def _resolve_other_driver_rides(self, user, exclude_ride_id):
        """Same idea for a banned driver. A ride they've only been *assigned*
        (not yet picked up) is safe to reopen for someone else, same as an
        ordinary driver cancellation. A ride already *started* can't be
        safely handed to a new driver expecting to pick up where a stranger
        currently is with the wrong context — that one just ends."""
        others = RideRequest.objects.filter(
            driver=user, status__in=["accepted", "started"]
        ).exclude(id=exclude_ride_id)
        for ride in others:
            if ride.status == "accepted":
                ride.driver = None
                ride.status = "pending"
                ride.accepted_at = None
                ride.pending_alert_sent_at = None
                ride.save(update_fields=["driver", "status", "accepted_at", "pending_alert_sent_at"])
                notify_rider(ride.id, {
                    "type": "ride_update", "event": "driver_cancelled", "ride_id": ride.id,
                    "message": "Your driver's account was suspended. We're finding you another one.",
                })
                online_driver_ids = list(
                    User.objects.filter(
                        driver__is_online=True, driver__is_approved=True
                    ).exclude(id=user.id).values_list("id", flat=True)
                )
                notify_driver_pool(
                    {"type": "new_ride_request", "ride_id": ride.id, "message": "A ride is now available"},
                    push_to_user_ids=online_driver_ids,
                )
            else:
                ride.status = "cancelled"
                ride.cancelled_at = timezone.now()
                ride.save(update_fields=["status", "cancelled_at"])
                notify_rider(ride.id, {
                    "type": "ride_update", "event": "cancelled", "ride_id": ride.id,
                    "message": "Your trip was cancelled. Your driver's account was suspended. Contact support.",
                })

    def ban_rider(self, request, queryset):
        banned = 0
        for dispute in queryset:
            user = dispute.ride.passenger
            if user.is_active:
                user.is_active = False
                user.save(update_fields=["is_active"])
                self._cancel_other_active_rides(user, dispute.ride_id)
                banned += 1
            if dispute.status == "open":
                dispute.status = "resolved"
                dispute.resolved_at = timezone.now()
                dispute.resolution_note = dispute.resolution_note or "Rider banned by admin."
                dispute.save(update_fields=["status", "resolved_at", "resolution_note"])
        self.message_user(request, f"Banned {banned} rider account(s). They're logged out immediately.")

    ban_rider.short_description = "Ban the rider on selected dispute(s)"

    def ban_driver(self, request, queryset):
        banned = 0
        for dispute in queryset:
            driver_user = dispute.ride.driver
            if driver_user and driver_user.is_active:
                driver_user.is_active = False
                driver_user.save(update_fields=["is_active"])
                self._resolve_other_driver_rides(driver_user, dispute.ride_id)
                banned += 1
                # The driver's own conduct was the problem here, not the
                # rider's — clear the rider's block the same way dismiss does.
                ride = dispute.ride
                ride.payment_status = "pending"
                ride.save(update_fields=["payment_status"])
                if dispute.status == "open":
                    dispute.status = "resolved"
                    dispute.resolved_at = timezone.now()
                    dispute.resolution_note = dispute.resolution_note or "Driver banned by admin."
                    dispute.save(update_fields=["status", "resolved_at", "resolution_note"])
        self.message_user(request, f"Banned {banned} driver account(s). They're logged out immediately.")

    ban_driver.short_description = "Ban the driver on selected dispute(s)"


@admin.register(DriverPayout)
class DriverPayoutAdmin(admin.ModelAdmin):
    """One row per card-paid ride, created automatically once Paystack
    confirms payment. This no longer transfers money itself — it just
    records what's owed until the next weekly payout run (see
    WeeklyPayoutBatchAdmin below) combines everyone's un-batched rows into
    one transfer per driver. "Retry transfer" here fires an off-cycle
    transfer for just this one ride's amount, for when a driver needs
    paying before their week is up — the normal path is the batch."""

    list_display = ["id", "ride", "driver_name", "amount", "platform_fee", "status", "batch", "bank_details", "created_at", "paid_at"]
    list_filter = ["status"]
    search_fields = ["driver__full_name", "driver__account_number", "ride__id"]
    readonly_fields = ["driver", "ride", "amount", "platform_fee", "created_at", "bank_details", "paystack_reference", "batch"]
    actions = ["retry_transfer", "mark_as_paid", "mark_as_processing", "mark_as_failed", "run_weekly_payout_now"]
    ordering = ["-created_at"]

    def driver_name(self, obj):
        return obj.driver.full_name

    driver_name.short_description = "Driver"

    def bank_details(self, obj):
        return f"{obj.driver.bank_name}, {obj.driver.account_number} ({obj.driver.account_holder_name})"

    bank_details.short_description = "Bank details"

    def retry_transfer(self, request, queryset):
        retried = 0
        for payout in queryset.filter(status__in=["pending", "failed"]):
            initiate_transfer_for_payout(payout)
            retried += 1
        self.message_user(request, f"Retried {retried} transfer(s). Check status after a moment.")

    retry_transfer.short_description = "Retry transfer via Paystack"

    def mark_as_paid(self, request, queryset):
        updated = 0
        for payout in queryset.exclude(status="paid"):
            payout.status = "paid"
            payout.paid_at = timezone.now()
            payout.save(update_fields=["status", "paid_at"])
            updated += 1
        self.message_user(request, f"Marked {updated} payout(s) as paid.")

    mark_as_paid.short_description = "Mark selected payouts as paid (after sending the transfer yourself)"

    def mark_as_processing(self, request, queryset):
        updated = queryset.exclude(status="paid").update(status="processing")
        self.message_user(request, f"Marked {updated} payout(s) as processing.")

    mark_as_processing.short_description = "Mark selected payouts as processing"

    def mark_as_failed(self, request, queryset):
        updated = queryset.exclude(status="paid").update(status="failed")
        self.message_user(request, f"Marked {updated} payout(s) as failed.")

    mark_as_failed.short_description = "Mark selected payouts as failed"

    def run_weekly_payout_now(self, request, queryset):
        """Ignores whatever rows are selected, this is just the easiest
        place to put a button, since the real target (WeeklyPayoutBatch)
        starts out empty with nothing to select. Combines every driver's
        un-batched earnings into one transfer each. The Monday cron only
        emails a review of these same numbers (see send_weekly_payout_reminder)
        rather than calling this directly, so clicking it here is currently
        the only thing that actually moves money. Safe to click any time,
        a driver with nothing outstanding is simply skipped."""
        result = run_weekly_payouts()
        self.message_user(
            request,
            f"Weekly payout run complete. {result['batches_created']} driver batch(es) created. "
            "Check Weekly Payout Batches below for status.",
        )

    run_weekly_payout_now.short_description = "▶ Run this week's payout now (ignores selection)"

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("driver", "ride")


@admin.register(WeeklyPayoutBatch)
class WeeklyPayoutBatchAdmin(admin.ModelAdmin):
    """One row per driver per weekly run — created automatically by
    run_weekly_payouts (see services/payout_service.py, triggered by the
    weekly-driver-payouts GitHub Actions cron), which also fires the actual
    Paystack Transfer for the combined amount. Only needs manual attention
    if that transfer failed."""

    list_display = ["id", "driver_name", "amount", "status", "period_start", "period_end", "bank_details", "created_at", "paid_at"]
    list_filter = ["status"]
    search_fields = ["driver__full_name", "driver__account_number"]
    readonly_fields = ["driver", "period_start", "period_end", "amount", "created_at", "bank_details", "paystack_reference"]
    actions = ["retry_transfer", "mark_as_paid", "mark_as_failed"]
    ordering = ["-created_at"]

    def driver_name(self, obj):
        return obj.driver.full_name

    driver_name.short_description = "Driver"

    def bank_details(self, obj):
        return f"{obj.driver.bank_name}, {obj.driver.account_number} ({obj.driver.account_holder_name})"

    bank_details.short_description = "Bank details"

    def retry_transfer(self, request, queryset):
        retried = 0
        for batch in queryset.filter(status__in=["pending", "failed"]):
            initiate_transfer_for_batch(batch)
            retried += 1
        self.message_user(request, f"Retried {retried} batch transfer(s). Check status after a moment.")

    retry_transfer.short_description = "Retry transfer via Paystack"

    def mark_as_paid(self, request, queryset):
        updated = 0
        for batch in queryset.exclude(status="paid"):
            batch.status = "paid"
            batch.paid_at = timezone.now()
            batch.save(update_fields=["status", "paid_at"])
            batch.payouts.update(status="paid", paid_at=batch.paid_at)
            updated += 1
        self.message_user(request, f"Marked {updated} batch(es) as paid (and every ride-level payout under them).")

    mark_as_paid.short_description = "Mark selected batches as paid (after sending the transfer yourself)"

    def mark_as_failed(self, request, queryset):
        updated = queryset.exclude(status="paid").update(status="failed")
        self.message_user(request, f"Marked {updated} batch(es) as failed.")

    mark_as_failed.short_description = "Mark selected batches as failed"

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("driver")


@admin.register(CashDebtEntry)
class CashDebtEntryAdmin(admin.ModelAdmin):
    """Read-only ledger — charges are created automatically by
    services/cash_debt_service.py, settlements by DriverAdmin.settle_cash_debt.
    Nothing here should be hand-edited; it's the audit trail behind
    Driver.cash_debt, not a data-entry screen."""

    list_display = ["id", "driver", "entry_type", "amount", "ride", "created_at"]
    list_filter = ["entry_type"]
    search_fields = ["driver__full_name"]
    readonly_fields = ["driver", "ride", "entry_type", "amount", "note", "created_at"]
    ordering = ["-created_at"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("driver", "ride")
