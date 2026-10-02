from __future__ import annotations

from datetime import datetime

from ninja import Schema


class NotificationOut(Schema):
    id: int
    message: str
    created_at: datetime
    is_active: bool


class NotificationCountOut(Schema):
    count: int


class DeviceRegisterIn(Schema):
    token: str
    platform: str = "android"
    app_version: str = ""


class DeviceRegisterOut(Schema):
    status: str
