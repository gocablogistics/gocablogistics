import logging

from django.conf import settings
from django.contrib.auth.models import User
from ...utils.branded_mail import send_branded_email
from django.db import IntegrityError, transaction
from django.utils import timezone
from ninja.errors import HttpError
from ninja_jwt.exceptions import TokenError
from ninja_jwt.tokens import RefreshToken

from ...models import Driver, Rider

logger = logging.getLogger(__name__)


def _notify_admin_of_new_driver(driver: Driver) -> None:
    """Emails whoever handles driver approvals so a human reviews the new
    account promptly — same silent-no-op-if-unconfigured pattern as
    payment_service._notify_admin_of_dispute. The account is still fully
    visible in Django admin either way."""
    if not settings.ADMIN_NOTIFICATION_EMAIL:
        return

    admin_url = f"{settings.ADMIN_SITE_URL}/admin/gocabapp/driver/{driver.id}/change/"
    try:
        send_branded_email(
            subject=f"GoCab: new driver awaiting approval, {driver.full_name}",
            to=[settings.ADMIN_NOTIFICATION_EMAIL],
            template_name="email/admin_alert.html",
            context={
                "heading": "New driver awaiting approval",
                "intro": f"{driver.full_name} just signed up as a {driver.vehicle_type} driver.",
                "rows": [
                    {"label": "Name", "value": driver.full_name},
                    {"label": "Phone", "value": driver.phone_number},
                    {"label": "Vehicle", "value": driver.vehicle_type},
                ],
                "button_label": "Review driver",
                "button_url": admin_url,
            },
        )
    except Exception:
        logger.exception("Failed to email admin about new driver id=%s", driver.id)


def _phone_taken(phone_number: str) -> bool:
    return (
        Rider.objects.filter(phone_number=phone_number).exists()
        or Driver.objects.filter(phone_number=phone_number).exists()
    )


def _email_taken(email: str) -> bool:
    return User.objects.filter(email__iexact=email).exists()


def create_rider(data) -> User:
    if _phone_taken(data.phone_number):
        raise HttpError(400, "This phone number is already registered.")
    if _email_taken(data.email):
        raise HttpError(400, "This email is already registered.")

    referrer = None
    referral_code = getattr(data, "referral_code", None)
    if referral_code:
        referrer = Rider.objects.filter(referral_code=referral_code).first()
        if referrer is None:
            raise HttpError(400, "That referral code doesn't match any account.")

    try:
        with transaction.atomic():
            user = User.objects.create_user(
                username=data.phone_number,
                email=data.email,
            )
            Rider.objects.create(
                user=user,
                full_name=data.full_name,
                email=data.email,
                phone_number=data.phone_number,
                address=data.address,
                latitude=data.latitude,
                longitude=data.longitude,
                location_updated_at=timezone.now() if data.latitude is not None else None,
                referred_by=referrer,
            )
    except IntegrityError:
        logger.warning("Rider registration race on phone %s", data.phone_number)
        raise HttpError(400, "An account with these details already exists.")

    return user


def create_driver(data, files: dict) -> User:
    if _phone_taken(data.phone_number):
        raise HttpError(400, "This phone number is already registered.")
    if _email_taken(data.email):
        raise HttpError(400, "This email is already registered.")
    # Scoped to (bank, account number) — the same digits at a different
    # bank are a genuinely different real account, not a duplicate.
    if Driver.objects.filter(account_number=data.account_number, bank_name=data.bank_name).exists():
        raise HttpError(400, "This bank account is already registered.")

    try:
        with transaction.atomic():
            user = User.objects.create_user(
                username=data.phone_number,
                email=data.email,
            )
            driver = Driver.objects.create(
                user=user,
                full_name=data.full_name,
                phone_number=data.phone_number,
                date_of_birth=data.date_of_birth,
                vehicle_type=data.vehicle_type,
                vehicle_model=data.vehicle_model or "",
                vehicle_brand=data.vehicle_brand or "",
                vehicle_color=data.vehicle_color,
                production_year=data.production_year,
                license_plate=data.license_plate,
                national_identification_number=data.national_identification_number,
                bank_name=data.bank_name,
                paystack_bank_code=data.bank_code or "",
                account_number=data.account_number,
                account_holder_name=data.account_holder_name,
                latitude=data.latitude,
                longitude=data.longitude,
                current_address=data.current_address or "",
                is_approved=False,
                **files,
            )
    except IntegrityError:
        logger.warning("Driver registration race on phone %s", data.phone_number)
        raise HttpError(400, "An account with these details already exists.")

    _notify_admin_of_new_driver(driver)
    return user


def resolve_role_and_profile(user: User):
    """Driver takes precedence over Rider — mirrors the legacy session-based
    signin() view's account-type resolution order for a dual-role account."""
    try:
        return "driver", user.driver
    except Driver.DoesNotExist:
        pass
    try:
        return "rider", user.rider
    except Rider.DoesNotExist:
        pass
    return None, None


def get_user_by_email(email: str) -> User:
    user = User.objects.filter(email__iexact=email).first()
    if user is None:
        raise HttpError(404, "No account found with that email. Please sign up.")
    return user


