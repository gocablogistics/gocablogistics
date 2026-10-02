from pathlib import Path
from datetime import timedelta
import os
import logging
from dotenv import load_dotenv

load_dotenv()


BASE_DIR = Path(__file__).resolve().parent.parent.parent

SECRET_KEY = os.getenv("SECRET_KEY")

# Error tracking (api/main.py's generic exception handler reports here and
# hands back the resulting event id, so "registration failed, our servers
# are busy" on a crash comes with a code you can look up in Sentry instead
# of needing someone to describe a stack trace). Same no-op-until-configured
# pattern as FCM/Resend elsewhere in this file: empty SENTRY_DSN just means
# nothing gets sent anywhere, so this is safe to leave in before a Sentry
# project exists.
SENTRY_DSN = os.getenv("SENTRY_DSN", "")
if SENTRY_DSN:
    import sentry_sdk
    from sentry_sdk.integrations.django import DjangoIntegration

    sentry_sdk.init(
        dsn=SENTRY_DSN,
        integrations=[DjangoIntegration()],
        # Every request's trace — fine at GoCab's current volume; revisit
        # (sample down) if/when traffic grows enough for this to cost real
        # money on a paid Sentry plan.
        traces_sample_rate=1.0,
        # Request bodies/user data can include phone numbers, NIN, bank
        # details — never worth sending to a third party by default.
        send_default_pii=False,
    )

INSTALLED_APPS = [
    "daphne",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    # cloudinary_storage must come before staticfiles per its own docs.
    "cloudinary_storage",
    "django.contrib.staticfiles",
    "cloudinary",
    "django.contrib.humanize",
    "corsheaders",
    "ninja_jwt.token_blacklist",
    "gocabapp",
]

MIDDLEWARE = [
    "django.middleware.cache.UpdateCacheMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "gocabapp.middleware.JWTCookieAuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "Gocabservices.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [os.path.join(BASE_DIR, "templates")],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
            "builtins": ["django.templatetags.static"],
        },
    },
]

WSGI_APPLICATION = "Gocabservices.wsgi.application"
ASGI_APPLICATION = "Gocabservices.asgi.application"

APPEND_SLASH = False

# USE_TZ=True (Django default) means every datetime is stored/serialized as
# an unambiguous, explicitly-UTC value — the frontend can then always
# compute correct elapsed time regardless of what timezone the SERVER
# happens to be running in, or what timezone a rider's PHONE is set to.
# Without this, a naive datetime like "2026-09-22T22:30:59" has to be
# *guessed* by the browser as its own local time, which silently breaks the
# moment the server's OS clock and the device's are in different zones —
# confirmed live: the "no drivers available" message (computed client-side
# from a ride's requested_at) showed up immediately instead of after 45
# minutes, because that guess was wrong. TIME_ZONE only controls what
# timezone Django *displays* naive-looking local time as (e.g. in the admin
# and in emails) — the actual stored/transmitted values stay UTC either way.
USE_TZ = True
TIME_ZONE = "Africa/Lagos"

# ============ API KEYS ============
GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")
BASE_URL = os.getenv("BASE_URL", "https://fidamano.onrender.com")
# Where the React SPA is served — used as the Paystack callback target for
# checkouts initiated via the JSON API, so payment returns land back in the
# SPA instead of the legacy server-rendered pages BASE_URL points at.
FRONTEND_BASE_URL = os.getenv("FRONTEND_BASE_URL", "http://localhost:3000")
PAYSTACK_SECRET_KEY = os.getenv("PAYSTACK_SECRET_KEY")
PAYSTACK_PUBLIC_KEY = os.getenv("PAYSTACK_PUBLIC_KEY")
RESEND_API_KEY = os.getenv("RESEND_API_KEY")
# Where payment-dispute alerts go — set this to whoever handles support.
# Disputes still show up in Django admin either way; if this is unset, we
# just skip the email rather than erroring the report/response request.
ADMIN_NOTIFICATION_EMAIL = os.getenv("ADMIN_NOTIFICATION_EMAIL", "")

# ============ AUTH ============
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher",
]

# ============ API AUTH (JWT) ============
# Shared, stateless auth for the web app, Android and iOS clients — one
# token contract for all three. Short-lived access token limits the blast
# radius of a leaked token; rotating + blacklisted refresh tokens mean a
# stolen refresh token only works once before it's invalidated.
NINJA_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=30),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=30),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": True,
    "ALGORITHM": "HS256",
    "SIGNING_KEY": SECRET_KEY,
    "AUTH_HEADER_TYPES": ("Bearer",),
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
}

