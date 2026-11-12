"""Coverage for utils/distance_utils.py's own units — haversine_km,
geocode, google_distance, route_with_coords's implausible-distance
sanity check, and detect_city — previously only exercised indirectly
(get_nearby_rides already has coverage in test_nearby_rides_router.py;
these are the pieces under it that never had direct tests of their
own). Google Maps calls are mocked at gmaps.geocode/gmaps.distance_matrix
— the already-constructed client instance distance_utils.py builds at
import time — never a real network call.
"""
from unittest.mock import patch

from django.core.cache import cache
from django.test import SimpleTestCase, TestCase

from gocabapp.utils.distance_utils import (
    detect_city,
    geocode,
    google_distance,
    haversine_km,
    route_with_coords,
)

_GEOCODE_PATCH_TARGET = "gocabapp.utils.distance_utils.gmaps.geocode"
_DISTANCE_MATRIX_PATCH_TARGET = "gocabapp.utils.distance_utils.gmaps.distance_matrix"


class HaversineKmTests(SimpleTestCase):
    def test_a_known_one_degree_latitude_gap(self):
        self.assertEqual(haversine_km(6.0, 5.0, 7.0, 5.0), 111.19)

    def test_the_same_point_is_zero_km(self):
        self.assertEqual(haversine_km(6.33, 5.60, 6.33, 5.60), 0.0)

    def test_invalid_input_returns_none_instead_of_raising(self):
        self.assertIsNone(haversine_km("not-a-number", 5.0, 6.0, 5.0))


class GeocodeTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_a_successful_lookup_returns_coordinates_and_caches_them(self):
        with patch(_GEOCODE_PATCH_TARGET, return_value=[
            {"geometry": {"location": {"lat": 6.33, "lng": 5.60}}}
        ]) as mock_geocode:
            result = geocode("Ring Road, Benin City")
        self.assertEqual(result, {"lat": 6.33, "lng": 5.60})
        mock_geocode.assert_called_once()

        with patch(_GEOCODE_PATCH_TARGET) as mock_geocode_again:
            cached = geocode("Ring Road, Benin City")
        mock_geocode_again.assert_not_called()
        self.assertEqual(cached, {"lat": 6.33, "lng": 5.60})

    def test_an_empty_result_returns_none(self):
        with patch(_GEOCODE_PATCH_TARGET, return_value=[]):
            self.assertIsNone(geocode("Nowhere, Nowhere"))

    def test_an_exception_returns_none_instead_of_raising(self):
        with patch(_GEOCODE_PATCH_TARGET, side_effect=Exception("boom")):
            self.assertIsNone(geocode("Ring Road, Benin City"))


class GoogleDistanceTests(TestCase):
    def setUp(self):
        cache.clear()

    def _ok_result(self, meters, seconds):
        return {
            "status": "OK",
            "rows": [{"elements": [{
                "status": "OK",
                "distance": {"value": meters},
                "duration_in_traffic": {"value": seconds},
            }]}],
        }

    def test_an_ok_result_returns_km_and_minutes(self):
        with patch(_DISTANCE_MATRIX_PATCH_TARGET, return_value=self._ok_result(5000, 600)):
            distance_km, duration_min = google_distance("A", "B")
        self.assertEqual(distance_km, 5.0)
        self.assertEqual(duration_min, 10.0)

    def test_a_non_ok_top_level_status_returns_none_none(self):
        with patch(_DISTANCE_MATRIX_PATCH_TARGET, return_value={"status": "ZERO_RESULTS"}):
            self.assertEqual(google_distance("A", "B"), (None, None))

    def test_a_non_ok_element_status_returns_none_none(self):
        bad = {"status": "OK", "rows": [{"elements": [{"status": "NOT_FOUND"}]}]}
        with patch(_DISTANCE_MATRIX_PATCH_TARGET, return_value=bad):
            self.assertEqual(google_distance("A", "B"), (None, None))

    def test_an_exception_returns_none_none(self):
        with patch(_DISTANCE_MATRIX_PATCH_TARGET, side_effect=Exception("boom")):
            self.assertEqual(google_distance("A", "B"), (None, None))

    def test_a_result_is_cached_and_reused(self):
        with patch(_DISTANCE_MATRIX_PATCH_TARGET, return_value=self._ok_result(5000, 600)) as mock_dm:
            google_distance("A", "B")
        with patch(_DISTANCE_MATRIX_PATCH_TARGET) as mock_dm_again:
            result = google_distance("A", "B")
        mock_dm_again.assert_not_called()
        self.assertEqual(result, (5.0, 10.0))


class RouteWithCoordsTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_a_geocode_failure_short_circuits_to_all_none(self):
        with patch("gocabapp.utils.distance_utils.geocode", return_value=None):
            result = route_with_coords("Nowhere", "Somewhere")
        self.assertEqual(result, (None, None, None, None))

    def test_the_normal_path_passes_through_googles_numbers(self):
        with patch(
            "gocabapp.utils.distance_utils.geocode",
            side_effect=[{"lat": 6.33, "lng": 5.60}, {"lat": 6.335, "lng": 5.604}],
        ), patch(
            "gocabapp.utils.distance_utils.google_distance", return_value=(2.0, 6.0),
        ):
            distance_km, duration_min, pickup, dest = route_with_coords("A", "B")
        self.assertEqual(distance_km, 2.0)
        self.assertEqual(duration_min, 6.0)
        self.assertEqual(pickup, {"lat": 6.33, "lng": 5.60})

    def test_an_implausibly_short_driving_distance_is_corrected_to_an_estimate(self):
        """Documented sanity check: a driving distance under half the
        straight-line distance is almost certainly a bad Google reading
        (a ferry route, a data glitch), not a real shortcut — the
        function replaces it with straight_line * 1.2 instead of trusting it."""
        pickup = {"lat": 6.0, "lng": 5.0}
        dest = {"lat": 7.0, "lng": 5.0}  # 111.19km apart in a straight line
        with patch(
            "gocabapp.utils.distance_utils.geocode", side_effect=[pickup, dest],
        ), patch(
            # Implausible: Google claims only 10km driving distance for a
            # 111km straight-line gap.
            "gocabapp.utils.distance_utils.google_distance", return_value=(10.0, 15.0),
        ):
            distance_km, duration_min, _, _ = route_with_coords("A", "B")
        self.assertAlmostEqual(distance_km, round(111.19 * 1.2, 2))
        self.assertNotEqual(distance_km, 10.0)

    def test_a_plausible_driving_distance_is_left_alone(self):
        pickup = {"lat": 6.0, "lng": 5.0}
        dest = {"lat": 6.01, "lng": 5.0}  # ~1.1km straight line
        with patch(
            "gocabapp.utils.distance_utils.geocode", side_effect=[pickup, dest],
        ), patch(
            "gocabapp.utils.distance_utils.google_distance", return_value=(1.5, 3.0),
        ):
            distance_km, duration_min, _, _ = route_with_coords("A", "B")
        self.assertEqual(distance_km, 1.5)
        self.assertEqual(duration_min, 3.0)


class DetectCityTests(SimpleTestCase):
    def test_coordinates_inside_the_benin_box(self):
        self.assertEqual(detect_city(6.33, 5.60), "benin")

    def test_coordinates_inside_the_lagos_box(self):
        self.assertEqual(detect_city(6.5, 3.2), "lagos")

    def test_coordinates_outside_every_known_city(self):
        self.assertEqual(detect_city(0.0, 0.0), "unknown")
