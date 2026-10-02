from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta
import logging
import secrets

logger = logging.getLogger(__name__)

# No 0/O/1/I — avoids look-alike chars when a referral code is read aloud
# or typed back in from a screenshot/text message.
_REFERRAL_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _generate_unique_referral_code(length: int = 6) -> str:
    for _ in range(10):
        code = "".join(secrets.choice(_REFERRAL_CODE_ALPHABET) for _ in range(length))
        if not Rider.objects.filter(referral_code=code).exists():
            return code
    # Astronomically unlikely at any realistic user count (32**6 ≈ 1 billion
    # combinations) — widen rather than loop forever if it ever happens.
    return "".join(secrets.choice(_REFERRAL_CODE_ALPHABET) for _ in range(length + 2))


class Rider(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, blank=True, null=True)
    full_name = models.CharField(max_length=255, blank=True, null=True)
    email = models.EmailField(unique=True, blank=True, null=True)
    phone_number = models.CharField(max_length=15, unique=True, blank=True, null=True)
    address = models.CharField(max_length=255, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    # Live position shared back to the driver pre-pickup — mirrors Driver's
    # own latitude/longitude below, same purpose in reverse.
    latitude = models.FloatField(blank=True, null=True)
    longitude = models.FloatField(blank=True, null=True)
    location_updated_at = models.DateTimeField(null=True, blank=True)
    # Same CharField-storing-a-stringified-float pattern as Driver.rating
    # below, kept consistent on purpose — every place that already reads
    # Driver.rating does `float(x.rating) if x.rating else 4.5`, so mirroring
    # the type here means the same pattern works for riders unchanged.
    rating = models.CharField(max_length=100, blank=True, null=True)
    # Mirrors Driver.is_flagged/flagged_reason — set either by an admin
    # (PaymentDisputeAdmin.flag_rider) or automatically after repeat
    # non-payment reports (see fraud_checks.RIDER_NONPAYMENT_AUTO_FLAG_COUNT).
    # Blocks new bookings entirely until an admin clears it — deliberately
    # NOT self-clearing just by paying off one ride, unlike the ordinary
    # "reported" state: this is for a rider who's done it more than once.
    is_flagged = models.BooleanField(default=False)
    flagged_reason = models.TextField(blank=True, default="")
    # Referral program (see settings.REFERRAL_REWARD_AMOUNT and
    # services/payment_service._maybe_credit_referral_reward). Every rider
    # gets a code the moment their account is created (see save() below) —
    # generated up front rather than lazily so it's always ready to
    # show/share from the very first login.
    referral_code = models.CharField(max_length=8, unique=True, blank=True, null=True)
    # Set once, at signup, from whichever code (if any) the new rider
    # entered — never changed afterwards, so who-referred-whom stays fixed
    # even if a referrer's own code were ever regenerated.
    referred_by = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="referrals"
    )
    # Flips true the first time THIS rider's referrer gets credited for
    # referring them — guards against crediting the same referrer twice off
    # two separate paid rides from the same referred rider.
    referral_reward_credited = models.BooleanField(default=False)
    # Promotional credit only — never real money that left GoCab's account,
    # so nothing here is refundable/transferable/withdrawable. Auto-applied
    # to reduce what this rider is charged online at checkout time (see
    # payment_service._create_payment_link) until it's used up.
    wallet_credit_balance = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    def __str__(self):
        return self.full_name

    def save(self, *args, **kwargs):
        if not self.referral_code:
            self.referral_code = _generate_unique_referral_code()
            update_fields = kwargs.get("update_fields")
            if update_fields is not None:
                kwargs["update_fields"] = list(update_fields) + ["referral_code"]
        super().save(*args, **kwargs)

    def update_location(self, latitude, longitude):
        self.latitude = latitude
        self.longitude = longitude
        self.location_updated_at = timezone.now()
        self.save(update_fields=["latitude", "longitude", "location_updated_at"])


