import hashlib
import logging
import secrets

from django.conf import settings
from django.core import signing
from django.core.cache import cache
from ninja.errors import HttpError

from gocabapp.utils.branded_mail import send_branded_email

logger = logging.getLogger(__name__)

CODE_TTL_SECONDS = 10 * 60
MAX_ATTEMPTS = 5

VERIFIED_TOKEN_SALT = "gocab-email-verified"
VERIFIED_TOKEN_MAX_AGE_SECONDS = 15 * 60


def _cache_key(email: str) -> str:
    return f"otp:{email.lower()}"


def _hash_code(email: str, code: str) -> str:
    # Peppered with SECRET_KEY so a cache dump alone can't be brute-forced
    # offline. Not password-hasher-grade on purpose — this is a 6-digit,
    # single-use, short-lived, attempt-limited code, not a long-term secret.
    payload = f"{settings.SECRET_KEY}:{email.lower()}:{code}".encode()
    return hashlib.sha256(payload).hexdigest()


def send_code(email: str) -> None:
    """Generate a 6-digit code, cache its hash (Redis in prod, keyed off the
    email so login and registration share one code), and email it. Consumed
    once by whichever of verify-code/register-rider/register-driver checks
    it first — there's no separate 'purpose' to track."""
    code = f"{secrets.randbelow(1_000_000):06d}"
    cache.set(
        _cache_key(email),
        {"hash": _hash_code(email, code), "attempts": 0},
        timeout=CODE_TTL_SECONDS,
    )
    send_branded_email(
        subject="Your GoCab verification code",
        to=[email],
        template_name="email/otp_code.html",
        context={"code": code},
    )
    logger.info("OTP sent to %s", email)


def verify_code(email: str, code: str) -> None:
    key = _cache_key(email)
    entry = cache.get(key)
    if not entry:
        raise HttpError(400, "Code expired or not requested. Please request a new code.")

    if entry["attempts"] >= MAX_ATTEMPTS:
        cache.delete(key)
        raise HttpError(429, "Too many incorrect attempts. Please request a new code.")

    if entry["hash"] != _hash_code(email, code):
        entry["attempts"] += 1
        cache.set(key, entry, timeout=CODE_TTL_SECONDS)
        raise HttpError(400, "Incorrect code.")

    cache.delete(key)


def issue_verified_token(email: str) -> str:
    """A short-lived proof that this email already passed OTP verification
    once (e.g. on the homepage's single email step), so a new user handed
    off into the full signup form doesn't have to enter the same one-time
    code twice — it was already consumed by the time we know they need to
    register."""
    return signing.dumps({"email": email.lower()}, salt=VERIFIED_TOKEN_SALT)


def consume_verified_token(token: str, email: str) -> None:
    try:
        data = signing.loads(
            token, salt=VERIFIED_TOKEN_SALT, max_age=VERIFIED_TOKEN_MAX_AGE_SECONDS
        )
    except signing.BadSignature:
        raise HttpError(400, "Verification expired. Please verify your email again.")

    if data.get("email") != email.lower():
        raise HttpError(400, "Verification expired. Please verify your email again.")
