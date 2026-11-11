"""Coverage for POST /auth/register/driver — previously untested at any
level. Focuses on what's unique to this endpoint versus register/rider:
the multipart file-upload size/type validation, the Bike-only required
fields, and that a successful registration does NOT issue tokens (an
unapproved driver can't log in yet)."""
import datetime
import re

from django.contrib.auth.models import User
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from gocabapp.api.auth import otp
from gocabapp.models import Driver

_VALID_IMAGE = b"\xff\xd8\xff" + b"0" * 100  # content bytes don't matter, only size/content_type do here


def _real_code(email: str) -> str:
    otp.send_code(email)
    body = mail.outbox[-1].body
    match = re.search(r"\b\d{6}\b", body)
    return match.group()


def _valid_form(email: str, **overrides) -> dict:
    form = {
        "full_name": "New Driver",
        "email": email,
        "phone_number": "+2348100000010",
        "code": _real_code(email),
        "date_of_birth": "1995-01-01",
        "national_identification_number": "REGDRVNIN1",
        "vehicle_type": "Bike",
        "vehicle_color": "Black",
        "vehicle_model": "Honda",
        "vehicle_brand": "Honda",
        "production_year": "2020",
        "license_plate": "XYZ-999",
        "bank_name": "Test Bank",
        "account_number": "1234567890",
        "account_holder_name": "New Driver",
        "latitude": "6.33",
        "longitude": "5.60",
    }
    form.update(overrides)
    return form


def _valid_files() -> dict:
    return {
        "drivers_license": SimpleUploadedFile("license.jpg", _VALID_IMAGE, content_type="image/jpeg"),
        "passport_photo": SimpleUploadedFile("selfie.jpg", _VALID_IMAGE, content_type="image/jpeg"),
        "nin_slip_photo": SimpleUploadedFile("nin.jpg", _VALID_IMAGE, content_type="image/jpeg"),
        "vehicle_picture": SimpleUploadedFile("vehicle.jpg", _VALID_IMAGE, content_type="image/jpeg"),
    }


class DriverRegistrationTests(TestCase):
    def test_a_valid_registration_creates_an_unapproved_driver_with_no_tokens(self):
        email = "newdriver1@example.com"
        response = self.client.post(
            "/api/v1/auth/register/driver",
            data={**_valid_form(email), **_valid_files()},
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("access", response.json())
        driver = Driver.objects.get(user__email=email)
        self.assertFalse(driver.is_approved)

    def test_missing_verification_code_is_rejected(self):
        email = "newdriver2@example.com"
        form = _valid_form(email)
        form.pop("code")
        response = self.client.post(
            "/api/v1/auth/register/driver", data={**form, **_valid_files()},
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Driver.objects.filter(user__email=email).exists())

    def test_an_oversized_upload_is_rejected(self):
        email = "newdriver3@example.com"
        files = _valid_files()
        files["passport_photo"] = SimpleUploadedFile(
            "huge.jpg", b"0" * (8 * 1024 * 1024 + 1), content_type="image/jpeg",
        )
        response = self.client.post(
            "/api/v1/auth/register/driver", data={**_valid_form(email), **files},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("8MB", response.json()["detail"])

    def test_a_disallowed_file_type_is_rejected(self):
        email = "newdriver4@example.com"
        files = _valid_files()
        files["vehicle_picture"] = SimpleUploadedFile(
            "vehicle.txt", b"not an image", content_type="text/plain",
        )
        response = self.client.post(
            "/api/v1/auth/register/driver", data={**_valid_form(email), **files},
        )
        self.assertEqual(response.status_code, 400)

    def test_a_bike_missing_its_required_vehicle_fields_is_rejected(self):
        email = "newdriver5@example.com"
        form = _valid_form(email)
        form.pop("vehicle_model")
        response = self.client.post(
            "/api/v1/auth/register/driver", data={**form, **_valid_files()},
        )
        self.assertEqual(response.status_code, 422)
        self.assertFalse(Driver.objects.filter(user__email=email).exists())

    def test_a_bicycle_does_not_need_the_bike_only_fields(self):
        email = "newdriver6@example.com"
        form = _valid_form(email, vehicle_type="Bicycle")
        # Omitted entirely, not set to "" — these are Optional fields, and
        # an empty multipart string fails int/str-length coercion the same
        # way a genuinely missing field wouldn't.
        for field in ("vehicle_model", "vehicle_brand", "production_year", "license_plate"):
            form.pop(field)
        response = self.client.post(
            "/api/v1/auth/register/driver", data={**form, **_valid_files()},
        )
        self.assertEqual(response.status_code, 200)

    def test_duplicate_phone_number_is_rejected(self):
        existing = User.objects.create_user(username="+2348100000010", email="existing@example.com")
        Driver.objects.create(
            user=existing, full_name="Existing Driver", phone_number="+2348100000010",
            date_of_birth=datetime.date(1990, 1, 1), vehicle_type="Bike",
            national_identification_number="EXISTINGNIN", bank_name="Old Bank",
            account_number="0000000000", account_holder_name="Existing Driver",
        )
        email = "newdriver7@example.com"
        response = self.client.post(
            "/api/v1/auth/register/driver", data={**_valid_form(email), **_valid_files()},
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Driver.objects.filter(user__email=email).exists())
