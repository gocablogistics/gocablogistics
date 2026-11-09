"""estimate_fare_from_locations is the function behind the live,
public fare-estimate endpoint real riders hit before booking. A real
bug lived here: if the route came back as 0 distance/duration (same
pickup and destination, or a Google Maps edge case), it returned
(None, 200) — a "success" response with no actual fare, which the
Ninja endpoint then tried to add a "quote" key to, crashing outright.
"""
from unittest.mock import patch

from django.test import SimpleTestCase

from gocabapp.services.payment_service import estimate_fare_from_locations


class EstimateFareFromLocationsTests(SimpleTestCase):
    def test_zero_distance_route_returns_a_clean_error_not_none(self):
        with patch(
            "gocabapp.services.payment_service.google_distance",
            return_value=(0, 0),
        ):
            body, status = estimate_fare_from_locations("Same Place", "Same Place", "Bike")
        self.assertEqual(status, 400)
        self.assertIn("error", body)

    def test_normal_route_returns_a_real_fare(self):
        with patch(
            "gocabapp.services.payment_service.google_distance",
            return_value=(10.2, 25.0),
        ):
            body, status = estimate_fare_from_locations("A", "B", "Bike")
        self.assertEqual(status, 200)
        self.assertIn("total_fare", body)
        self.assertGreater(body["total_fare"], 0)