def authenticate_by_email(email: str):
    user = get_user_by_email(email)

    if not user.is_active:
        # Banned accounts (admin sets is_active=False from a payment
        # dispute or elsewhere). ninja_jwt's JWTAuth already re-checks
        # is_active on every authenticated request — so this only closes
        # the gap where a banned user could otherwise still complete OTP
        # login and be issued a token before their first API call fails.
        raise HttpError(403, "This account has been suspended. Contact support.")

    role, profile = resolve_role_and_profile(user)
    if role is None:
        raise HttpError(403, "This account has no rider or driver profile.")
    if role == "driver" and profile.needs_reverification:
        reason = f" Reason: {profile.rejection_reason}" if profile.rejection_reason else ""
        raise HttpError(
            403,
            f"Your driver documents need another look. Please check what you uploaded.{reason}",
        )
    if role == "driver" and not profile.is_approved:
        raise HttpError(
            403,
            "Your driver account is pending approval. Please wait for admin verification.",
        )

    return user, role, profile


def issue_token_pair(user: User, role: str) -> RefreshToken:
    refresh = RefreshToken.for_user(user)
    refresh["role"] = role
    return refresh


def rotate_refresh_token(refresh_str: str) -> RefreshToken:
    try:
        old = RefreshToken(refresh_str)
    except TokenError as exc:
        raise HttpError(401, str(exc) or "Invalid or expired refresh token.")

    try:
        user = User.objects.get(id=old["user_id"])
    except User.DoesNotExist:
        raise HttpError(401, "User no longer exists.")

    role = old.get("role")
    if not role:
        role, _ = resolve_role_and_profile(user)

    new_refresh = issue_token_pair(user, role)
    old.blacklist()
    return new_refresh


def blacklist_refresh_token(refresh_str: str) -> None:
    try:
        RefreshToken(refresh_str).blacklist()
    except TokenError:
        # Already invalid/expired/blacklisted — logout is idempotent either way.
        pass


def user_out_payload(user: User, role: str, profile) -> dict:
    return {
        "id": user.id,
        "role": role,
        "full_name": profile.full_name,
        "phone_number": profile.phone_number,
        "email": getattr(profile, "email", None) or user.email or None,
        "is_approved": getattr(profile, "is_approved", None),
        # Rider.address / Driver.current_address — different field names on
        # each profile, so try both rather than picking one and getting None
        # back for the other role.
        "address": getattr(profile, "address", None) or getattr(profile, "current_address", None) or None,
        # Riders only — see Rider.referral_code / wallet_credit_balance.
        # None for a driver profile, which has neither field.
        "referral_code": getattr(profile, "referral_code", None),
        "wallet_credit_balance": getattr(profile, "wallet_credit_balance", None),
    }


def deactivate_account(user: User) -> tuple[dict, int]:
    """Self-service account deletion — a soft delete (is_active=False, same
    mechanism admin.py's ban_rider/ban_driver already use, which ninja_jwt's
    get_user() checks on every request) rather than actually destroying rows:
    ride history, payment/payout records, and dispute records all need to
    survive for accounting and dispute-resolution purposes even after
    someone deletes their account. Blocked while a ride is actually in
    progress, same reasoning as every other "you have an active ride" guard
    in this codebase.

    Unlike an admin ban, this also frees up the phone number/email/bank
    account so the same person can register a brand-new account with them
    — a self-delete is the user's own choice, not a penalty, so there's no
    reason to permanently squat on their identity. Ban stays untouched:
    that's deliberately meant to keep blocking the same details."""
    from ...models import RideRequest

    if hasattr(user, "rider"):
        has_active = RideRequest.objects.filter(
            passenger=user, status__in=["pending", "accepted", "started"]
        ).exists()
        if has_active:
            return {"error": "Finish or cancel your active ride before deleting your account."}, 409

    if hasattr(user, "driver"):
        has_active = RideRequest.objects.filter(
            driver=user, status__in=["accepted", "started"]
        ).exists()
        if has_active:
            return {"error": "Finish your active trip before deleting your account."}, 409
        if user.driver.is_online:
            user.driver.is_online = False
            user.driver.save(update_fields=["is_online"])

    # Free up the unique identity fields a fresh registration would
    # otherwise collide with. phone_number/email are nullable on both
    # profiles, so clearing them is enough; account_number isn't nullable
    # (real bank data) so it gets a short, guaranteed-unique placeholder
    # instead of being blanked to "" (two blanked drivers would collide
    # with each other under the unique constraint; two NULLs never do).
    if hasattr(user, "rider"):
        user.rider.phone_number = None
        user.rider.email = None
        user.rider.save(update_fields=["phone_number", "email"])

    if hasattr(user, "driver"):
        user.driver.phone_number = None
        user.driver.account_number = f"deleted-{user.id}"
        user.driver.save(update_fields=["phone_number", "account_number"])

    user.username = f"deleted-{user.id}-{user.username}"[:150]
    user.email = ""
    user.is_active = False
    user.save(update_fields=["username", "email", "is_active"])
    logger.info("Account deactivated user_id=%s", user.id)
    return {"message": "Your account has been deleted."}, 200
