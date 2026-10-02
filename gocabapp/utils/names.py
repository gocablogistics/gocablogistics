"""One place to get a person's real name for display.

Accounts in this app never set Django's built-in first/last name, so
User.get_full_name() is always empty — and the username is the person's phone
number (phone-first identity), so falling back to it shows a phone number where a
name belongs. The real name lives on the Driver / Rider profile.
"""
from __future__ import annotations


def display_name(user, prefer: str = "driver", fallback: str = "GoCab user") -> str:
    """The profile's full_name, checking the profile that matches the role first.
    Never the username; `fallback` (a neutral word like "Your driver") when the
    profile has no name."""
    if user is None:
        return fallback
    order = ("driver", "rider") if prefer == "driver" else ("rider", "driver")
    for attr in order:
        # A missing reverse one-to-one raises an AttributeError subclass, so the
        # default makes this safe for users without that profile.
        profile = getattr(user, attr, None)
        name = (getattr(profile, "full_name", None) or "").strip()
        if name:
            return name
    return fallback
