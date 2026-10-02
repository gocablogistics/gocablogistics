from django.conf import settings

ACCESS_COOKIE_NAME = "gocab_access"
REFRESH_COOKIE_NAME = "gocab_refresh"

_COOKIE_FLAGS = {"httponly": True, "samesite": "Lax"}


def _secure() -> bool:
    return not settings.DEBUG


def set_auth_cookies(response, access: str, refresh: str) -> None:
    """Store the same tokens the mobile apps get in the response body as
    httpOnly cookies instead, so the web app authenticates through the
    identical JWT/service layer without exposing tokens to page JS."""
    access_max_age = int(settings.NINJA_JWT["ACCESS_TOKEN_LIFETIME"].total_seconds())
    refresh_max_age = int(settings.NINJA_JWT["REFRESH_TOKEN_LIFETIME"].total_seconds())

    response.set_cookie(
        ACCESS_COOKIE_NAME,
        access,
        max_age=access_max_age,
        secure=_secure(),
        **_COOKIE_FLAGS,
    )
    response.set_cookie(
        REFRESH_COOKIE_NAME,
        refresh,
        max_age=refresh_max_age,
        secure=_secure(),
        **_COOKIE_FLAGS,
    )


def clear_auth_cookies(response) -> None:
    response.delete_cookie(ACCESS_COOKIE_NAME)
    response.delete_cookie(REFRESH_COOKIE_NAME)
