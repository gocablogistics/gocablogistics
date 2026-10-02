from __future__ import annotations

from django.core.cache import cache
from ninja.errors import HttpError


def throttle(
    cache_key: str, limit: int, window_seconds: int, message: str | None = None
) -> None:
    """Fixed-window request counter backed by the shared cache (Redis in
    production), so limits hold across every app server, not just one.

    message lets each call site say what actually got limited (registration,
    a code request, etc.) — the previous one-size-fits-all "Too many
    attempts" left someone hitting, say, the registration limit with no way
    to tell that apart from a genuine network failure elsewhere in the flow.
    """
    try:
        count = cache.incr(cache_key)
    except ValueError:
        cache.set(cache_key, 1, timeout=window_seconds)
        count = 1

    if count > limit:
        raise HttpError(429, message or "Too many attempts. Please try again shortly.")