class Driver(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    full_name = models.CharField(max_length=255)
    phone_number = models.CharField(max_length=15, unique=True, blank=True, null=True)
    date_of_birth = models.DateField()
    vehicle_type = models.CharField(max_length=50)
    # Bike-only per the signup wizard's field rules — a Bicycle only ever
    # sets vehicle_picture + vehicle_color, so this has to tolerate blank.
    vehicle_model = models.CharField(max_length=100, blank=True, default="")
    vehicle_brand = models.CharField(max_length=100, blank=True, default="")
    vehicle_color = models.CharField(max_length=50, blank=True, default="")
    production_year = models.PositiveIntegerField(blank=True, null=True)
    rating = models.CharField(max_length=100, blank=True, null=True)
    license_plate = models.CharField(max_length=100, blank=True, null=True)
    # max_length=255, not Django's FileField default of 100 — the real bug
    # behind a "value too long for type character varying(100)" crash on
    # driver registration: the DEFAULT max_length only ever applies to the
    # storage PATH (folder + filename), not the file's content, and a real
    # photo's filename from someone's phone, plus the Cloudinary storage
    # folder prefix, routinely exceeds 100 characters.
    drivers_license = models.FileField(upload_to="documents/drivers_license/", max_length=255)
    # A live photo of the vehicle itself — required for both Bike and
    # Bicycle, unlike the Bike-only fields above.
    vehicle_picture = models.FileField(upload_to="documents/vehicle_pictures/", default="", blank=True, max_length=255)
    # unique=True closes the "banned driver just re-registers with a new
    # phone/email but the same real-world ID" loophole — phone_number,
    # email and account_number were already enforced, this one never was.
    national_identification_number = models.CharField(max_length=100, unique=True)
    nin_slip_photo = models.FileField(upload_to="documents/nin_slips/", default="", blank=True, max_length=255)
    # A live selfie, not a scanned ID photo — kept under the old field name
    # since it's functionally the same "photo of the person" slot the
    # legacy passport_photo upload already filled.
    passport_photo = models.FileField(upload_to="documents/passport_photos/", max_length=255)
    bank_name = models.CharField(max_length=100)
    # NOT unique on its own — Nigerian account numbers aren't unique
    # across banks, so the same digits at a different bank are two
    # completely unrelated real accounts. A driver genuinely re-using an
    # account number at a different bank than an existing driver was
    # wrongly rejected as "already registered" until this was scoped to
    # the (bank, account number) pair below.
    account_number = models.CharField(max_length=20)
    account_holder_name = models.CharField(max_length=255)
    # Paystack's numeric bank code, resolved from bank_name the first time a
    # transfer recipient is created for this driver (see payout_service.py)
    # — Paystack's Transfer Recipient API needs this, not the free-text name.
    paystack_bank_code = models.CharField(max_length=10, blank=True, default="")
    # A recipient only needs to be created once per driver; every later
    # payout reuses this code instead of hitting the recipient endpoint again.
    paystack_recipient_code = models.CharField(max_length=100, blank=True, default="")
    latitude = models.FloatField(blank=True, null=True)
    longitude = models.FloatField(blank=True, null=True)
    current_address = models.CharField(max_length=255, blank=True)
    location_updated_at = models.DateTimeField(auto_now=True)
    is_approved = models.BooleanField(default=False)
    # Distinguishes "not yet reviewed" (both False) from "an admin looked at
    # this and found a problem with the uploaded documents" (needs_reverification
    # True) — a driver can't log in until is_approved is True either way, but
    # the login error message differs so a rejected driver actually knows to
    # go check what they uploaded instead of just waiting indefinitely.
    needs_reverification = models.BooleanField(default=False)
    rejection_reason = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    is_busy = models.BooleanField(default=False)
    # Explicit availability toggle — distinct from is_busy (mid-trip).
    # Starts False: a driver who just logged in isn't visible for new
    # requests until they deliberately go online.
    is_online = models.BooleanField(default=False)
    # Running total of platform commission owed on cash rides — GoCab never
    # touches that cash directly, so this is what stands in for actually
    # collecting it. Cached here (audit trail lives in CashDebtEntry) so
    # the go-online/accept-ride block check is a single-field read, not an
    # aggregate query on every request.
    cash_debt = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    # Set only by PaymentDisputeAdmin.flag_driver, after an admin reviews a
    # rider's report of the driver — mirrors payment_status == "disputed" on
    # the rider side. A fresh report alone never sets this (see
    # payment_service.report_driver); it's the same "report goes to admin
    # first, human decides" principle applied to the other direction.
    is_flagged = models.BooleanField(default=False)
    flagged_reason = models.TextField(blank=True, default="")
    current_ride = models.ForeignKey(
        "RideRequest",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="active_driver",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["bank_name", "account_number"], name="unique_bank_account_number",
            ),
        ]

    def __str__(self):
        return self.user.username

    def get_location(self):
        """Return location as tuple (lat, lng)"""
        if self.latitude and self.longitude:
            return (self.latitude, self.longitude)
        return None

    def update_location(self, latitude, longitude, address=None):
        """Update driver's location"""
        self.latitude = latitude
        self.longitude = longitude
        if address:
            self.current_address = address
        self.location_updated_at = timezone.now()
        self.save()

    def can_accept_ride(self):
        """Check if driver can accept a new ride - with better logic"""
        try:
            active_rides = RideRequest.objects.filter(
                driver=self.user, status__in=["accepted", "started"]
            )
            return not active_rides.exists()
        except Exception as e:
            # If there's any error, assume driver can accept rides
            logger.error(f"Error checking driver status: {e}")
            return True

    def set_available(self):
        """Set driver as available - make it robust"""
        try:
            # If you have a busy field, update it
            if hasattr(self, "is_busy"):
                self.is_busy = False
                self.save(update_fields=["is_busy"])

            # Also clear any current_ride reference if it exists
            if hasattr(self, "current_ride"):
                self.current_ride = None
                self.save(update_fields=["current_ride"])

            logger.info(f"Driver {self.user.username} set to available")
        except Exception as e:
            logger.error(f"Error setting driver available: {e}")

    def set_busy(self, ride):
        """Set driver as busy with a ride - make it robust"""
        try:
            # If you have a busy field, update it
            if hasattr(self, "is_busy"):
                self.is_busy = True
                self.save(update_fields=["is_busy"])

            # Also set current_ride reference if it exists
            if hasattr(self, "current_ride"):
                self.current_ride = ride
                self.save(update_fields=["current_ride"])

            logger.info(f"Driver {self.user.username} set to busy with ride {ride.id}")
        except Exception as e:
            logger.error(f"Error setting driver busy: {e}")

    def __str__(self):
        return f"{self.full_name} - {'Busy' if self.is_busy else 'Available'}"


