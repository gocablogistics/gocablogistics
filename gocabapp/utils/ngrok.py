"""Dev-only helper for demoing to a client through ngrok. See
Gocabservices/settings/development.py for the matching ALLOWED_HOSTS/CORS/
CSRF setup this depends on."""
from __future__ import annotations

import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

_NGROK_LOCAL_API = "http://127.0.0.1:4040/api/tunnels"
_FRONTEND_PORT_SUFFIX = ":3000"


def resolve_frontend_base_url() -> str:
    """In DEBUG, auto-detects a running ngrok tunnel pointed at the Vite
    dev server and uses its public URL for things like Paystack's payment
    callback — so a client demo works without manually setting and
    re-exporting FRONTEND_BASE_URL every time the tunnel restarts with a
    new random subdomain. Computed per-call rather than once at settings
    load time specifically so it keeps up if the tunnel gets restarted
    mid-demo without a Django restart.

    Falls back to the configured/default FRONTEND_BASE_URL immediately
    (short timeout, never raises) whenever ngrok's local API isn't
    reachable, which is the normal case for everyday dev work — this
    should never be able to slow down or break a real request."""
    if not settings.DEBUG:
        return settings.FRONTEND_BASE_URL
    try:
        response = requests.get(_NGROK_LOCAL_API, timeout=0.3)
        response.raise_for_status()
        for tunnel in response.json().get("tunnels", []):
            addr = tunnel.get("config", {}).get("addr", "")
            public_url = tunnel.get("public_url", "")
            if addr.endswith(_FRONTEND_PORT_SUFFIX) and public_url.startswith("https"):
                return public_url
    except requests.RequestException:
        pass
    except Exception:
        logger.exception("Unexpected error probing ngrok's local API")
    return settings.FRONTEND_BASE_URL
