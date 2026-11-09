"""Tests against the stated one-time-code rules in otp.py's own
docstrings/comments: a code works exactly once, a wrong guess doesn't
burn the real code, and too many wrong guesses locks it out entirely."""
from django.core.cache import cache
from django.test import SimpleTestCase
from ninja.errors import HttpError

from gocabapp.api.auth import otp


class OtpTests(SimpleTestCase):
    def setUp(self):
        cache.clear()

    def _sent_code(self, email: str) -> str:
        """send_code only emails the code, it never returns it — pull the
        real code back out of the cache the same way verify_code checks
        it, by brute-forcing against the stored hash. Fine for a test;
        otp.py's own comment confirms this isn't meant to resist that."""
        otp.send_code(email)
        entry = cache.get(otp._cache_key(email))
        for guess in range(1_000_000):
            code = f"{guess:06d}"
            if otp._hash_code(email, code) == entry["hash"]:
                return code
        raise AssertionError("could not recover the sent code")

    def test_correct_code_verifies(self):
        code = self._sent_code("rider@example.com")
        otp.verify_code("rider@example.com", code)  # must not raise

    def test_code_cannot_be_replayed(self):
        """A code must work exactly once — reusing it must fail even
        though it was correct the first time."""
        code = self._sent_code("rider@example.com")
        otp.verify_code("rider@example.com", code)
        with self.assertRaises(HttpError):
            otp.verify_code("rider@example.com", code)

    def test_wrong_code_does_not_burn_the_real_code(self):
        """One incorrect guess shouldn't invalidate the real code — the
        rider should still be able to enter the right one right after a
        typo, up to the attempt limit."""
        code = self._sent_code("rider@example.com")
        with self.assertRaises(HttpError):
            otp.verify_code("rider@example.com", "000000")
        otp.verify_code("rider@example.com", code)  # still works

    def test_too_many_wrong_guesses_locks_it_out(self):
        """otp.MAX_ATTEMPTS wrong guesses in a row must lock the code out
        entirely — the correct code must stop working, not just keep
        allowing unlimited retries."""
        code = self._sent_code("rider@example.com")
        for _ in range(otp.MAX_ATTEMPTS):
            with self.assertRaises(HttpError):
                otp.verify_code("rider@example.com", "000000")
        with self.assertRaises(HttpError):
            otp.verify_code("rider@example.com", code)

    def test_code_is_scoped_to_its_own_email(self):
        """A code sent to one address must not verify for a different
        one, even as a coincidence — the hash is peppered with the email
        specifically to guarantee this."""
        code = self._sent_code("rider@example.com")
        with self.assertRaises(HttpError):
            otp.verify_code("someone-else@example.com", code)
