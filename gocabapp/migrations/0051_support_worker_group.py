"""Creates a "Support Worker" staff group scoped to exactly what a worker
should be able to do: resolve disputes. Nothing else — no driver approval,
no payouts, no bank details, no ride data outside of what a dispute
already shows. Full, unrestricted access (everything else in Django
admin) stays reserved for a superuser account, i.e. the CEO.

Assigning someone to this group, instead of making them a superuser, is
the actual authorization control: create their User in Django admin,
tick "Staff status", leave "Superuser status" off, and add them to this
group under Groups. Nothing else needs building — Django's own permission
system already gates every other admin page/action correctly once this
exists.
"""
from django.db import migrations


def create_support_worker_group(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")

    group, _ = Group.objects.get_or_create(name="Support Worker")
    codenames = ["view_paymentdispute", "change_paymentdispute"]
    perms = Permission.objects.filter(
        content_type__app_label="gocabapp", codename__in=codenames,
    )
    group.permissions.set(perms)


def remove_support_worker_group(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Group.objects.filter(name="Support Worker").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("gocabapp", "0050_bank_account_composite_unique"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [
        migrations.RunPython(create_support_worker_group, remove_support_worker_group),
    ]
