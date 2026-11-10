"""Coverage for the notifications endpoints — list, unread count,
mark-read, mark-all-read, register-device. Had zero tests despite being
on the critical path for the push-notification work done this session
(a device never actually gets notified unless register-device succeeds).
"""
import json

from django.contrib.auth.models import User
from django.test import TestCase

from gocabapp.models import DeviceToken, Notification


def _auth_header(user: User) -> dict:
    from ninja_jwt.tokens import RefreshToken
    token = str(RefreshToken.for_user(user).access_token)
    return {"HTTP_AUTHORIZATION": f"Bearer {token}"}


class NotificationListAndCountTests(TestCase):
    def test_lists_only_this_users_notifications_newest_first(self):
        user = User.objects.create_user(username="notifyuser1", email="notifyuser1@example.com")
        other = User.objects.create_user(username="notifyuser1b", email="notifyuser1b@example.com")
        Notification.objects.create(user=user, message="first", is_active=True)
        Notification.objects.create(user=user, message="second", is_active=True)
        Notification.objects.create(user=other, message="not yours", is_active=True)

        response = self.client.get("/api/v1/notifications", **_auth_header(user))
        self.assertEqual(response.status_code, 200)
        messages = [n["message"] for n in response.json()]
        self.assertEqual(messages, ["second", "first"])

    def test_unread_count_only_counts_active_ones(self):
        user = User.objects.create_user(username="notifyuser2", email="notifyuser2@example.com")
        Notification.objects.create(user=user, message="active", is_active=True)
        Notification.objects.create(user=user, message="already read", is_active=False)

        response = self.client.get("/api/v1/notifications/count", **_auth_header(user))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 1)


class MarkReadTests(TestCase):
    def test_mark_one_read_decrements_the_count(self):
        user = User.objects.create_user(username="notifyuser3", email="notifyuser3@example.com")
        n1 = Notification.objects.create(user=user, message="one", is_active=True)
        Notification.objects.create(user=user, message="two", is_active=True)

        response = self.client.post(f"/api/v1/notifications/{n1.id}/read", **_auth_header(user))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 1)
        n1.refresh_from_db()
        self.assertFalse(n1.is_active)

    def test_cannot_mark_someone_elses_notification_read(self):
        owner = User.objects.create_user(username="notifyuser4", email="notifyuser4@example.com")
        other = User.objects.create_user(username="notifyuser4b", email="notifyuser4b@example.com")
        n = Notification.objects.create(user=owner, message="mine", is_active=True)

        response = self.client.post(f"/api/v1/notifications/{n.id}/read", **_auth_header(other))
        self.assertEqual(response.status_code, 404)
        n.refresh_from_db()
        self.assertTrue(n.is_active)

    def test_mark_all_read_zeroes_the_count(self):
        user = User.objects.create_user(username="notifyuser5", email="notifyuser5@example.com")
        Notification.objects.create(user=user, message="a", is_active=True)
        Notification.objects.create(user=user, message="b", is_active=True)

        response = self.client.post("/api/v1/notifications/read-all", **_auth_header(user))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 0)
        self.assertEqual(Notification.objects.filter(user=user, is_active=True).count(), 0)


class RegisterDeviceTests(TestCase):
    def test_registers_a_new_token(self):
        user = User.objects.create_user(username="notifyuser6", email="notifyuser6@example.com")
        response = self.client.post(
            "/api/v1/notifications/register-device",
            data=json.dumps({"token": "fcm-token-abc", "platform": "ios", "app_version": "1.0"}),
            content_type="application/json",
            **_auth_header(user),
        )
        self.assertEqual(response.status_code, 200)
        token = DeviceToken.objects.get(token="fcm-token-abc")
        self.assertEqual(token.user_id, user.id)
        self.assertEqual(token.platform, "ios")
        self.assertTrue(token.is_active)

    def test_re_registering_the_same_token_under_a_different_account_moves_it(self):
        """A device that logs out and back in as someone else on the same
        token must re-home to the new account, not stay stuck on the old
        one (update_or_create keyed on the globally-unique token)."""
        first_user = User.objects.create_user(username="notifyuser7a", email="notifyuser7a@example.com")
        second_user = User.objects.create_user(username="notifyuser7b", email="notifyuser7b@example.com")

        self.client.post(
            "/api/v1/notifications/register-device",
            data=json.dumps({"token": "shared-device-token", "platform": "android", "app_version": "1.0"}),
            content_type="application/json",
            **_auth_header(first_user),
        )
        self.client.post(
            "/api/v1/notifications/register-device",
            data=json.dumps({"token": "shared-device-token", "platform": "android", "app_version": "1.0"}),
            content_type="application/json",
            **_auth_header(second_user),
        )
        self.assertEqual(DeviceToken.objects.filter(token="shared-device-token").count(), 1)
        token = DeviceToken.objects.get(token="shared-device-token")
        self.assertEqual(token.user_id, second_user.id)
