"""Coverage for GET /rides/referrals — previously untested at any level."""
from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from ninja_jwt.tokens import RefreshToken

from gocabapp.models import Driver, Rider


def _make_rider(suffix: str, referred_by=None) -> Rider:
    user = User.objects.create_user(username=f"refgetrider{suffix}", email=f"refgetrider{suffix}@example.com")
    return Rider.objects.create(user=user, full_name=f"Rider {suffix}", referred_by=referred_by)


def _make_driver(suffix: str) -> Driver:
    import datetime
    user = User.objects.create_user(username=f"refgetdriver{suffix}", email=f"refgetdriver{suffix}@example.com")
    return Driver.objects.create(
        user=user, full_name=f"Driver {suffix}", phone_number=f"+23470500000{suffix}",
        date_of_birth=datetime.date(1995, 1, 1), vehicle_type="Bike",
        national_identification_number=f"REFGETNIN{suffix}", bank_name="Test Bank",
        account_number=f"222205{suffix}0", account_holder_name=f"Driver {suffix}", is_approved=True,
    )


def _auth_header(user: User) -> dict:
    token = str(RefreshToken.for_user(user).access_token)
    return {"HTTP_AUTHORIZATION": f"Bearer {token}"}


class ReferralsEndpointTests(TestCase):
    def test_requires_a_rider_profile(self):
        driver = _make_driver("1")
        response = self.client.get("/api/v1/rides/referrals", **_auth_header(driver.user))
        self.assertEqual(response.status_code, 404)

    def test_includes_the_riders_own_code_and_wallet_balance(self):
        rider = _make_rider("1")
        response = self.client.get("/api/v1/rides/referrals", **_auth_header(rider.user))
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["referral_code"], rider.referral_code)
        self.assertEqual(body["wallet_credit_balance"], float(rider.wallet_credit_balance))

    @override_settings(REFERRAL_REWARD_AMOUNT=750.0)
    def test_reflects_the_current_reward_amount_setting(self):
        rider = _make_rider("2")
        response = self.client.get("/api/v1/rides/referrals", **_auth_header(rider.user))
        self.assertEqual(response.json()["referral_reward_amount"], 750.0)

    def test_lists_referred_riders_newest_first_with_reward_status(self):
        referrer = _make_rider("3")
        _make_rider("4", referred_by=referrer)
        newest = _make_rider("5", referred_by=referrer)
        newest.referral_reward_credited = True
        newest.save(update_fields=["referral_reward_credited"])

        response = self.client.get("/api/v1/rides/referrals", **_auth_header(referrer.user))
        body = response.json()["referrals"]
        self.assertEqual(len(body), 2)
        self.assertEqual(body[0]["full_name"], "Rider 5")
        self.assertTrue(body[0]["reward_earned"])
        self.assertFalse(body[1]["reward_earned"])

    def test_a_rider_with_no_referrals_gets_an_empty_list_not_an_error(self):
        rider = _make_rider("6")
        response = self.client.get("/api/v1/rides/referrals", **_auth_header(rider.user))
        self.assertEqual(response.json()["referrals"], [])
