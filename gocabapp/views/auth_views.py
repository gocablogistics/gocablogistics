from urllib.parse import urlencode

from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.contrib.auth import logout
from django.urls import reverse
from ninja.errors import HttpError
from pydantic import ValidationError as PydanticValidationError
from ..models import Rider, Driver
from ..forms import UpgradeToDriverForm
from ..api.auth import otp, services
from ..api.auth.cookies import REFRESH_COOKIE_NAME, clear_auth_cookies, set_auth_cookies
from ..api.auth.schemas import DriverRegisterIn, RiderRegisterIn

import logging
from django.views.decorators.csrf import csrf_exempt

logger = logging.getLogger(__name__)

from django.forms import BaseForm

DRIVER_DOCUMENT_FIELDS = [
    "drivers_license",
    "vehicle_insurance",
    "vehicle_registration",
    "roadworthiness_certificate",
    "proof_of_residency",
    "passport_photo",
]



def push_form_errors_to_messages(request, form: BaseForm) -> None:
    for field, errors in form.errors.items():
        field_name = field.replace("_", " ").title()
        for error in errors:
            messages.error(request, f"{field_name}: {error}")


def _push_pydantic_errors_to_messages(request, exc: PydanticValidationError) -> None:
    for error in exc.errors():
        field = str(error["loc"][-1]) if error["loc"] else "field"
        field_name = field.replace("_", " ").title()
        messages.error(request, f"{field_name}: {error['msg']}")


def resolve_active_role(request):
    """For a dual-role (rider+driver) account, which dashboard 'home' is
    currently pointed at. This is a UI preference only, stored in the
    session and set via switch_role() below — it does not affect what the
    account is authorized to do; that's still governed entirely by which
    Rider/Driver profiles exist, same as the JWT API's role resolution in
    gocabapp.api.auth.services.resolve_role_and_profile."""
    user = request.user
    has_driver = hasattr(user, "driver")
    has_rider = hasattr(user, "rider")

    if has_driver and has_rider:
        active = request.session.get("active_role")
        if active not in ("driver", "rider"):
            active = "driver"
            request.session["active_role"] = active
        return active
    if has_driver:
        return "driver"
    if has_rider:
        return "rider"
    return None


def _verify_registration(email: str, code: str, verified_token: str) -> None:
    """A signup POST proves its email either the normal way (a fresh code
    entered on this form) or via a verified_token handed off from the
    homepage's single email step (see home()), which already consumed a
    code for this same email — whichever the form actually carries."""
    if verified_token:
        otp.consume_verified_token(verified_token, email)
    else:
        otp.verify_code(email, code)


