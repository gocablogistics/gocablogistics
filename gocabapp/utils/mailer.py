"""Sends admin-facing alert emails (disputes, new-driver signups, stale
rides) through Resend's SMTP relay. Originally built deliberately separate
from Django's global EMAIL_BACKEND, back when that stayed on the console
backend to protect OTP login (otp.py) from a provider failure — as of
2026-10-02 the global backend also points at this same Resend connection
(see settings/base.py), so this module and otp.py both end up sending
through the same proven path. Kept as its own function regardless, since
admin alerts take a recipient_list rather than a single address.

Safe no-op behavior matches every other "unconfigured until you set a key"
integration in this project: no RESEND_API_KEY means this call just falls
back to Django's default send_mail() (whatever EMAIL_BACKEND is, which
itself falls back to console with no key — see settings/base.py), so
nothing breaks before Resend is actually wanted.
"""
from __future__ import annotations

import logging

from django.conf import settings
from django.core.mail import get_connection, send_mail

logger = logging.getLogger(__name__)


def send_admin_mail(subject: str, message: str, recipient_list: list[str]) -> None:
    if not recipient_list:
        return

    if not settings.RESEND_API_KEY:
        send_mail(subject=subject, message=message, from_email=None, recipient_list=recipient_list)
        return

    try:
        connection = get_connection(
            backend="django.core.mail.backends.smtp.EmailBackend",
            host=settings.RESEND_SMTP_HOST,
            port=settings.RESEND_SMTP_PORT,
            username="resend",
            password=settings.RESEND_API_KEY,
            use_tls=True,
        )
        send_mail(
            subject=subject, message=message, from_email=settings.RESEND_FROM_EMAIL,
            recipient_list=recipient_list, connection=connection,
        )
    except Exception:
        logger.exception("send_admin_mail via Resend failed — subject=%r", subject)
