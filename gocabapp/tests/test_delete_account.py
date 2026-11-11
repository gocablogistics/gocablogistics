"""Coverage for POST /auth/delete-account — previously untested at any
level. Soft-delete (is_active=False) that frees up phone/email/bank
identity fields so the same person can register fresh, but only once
there's no ride actually in progress."""
import datetime
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from ninja_jwt.tokens import RefreshToken

from gocabapp.models import Driver, Rider, RideRequest


def _make_rider(suffix: str) -> Rider:
    user = User.objects.create_user(
        username=f"delrider{suffix}", email=f"delrider{suffix}@example.com",
    )
    return Rider.objects.create(
        user=user, full_name=f"Rider {suffix}", phone_number=f"+23470900000{suffix}",
    )


def _make_driver(suffix: str, **extra) -> Driver:
    user = User.objects.create_user(
        username=f"deldriver{suffix}", email=f"deldriver{suffix}@example.com",
    )
    return Driver.objects.create(
        user=user, full_name=f"Driver {suffix}", phone_number=f"+23471900000{suffix}",
        date_of_birth=datetime.date(1995, 1, 1), vehicle_type="Bike",
        national_identification_number=f"DELNIN{suffix}", bank_name="Test Bank",
        account_number=f"555005{suffix}0", account_holder_name=f"Driver {suffix}",
        is_approved=True, **extra,
    )


def _auth_header(user: User) -> dict:
    token = str(RefreshToken.for_user(user).access_token)
    return {"HTTP_AUTHORIZATION": f"Bearer {token}"}


class DeleteAccountTests(TestCase):
    def test_a_rider_with_no_active_ride_can_delete_their_account(self):
        rider = _make_rider("1")
        user_id = rider.user.id
        response = self.client.post("/api/v1/auth/delete-account", **_auth_header(rider.user))
        self.assertEqual(response.status_code, 200)
        user = User.objects.get(id=user_id)
        self.assertFalse(user.is_active)
        self.assertEqual(user.email, "")
        rider.refresh_from_db()
        self.assertIsNone(rider.phone_number)
        self.assertIsNone(rider.email)

    def test_a_rider_with_a_pending_ride_cannot_delete_their_account(self):
        rider = _make_rider("2")
        RideRequest.objects.create(
            passenger=rider.user, current_location="A", destination="B",
            status="pending", vehicle_type="Bike", total_fare=Decimal("1000"),
        )
        response = self.client.post("/api/v1/auth/delete-account", **_auth_header(rider.user))
        self.assertEqual(response.status_code, 409)
        rider.user.refresh_from_db()
        self.assertTrue(rider.user.is_active)

    def test_a_rider_with_only_a_completed_ride_can_still_delete(self):
        rider = _make_rider("3")
        RideRequest.objects.create(
            passenger=rider.user, current_location="A", destination="B",
            status="completed", vehicle_type="Bike", total_fare=Decimal("1000"),
            payment_status="paid",
        )
        response = self.client.post("/api/v1/auth/delete-account", **_auth_header(rider.user))
        self.assertEqual(response.status_code, 200)

    def test_a_driver_with_an_active_trip_cannot_delete_their_account(self):
        driver = _make_driver("1")
        rider = _make_rider("4")
        RideRequest.objects.create(
            passenger=rider.user, driver=driver.user, current_location="A", destination="B",
            status="started", vehicle_type="Bike", total_fare=Decimal("1000"),
        )
        response = self.client.post("/api/v1/auth/delete-account", **_auth_header(driver.user))
        self.assertEqual(response.status_code, 409)

    def test_deleting_a_driver_account_takes_them_offline_and_frees_the_bank_account(self):
        driver = _make_driver("2", is_online=True)
        response = self.client.post("/api/v1/auth/delete-account", **_auth_header(driver.user))
        self.assertEqual(response.status_code, 200)
        driver.refresh_from_db()
        self.assertFalse(driver.is_online)
        self.assertIsNone(driver.phone_number)
        self.assertEqual(driver.account_number, f"deleted-{driver.user.id}")

    def test_after_deletion_the_same_phone_number_can_register_again(self):
        """The actual point of clearing these fields instead of just
        banning — confirmed by having a second rider genuinely reuse the
        first one's now-freed phone number."""
        rider = _make_rider("5")
        phone = rider.phone_number
        self.client.post("/api/v1/auth/delete-account", **_auth_header(rider.user))

        second = _make_rider("6")
        second.phone_number = phone
        second.save(update_fields=["phone_number"])
        self.assertEqual(Rider.objects.filter(phone_number=phone).count(), 1)

    def test_a_deactivated_users_token_no_longer_authenticates(self):
        """is_active=False must actually lock the account out, not just
        cosmetically mark it — ninja_jwt's own get_user() checks this on
        every request."""
        rider = _make_rider("7")
        header = _auth_header(rider.user)
        self.client.post("/api/v1/auth/delete-account", **header)

        response = self.client.get("/api/v1/auth/me", **header)
        self.assertEqual(response.status_code, 401)
