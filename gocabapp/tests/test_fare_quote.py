"""Tests against the documented rules in utils/fare_quote.py: a quote
locks in the price shown at estimate time so surge/route recalculation
between estimate and booking doesn't silently change what's charged —
but it must be genuinely tamper-proof (HMAC-signed with SECRET_KEY, not
just obscured), scoped to the exact route+vehicle it was issued for, and
never honored past a sane staleness point without at least checking the
price hasn't moved."""
import time
from django.core import signing
from django.test import TestCase, override_settings
from ninja.errors import HttpError

from gocabapp.utils.fare_quote import make_fare_quote, resolve_fare


class FareQuoteRoundTripTests(TestCase):
    def test_a_matching_unexpired_quote_is_honored_even_if_the_fresh_fare_differs(self):
        """The whole point of locking a quote — surge moved the fresh
        fare up, but the rider booked within the window, so they get
        exactly what they were shown."""
        quote = make_fare_quote("A", "B", 1000.0, "Bike")
        fare = resolve_fare(quote, "A", "B", "Bike", fresh_fare=1500.0)
        self.assertEqual(fare, 1000.0)

    def test_no_quote_uses_the_fresh_fare(self):
        fare = resolve_fare(None, "A", "B", "Bike", fresh_fare=1234.0)
        self.assertEqual(fare, 1234.0)


class FareQuoteTamperResistanceTests(TestCase):
    def test_a_quote_signed_with_a_different_salt_is_rejected(self):
        """Simulates a forged quote — anything not signed with this
        exact salt/key must fall back to the fresh fare, not be trusted."""
        forged = signing.dumps(
            {"p": "A", "d": "B", "f": 1.0, "v": "Bike"}, salt="not-the-real-salt"
        )
        fare = resolve_fare(forged, "A", "B", "Bike", fresh_fare=5000.0)
        self.assertEqual(fare, 5000.0)

    def test_a_truncated_quote_string_is_rejected(self):
        quote = make_fare_quote("A", "B", 1000.0, "Bike")
        tampered = quote[:-5]  # corrupt the signature portion
        fare = resolve_fare(tampered, "A", "B", "Bike", fresh_fare=5000.0)
        self.assertEqual(fare, 5000.0)

    def test_garbage_input_is_rejected_not_crashed_on(self):
        fare = resolve_fare("not-a-real-quote-at-all", "A", "B", "Bike", fresh_fare=5000.0)
        self.assertEqual(fare, 5000.0)

    def test_quote_for_a_different_route_is_not_honored(self):
        """A quote for A→B must never be reusable to lock a price on a
        completely different, possibly more expensive, C→D route."""
        quote = make_fare_quote("A", "B", 500.0, "Bike")
        fare = resolve_fare(quote, "C", "D", "Bike", fresh_fare=5000.0)
        self.assertEqual(fare, 5000.0)

    def test_quote_for_a_different_vehicle_type_is_not_honored(self):
        quote = make_fare_quote("A", "B", 500.0, "Bicycle")
        fare = resolve_fare(quote, "A", "B", "Bike", fresh_fare=1500.0)
        self.assertEqual(fare, 1500.0)


@override_settings(FARE_QUOTE_MAX_AGE_SECONDS=1)
class FareQuoteExpiryTests(TestCase):
    def test_expired_quote_still_honored_if_the_price_has_not_really_moved(self):
        quote = make_fare_quote("A", "B", 1000.0, "Bike")
        time.sleep(1.2)
        fare = resolve_fare(quote, "A", "B", "Bike", fresh_fare=1000.5)  # within ₦1
        self.assertEqual(fare, 1000.0)

    def test_expired_quote_with_a_real_price_change_asks_for_a_new_estimate(self):
        quote = make_fare_quote("A", "B", 1000.0, "Bike")
        time.sleep(1.2)
        with self.assertRaises(HttpError) as ctx:
            resolve_fare(quote, "A", "B", "Bike", fresh_fare=2000.0)
        self.assertEqual(ctx.exception.status_code, 409)

    def test_expired_quote_for_a_different_route_falls_back_cleanly(self):
        quote = make_fare_quote("A", "B", 1000.0, "Bike")
        time.sleep(1.2)
        fare = resolve_fare(quote, "C", "D", "Bike", fresh_fare=2000.0)
        self.assertEqual(fare, 2000.0)