class RideRequest(models.Model):
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("accepted", "Accepted"),
        ("started", "Started"),
        ("completed", "Completed"),
        ("cancelled", "Cancelled"),
    ]

    PAYMENT_STATUS_CHOICES = [
        ("pending", "Pending"),
        ("paid", "Paid"),
        ("failed", "Failed"),
        ("refunded", "Refunded"),
        # Someone reported non-payment, but it hasn't been reviewed yet —
        # doesn't block booking on its own (see fraud_checks.has_disputed_unpaid_ride).
        # A report from either side can be false or retaliatory, so nothing
        # here restricts an account until a human actually looks at it.
        ("reported", "Reported, awaiting admin review"),
        # An admin reviewed an open report and chose to flag the account —
        # this is the only state that actually blocks new bookings.
        ("disputed", "Disputed, flagged by admin"),
    ]

    PAYMENT_METHOD_CHOICES = [
        ("online", "Online"),
        ("cash", "Cash"),
    ]

    VEHICLE_TYPE_CHOICES = [
        ("Bike", "Bike"),
        ("Bicycle", "Bicycle"),
    ]

    passenger = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="ride_requests"
    )
    driver = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ride_requests_as_driver",
    )
    current_location = models.CharField(max_length=255)
    pickup_latitude = models.FloatField(blank=True, null=True)
    pickup_longitude = models.FloatField(blank=True, null=True)
    destination_latitude = models.FloatField(blank=True, null=True)
    destination_longitude = models.FloatField(blank=True, null=True)
    destination = models.CharField(max_length=255)
    # Who's actually receiving the delivery, if different from the account
    # booking it — optional, since a ride can just as easily be for the
    # passenger themself.
    recipient_phone_number = models.CharField(max_length=20, blank=True, default="")
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="pending")
    payment_status = models.CharField(
        max_length=10, choices=PAYMENT_STATUS_CHOICES, default="pending"
    )
    payment_reference = models.CharField(max_length=255, null=True, blank=True)
    payment_method = models.CharField(
        max_length=10, choices=PAYMENT_METHOD_CHOICES, default="online"
    )
    # A rider-side code the driver must enter to confirm cash was received —
    # doesn't cryptographically prove cash changed hands, but does mean a
    # driver can't unilaterally mark a cash ride paid without the rider's
    # active participation (and vice versa, a rider can't be falsely marked
    # as having paid without disclosing it).
    cash_confirmation_code = models.CharField(max_length=4, null=True, blank=True)
    cash_confirmation_attempts = models.PositiveSmallIntegerField(default=0)
    paid_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    requested_at = models.DateTimeField(auto_now_add=True)
    accepted_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    base_fare = models.DecimalField(max_digits=10, decimal_places=2, default=500.00)
    distance_km = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True
    )
    duration_min = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True
    )
    time_fare = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    distance_fare = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    total_fare = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    surge_multiplier = models.DecimalField(max_digits=3, decimal_places=1, default=1.0)
    # Same two values as Driver.vehicle_type (free CharField there, choices
    # here since this side is always set from a validated schema field).
    # Chosen by the rider at booking time — see utils/fare_pricing.py for
    # why the two are priced differently, and utils/distance_utils.py's
    # get_nearby_rides, which only shows a ride to a driver whose own
    # vehicle_type matches. Defaults to "Bike" for rides created before
    # this field existed, since every ride was priced (and matchable by
    # anyone) as if it were one anyway.
    vehicle_type = models.CharField(max_length=10, choices=VEHICLE_TYPE_CHOICES, default="Bike")
    # Snapshotted at checkout time (payment_service._create_payment_link)
    # from whatever the rider's Rider.wallet_credit_balance was then — the
    # Paystack charge (or, if this covers the fare entirely, the wallet-only
    # payment) is for total_fare minus this. Only actually deducted from the
    # rider's live balance once payment is confirmed (see
    # _apply_verified_online_payment); kept afterwards purely as a record
    # for display ("₦200 wallet credit applied").
    wallet_credit_applied = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    # Set the first time the stale-ride sweep (services/stale_ride_service.py)
    # emails an admin about this ride sitting unmatched too long — guards
    # against re-alerting on the same ride every time the sweep runs (every
    # 15-30 min) until it resolves. Cleared whenever a ride is reopened to
    # "pending" (driver_trip_service.run_driver_cancel_ride) so a ride that
    # goes stale again gets a fresh alert instead of staying silenced by an
    # alert from its previous time around. Two separate fields (not one
    # shared one) because a single ride can genuinely go stale at both the
    # pending stage AND, later, the started stage — a shared field would let
    # the first alert permanently suppress the second.
    pending_alert_sent_at = models.DateTimeField(null=True, blank=True)
    # Same idea, for a trip that started and never got marked complete.
    started_alert_sent_at = models.DateTimeField(null=True, blank=True)
    # One-time "you still owe for this trip" push to the rider (see
    # stale_ride_service._sweep_unpaid_completed) — stamped so it never repeats.
    unpaid_reminder_sent_at = models.DateTimeField(null=True, blank=True)
    # One-time "your driver has arrived" push to the rider, stamped the
    # moment a driver location ping first lands within
    # pickup_eta_service.ARRIVED_KM of the pickup point — same guard
    # pattern as the alert fields above, so sitting at the pickup point
    # doesn't re-fire it on every subsequent ping.
    arrival_notified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            # DB-level backstop for the check in rides/router.py:request_ride
            # — that check-then-create has a small race window (two rapid
            # requests could both pass it before either row exists); this
            # closes it for real instead of just narrowing it.
            models.UniqueConstraint(
                fields=["passenger"],
                condition=models.Q(status__in=["pending", "accepted", "started"]),
                name="one_active_ride_per_rider",
            ),
        ]

    def __str__(self):
        return f"Request by {self.passenger.username} from {self.current_location} to {self.destination}"

    def is_paid(self):
        return self.payment_status == "paid"

    def mark_as_paid(self, reference):
        self.payment_status = "paid"
        self.payment_reference = reference
        self.paid_at = timezone.now()
        self.save()

    def set_pickup_coordinates(self, lat, lng):
        self.pickup_latitude = lat
        self.pickup_longitude = lng
        self.save()

    @property
    def driver_earnings(self):
        from .utils.fare_pricing import DRIVER_EARNINGS_RATE

        if self.total_fare:
            return float(self.total_fare) * DRIVER_EARNINGS_RATE
        return 0.0

    @classmethod
    def get_available_rides_for_driver(cls, driver):
        """Get rides that this specific driver can see and accept"""
        return cls.objects.filter(status="pending", driver__isnull=True).exclude(
            # Exclude rides that other drivers are currently viewing/accepting
            id__in=RideRequest.objects.filter(
                status="pending",
                driver__isnull=True,
                # Add any other exclusion logic here
            ).values("id")
        )

    @classmethod
    def cleanup_canceled_rides(cls, days_old=7):
        """Delete canceled rides older than X days"""
        from django.utils import timezone
        from datetime import timedelta

        cutoff_date = timezone.now() - timedelta(days=days_old)

        deleted_count = cls.objects.filter(
            status="cancelled", requested_at__lt=cutoff_date
        ).delete()

        n = deleted_count[0]
        logger.info("Deleted %s cancelled rides older than %s days", n, days_old)
        return n


