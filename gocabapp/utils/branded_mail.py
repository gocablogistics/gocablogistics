"""Sends branded, logo-carrying HTML emails (OTP codes, etc.) through
whichever EMAIL_BACKEND is active. The GoCab logo is embedded inline via
Content-ID rather than linked as a remote URL — most email clients block
remote images by default until the recipient explicitly allows them, which
would make the logo invisible on first open; inline embedding shows it
immediately, every time, regardless of GoCab's own hosting status.
"""
from __future__ import annotations

from email.mime.image import MIMEImage
from pathlib import Path

from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils.html import strip_tags

LOGO_PATH = Path(__file__).resolve().parent.parent / "static" / "email" / "gocab-logo.png"
LOGO_CID = "gocab-logo"


def send_branded_email(subject: str, to: list[str], template_name: str, context: dict) -> None:
    html_body = render_to_string(template_name, {**context, "logo_cid": LOGO_CID})
    text_body = strip_tags(html_body)

    email = EmailMultiAlternatives(subject=subject, body=text_body, to=to)
    email.attach_alternative(html_body, "text/html")

    if LOGO_PATH.exists():
        with open(LOGO_PATH, "rb") as f:
            logo = MIMEImage(f.read())
        logo.add_header("Content-ID", f"<{LOGO_CID}>")
        logo.add_header("Content-Disposition", "inline", filename="gocab-logo.png")
        email.attach(logo)

    email.send()
