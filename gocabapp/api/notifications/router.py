from __future__ import annotations

from ninja import Router
from ninja.errors import HttpError
from ninja_jwt.authentication import JWTAuth

from ...models import DeviceToken, Notification
from ...services.ride_events import notify_notification_count
from .schemas import DeviceRegisterIn, DeviceRegisterOut, NotificationCountOut, NotificationOut

router = Router(tags=["notifications"])


@router.get("", response=list[NotificationOut], auth=JWTAuth())
def list_notifications(request):
    return list(
        Notification.objects.filter(user=request.user).order_by("-created_at")[:20]
    )


@router.get("/count", response=NotificationCountOut, auth=JWTAuth())
def unread_count(request):
    count = Notification.objects.filter(user=request.user, is_active=True).count()
    return {"count": count}


@router.post("/{notification_id}/read", response=NotificationCountOut, auth=JWTAuth())
def mark_read(request, notification_id: int):
    try:
        n = Notification.objects.get(id=notification_id, user=request.user)
    except Notification.DoesNotExist:
        raise HttpError(404, "Notification not found")
    n.is_active = False
    n.save(update_fields=["is_active"])

    count = Notification.objects.filter(user=request.user, is_active=True).count()
    notify_notification_count(request.user.id, count)
    return {"count": count}


@router.post("/read-all", response=NotificationCountOut, auth=JWTAuth())
def mark_all_read(request):
    Notification.objects.filter(user=request.user, is_active=True).update(is_active=False)
    notify_notification_count(request.user.id, 0)
    return {"count": 0}


@router.post("/register-device", response=DeviceRegisterOut, auth=JWTAuth())
def register_device(request, payload: DeviceRegisterIn):
    # update_or_create on `token` (globally unique) — also transparently
    # re-homes a token that logs out and back in as a different account on
    # the same device.
    DeviceToken.objects.update_or_create(
        token=payload.token,
        defaults={
            "user": request.user,
            "platform": payload.platform,
            "app_version": payload.app_version,
            "is_active": True,
        },
    )
    return {"status": "ok"}
