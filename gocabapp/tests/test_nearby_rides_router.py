"""Coverage for GET /rides/nearby — previously untested at any level.
Real-world Benin City coordinates throughout (GoCab's one active city),
picked to land cleanly on one side or the other of distance_utils.py's
CITY_BOUNDARIES/CITY_DISTANCE_LIMITS without needing to mock anything —
no network call is ever on the path here (get_nearby_rides is pure
haversine math, not a Google Maps call)."""
import datetime
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from ninja_jwt.tokens import RefreshToken

from gocabapp.models import Driver, Rider, RideRequest

DRIVER_LAT, DRIVER_LNG = 6.33, 5.60
NEARBY_PICKUP = (6.335, 5.604)
NEARBY_DEST = (6.32, 5.59)
# ~10km east, same city box (benin: lat 6.2-6.4, lng 5.5-5.8) — past
# CITY_DISTANCE_LIMITS["benin"]["max_pickup_distance"] (6km) without
# crossing into a different city's box.
TOO_FAR_PICKUP = (6.33, 5.691)
LAGOS_PICKUP = (6.5, 3.0)
LAGOS_DEST = (6.55, 3.1)


def _make_rider(suffix: str) -> Rider:
    user = User.objects.create_user(username=f"nearbyrider{suffix}", email=f"nearbyrider{suffix}@example.com")
    return Rider.objects.create(user=user, full_name=f"Rider {suffix}")


def _make_driver(suffix: str, **extra) -> Driver:
    user = User.objects.create_user(username=f"nearbydriver{suffix}", email=f"nearbydriver{suffix}@example.com")
    extra.setdefault("vehicle_type", "Bike")
    return Driver.objects.create(
        user=user, full_name=f"Driver {suffix}", phone_number=f"+23470300000{suffix}",
        date_of_birth=datetime.date(1995, 1, 1),
        national_identification_number=f"NEARNIN{suffix}", bank_name="Test Bank",
        account_number=f"999995{suffix}0", account_holder_name=f"Driver {suffix}", is_approved=True,
        **extra,
    )


def _make_pending_ride(rider: Rider, pickup, dest, vehicle_type="Bike") -> RideRequest:
    return RideRequest.objects.create(
        passenger=rider.user, current_location="A", destination="B",
        status="pending", vehicle_type=vehicle_type, total_fare=Decimal("1000"),
        pickup_latitude=pickup[0], pickup_longitude=pickup[1],
        destination_latitude=dest[0], destination_longitude=dest[1],
    )


def _auth_header(user: User) -> dict:
    token = str(RefreshToken.for_user(user).access_token)
    return {"HTTP_AUTHORIZATION": f"Bearer {token}"}


class NearbyRidesTests(TestCase):
    def test_requires_a_driver_profile(self):
        rider = _make_rider("1")
        response = self.client.get("/api/v1/rides/nearby", **_auth_header(rider.user))
        self.assertEqual(response.status_code, 403)

    def test_offline_driver_sees_nothing_at_all(self):
        driver = _make_driver("1", is_online=False, latitude=DRIVER_LAT, longitude=DRIVER_LNG)
        rider = _make_rider("2")
        _make_pending_ride(rider, NEARBY_PICKUP, NEARBY_DEST)
        response = self.client.get("/api/v1/rides/nearby", **_auth_header(driver.user))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    def test_a_genuinely_nearby_same_city_ride_is_returned(self):
        driver = _make_driver("2", is_online=True, latitude=DRIVER_LAT, longitude=DRIVER_LNG)
        rider = _make_rider("3")
        ride = _make_pending_ride(rider, NEARBY_PICKUP, NEARBY_DEST)
        response = self.client.get("/api/v1/rides/nearby", **_auth_header(driver.user))
        body = response.json()
        self.assertEqual([r["id"] for r in body], [ride.id])
        self.assertEqual(body[0]["passenger_name"], "Rider 3")
        self.assertIsNotNone(body[0]["distance_from_driver"])

    def test_a_ride_past_the_citys_max_pickup_distance_is_excluded(self):
        driver = _make_driver("3", is_online=True, latitude=DRIVER_LAT, longitude=DRIVER_LNG)
        rider = _make_rider("4")
        _make_pending_ride(rider, TOO_FAR_PICKUP, NEARBY_DEST)
        response = self.client.get("/api/v1/rides/nearby", **_auth_header(driver.user))
        self.assertEqual(response.json(), [])

    def test_a_ride_in_a_different_city_is_excluded_even_if_geometrically_closer(self):
        driver = _make_driver("4", is_online=True, latitude=DRIVER_LAT, longitude=DRIVER_LNG)
        rider = _make_rider("5")
        _make_pending_ride(rider, LAGOS_PICKUP, LAGOS_DEST)
        response = self.client.get("/api/v1/rides/nearby", **_auth_header(driver.user))
        self.assertEqual(response.json(), [])

    def test_a_ride_for_a_different_vehicle_type_is_excluded(self):
        driver = _make_driver("5", is_online=True, latitude=DRIVER_LAT, longitude=DRIVER_LNG, vehicle_type="Bike")
        rider = _make_rider("6")
        _make_pending_ride(rider, NEARBY_PICKUP, NEARBY_DEST, vehicle_type="Bicycle")
        response = self.client.get("/api/v1/rides/nearby", **_auth_header(driver.user))
        self.assertEqual(response.json(), [])

    def test_a_ride_someone_else_already_accepted_is_excluded(self):
        driver = _make_driver("6", is_online=True, latitude=DRIVER_LAT, longitude=DRIVER_LNG)
        other_driver = _make_driver("7")
        rider = _make_rider("7")
        ride = _make_pending_ride(rider, NEARBY_PICKUP, NEARBY_DEST)
        ride.driver = other_driver.user
        ride.status = "accepted"
        ride.save()
        response = self.client.get("/api/v1/rides/nearby", **_auth_header(driver.user))
        self.assertEqual(response.json(), [])

    def test_a_driver_with_no_location_set_yet_falls_back_to_any_pending_matching_ride(self):
        """Documented fallback in rides/router.py's nearby_rides — no
        location means no distance/city filtering is even possible, so
        every pending ride of the right vehicle type shows up instead of
        nothing."""
        driver = _make_driver("8", is_online=True, latitude=None, longitude=None)
        rider = _make_rider("8")
        ride = _make_pending_ride(rider, LAGOS_PICKUP, LAGOS_DEST)  # would fail the city check if filtered
        response = self.client.get("/api/v1/rides/nearby", **_auth_header(driver.user))
        self.assertEqual([r["id"] for r in response.json()], [ride.id])
