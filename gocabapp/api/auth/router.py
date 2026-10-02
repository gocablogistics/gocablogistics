from django.conf import settings
from django.contrib.auth.models import User
from django.http import JsonResponse
from ninja import File, Form, Router
from ninja.errors import HttpError
from ninja.files import UploadedFile
from ninja_jwt.authentication import JWTAuth

from . import otp, services
from .schemas import (
    DriverRegisterIn,
    MessageOut,
    RefreshIn,
    RefreshOut,
    RequestCodeIn,
    RiderRegisterIn,
    TokenPairOut,
    UserOut,
    VerifyCodeIn,
)
from .throttle import throttle
from .utils import get_client_ip

router = Router(tags=["auth"])

# Nothing validated file size/type on driver document uploads before this —
# an applicant (malicious or just fumbling a huge phone photo/video) could
# push arbitrarily large or wrong-type files into storage with no pushback.
MAX_UPLOAD_SIZE_BYTES = 8 * 1024 * 1024
ALLOWED_UPLOAD_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp", "image/heic", "image/heif"}


def _validate_upload(file: UploadedFile, label: str) -> None:
    if file.size and file.size > MAX_UPLOAD_SIZE_BYTES:
        raise HttpError(400, f"{label} must be under {MAX_UPLOAD_SIZE_BYTES // (1024 * 1024)}MB.")
    if file.content_type not in ALLOWED_UPLOAD_CONTENT_TYPES:
        raise HttpError(400, f"{label} must be a JPEG, PNG, WEBP, or HEIC image.")


def _token_pair_response(refresh, user, role, profile) -> dict:
    return {
        "access": str(refresh.access_token),
        "refresh": str(refresh),
        "token_type": "bearer",
        "user": services.user_out_payload(user, role, profile),
    }


@router.post("/request-code", response=MessageOut)
def request_code(request, payload: RequestCodeIn):
    code_limit_message = "You've requested too many codes. Please wait a few minutes and try again."
    throttle(
        f"throttle:request-code:ip:{get_client_ip(request)}",
        settings.AUTH_THROTTLE_CODE_LIMIT,
        settings.AUTH_THROTTLE_CODE_WINDOW_SECONDS,
        message=code_limit_message,
    )
    throttle(
        f"throttle:request-code:email:{payload.email.lower()}",
        settings.AUTH_THROTTLE_CODE_LIMIT,
        settings.AUTH_THROTTLE_CODE_WINDOW_SECONDS,
        message=code_limit_message,
    )
    otp.send_code(payload.email)
    return {"detail": f"A verification code has been sent to {payload.email}."}


@router.post("/verify-code", response=TokenPairOut)
def verify_code(request, payload: VerifyCodeIn):
    throttle(
        f"throttle:verify-code:ip:{get_client_ip(request)}",
        settings.AUTH_THROTTLE_LOGIN_LIMIT,
        settings.AUTH_THROTTLE_LOGIN_WINDOW_SECONDS,
        message="Too many incorrect code attempts. Please wait a few minutes and try again.",
    )
    otp.verify_code(payload.email, payload.code)

    if not User.objects.filter(email__iexact=payload.email).exists():
        # The OTP check above already proved this person owns the email —
        # a new user routed on to /signup from here shouldn't have to
        # enter another code just to prove the same thing twice. Hand back
        # a short-lived verified_token the signup endpoint can accept
        # instead of a fresh code.
        token = otp.issue_verified_token(payload.email)
        return JsonResponse(
            {"detail": "No account found with that email. Please sign up.", "verified_token": token},
            status=404,
        )

    user, role, profile = services.authenticate_by_email(payload.email)
    refresh = services.issue_token_pair(user, role)
    return _token_pair_response(refresh, user, role, profile)


