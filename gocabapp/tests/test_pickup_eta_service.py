"""Coverage for pickup_eta_service.py — only ever exercised indirectly
before this (through the None-returning short-circuit paths in the
active-ride router tests), never its actual ETA math, the ARRIVED_KM
boundary, or the Google-calibration caching/fallback behavior."""
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import SimpleTestCase, TestCase

from gocabapp.services.pickup_eta_service import ARRIVED_KM, compute_pickup_eta

_GMAPS_PATCH_TARGET = "gocabapp.services.pickup_eta_service._gmaps"
_ESTIMATE_MINUTES_PATCH_TARGET = "gocabapp.services.pickup_eta_service.estimate_pickup_minutes"

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
    """Goes entirely through the real public entry point, compute_pickup_eta
    — not the private _traffic_ratio helper behind it, so a harmless
    internal refactor (renaming it, inlining it) can't break these.
    estimate_pickup_minutes is pinned to a fixed value so eta_min is a
    precisely predictable number regardless of the real formula, which
    isolates what's actually under test here: the traffic-ratio
    calibration, not fare_pricing's distance-to-minutes math."""

    def setUp(self):
        cache.clear()

    def _ride(self, ride_id):
        return _FakeRide(*PICKUP, ride_id=ride_id)

    def test_a_cached_ratio_is_reused_without_calling_google_again(self):
        fake_client = MagicMock()
        fake_client.distance_matrix.return_value = {
            "status": "OK",
            "rows": [{"elements": [{"status": "OK", "duration_in_traffic": {"value": 1200}}]}],  # 20 min
        }
        ride = self._ride(301)
        with patch(_ESTIMATE_MINUTES_PATCH_TARGET, return_value=10.0), \
             patch(_GMAPS_PATCH_TARGET, return_value=fake_client):
            first = compute_pickup_eta(ride, *FAR_DRIVER, allow_google_call=True)
            second = compute_pickup_eta(ride, *FAR_DRIVER, allow_google_call=True)
        self.assertEqual(fake_client.distance_matrix.call_count, 1)
        self.assertEqual(first["eta_min"], second["eta_min"])

    def test_a_good_google_reading_scales_the_eta_up(self):
        fake_client = MagicMock()
        fake_client.distance_matrix.return_value = {
            "status": "OK",
            "rows": [{"elements": [{"status": "OK", "duration_in_traffic": {"value": 1200}}]}],  # 20 min
        }
        ride = self._ride(302)
        with patch(_ESTIMATE_MINUTES_PATCH_TARGET, return_value=10.0), \
             patch(_GMAPS_PATCH_TARGET, return_value=fake_client):
            result = compute_pickup_eta(ride, *FAR_DRIVER, allow_google_call=True)
        # 20 real minutes vs. a 10-minute formula estimate -> ratio 2.0
        self.assertEqual(result["eta_min"], 20)

    def test_an_extreme_reading_is_clamped_to_the_ratio_bounds(self):
        fake_client = MagicMock()
        fake_client.distance_matrix.return_value = {
            "status": "OK",
            "rows": [{"elements": [{"status": "OK", "duration_in_traffic": {"value": 6000}}]}],  # 100 min
        }
        ride = self._ride(303)
        with patch(_ESTIMATE_MINUTES_PATCH_TARGET, return_value=10.0), \
             patch(_GMAPS_PATCH_TARGET, return_value=fake_client):
            result = compute_pickup_eta(ride, *FAR_DRIVER, allow_google_call=True)
        # Raw ratio would be 10x (100 real minutes / 10 formula minutes) —
        # clamped to the documented 3.0 ceiling before scaling the base.
        self.assertEqual(result["eta_min"], 30)

    def test_a_google_failure_falls_back_to_the_formula_estimate_and_only_tries_once(self):
        """So a Google outage costs at most one failed call per ride, not
        one per 15-second location ping — confirmed across two calls."""
        ride = self._ride(304)
        with patch(_ESTIMATE_MINUTES_PATCH_TARGET, return_value=10.0), \
             patch(_GMAPS_PATCH_TARGET, side_effect=Exception("boom")) as mock_gmaps:
            first = compute_pickup_eta(ride, *FAR_DRIVER, allow_google_call=True)
            second = compute_pickup_eta(ride, *FAR_DRIVER, allow_google_call=True)
        self.assertEqual(first["eta_min"], 10)
        self.assertEqual(second["eta_min"], 10)
        self.assertEqual(mock_gmaps.call_count, 1)

    def test_a_sub_one_minute_base_estimate_skips_google_entirely(self):
        ride = self._ride(305)
        with patch(_ESTIMATE_MINUTES_PATCH_TARGET, return_value=0.5), \
             patch(_GMAPS_PATCH_TARGET) as mock_gmaps:
            result = compute_pickup_eta(ride, *FAR_DRIVER, allow_google_call=True)
            mock_gmaps.assert_not_called()
        self.assertEqual(result["eta_min"], 1)  # max(1, ceil(0.5 * 1.0))
