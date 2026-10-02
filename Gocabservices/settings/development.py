from .base import *
from corsheaders.defaults import default_headers
import dj_database_url
import redis

DEBUG = True

# Testing means booking and cancelling over and over — the real limit (5 per 24h)
# would lock the tester out after a few tries. Development only.
RIDER_CANCELLATION_LIMIT = 50
DRIVER_CANCELLATION_LIMIT = 50
WHITENOISE_AUTOREFRESH = True

ALLOWED_HOSTS = [
    "localhost", "127.0.0.1",
    # The Mac's LAN IP — so a phone on the same WiFi hitting the backend
    # directly (the installed APK, not through the Vite dev server) isn't
    # rejected outright. Update this if the router ever hands out a
    # different address.
    "192.168.100.23",
    # Wildcard, so any freshly-generated ngrok subdomain works without
    # editing this file per session — only needed for temporarily tunneling
    # dev out to show a client; harmless otherwise since dev traffic never
    # actually crosses these hosts unless you're the one running a tunnel.
    # ngrok has used several free-tier domain suffixes over time (.io, then
    # .ngrok-free.app, now .ngrok-free.dev) — listing all of them since
    # there's no real cost to a stale entry, but a missing current one is
    # exactly the "why is my demo 400ing" problem this exists to avoid.
    ".ngrok-free.app", ".ngrok-free.dev", ".ngrok.io", ".ngrok.app",
]

CORS_ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    # The Tauri Android app's WebView origin — without this, every REST call
    # from the installed APK is blocked by CORS even with the right API URL.
    "http://tauri.localhost",
    "https://tauri.localhost",
]
CORS_ALLOWED_ORIGIN_REGEXES = [
    r"^https://.*\.ngrok-free\.app$",
    r"^https://.*\.ngrok-free\.dev$",
    r"^https://.*\.ngrok\.io$",
    r"^https://.*\.ngrok\.app$",
]
# ngrok's free tier can answer WebView requests with an HTML warning page
# instead of the API's JSON; the client sends this header to skip it, and it
# has to be allow-listed or the CORS preflight rejects the request.
CORS_ALLOW_HEADERS = list(default_headers) + ["ngrok-skip-browser-warning"]
CSRF_TRUSTED_ORIGINS = [
    "https://*.ngrok-free.app",
    "https://*.ngrok-free.dev",
    "https://*.ngrok.io",
    "https://*.ngrok.app",
]

DATABASES = {
    "default": dj_database_url.config(
        default=os.getenv("DATABASE_URL"), conn_max_age=0, ssl_require=False
    )
}


CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "unique-snowflake",
        "TIMEOUT": 300,
        "OPTIONS": {"MAX_ENTRIES": 1000},
    }
}
# InMemoryChannelLayer looks convenient for local dev but is genuinely
# unreliable here: Ninja's sync view functions run in a worker thread via
# Daphne's sync-to-async bridge, and the in-memory layer's group/channel
# state doesn't reliably cross that thread boundary — group_send() from a
# view can silently vanish instead of reaching a WebSocket consumer
# subscribed on the main event loop. Verified directly: an accept/start
# REST call succeeded but the rider's subscribed socket received nothing.
# Redis (already what production uses) doesn't have this problem, so dev
# matches prod instead of using a backend production never actually relies on.
# Deliberately NOT reading the shared .env's REDIS_URL here — that points at
# production's cloud Redis (Upstash), which this machine can't reach and
# has no business talking to for local dev anyway. A dedicated var keeps
# dev fully separate; it only needs `redis-server` running locally.
DEV_REDIS_URL = os.getenv("DEV_REDIS_URL", "redis://127.0.0.1:6379/0")
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {
            "hosts": [DEV_REDIS_URL],
            "capacity": 1500,
            "expiry": 10,
        },
    },
}

CACHE_MIDDLEWARE_ALIAS = "default"
CACHE_MIDDLEWARE_SECONDS = 300
CACHE_MIDDLEWARE_KEY_PREFIX = "gocab"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "standard"},
    },
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "django": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "gocabapp": {"handlers": ["console"], "level": "DEBUG", "propagate": False},
    },
}