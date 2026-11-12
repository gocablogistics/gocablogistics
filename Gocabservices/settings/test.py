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

# Same isolation problem as FCM above, for file uploads: a real .env has
# a real CLOUDINARY_CLOUD_NAME, which flips base.py's DEFAULT_FILE_STORAGE
# over to the real Cloudinary account. Confirmed locally — a driver-
# registration test that uploads real file objects (SimpleUploadedFile)
# triggered an actual network call to api.cloudinary.com instead of
# writing to local disk. CI never has this problem by accident (it never
# sets CLOUDINARY_CLOUD_NAME), but that's relying on an absence rather
# than guaranteeing it — this clears the storage override explicitly so
# tests can never depend on what happens to be in the environment.
CLOUDINARY_STORAGE = {"CLOUD_NAME": "", "API_KEY": "", "API_SECRET": ""}
DEFAULT_FILE_STORAGE = "django.core.files.storage.FileSystemStorage"

# Creating a RideRequest fires a signal that broadcasts over the channel
# layer (ride_signals.py) — the real one needs Redis; this one is
# Channels' own in-memory layer, built specifically for tests.
CHANNEL_LAYERS = {
    "default": {"BACKEND": "channels.layers.InMemoryChannelLayer"},
}