# Login/register throttling (cache-backed, works across all app servers via
# the shared Redis cache) to blunt credential-stuffing / brute force at scale.
AUTH_THROTTLE_LOGIN_LIMIT = 10
AUTH_THROTTLE_LOGIN_WINDOW_SECONDS = 5 * 60
# Raised from 5 to 12 (2026-09-30) — a driver registration retried on a
# weak mobile connection can genuinely fail (or look like it failed, if the
# response never makes it back) several times before one actually lands,
# and each attempt counts here regardless of outcome. 12/hour still blunts
# real abuse (this isn't the OTP-code endpoint — an attacker gains little
# from hammering registration itself) while giving real retries headroom.
AUTH_THROTTLE_REGISTER_LIMIT = 12
AUTH_THROTTLE_REGISTER_WINDOW_SECONDS = 60 * 60
# Raised from 5 to 8 (2026-09-30) — 5-per-10-min was tripping during normal
# testing/retries. 8 is still well inside standard practice for an email
# code-request endpoint (most apps sit in the 3-5-per-5-15min range; email
# is cheap to send, unlike SMS, so there's headroom either way).
AUTH_THROTTLE_CODE_LIMIT = 8
AUTH_THROTTLE_CODE_WINDOW_SECONDS = 10 * 60

# /rides/estimate-fare is public (a visitor needs a price before signing up)
# and calls Google's paid Distance Matrix API per request — unthrottled,
# that's an open door to a surprise bill or quota exhaustion.
FARE_ESTIMATE_THROTTLE_LIMIT = 20
FARE_ESTIMATE_THROTTLE_WINDOW_SECONDS = 5 * 60

# GoCab never touches cash — its 25% commission on a cash ride is tracked
# as debt (Driver.cash_debt) instead of collected at payment time. Once a
# driver's owed balance reaches this, they're blocked from going online /
# accepting new rides until an admin confirms they've settled up outside
# the app (see DriverAdmin.settle_cash_debt).
CASH_DEBT_BLOCK_THRESHOLD = 5000

# Instant cash-out (services/payout_service.initiate_instant_cashout) — a
# driver can pull their current card-ride earnings out right away instead
# of waiting for the free weekly batch, same model as Uber's Flex Pay in
# Nigeria (₦100/cash-out there): the driver pays for the speed, GoCab
# doesn't eat the extra off-cycle Paystack transfer cost itself.
INSTANT_CASHOUT_FEE = float(os.getenv("INSTANT_CASHOUT_FEE", "100"))
# Below this, cashing out isn't worth doing — Uber's own Flex Pay sets a
# ~₦210 floor in Nigeria (against the same ₦100 fee), which nets a driver
# roughly ₦110 at minimum rather than a near-zero gain. Mirrored here
# directly rather than guessing a different number.
INSTANT_CASHOUT_MIN_BALANCE = float(os.getenv("INSTANT_CASHOUT_MIN_BALANCE", "210"))

# Card/wallet-only for now while GoCab is new — cash brings real collection
# risk (the debt-ledger-plus-block system above exists purely to manage
# that) that isn't worth carrying pre-launch. All the cash code paths stay
# intact; this is the single switch to bring cash back once there's enough
# volume/trust to justify the risk again.
CASH_PAYMENTS_ENABLED = False

# Rating consequence (services/rating_service.py) — a driver's average
# falling below this, with at least this many ratings behind it (so one bad
# rating from a new driver can't trip it), auto-flags them the same way an
# admin-reviewed payment dispute does: blocked from going online until an
# admin looks at it and clears it. Never an automatic ban.
RATING_AUTO_FLAG_THRESHOLD = float(os.getenv("RATING_AUTO_FLAG_THRESHOLD", "2.0"))
RATING_AUTO_FLAG_MIN_COUNT = int(os.getenv("RATING_AUTO_FLAG_MIN_COUNT", "5"))

# A driver with this many rider conduct reports (report_driver — the
# behavioural counterpart to the rider-side non-payment reports) against
# them, ever, gets auto-flagged the same way — mirrors
# RIDER_NONPAYMENT_AUTO_FLAG_COUNT below.
DRIVER_REPORT_AUTO_FLAG_COUNT = int(os.getenv("DRIVER_REPORT_AUTO_FLAG_COUNT", "3"))

