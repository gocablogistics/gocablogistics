"""Tests against the stated one-time-code rules in otp.py's own
docstrings/comments: a code works exactly once, a wrong guess doesn't
burn the real code, and too many wrong guesses locks it out entirely."""
import re

from django.core import mail
from django.core.cache import cache
from django.test import SimpleTestCase
from ninja.errors import HttpError

from gocabapp.api.auth import otp


class OtpTests(SimpleTestCase):
    def setUp(self):
        cache.clear()

    def _sent_code(self, email: str) -> str:
        """send_code only emails the code, it never returns it — pull it
        out of the actual email that was sent, the same way a real rider
        would read it off their inbox. Deliberately not reaching into
        otp.py's cache/hash internals: this way the test only depends on
        the real, user-visible contract (a 6-digit code arrives by
        email), not on how the code happens to be stored server-side."""
        otp.send_code(email)
        body = mail.outbox[-1].body
        match = re.search(r"\b\d{6}\b", body)
        if not match:
            raise AssertionError(f"no 6-digit code found in sent email body: {body!r}")
        return match.group()

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
