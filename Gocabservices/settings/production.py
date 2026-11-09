from corsheaders.defaults import default_headers
from .base import *
import dj_database_url
import redis

DEBUG = False
WHITENOISE_AUTOREFRESH = False

PUBLIC_HOSTS = [h.strip() for h in os.getenv("PUBLIC_HOSTS", "").split(",") if h.strip()]
ALLOWED_HOSTS = ["localhost", "127.0.0.1", *PUBLIC_HOSTS]
CSRF_TRUSTED_ORIGINS = [f"https://{h}" for h in PUBLIC_HOSTS]
CORS_ALLOWED_ORIGINS = [f"https://{h}" for h in PUBLIC_HOSTS] + [
    "http://tauri.localhost",
    "https://tauri.localhost",
    # Android maps its custom scheme to http(s)://tauri.localhost (the two
    # entries above) because the older Android WebView can't serve a custom
    # URI scheme directly — iOS's WKWebView can, so Tauri's iOS build likely
    # uses the literal "tauri://localhost" origin instead. Added defensively
    # since this is the very first iOS build and that's unconfirmed.
    "tauri://localhost",
]
CORS_ALLOW_HEADERS = list(default_headers)

CSRF_COOKIE_SECURE = True
SESSION_COOKIE_SECURE = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
# nginx already redirects HTTP to HTTPS (certbot --redirect), this is
# defense in depth so Django itself never serves anything over plain HTTP
# even if that nginx config is ever changed. Safe with the proxy header
# above already in place, no redirect loop.
SECURE_SSL_REDIRECT = True
# Starting conservative (1 hour) rather than the usual year-long
# recommendation — this domain is a dedicated API host that will only ever
# be HTTPS, but HSTS is hard to safely undo once browsers cache it, so
# prove it out at low volume first and raise this once confident.
SECURE_HSTS_SECONDS = 3600

MIDDLEWARE.insert(1, "django.middleware.gzip.GZipMiddleware")


TEMPLATES[0]["APP_DIRS"] = False
TEMPLATES[0]["OPTIONS"]["loaders"] = [
    (
        "django.template.loaders.cached.Loader",
        [
            "django.template.loaders.filesystem.Loader",
            "django.template.loaders.app_directories.Loader",
        ],
    ),
]


DATABASES = {
    "default": dj_database_url.config(
        default=os.getenv("DATABASE_URL"), conn_max_age=600, ssl_require=True
    )
}
DATABASES["default"]["OPTIONS"] = {
    "connect_timeout": 10,
    "keepalives": 1,
    "keepalives_idle": 30,
    "keepalives_interval": 10,
    "keepalives_count": 5,
}



REDIS_URL = os.getenv("REDIS_URL")

CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": REDIS_URL,
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
            "CONNECTION_POOL_CLASS": "redis.BlockingConnectionPool",
            "CONNECTION_POOL_CLASS_KWARGS": {"max_connections": 20, "timeout": 20},
            "SOCKET_CONNECT_TIMEOUT": 5,
            "SOCKET_TIMEOUT": 5,
            "IGNORE_EXCEPTIONS": True,
            "RETRY_ON_TIMEOUT": True,
        },
        "KEY_PREFIX": "gocab",
        "TIMEOUT": 300,
    }
}

CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {
            "hosts": [REDIS_URL],
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
        "gocabapp": {"handlers": ["console"], "level": "INFO", "propagate": False},
    },
}