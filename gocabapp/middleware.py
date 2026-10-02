import logging

from django.contrib.auth.models import User
from ninja_jwt.exceptions import TokenError
from ninja_jwt.tokens import AccessToken

from .api.auth import services
from .api.auth.cookies import (
    ACCESS_COOKIE_NAME,
    REFRESH_COOKIE_NAME,
    clear_auth_cookies,
    set_auth_cookies,
)

logger = logging.getLogger(__name__)


class JWTCookieAuthenticationMiddleware:
    """Authenticates the web app from the same JWT tokens the mobile apps
    use over the Authorization header — issued and validated by
    gocabapp.api.auth.services, the one source of truth for both clients.

    Must run after AuthenticationMiddleware. If the session already produced
    an authenticated user (e.g. a staff member logged into /admin/), that is
    left untouched; this only fills in request.user when it's anonymous.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        rotated_tokens = None
        should_clear = False

        if request.user.is_anonymous:
            access_str = request.COOKIES.get(ACCESS_COOKIE_NAME)
            refresh_str = request.COOKIES.get(REFRESH_COOKIE_NAME)

            user = self._user_from_access(access_str) if access_str else None
            if user is not None:
                request.user = user
            elif refresh_str:
                user, rotated_tokens = self._silent_refresh(refresh_str)
                if user is not None:
                    request.user = user
                else:
                    should_clear = True

        response = self.get_response(request)

        if rotated_tokens:
            set_auth_cookies(response, **rotated_tokens)
        elif should_clear:
            clear_auth_cookies(response)

        return response

    @staticmethod
    def _user_from_access(access_str: str):
        try:
            token = AccessToken(access_str)
        except TokenError:
            return None
        try:
            return User.objects.get(id=token["user_id"])
        except User.DoesNotExist:
            return None

    @staticmethod
    def _silent_refresh(refresh_str: str):
        """Access cookie expired (every 30 min) but the refresh cookie is
        still good — rotate quietly so the browser session doesn't drop
        every half hour the way the old Django session did every 7 days."""
        try:
            new_refresh = services.rotate_refresh_token(refresh_str)
        except Exception:
            return None, None

        try:
            user = User.objects.get(id=new_refresh["user_id"])
        except User.DoesNotExist:
            return None, None

        tokens = {"access": str(new_refresh.access_token), "refresh": str(new_refresh)}
        return user, tokens