# A rider reported for non-payment this many times, ever (lifetime, not a
# rolling window — unlike the cancellation counters below, repeated
# non-payment is a trust problem that shouldn't reset just because time
# passed), gets auto-flagged the same way an admin manually flagging one
# does (see fraud_checks.is_rider_flagged) — blocked from booking at all
# until a human clears it. Paying off any one reported ride only clears
# that ride's own state, never this account-level flag once it's set.
RIDER_NONPAYMENT_AUTO_FLAG_COUNT = int(os.getenv("RIDER_NONPAYMENT_AUTO_FLAG_COUNT", "3"))

# Abuse protection (services/fraud_checks.py): this many cancellations inside the
# rolling 24-hour window pauses new bookings (riders) / accepting (drivers) until
# the oldest ones age out. development.py raises both so testing doesn't lock
# anyone out; production keeps the real values.
RIDER_CANCELLATION_LIMIT = int(os.getenv("RIDER_CANCELLATION_LIMIT", "5"))
DRIVER_CANCELLATION_LIMIT = int(os.getenv("DRIVER_CANCELLATION_LIMIT", "5"))

# Rider-facing "no drivers nearby" nudge (distinct from
# STALE_PENDING_ALERT_MINUTES below, which only emails an admin) — after a
# ride sits unmatched this long, the rider sees a message suggesting they
# try again or call support, with a number to call. Purely informational;
# the ride itself is left exactly as it was, still open for a driver to
# accept at any point.
NO_DRIVERS_MESSAGE_MINUTES = int(os.getenv("NO_DRIVERS_MESSAGE_MINUTES", "45"))
# TODO: swap in the real GoCab logistics support line before launch —
# matches Support.tsx's own TODO on SUPPORT_EMAIL.
SUPPORT_PHONE_NUMBER = os.getenv("SUPPORT_PHONE_NUMBER", "+2340000000000")

# Referral program (services/payment_service._maybe_credit_referral_reward):
# one-sided — only the existing rider who referred someone gets rewarded,
# and only once that new rider's first ride is actually PAID (not just
# booked), which is what stops someone farming throwaway signups for free
# credit. Paid into Rider.wallet_credit_balance, which is then auto-applied
# to reduce what a rider is charged online at their next checkout
# (payment_service._create_payment_link) — never paid out as real cash, so
# there's no Paystack transfer/fraud surface to this at all.
REFERRAL_REWARD_AMOUNT = float(os.getenv("REFERRAL_REWARD_AMOUNT", "500.00"))

# Stale-ride sweep (services/stale_ride_service.py) — a periodic job (see
# /internal/sweep-stale-rides) that catches rides Django's own signals never
# resolve on their own: nobody accepted it, a driver accepted and went
# quiet, or a trip started and never got marked complete. Windows are
# deliberately generous — GoCab's driver density is nowhere near Uber's, so
# an aggressive timeout risks killing a request that would've matched fine
# given more time.
STALE_PENDING_ALERT_MINUTES = int(os.getenv("STALE_PENDING_ALERT_MINUTES", "60"))
STALE_ACCEPTED_TIMEOUT_MINUTES = int(os.getenv("STALE_ACCEPTED_TIMEOUT_MINUTES", "45"))
STALE_STARTED_ALERT_MINUTES = int(os.getenv("STALE_STARTED_ALERT_MINUTES", "300"))
# A finished trip still unpaid this long gets one push reminder to the rider
# (the sweep runs every ~15 min, so the real delay is this plus up to 15).
UNPAID_REMINDER_MINUTES = int(os.getenv("UNPAID_REMINDER_MINUTES", "10"))
# How long a shown price stays locked for booking (see utils/fare_quote.py).
FARE_QUOTE_MAX_AGE_SECONDS = int(os.getenv("FARE_QUOTE_MAX_AGE_SECONDS", str(15 * 60)))
# Shared secret for the sweep endpoint — there's no user/JWT for an
# automated job to authenticate as, so this is checked the same way the
# Paystack webhook checks its signature (see api/main.py). Empty/unset
# means the endpoint always 401s rather than silently accepting no secret.
STALE_SWEEP_SECRET = os.getenv("STALE_SWEEP_SECRET", "")

# ============ CORS ============
# Native Android/iOS clients don't send Origin headers and aren't subject to
# CORS. This only matters for a browser-based web client hitting the API
# from a different origin; each settings module sets its own allowlist.
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOWED_ORIGINS = []