class DriverCancellation(models.Model):
    """Audit trail for driver-initiated cancellations. Needed because
    run_driver_cancel_ride reverts the ride to status="pending" (so another
    driver can pick it up) rather than "cancelled" — that overwrite means
    there's otherwise no record a cancellation happened at all, which a
    rolling-window fraud/abuse check needs."""

    driver = models.ForeignKey(User, on_delete=models.CASCADE)
    ride = models.ForeignKey(RideRequest, on_delete=models.SET_NULL, null=True, blank=True)
    cancelled_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.driver.username} cancelled ride {self.ride_id} at {self.cancelled_at}"


class PaymentDispute(models.Model):
    """One complaint thread per ride — either side can open it (a driver's
    non-payment report via payment_service.report_nonpayment, or a rider's
    conduct report about the driver via payment_service.report_driver) and
    the other side can add their statement via respond_to_dispute. Resolved
    by an admin, not auto-decided in either party's favor just because one
    of them clicked a button first."""

    STATUS_CHOICES = [
        ("open", "Open"),
        ("resolved", "Resolved"),
        ("dismissed", "Dismissed"),
    ]

    ride = models.OneToOneField(RideRequest, on_delete=models.CASCADE, related_name="dispute")
    driver_statement = models.TextField(blank=True, default="")
    rider_statement = models.TextField(blank=True, default="")
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="open")
    created_at = models.DateTimeField(auto_now_add=True)
    rider_responded_at = models.DateTimeField(null=True, blank=True)
    driver_responded_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolution_note = models.TextField(blank=True, default="")

    def __str__(self):
        return f"Dispute on ride {self.ride_id} ({self.status})"


