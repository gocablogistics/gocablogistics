import phonenumbers


def normalize_phone_number(raw: str) -> str:
    """Normalize and strictly validate a Nigerian phone number to E.164
    (+234...), using Google's libphonenumber (via the `phonenumbers`
    package) rather than a hand-rolled digit-count check — this actually
    verifies the number matches a real Nigerian mobile numbering pattern,
    not just "10-15 digits".

    Accepts local Nigerian format (0801...), with-country-code (234801...,
    +234801...) or bare subscriber digits, so riders/drivers can type
    whatever they're used to on web or mobile and still resolve to the
    same stored identity. Deliberately rejects valid numbers from any
    other country — GoCab only operates in Nigeria right now.
    """
    raw = (raw or "").strip()
    try:
        parsed = phonenumbers.parse(raw, "NG")
    except phonenumbers.NumberParseException:
        raise ValueError(
            "Enter a valid Nigerian phone number, e.g. 08012345678 or +2348012345678"
        )

    if not phonenumbers.is_valid_number(parsed) or phonenumbers.region_code_for_number(parsed) != "NG":
        raise ValueError(
            "Enter a valid Nigerian phone number, e.g. 08012345678 or +2348012345678"
        )

    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)


def get_client_ip(request) -> str:
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "unknown")
