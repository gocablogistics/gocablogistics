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


@login_required(login_url="home")
def switch_role(request, role):
    if role not in ("rider", "driver") or not hasattr(request.user, role):
        messages.error(request, "You don't have that account type set up.")
        return redirect("home")

    request.session["active_role"] = role
    return redirect("home")


def home(request):
    # The homepage IS the auth entry point (Uber's single phone-number-first
    # screen, adapted to email) — one email field handles both sign-in and
    # sign-up. The email step itself is handled client-side by home.html
    # calling /api/v1/auth/request-code directly; this view only ever
    # receives the final POST (email + code).
    if request.user.is_authenticated:
        try:
            active_role = resolve_active_role(request)
        except Exception as e:
            logger.error(f"Profile detection error for {request.user}: {e}")
            active_role = None

        if active_role == "driver":
            return redirect("driver_dashboard")
        elif active_role == "rider":
            return redirect("rider_dashboard")

    if request.method == "POST":
        email = request.POST.get("email", "").strip()
        code = request.POST.get("code", "").strip()

        try:
            otp.verify_code(email, code)
        except HttpError as exc:
            messages.error(request, exc.message)
            return render(request, "home.html", {"email": email})

        try:
            user, role, profile = services.authenticate_by_email(email)
        except HttpError as exc:
            if exc.status_code == 404:
                # Email is verified but no account exists yet — hand off to
                # the full signup form. It carries a verified_token instead
                # of re-sending a code (this one's already been consumed).
                token = otp.issue_verified_token(email)
                query = urlencode({"email": email, "vtoken": token})
                return redirect(f"{reverse('signup')}?{query}")

            messages.error(request, exc.message)
            return render(request, "home.html", {"email": email})

        refresh = services.issue_token_pair(user, role)
        response = redirect("driver_dashboard" if role == "driver" else "rider_dashboard")
        set_auth_cookies(response, access=str(refresh.access_token), refresh=str(refresh))
        return response

    return render(request, "home.html")


def _verify_registration(email: str, code: str, verified_token: str) -> None:
    """A signup POST proves its email either the normal way (a fresh code
    entered on this form) or via a verified_token handed off from the
    homepage's single email step (see home()), which already consumed a
    code for this same email — whichever the form actually carries."""
    if verified_token:
        otp.consume_verified_token(verified_token, email)
    else:
        otp.verify_code(email, code)


def signup(request, default_role="rider"):
    # One signup entry point for both roles, going through the same
    # gocabapp.api.auth.services + schemas the JSON API uses — the role
    # toggle in signup.html just picks which schema/service function this
    # view calls. Legacy get-a-ride/become-a-driver URLs still work; they
    # just pre-select a role via default_role (see urls.py).
    role = request.POST.get("role") or request.GET.get("role") or default_role
    if role not in ("rider", "driver"):
        role = "rider"

    if request.method != "POST":
        return render(
            request,
            "signup.html",
            {
                "role": role,
                "prefill_email": request.GET.get("email", ""),
                "verified_token": request.GET.get("vtoken", ""),
            },
        )

    verified_token = request.POST.get("verified_token", "")

    if role == "driver":
        missing_docs = [f for f in DRIVER_DOCUMENT_FIELDS if f not in request.FILES]
        if missing_docs:
            messages.error(request, "Please upload all required documents.")
            return render(request, "signup.html", {"role": role})

        try:
            data = DriverRegisterIn(
                full_name=request.POST.get("full_name", ""),
                email=request.POST.get("email", ""),
                phone_number=request.POST.get("phone_number", ""),
                code=request.POST.get("code") or None,
                date_of_birth=request.POST.get("date_of_birth", ""),
                national_identification_number=request.POST.get(
                    "national_identification_number", ""
                ),
                vehicle_type=request.POST.get("vehicle_type", ""),
                vehicle_model=request.POST.get("vehicle_model", ""),
                license_plate=request.POST.get("license_plate", ""),
                bank_name=request.POST.get("bank_name", ""),
                account_number=request.POST.get("account_number", ""),
                account_holder_name=request.POST.get("account_holder_name", ""),
                latitude=float(request.POST.get("latitude") or 0),
                longitude=float(request.POST.get("longitude") or 0),
                current_address=request.POST.get("current_address", ""),
            )
        except (PydanticValidationError, ValueError) as exc:
            if isinstance(exc, PydanticValidationError):
                _push_pydantic_errors_to_messages(request, exc)
            else:
                messages.error(request, "Please check your location and try again.")
            return render(request, "signup.html", {"role": role})

        files = {f: request.FILES[f] for f in DRIVER_DOCUMENT_FIELDS}

        try:
            _verify_registration(data.email, data.code or "", verified_token)
            services.create_driver(data, files)
        except HttpError as exc:
            messages.error(request, exc.message)
            return render(request, "signup.html", {"role": role})

        messages.success(
            request,
            "Application submitted! Awaiting admin approval. You'll be able to "
            "log in once approved.",
        )
        return redirect("signin")

    # role == "rider"
    try:
        data = RiderRegisterIn(
            full_name=request.POST.get("full_name", ""),
            phone_number=request.POST.get("phone_number", ""),
            email=request.POST.get("email", ""),
            address=request.POST.get("address") or None,
            code=request.POST.get("code") or None,
        )
    except PydanticValidationError as exc:
        _push_pydantic_errors_to_messages(request, exc)
        return render(request, "signup.html", {"role": role})

    try:
        _verify_registration(data.email, data.code or "", verified_token)
        user = services.create_rider(data)
    except HttpError as exc:
        messages.error(request, exc.message)
        return render(request, "signup.html", {"role": role})

    user_role, _profile = services.resolve_role_and_profile(user)
    refresh = services.issue_token_pair(user, user_role)
    response = redirect("rider_dashboard")
    set_auth_cookies(response, access=str(refresh.access_token), refresh=str(refresh))
    return response


