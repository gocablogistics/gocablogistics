"""Tests written against what fare calculation is supposed to do, not
against whatever the code currently outputs — see calculate_ride_fare's
own docstring/comments for the stated rules being checked here.

The ₦10-rounding rule exists because of a real incident: ride #429 was
priced at ₦7,497, the rider's bank rejected the transfer as "wrong
amount" because it wasn't a round figure. test_total_is_always_a_multiple_of_ten
is the test that would have caught that before it ever reached a real
rider's bank app.
"""
from django.test import SimpleTestCase

from gocabapp.utils.fare_pricing import VEHICLE_RATES, calculate_ride_fare


class FareRoundingTests(SimpleTestCase):
    def test_total_is_always_a_multiple_of_ten(self):
        """The rule that exists specifically because a real bank transfer
        got rejected over this — ride #429, ₦7,497."""
        trips = [
            (1.0, 4.0), (3.3, 10.0), (7.7, 20.0), (10.2, 25.0),
            (19.36, 35.27), (25.5, 60.0), (0.4, 2.0), (60.0, 90.0),
        ]
        for distance_km, duration_min in trips:
            for vehicle_type in ("Bike", "Bicycle"):
                result = calculate_ride_fare(distance_km, duration_min, vehicle_type)
                self.assertEqual(
                    result["total_fare"] % 10, 0,
                    f"{vehicle_type} {distance_km}km/{duration_min}min gave "
                    f"₦{result['total_fare']}, not a multiple of 10",
                )

    def test_line_items_add_up_to_the_total(self):
        """The breakdown shown to the rider (base + distance + time) has to
        actually sum to the total charged — a rider comparing the numbers
        themselves should never find them not adding up."""
        result = calculate_ride_fare(10.2, 25.0, "Bike")
        self.assertEqual(
            result["base_fare"] + result["distance_fare"] + result["time_fare"],
            result["total_fare"],
        )

    def test_minimum_fare_is_respected(self):
        """A trip too short/quick to earn the per-km/per-min rate still
        charges at least the vehicle's stated minimum."""
        result = calculate_ride_fare(0.1, 0.5, "Bike")
        self.assertGreaterEqual(result["total_fare"], VEHICLE_RATES["Bike"]["min_fare"])

    def test_bicycle_is_cheaper_than_bike_for_the_same_trip(self):
        """Stated business rule: Bicycle prices ~20-23% below Bike."""
        bike = calculate_ride_fare(10.0, 25.0, "Bike")
        bicycle = calculate_ride_fare(10.0, 25.0, "Bicycle")
        self.assertLess(bicycle["total_fare"], bike["total_fare"])

    def test_unknown_vehicle_type_falls_back_to_bike_rates(self):
        """calculate_ride_fare's own fallback: an unrecognised vehicle_type
        shouldn't crash or silently charge ₦0, it falls back to Bike."""
        result = calculate_ride_fare(5.0, 15.0, "Spaceship")
        bike = calculate_ride_fare(5.0, 15.0, "Bike")
        self.assertEqual(result["total_fare"], bike["total_fare"])

    def test_total_never_negative(self):
        result = calculate_ride_fare(0.01, 0.01, "Bike")
        self.assertGreater(result["total_fare"], 0)

    def test_zero_distance_or_duration_returns_none_not_a_crash(self):
        """Documented behaviour (see the guard at the top of
        calculate_ride_fare): a 0/invalid distance or duration returns
        None rather than a bogus fare — callers are responsible for
        turning that into a clean error, not a crash. See
        test_estimate_fare_from_locations_handles_zero_distance_cleanly
        for the real incident this caught: the live fare-estimate
        endpoint didn't check for this and would have returned a
        misleading 200 with a null body, or crashed outright."""
        self.assertIsNone(calculate_ride_fare(0, 0, "Bike"))
        self.assertIsNone(calculate_ride_fare(5.0, 0, "Bike"))


class SurgePricingAddsUpTests(SimpleTestCase):
    """Specifically targets the bug a standards-based test caught on
    2026-10-07: surge was only ever applied to the final total, never to
    the displayed base/distance/time components, so the breakdown never
    matched the total on any surge-priced ride, not as a rare rounding
    edge case — on every single one."""

    def test_components_add_up_to_total_even_during_surge(self):
        from unittest.mock import patch
        with patch("gocabapp.utils.fare_pricing._surge_multiplier", return_value=1.1):
            result = calculate_ride_fare(10.2, 25.0, "Bike")
        self.assertEqual(
            result["base_fare"] + result["distance_fare"] + result["time_fare"],
            result["total_fare"],
        )

    def test_surge_actually_increases_the_total(self):
        from unittest.mock import patch
        with patch("gocabapp.utils.fare_pricing._surge_multiplier", return_value=1.0):
            normal = calculate_ride_fare(10.2, 25.0, "Bike")
        with patch("gocabapp.utils.fare_pricing._surge_multiplier", return_value=1.1):
            surged = calculate_ride_fare(10.2, 25.0, "Bike")
        self.assertGreater(surged["total_fare"], normal["total_fare"])
