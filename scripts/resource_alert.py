"""Checks disk and memory on this box and emails the admin only if
something's actually crossed a threshold — run every 15 minutes by a
systemd timer (see resource-alert.timer/.service on the server). Silent
on every normal run; this is the gap that let the earlier Redis crash go
unnoticed until a user hit it, see gocabapp/utils/mailer.py for the same
no-op-safe pattern used everywhere else in this project.
"""
from __future__ import annotations

import os
import shutil
import subprocess

DISK_THRESHOLD_PERCENT = 85
MEM_AVAILABLE_THRESHOLD_PERCENT = 10


def _disk_used_percent(path: str = "/") -> float:
    total, used, _free = shutil.disk_usage(path)
    return (used / total) * 100


def _mem_available_percent() -> float:
    total = available = None
    with open("/proc/meminfo") as f:
        for line in f:
            if line.startswith("MemTotal:"):
                total = int(line.split()[1])
            elif line.startswith("MemAvailable:"):
                available = int(line.split()[1])
    if not total or available is None:
        return 100.0
    return (available / total) * 100


def main() -> None:
    problems = []

    disk_pct = _disk_used_percent()
    if disk_pct >= DISK_THRESHOLD_PERCENT:
        problems.append(f"Disk usage is at {disk_pct:.0f}% (alert threshold {DISK_THRESHOLD_PERCENT}%).")

    mem_avail_pct = _mem_available_percent()
    if mem_avail_pct <= MEM_AVAILABLE_THRESHOLD_PERCENT:
        problems.append(
            f"Only {mem_avail_pct:.0f}% of memory is available (alert threshold {MEM_AVAILABLE_THRESHOLD_PERCENT}%)."
        )

    if not problems:
        return

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Gocabservices.settings.production")
    import django

    django.setup()

    from django.conf import settings
    from gocabapp.utils.mailer import send_admin_mail

    if not settings.RESOURCE_ALERT_EMAIL:
        return

    hostname = subprocess.run(["hostname"], capture_output=True, text=True, check=False).stdout.strip()
    send_admin_mail(
        subject="GoCab server resource alert",
        message=(
            f"Server: {hostname}\n\n" + "\n".join(problems) +
            "\n\nThis is informational — check the server and clear space or restart "
            "services as needed. No automatic action was taken."
        ),
        recipient_list=[settings.RESOURCE_ALERT_EMAIL],
    )


if __name__ == "__main__":
    main()
