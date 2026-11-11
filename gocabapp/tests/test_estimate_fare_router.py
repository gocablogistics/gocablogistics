"""Coverage for POST /rides/estimate-fare at the HTTP layer — the
underlying estimate_fare_from_locations function already has direct unit
coverage in test_estimate_fare.py. This file is for what only exists at
the router layer: it's deliberately public (no auth), rate-limited per
IP since it calls a paid Google API, and signs a fare_quote onto a
successful response for /rides/request to later honor."""
import json
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase, override_settings

_GOOGLE_DISTANCE_PATCH_TARGET = "gocabapp.services.payment_service.google_distance"


class EstimateFareRouterTests(TestCase):
    def setUp(self):
        # The throttle counter is keyed only by client IP, not by test —
        # without clearing it, an earlier test's calls in this same file
        # would silently count towards test_is_throttled_per_ip_after_the_limit's
        # budget, making it flaky depending on test execution order.
        cache.clear()

    def test_works_with_no_auth_at_all(self):
        with patch(_GOOGLE_DISTANCE_PATCH_TARGET, return_value=(10.0, 20.0)):
            response = self.client.post(
                "/api/v1/rides/estimate-fare",
                data=json.dumps({"pickup": "A", "destination": "B", "vehicle_type": "Bike"}),
                content_type="application/json",
            )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertGreater(body["total_fare"], 0)

    def test_response_carries_a_signed_quote(self):
        with patch(_GOOGLE_DISTANCE_PATCH_TARGET, return_value=(10.0, 20.0)):
            response = self.client.post(
                "/api/v1/rides/estimate-fare",
                data=json.dumps({"pickup": "A", "destination": "B", "vehicle_type": "Bike"}),
                content_type="application/json",
            )
        self.assertIsNotNone(response.json()["quote"])

    def test_an_unestimatable_route_is_a_clean_400(self):
        with patch(_GOOGLE_DISTANCE_PATCH_TARGET, return_value=(0, 0)):
            response = self.client.post(
                "/api/v1/rides/estimate-fare",
                data=json.dumps({"pickup": "Same", "destination": "Same", "vehicle_type": "Bike"}),
                content_type="application/json",
            )
        self.assertEqual(response.status_code, 400)

    @override_settings(FARE_ESTIMATE_THROTTLE_LIMIT=2, FARE_ESTIMATE_THROTTLE_WINDOW_SECONDS=300)
    def test_is_throttled_per_ip_after_the_limit(self):
        with patch(_GOOGLE_DISTANCE_PATCH_TARGET, return_value=(10.0, 20.0)):
            for _ in range(2):
                response = self.client.post(
                    "/api/v1/rides/estimate-fare",
                    data=json.dumps({"pickup": "A", "destination": "B", "vehicle_type": "Bike"}),
                    content_type="application/json",
                )
                self.assertEqual(response.status_code, 200)
            throttled = self.client.post(
                "/api/v1/rides/estimate-fare",
                data=json.dumps({"pickup": "A", "destination": "B", "vehicle_type": "Bike"}),
                content_type="application/json",
            )
        self.assertEqual(throttled.status_code, 429)