# ============ SESSIONS ============
SESSION_COOKIE_AGE = 7 * 24 * 60 * 60
SESSION_SAVE_EVERY_REQUEST = True
SESSION_EXPIRE_AT_BROWSER_CLOSE = False
SESSION_ENGINE = "django.contrib.sessions.backends.db"

# ============ STATIC & MEDIA FILES ============
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
STATIC_URL = "/static/"
STATIC_ROOT = os.path.join(BASE_DIR, "staticfiles")
STATICFILES_DIRS = (os.path.join(BASE_DIR, "static"),)
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# Driver documents (license, insurance, NIN, etc.) go to Cloudinary rather
# than local disk — on Render (and most PaaS hosts) the filesystem is
# ephemeral, so anything saved locally is silently gone on the next
# redeploy or restart. Only MEDIA (user uploads) moves; static assets stay
# on Whitenoise below, unaffected.
CLOUDINARY_STORAGE = {
    "CLOUD_NAME": os.getenv("CLOUDINARY_CLOUD_NAME", ""),
    "API_KEY": os.getenv("CLOUDINARY_API_KEY", ""),
    "API_SECRET": os.getenv("CLOUDINARY_API_SECRET", ""),
}
if CLOUDINARY_STORAGE["CLOUD_NAME"]:
    # RawMediaCloudinaryStorage, not MediaCloudinaryStorage — driver uploads
    # are a mix of photos and PDFs, and MediaCloudinaryStorage's default
    # "image" resource type rejects anything Cloudinary can't parse as an
    # image (confirmed directly: a plain text test upload failed with
    # "Invalid image file"). "raw" stores any file type as-is; GoCab never
    # needs Cloudinary's image transforms anyway.
    DEFAULT_FILE_STORAGE = "cloudinary_storage.storage.RawMediaCloudinaryStorage"

# Firebase Cloud Messaging (push notifications) — services/push_service.py
# reads whichever of these is set to init the firebase_admin SDK once.
# FCM_CREDENTIALS_PATH is for local dev (a gitignored service-account JSON
# file on disk); FCM_CREDENTIALS_JSON is for Render, where pasting the raw
# JSON in as an env var is easier than mounting a file. Neither being set is
# a normal, supported state — push sends just no-op until one is.
FCM_CREDENTIALS_PATH = os.getenv("FCM_CREDENTIALS_PATH", "")
FCM_CREDENTIALS_JSON = os.getenv("FCM_CREDENTIALS_JSON", "")

STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"
WHITENOISE_MAX_AGE = 31536000
WHITENOISE_USE_FINDERS = True

USE_X_FORWARDED_HOST = True
USE_X_FORWARDED_PORT = True
# Real OTP/confirmation emails through Resend. First attempt on 2026-10-02
# was reverted same-day after a live test proved a valid API key alone isn't
# enough — Resend rejects every recipient except the account's own address
# until the "from" domain is verified. gocablogistics.com was verified in
# Resend's dashboard later that day, confirmed via a real send to an address
# that ISN'T the Resend account's own, and RESEND_DOMAIN_VERIFIED flipped to
# True in .env — this block has sent live since.
RESEND_SMTP_HOST = "smtp.resend.com"
RESEND_SMTP_PORT = 587
# Falls back to onboarding@resend.dev (Resend's pre-verified sandbox sender)
# only if DEFAULT_FROM_EMAIL isn't set in .env — sending "from" an unverified
# custom domain gets rejected outright, so don't point this at an
# @gocablogistics.com address unless that domain shows Verified in Resend's
# dashboard first.
RESEND_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", "GoCab <onboarding@resend.dev>")

# Gated on this SECOND flag, not just RESEND_API_KEY's presence — a valid key
# alone isn't enough; Resend's sandbox restriction blocks every recipient
# except the account's own address until the domain is actually verified.
# Only set "True" in .env once Resend's dashboard shows the domain Verified.
RESEND_DOMAIN_VERIFIED = os.getenv("RESEND_DOMAIN_VERIFIED", "False").lower() == "true"

if RESEND_API_KEY and RESEND_DOMAIN_VERIFIED:
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
    EMAIL_HOST = RESEND_SMTP_HOST
    EMAIL_PORT = RESEND_SMTP_PORT
    EMAIL_HOST_USER = "resend"
    EMAIL_HOST_PASSWORD = RESEND_API_KEY
    EMAIL_USE_TLS = True
    DEFAULT_FROM_EMAIL = RESEND_FROM_EMAIL
else:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
    DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", "GoCab <no-reply@gocab.app>")