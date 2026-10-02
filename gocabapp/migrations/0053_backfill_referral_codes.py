# Existing riders (created before the referral program existed) all have
# referral_code=NULL after 0052 — this backfills one for each so every
# current rider can start sharing a code immediately, without waiting for
# some unrelated save() call to happen to touch their row first.
from django.db import migrations

# Mirrors models._REFERRAL_CODE_ALPHABET / _generate_unique_referral_code —
# duplicated here (migrations must not import from the live models module,
# since a future model change could make that import fail against an old
# migration) rather than shared.
_REFERRAL_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def backfill_referral_codes(apps, schema_editor):
    import secrets

    Rider = apps.get_model("gocabapp", "Rider")
    existing = set(
        Rider.objects.exclude(referral_code__isnull=True).values_list("referral_code", flat=True)
    )
    for rider in Rider.objects.filter(referral_code__isnull=True):
        while True:
            code = "".join(secrets.choice(_REFERRAL_CODE_ALPHABET) for _ in range(6))
            if code not in existing:
                existing.add(code)
                break
        rider.referral_code = code
        rider.save(update_fields=["referral_code"])


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("gocabapp", "0052_referral_program"),
    ]

    operations = [
        migrations.RunPython(backfill_referral_codes, noop_reverse),
    ]
