from __future__ import annotations

import logging

from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from ..models import Driver, Notification
from ..services.push_service import send_push_to_user
from ..services.ride_events import notify_notification_count

logger = logging.getLogger(__name__)


@receiver(pre_save, sender=Driver)
def _stash_previous_approval(sender, instance: Driver, **kwargs):
    """post_save doesn't get the pre-update value, so stash it here to
    detect the False -> True transition in notify_driver_approved below."""
    if not instance.pk:
        instance._was_approved = False
        return
    try:
        instance._was_approved = Driver.objects.only("is_approved").get(pk=instance.pk).is_approved
    except Driver.DoesNotExist:
        instance._was_approved = False


@receiver(post_save, sender=Driver)
def notify_driver_approved(sender, instance: Driver, created: bool, **kwargs):
    if created:
        return
    was_approved = getattr(instance, "_was_approved", False)
    if not was_approved and instance.is_approved:
        Notification.objects.create(
            user=instance.user,
            message="Your driver account has been approved. Log in to go online.",
            is_active=True,
        )
        count = Notification.objects.filter(user=instance.user, is_active=True).count()
        notify_notification_count(instance.user.id, count)
        send_push_to_user(
            instance.user.id, "You're approved!",
            "Your driver account has been approved. Log in to go online.",
        )
        logger.info("Driver %s approved — notification created", instance.user_id)
