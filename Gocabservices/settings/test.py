"""Settings used only by `manage.py test`. Deliberately isolated from
everything real — a local SQLite file instead of Neon (so tests can
never touch, slow down, or risk real user/payment data), an in-memory
cache instead of Redis (so tests don't need Redis running and can't leak
state between runs), and the console email backend (so a test can never
actually send a real email to a real address)."""
from .base import *

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
    }
}

EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
SENTRY_DSN = ""
# The real .env points this at a real service-account file that exists
# on disk — without clearing it here, push_service would actually try to
# initialize Firebase with real credentials during a test run.
FCM_CREDENTIALS_PATH = ""
FCM_CREDENTIALS_JSON = ""

# Creating a RideRequest fires a signal that broadcasts over the channel
# layer (ride_signals.py) — the real one needs Redis; this one is
# Channels' own in-memory layer, built specifically for tests.
CHANNEL_LAYERS = {
    "default": {"BACKEND": "channels.layers.InMemoryChannelLayer"},
}