class Rating(models.Model):
    """One rating in one direction for one ride — rider-rates-driver and
    driver-rates-rider are both rows in this same table, distinguished by
    whether `rater` is the ride's passenger or its driver. A ride can get
    up to two Rating rows (one each way), never more per rater."""

    ride = models.ForeignKey(RideRequest, on_delete=models.CASCADE, related_name="ratings")
    rater = models.ForeignKey(User, on_delete=models.CASCADE, related_name="ratings_given")
    ratee = models.ForeignKey(User, on_delete=models.CASCADE, related_name="ratings_received")
    stars = models.PositiveSmallIntegerField()
    comment = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["ride", "rater"], name="one_rating_per_rater_per_ride"),
            models.CheckConstraint(
                check=models.Q(stars__gte=1) & models.Q(stars__lte=5),
                name="rating_stars_between_1_and_5",
            ),
        ]

    def __str__(self):
        return f"{self.rater.username} rated {self.ratee.username} {self.stars}★ (ride {self.ride_id})"


class DriverPayout(models.Model):
    PAYOUT_STATUS_CHOICES = [
        ("pending", "Pending"),
        ("processing", "Processing"),
        ("paid", "Paid"),
        ("failed", "Failed"),
    ]

    driver = models.ForeignKey(Driver, on_delete=models.CASCADE)
    # One payout per ride — also the DB-level guard against a duplicate
    # webhook delivery creating two payout rows for the same fare.
    ride = models.OneToOneField(RideRequest, on_delete=models.CASCADE)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    platform_fee = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(
        max_length=20, choices=PAYOUT_STATUS_CHOICES, default="pending"
    )
    # Only ever set directly by an off-cycle manual "Retry transfer"/"Mark as
    # paid" admin action on THIS one payout — the normal path is batch below.
    paystack_reference = models.CharField(max_length=100, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    # Which weekly run actually paid this out, once one has. Null the whole
    # time between the ride finishing and the next weekly batch — earned,
    # but not yet transferred. See WeeklyPayoutBatch / services/payout_service.py.
    batch = models.ForeignKey(
        "WeeklyPayoutBatch", null=True, blank=True, on_delete=models.SET_NULL, related_name="payouts",
    )

    def __str__(self):
        return f"{self.driver.full_name} - ₦{self.amount} - {self.status}"


class WeeklyPayoutBatch(models.Model):
    """One real Paystack Transfer per driver per payout run — earnings from
    every ride they completed since their last payout, combined into a
    single bank transfer instead of one micro-transfer per ride. Drivers
    used to be paid the instant each ride's payment confirmed; that's
    replaced by this weekly run (see services/payout_service.run_weekly_payouts,
    triggered the same way the stale-ride sweep is — an internal endpoint on
    a GitHub Actions cron)."""

    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("processing", "Processing"),
        ("paid", "Paid"),
        ("failed", "Failed"),
    ]

    driver = models.ForeignKey(Driver, on_delete=models.CASCADE)
    period_start = models.DateTimeField()
    period_end = models.DateTimeField()
    # What actually gets transferred — already net of cashout_fee below for
    # an instant cash-out; equal to the full sum of its payouts for an
    # ordinary free weekly batch (cashout_fee=0).
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    paystack_reference = models.CharField(max_length=100, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    # >0 only for a driver-requested instant cash-out (see
    # payout_service.initiate_instant_cashout) — same "driver pays for
    # speed, GoCab doesn't eat the cost" model as Uber's Flex Pay. 0 for
    # every ordinary free weekly batch, which is how an admin/driver tells
    # the two apart at a glance without a separate boolean field.
    cashout_fee = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    def __str__(self):
        kind = "instant cash-out" if self.cashout_fee else "weekly payout"
        return f"{self.driver.full_name} - ₦{self.amount} - {kind} - {self.status} ({self.period_start:%Y-%m-%d})"


class CashDebtEntry(models.Model):
    """Audit trail behind Driver.cash_debt — one "charge" row per cash ride
    (the commission GoCab is owed but never collected, since the cash went
    straight to the driver), and one "settlement" row whenever an admin
    confirms a driver has paid it off outside the app (see
    DriverAdmin.settle_cash_debt)."""

    ENTRY_TYPE_CHOICES = [
        ("charge", "Charge"),
        ("settlement", "Settlement"),
    ]

    driver = models.ForeignKey(Driver, on_delete=models.CASCADE, related_name="cash_debt_entries")
    # Null for settlement rows — a settlement clears the running balance,
    # it isn't tied to one specific ride.
    ride = models.ForeignKey(RideRequest, on_delete=models.CASCADE, null=True, blank=True)
    entry_type = models.CharField(max_length=20, choices=ENTRY_TYPE_CHOICES)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    note = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            # Guards against a duplicate charge for the same ride (e.g. a
            # race on the cash-confirmation endpoint) the same way
            # DriverPayout.ride's OneToOneField guards the card-payout side.
            models.UniqueConstraint(
                fields=["ride"],
                condition=models.Q(entry_type="charge"),
                name="one_cash_debt_charge_per_ride",
            ),
        ]

    def __str__(self):
        return f"{self.driver.full_name} - {self.entry_type} ₦{self.amount}"


