from __future__ import annotations

from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from channels.middleware import BaseMiddleware
from django.contrib.auth.models import AnonymousUser, User
from ninja_jwt.exceptions import TokenError
from ninja_jwt.tokens import AccessToken


@database_sync_to_async
def _user_from_token(token_str: str):
    try:
        token = AccessToken(token_str)
    except TokenError:
        return AnonymousUser()
    try:
        user = User.objects.get(id=token["user_id"])
    except User.DoesNotExist:
        return AnonymousUser()
    # ninja_jwt's own REST auth (JWTBaseAuthentication.get_user) rejects an
    # inactive user even with a still-valid, unexpired token — this custom
    # WS middleware is a separate code path and didn't have that same check,
    # so a banned/deleted account (admin ban, or self-service delete-account)
    # could keep an existing socket alive, or open a new one, for up to the
    # access token's remaining 30-minute lifetime after being banned.
    if not user.is_active:
        return AnonymousUser()
    return user


class JWTAuthMiddleware(BaseMiddleware):
    """Authenticates websocket connections with the same JWT access tokens
    the rest of the JSON API uses. A browser's native WebSocket API can't
    set an Authorization header, so the SPA connects with `?token=<access>`
    on the URL instead — this reads that query param rather than the
    session cookie channels.auth.AuthMiddlewareStack expects, since the app
    no longer uses Django's session-based login() anywhere.
    """

    async def __call__(self, scope, receive, send):
        query_string = scope.get("query_string", b"").decode()
        token = parse_qs(query_string).get("token", [None])[0]
        scope["user"] = await _user_from_token(token) if token else AnonymousUser()
        return await super().__call__(scope, receive, send)


def JWTAuthMiddlewareStack(inner):
    return JWTAuthMiddleware(inner)
