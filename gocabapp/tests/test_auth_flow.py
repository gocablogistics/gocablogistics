"""Router-level coverage for the auth flow that had none before: request a
code, verify it, register, refresh, logout, /me, switch-role. Also the
regression test for the two real production incidents this session on
rotate_refresh_token — reusing an already-rotated token (whether a near-
simultaneous race or a client that never got the first response) must not
silently log the user out. See services.py's own docstring on
rotate_refresh_token for the full story.
"""
import json

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase
from ninja_jwt.tokens import RefreshToken

from gocabapp.api.auth import otp
from gocabapp.models import Driver, Rider


def _real_code(email: str) -> str:
    otp.send_code(email)
    entry = cache.get(otp._cache_key(email))
    for guess in range(1_000_000):
        code = f"{guess:06d}"
        if otp._hash_code(email, code) == entry["hash"]:
            return code
    raise AssertionError("could not recover the sent code")


def _make_rider(suffix: str) -> Rider:
    user = User.objects.create_user(username=f"authrider{suffix}", email=f"authrider{suffix}@example.com")
    return Rider.objects.create(user=user, full_name=f"Rider {suffix}", phone_number=f"+23470000001{suffix}")


def _auth_header(user: User) -> dict:
    token = str(RefreshToken.for_user(user).access_token)
    return {"HTTP_AUTHORIZATION": f"Bearer {token}"}


class RequestAndVerifyCodeTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_verify_code_for_unknown_email_returns_404_with_verified_token(self):
        """New-user path: the code proves they own the email, so they
        shouldn't have to enter another one on the signup screen."""
        email = "brandnew@example.com"
        code = _real_code(email)
        response = self.client.post(
            "/api/v1/auth/verify-code",
            data=json.dumps({"email": email, "code": code}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 404)
        self.assertIn("verified_token", response.json())

    def test_verify_code_for_existing_user_returns_a_working_token_pair(self):
        rider = _make_rider("1")
        code = _real_code(rider.user.email)
        response = self.client.post(
            "/api/v1/auth/verify-code",
            data=json.dumps({"email": rider.user.email, "code": code}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("access", body)
        self.assertIn("refresh", body)
        self.assertEqual(body["user"]["role"], "rider")

    def test_wrong_code_is_rejected(self):
        rider = _make_rider("2")
        _real_code(rider.user.email)
        response = self.client.post(
            "/api/v1/auth/verify-code",
            data=json.dumps({"email": rider.user.email, "code": "000000"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)


class RegisterRiderTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_register_with_a_fresh_code_creates_a_working_account(self):
        email = "newrider@example.com"
        code = _real_code(email)
        response = self.client.post(
            "/api/v1/auth/register/rider",
            data=json.dumps({
                "full_name": "New Rider", "phone_number": "+2348100000001",
                "email": email, "code": code,
            }),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("access", body)
        self.assertTrue(Rider.objects.filter(phone_number="+2348100000001").exists())

    def test_register_with_neither_code_nor_verified_token_is_rejected(self):
        response = self.client.post(
            "/api/v1/auth/register/rider",
            data=json.dumps({
                "full_name": "No Code", "phone_number": "+2348100000002",
                "email": "nocode@example.com",
            }),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Rider.objects.filter(phone_number="+2348100000002").exists())


class MeAndSwitchRoleTests(TestCase):
    def test_me_returns_the_authenticated_users_profile(self):
        rider = _make_rider("3")
        response = self.client.get("/api/v1/auth/me", **_auth_header(rider.user))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["role"], "rider")

    def test_me_without_a_token_is_rejected(self):
        response = self.client.get("/api/v1/auth/me")
        self.assertEqual(response.status_code, 401)

    def test_switch_role_fails_cleanly_for_an_account_with_no_such_profile(self):
        rider = _make_rider("4")
        response = self.client.post(
            "/api/v1/auth/switch-role/driver", **_auth_header(rider.user),
        )
        self.assertEqual(response.status_code, 403)


class RefreshTokenTests(TestCase):
    """rotate_refresh_token is the function behind two real incidents this
    session (first a 60s replay-cache fix that still wasn't enough, then
    the actual fix: stop auto-blacklisting on rotation). These are the
    regression tests that should have existed before either bug shipped."""

    def test_refresh_issues_a_new_working_pair(self):
        rider = _make_rider("5")
        refresh = str(RefreshToken.for_user(rider.user))
        response = self.client.post(
            "/api/v1/auth/refresh",
            data=json.dumps({"refresh": refresh}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("access", body)
        self.assertIn("refresh", body)
        self.assertNotEqual(body["refresh"], refresh)

    def test_reusing_an_already_rotated_token_still_works_not_a_401(self):
        """The actual production bug: a backgrounded driver's app keeps
        retrying with a stale refresh token (the server already rotated
        it, but the client never got/saved that response). This must not
        log them out, no matter how much later the retry happens."""
        rider = _make_rider("6")
        original = str(RefreshToken.for_user(rider.user))

        first = self.client.post(
            "/api/v1/auth/refresh",
            data=json.dumps({"refresh": original}),
            content_type="application/json",
        )
        self.assertEqual(first.status_code, 200)

        # Reuse the SAME original token again, simulating the client that
        # never saved the first rotation's response.
        second = self.client.post(
            "/api/v1/auth/refresh",
            data=json.dumps({"refresh": original}),
            content_type="application/json",
        )
        self.assertEqual(second.status_code, 200)
        self.assertIn("access", second.json())

    def test_refresh_with_a_garbage_token_is_rejected(self):
        response = self.client.post(
            "/api/v1/auth/refresh",
            data=json.dumps({"refresh": "not-a-real-token"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 401)

    def test_logout_blacklists_the_token_for_real(self):
        """Explicit logout is the one case that SHOULD still kill a
        refresh token immediately — unlike the auto-rotation path above."""
        rider = _make_rider("7")
        refresh = str(RefreshToken.for_user(rider.user))

        logout_response = self.client.post(
            "/api/v1/auth/logout",
            data=json.dumps({"refresh": refresh}),
            content_type="application/json",
        )
        self.assertEqual(logout_response.status_code, 200)

        reuse_response = self.client.post(
            "/api/v1/auth/refresh",
            data=json.dumps({"refresh": refresh}),
            content_type="application/json",
        )
        self.assertEqual(reuse_response.status_code, 401)