class Trip(models.Model):
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("accepted", "Accepted"),
        ("started", "Started"),
        ("completed", "Completed"),
        ("cancelled", "Cancelled"),
    ]

    passenger = models.ForeignKey(User, on_delete=models.CASCADE, related_name="trips")
    driver = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="trips_as_driver",
    )
    pickup_location = models.CharField(max_length=255)
    pickup_latitude = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True
    )
    pickup_longitude = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True
    )
    dropoff_location = models.CharField(max_length=255)
    dropoff_latitude = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True
    )
    dropoff_longitude = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True
    )
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="pending")
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    distance_km = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True
    )
    estimated_time = models.DurationField(null=True, blank=True)
    is_paid = models.BooleanField(default=False)
    payment_reference = models.CharField(max_length=255, null=True, blank=True)

    def __str__(self):
        return f"Trip from {self.pickup_location} to {self.dropoff_location} - {self.status}"


class Fare(models.Model):
    trip = models.OneToOneField(Trip, on_delete=models.CASCADE, related_name="fare")
    base_fare = models.DecimalField(max_digits=10, decimal_places=2, default=500.00)
    per_km_rate = models.DecimalField(max_digits=10, decimal_places=2, default=50.00)
    per_minute_rate = models.DecimalField(
        max_digits=10, decimal_places=2, default=10.00
    )
    total_fare = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )

    def calculate_fare(self, distance_km, duration_minutes):
        self.total_fare = (
            self.base_fare
            + (distance_km * self.per_km_rate)
            + (duration_minutes * self.per_minute_rate)
        )
        self.save()
        return self.total_fare


class Notification(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"Notification for {self.user.username}"


class DeviceToken(models.Model):
    """An FCM registration token for one installed app instance. A user can
    have several rows (multiple devices); `token` alone is globally unique
    since FCM tokens are opaque and never shared, which also makes
    re-registering after a logout/login-as-someone-else on the same device
    a plain update rather than a special case — see
    services/push_service.py."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="device_tokens")
    token = models.CharField(max_length=255, unique=True)
    platform = models.CharField(max_length=20, default="android")
    app_version = models.CharField(max_length=20, blank=True, default="")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"DeviceToken({self.platform}) for {self.user.username}"


class RideMessage(models.Model):
    """In-ride chat between the passenger and driver — delivered live over
    the same ride_{id} channel-layer group RideUpdatesConsumer already uses
    for status/location updates (see services/ride_events.py:notify_rider,
    now used by both sides of a ride, not just the rider)."""

    ride = models.ForeignKey(RideRequest, on_delete=models.CASCADE, related_name="messages")
    sender = models.ForeignKey(User, on_delete=models.CASCADE, related_name="+")
    text = models.CharField(max_length=1000)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"Message on ride {self.ride_id} from {self.sender_id}"