@csrf_exempt
def upgrade_to_driver(request):
    user = request.user
    if not user.is_authenticated:
        messages.error(request, "You must be logged in to access this page.")
        return redirect("signin")
    if request.method == "POST":
        form = UpgradeToDriverForm(request.POST, request.FILES, user=user)
    else:
        form = UpgradeToDriverForm(user=user)
    if form.is_valid():
        try:
            Driver.objects.create(
                user=user,
                full_name=form.cleaned_data["full_name"],
                phone_number=form.cleaned_data["phone_number"],
                date_of_birth=form.cleaned_data["date_of_birth"],
                vehicle_type=form.cleaned_data["vehicle_type"],
                vehicle_model=form.cleaned_data["vehicle_model"],
                drivers_license=form.cleaned_data["drivers_license"],
                vehicle_insurance=form.cleaned_data["vehicle_insurance"],
                vehicle_registration=form.cleaned_data["vehicle_registration"],
                roadworthiness_certificate=form.cleaned_data[
                    "roadworthiness_certificate"
                ],
                national_identification_number=form.cleaned_data[
                    "national_identification_number"
                ],
                proof_of_residency=form.cleaned_data["proof_of_residency"],
                passport_photo=form.cleaned_data["passport_photo"],
                bank_name=form.cleaned_data["bank_name"],
                account_number=form.cleaned_data["account_number"],
                account_holder_name=form.cleaned_data["account_holder_name"],
                is_approved=False,
            )
            messages.success(request, "Upgrade successful! Awaiting admin approval.")
            return redirect("driver_dashboard")
        except Rider.DoesNotExist:
            messages.error(request, "You are not registered as a Rider.")
        except Exception as e:
            messages.error(request, f"An error occurred: {str(e)}")
    return render(request, "upgrade-to-driver.html", {"form": form})


def signin(request):
    # Delegates to the same gocabapp.api.auth.services/otp modules the JSON
    # API uses so web and mobile share one auth codepath — this view's only
    # job is translating a classic form POST into those calls and the
    # resulting JWT pair into httpOnly cookies (mobile gets the same pair in
    # the response body instead, via /api/v1/auth/verify-code). See
    # gocabapp.middleware.JWTCookieAuthenticationMiddleware for how those
    # cookies turn back into request.user on later requests.
    #
    # The email step (request-code) is handled client-side by signin.html
    # calling /api/v1/auth/request-code directly — this view only ever
    # receives the final verify step (email + code) as a POST.
    if request.method == "POST":
        email = request.POST.get("email", "").strip()
        code = request.POST.get("code", "").strip()

        try:
            otp.verify_code(email, code)
            user, role, profile = services.authenticate_by_email(email)
        except HttpError as exc:
            messages.error(request, exc.message)
            return render(request, "signin.html")

        refresh = services.issue_token_pair(user, role)
        response = redirect("driver_dashboard" if role == "driver" else "rider_dashboard")
        set_auth_cookies(response, access=str(refresh.access_token), refresh=str(refresh))
        return response

    return render(request, "signin.html")


def logout_view(request):
    refresh_str = request.COOKIES.get(REFRESH_COOKIE_NAME)
    if refresh_str:
        services.blacklist_refresh_token(refresh_str)

    logout(request)
    response = redirect("signin")
    clear_auth_cookies(response)
    return response
