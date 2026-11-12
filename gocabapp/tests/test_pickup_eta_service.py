"""Coverage for pickup_eta_service.py — only ever exercised indirectly
before this (through the None-returning short-circuit paths in the
active-ride router tests), never its actual ETA math, the ARRIVED_KM
boundary, or the Google-calibration caching/fallback behavior."""
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import SimpleTestCase, TestCase

from gocabapp.services.pickup_eta_service import ARRIVED_KM, _traffic_ratio, compute_pickup_eta

_GMAPS_PATCH_TARGET = "gocabapp.services.pickup_eta_service._gmaps"

# Real Benin City coordinates, a few km apart — same city box used
# elsewhere in this suite (distance_utils.CITY_BOUNDARIES["benin"]).
PICKUP = (6.335, 5.604)
NEARBY_DRIVER = (6.3351, 5.6041)  # well within ARRIVED_KM of PICKUP
FAR_DRIVER = (6.32, 5.60)  # a few km away, same city


class _FakeRide:
    def __init__(self, pickup_lat=None, pickup_lng=None, ride_id=1):
        self.id = ride_id
        self.pickup_latitude = pickup_lat
        self.pickup_longitude = pickup_lng


class ComputePickupEtaMissingDataTests(SimpleTestCase):
    def test_no_pickup_coordinates_returns_none(self):
        ride = _FakeRide(pickup_lat=None, pickup_lng=None)
        self.assertIsNone(compute_pickup_eta(ride, 6.33, 5.60))

    def test_no_driver_coordinates_returns_none(self):
        ride = _FakeRide(*PICKUP)
        self.assertIsNone(compute_pickup_eta(ride, None, None))

    def test_partial_pickup_coordinates_returns_none(self):
        ride = _FakeRide(pickup_lat=6.33, pickup_lng=None)
        self.assertIsNone(compute_pickup_eta(ride, 6.33, 5.60))


class ComputePickupEtaArrivalTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_within_arrived_km_reports_zero_eta(self):
        ride = _FakeRide(*PICKUP, ride_id=101)
        result = compute_pickup_eta(ride, *NEARBY_DRIVER)
        self.assertEqual(result["eta_min"], 0)
        self.assertLessEqual(result["distance_km"], ARRIVED_KM)

    def test_outside_arrived_km_with_no_google_call_still_returns_a_positive_eta(self):
        """allow_google_call=False (used inside the accept/location-update
        transactions, which must never block on the network) — ratio
        falls back to 1.0, but the base formula estimate still comes
        through, never None and never a network call."""
        ride = _FakeRide(*PICKUP, ride_id=102)
        with patch(_GMAPS_PATCH_TARGET) as mock_gmaps:
            result = compute_pickup_eta(ride, *FAR_DRIVER, allow_google_call=False)
            mock_gmaps.assert_not_called()
        self.assertIsNotNone(result)
        self.assertGreater(result["eta_min"], 0)
        self.assertGreater(result["distance_km"], ARRIVED_KM)


class TrafficRatioTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_disallowed_google_call_returns_the_neutral_ratio(self):
        ratio = _traffic_ratio(201, *FAR_DRIVER, *PICKUP, base_minutes=10, allow_google_call=False)
        self.assertEqual(ratio, 1.0)

    def test_a_cached_ratio_is_reused_without_calling_google_again(self):
        cache.set("pickup_eta_ratio_202", 1.7, 90)
        with patch(_GMAPS_PATCH_TARGET) as mock_gmaps:
            ratio = _traffic_ratio(202, *FAR_DRIVER, *PICKUP, base_minutes=10, allow_google_call=True)
            mock_gmaps.assert_not_called()
        self.assertEqual(ratio, 1.7)

    def test_a_good_google_reading_computes_and_caches_the_ratio(self):
        fake_client = MagicMock()
        fake_client.distance_matrix.return_value = {
            "status": "OK",
            "rows": [{"elements": [{"status": "OK", "duration_in_traffic": {"value": 1200}}]}],  # 20 min
        }
        with patch(_GMAPS_PATCH_TARGET, return_value=fake_client):
            ratio = _traffic_ratio(203, *FAR_DRIVER, *PICKUP, base_minutes=10, allow_google_call=True)
        self.assertEqual(ratio, 2.0)  # 20 actual minutes / 10 formula minutes
        self.assertEqual(cache.get("pickup_eta_ratio_203"), 2.0)

    def test_an_extreme_reading_is_clamped_to_the_ratio_bounds(self):
        fake_client = MagicMock()
        fake_client.distance_matrix.return_value = {
            "status": "OK",
            "rows": [{"elements": [{"status": "OK", "duration_in_traffic": {"value": 6000}}]}],  # 100 min
        }
        with patch(_GMAPS_PATCH_TARGET, return_value=fake_client):
            ratio = _traffic_ratio(204, *FAR_DRIVER, *PICKUP, base_minutes=10, allow_google_call=True)
        self.assertEqual(ratio, 3.0)  # clamped at _RATIO_MAX

    def test_a_google_failure_falls_back_to_the_neutral_ratio_and_still_caches_it(self):
        """So a Google outage costs at most one failed call per ride, not
        one per 15-second location ping."""
        with patch(_GMAPS_PATCH_TARGET, side_effect=Exception("boom")):
            ratio = _traffic_ratio(205, *FAR_DRIVER, *PICKUP, base_minutes=10, allow_google_call=True)
        self.assertEqual(ratio, 1.0)
        self.assertEqual(cache.get("pickup_eta_ratio_205"), 1.0)

    def test_a_sub_one_minute_base_estimate_skips_google_entirely(self):
        with patch(_GMAPS_PATCH_TARGET) as mock_gmaps:
            ratio = _traffic_ratio(206, *FAR_DRIVER, *PICKUP, base_minutes=0.5, allow_google_call=True)
            mock_gmaps.assert_not_called()
        self.assertEqual(ratio, 1.0)
