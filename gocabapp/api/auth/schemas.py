from datetime import date
from typing import Optional

from ninja import Schema
from pydantic import EmailStr, Field, field_validator, model_validator

from .utils import normalize_phone_number


def _validate_code(v: Optional[str]) -> Optional[str]:
    if v is None or v == "":
        return None
    v = v.strip()
    if not v.isdigit() or len(v) != 6:
        raise ValueError("Enter the 6-digit code.")
    return v


class RiderRegisterIn(Schema):
    # Mirrors Rider model column sizes — same reasoning as DriverRegisterIn
    # above, closing the same class of bug on this side too.
    full_name: str = Field(max_length=255)
    phone_number: str
    email: EmailStr
    address: Optional[str] = Field(default=None, max_length=255)
    # Captured from the signup wizard's location-permission step, if the
    # rider granted it — optional since a rider can still sign up having
    # denied/skipped that prompt.
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    # Either a fresh code, or a verified_token from an email already proven
    # via /verify-code (e.g. the login page's new-user redirect) — exactly
    # one is required, enforced in router.register_rider.
    code: Optional[str] = None
    verified_token: Optional[str] = None
    # Optional — another rider's Rider.referral_code. Validated/consumed in
    # services.create_rider; a code that doesn't match anyone is rejected
    # with a clear error rather than silently ignored, so a typo doesn't
    # quietly cost the referrer their reward.
    referral_code: Optional[str] = Field(default=None, max_length=8)

    @field_validator("phone_number")
    @classmethod
    def _normalize_phone(cls, v: str) -> str:
        return normalize_phone_number(v)

    @field_validator("full_name")
    @classmethod
    def _strip_full_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Full name is required")
        return v

    @field_validator("referral_code")
    @classmethod
    def _normalize_referral_code(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        v = v.strip().upper()
        return v or None

    @field_validator("code")
    @classmethod
    def _check_code(cls, v: Optional[str]) -> Optional[str]:
        return _validate_code(v)


class DriverRegisterIn(Schema):
    # max_length limits below all mirror the Driver model's own column
    # sizes (gocabapp/models.py) — without them, a value that's merely too
    # long for the database sailed straight past validation and only failed
    # once it hit Postgres, as a raw 500 (DataError: value too long for type
    # character varying(100)) instead of a clean 422 telling the driver
    # which field to shorten.
    full_name: str = Field(max_length=255)
    email: EmailStr
    phone_number: str
    # Either a fresh code, or a verified_token from an email already proven
    # via /verify-code (e.g. the login page's new-user redirect) — exactly
    # one is required, enforced in router.register_driver.
    code: Optional[str] = None
    verified_token: Optional[str] = None

    date_of_birth: date
    national_identification_number: str = Field(max_length=100)

    vehicle_type: str
    vehicle_color: str = Field(max_length=50)
    # Bike-only fields — a Bicycle only ever sets vehicle_type, vehicle_color,
    # and the vehicle_picture upload; enforced in _require_fields_for_bike.
    vehicle_model: Optional[str] = Field(default=None, max_length=100)
    vehicle_brand: Optional[str] = Field(default=None, max_length=100)
    production_year: Optional[int] = None
    license_plate: Optional[str] = Field(default=None, max_length=100)

    bank_name: str = Field(max_length=100)
    # Set when the frontend's bank dropdown (populated from Paystack's own
    # bank list) is used — lets payout_service skip its free-text
    # bank-name-matching fallback entirely and go straight to creating a
    # transfer recipient.
    bank_code: Optional[str] = None
    account_number: str
    account_holder_name: str = Field(max_length=255)

    latitude: float
    longitude: float
    current_address: Optional[str] = None

    @field_validator("phone_number")
    @classmethod
    def _normalize_phone(cls, v: str) -> str:
        return normalize_phone_number(v)

    @field_validator("code")
    @classmethod
    def _check_code(cls, v: Optional[str]) -> Optional[str]:
        return _validate_code(v)

    @field_validator("account_number")
    @classmethod
    def _validate_account_number(cls, v: str) -> str:
        if not v.isdigit() or len(v) != 10:
            raise ValueError("Account number must be 10 digits long.")
        return v

    @field_validator("vehicle_type")
    @classmethod
    def _validate_vehicle_type(cls, v: str) -> str:
        if v not in ("Bike", "Bicycle"):
            raise ValueError("Vehicle type must be 'Bike' or 'Bicycle'.")
        return v

    @model_validator(mode="after")
    def _require_fields_for_bike(self):
        if self.vehicle_type != "Bike":
            return self
        missing = []
        if not (self.license_plate or "").strip():
            missing.append("license plate")
        if not (self.vehicle_model or "").strip():
            missing.append("vehicle model")
        if not (self.vehicle_brand or "").strip():
            missing.append("vehicle brand")
        if self.production_year is None:
            missing.append("production year")
        if missing:
            raise ValueError(f"Required for a Bike: {', '.join(missing)}.")
        return self


class RequestCodeIn(Schema):
    email: EmailStr


class VerifyCodeIn(Schema):
    email: EmailStr
    code: str

    @field_validator("code")
    @classmethod
    def _check_code(cls, v: str) -> str:
        v = v.strip()
        if not v.isdigit() or len(v) != 6:
            raise ValueError("Enter the 6-digit code.")
        return v


class RefreshIn(Schema):
    refresh: str


class UserOut(Schema):
    id: int
    role: str
    full_name: str
    phone_number: str
    email: Optional[str] = None
    is_approved: Optional[bool] = None
    address: Optional[str] = None
    # Riders only — see Rider.referral_code / wallet_credit_balance. Always
    # None for a driver.
    referral_code: Optional[str] = None
    wallet_credit_balance: Optional[float] = None


class TokenPairOut(Schema):
    access: str
    refresh: str
    token_type: str = "bearer"
    user: UserOut


class RefreshOut(Schema):
    access: str
    refresh: str
    token_type: str = "bearer"


class MessageOut(Schema):
    detail: str