@router.post("/register/rider", response=TokenPairOut)
def register_rider(request, payload: RiderRegisterIn):
    throttle(
        f"throttle:register:ip:{get_client_ip(request)}",
        settings.AUTH_THROTTLE_REGISTER_LIMIT,
        settings.AUTH_THROTTLE_REGISTER_WINDOW_SECONDS,
        message="You've hit the limit for registration attempts from this connection. Please wait a bit and try again.",
    )
    if payload.verified_token:
        otp.consume_verified_token(payload.verified_token, payload.email)
    elif payload.code:
        otp.verify_code(payload.email, payload.code)
    else:
        raise HttpError(400, "Verification code is required.")
    user = services.create_rider(payload)
    role, profile = services.resolve_role_and_profile(user)
    refresh = services.issue_token_pair(user, role)
    return _token_pair_response(refresh, user, role, profile)


@router.post("/register/driver", response=MessageOut)
def register_driver(
    request,
    payload: Form[DriverRegisterIn],
    drivers_license: File[UploadedFile],
    passport_photo: File[UploadedFile],
    nin_slip_photo: File[UploadedFile],
    vehicle_picture: File[UploadedFile],
):
    throttle(
        f"throttle:register:ip:{get_client_ip(request)}",
        settings.AUTH_THROTTLE_REGISTER_LIMIT,
        settings.AUTH_THROTTLE_REGISTER_WINDOW_SECONDS,
        message="You've hit the limit for registration attempts from this connection. Please wait a bit and try again.",
    )
    if payload.verified_token:
        otp.consume_verified_token(payload.verified_token, payload.email)
    elif payload.code:
        otp.verify_code(payload.email, payload.code)
    else:
        raise HttpError(400, "Verification code is required.")

    _validate_upload(drivers_license, "Driver's license")
    _validate_upload(passport_photo, "Selfie")
    _validate_upload(nin_slip_photo, "NIN slip photo")
    _validate_upload(vehicle_picture, "Vehicle picture")

    # No tokens issued here — a Driver starts unapproved (is_approved=False)
    # and can't authenticate until an admin approves the account, same as
    # the legacy become_a_driver() view.
    services.create_driver(
        payload,
        {
            "drivers_license": drivers_license,
            "passport_photo": passport_photo,
            "nin_slip_photo": nin_slip_photo,
            "vehicle_picture": vehicle_picture,
        },
    )
    return {"detail": "Registration successful. Awaiting admin approval, usually within 30 minutes."}


@router.post("/refresh", response=RefreshOut)
def refresh_token(request, payload: RefreshIn):
    new_refresh = services.rotate_refresh_token(payload.refresh)
    return {
        "access": str(new_refresh.access_token),
        "refresh": str(new_refresh),
        "token_type": "bearer",
    }


@router.post("/logout", response=MessageOut)
def logout(request, payload: RefreshIn):
    services.blacklist_refresh_token(payload.refresh)
    return {"detail": "Logged out."}


@router.get("/me", response=UserOut, auth=JWTAuth())
def me(request):
    role, profile = services.resolve_role_and_profile(request.user)
    if role is None:
        raise HttpError(404, "No rider or driver profile found for this account.")
    return services.user_out_payload(request.user, role, profile)


@router.post("/delete-account", response=MessageOut, auth=JWTAuth())
def delete_account(request):
    body, status = services.deactivate_account(request.user)
    if status != 200:
        raise HttpError(status, body["error"])
    return {"detail": body["message"]}


@router.post("/switch-role/{role}", response=TokenPairOut, auth=JWTAuth())
def switch_role(request, role: str):
    # Mirrors the web app's account-menu role switcher (gocabapp.views.
    # auth_views.switch_role) for dual-role accounts — mints a fresh token
    # pair scoped to the other role rather than a session flag, since
    # mobile clients don't have a Django session to store it in.
    if role not in ("rider", "driver"):
        raise HttpError(400, "role must be 'rider' or 'driver'.")
    if not hasattr(request.user, role):
        raise HttpError(403, f"This account has no {role} profile.")

    profile = getattr(request.user, role)
    refresh = services.issue_token_pair(request.user, role)
    return _token_pair_response(refresh, request.user, role, profile)
