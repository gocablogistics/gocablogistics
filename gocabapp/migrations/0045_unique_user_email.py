"""
User.email (Django's built-in auth model) has no unique constraint by
default. Rider registration is already backstopped by Rider.email being
unique, but Driver has no email field of its own — a driver signup race
(two requests for the same email landing before either commits) can create
two Users sharing one email with nothing at the database layer to stop it.
Login-by-email (services.get_user_by_email) then silently resolves to
whichever row it finds first, and the other account becomes unreachable by
email. Confirmed reproducible in gocabapp/api/auth/services.create_driver.

Partial + case-insensitive so it doesn't collide with existing/blank emails
(deactivate_account intentionally sets email="" on soft-deleted accounts,
and any legacy blank-email superuser) — only real, non-blank emails are
required to be unique. Raw SQL because auth_user belongs to django.contrib.auth,
not this app; the two-table unique constraint is enforced at the DB layer
either way, and application code already catches IntegrityError on this path
(gocabapp/api/auth/services.py's create_rider/create_driver) exactly like it
does for phone_number/account_number collisions.
"""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("gocabapp", "0044_unpaid_reminder_sent_at"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
                CREATE UNIQUE INDEX gocabapp_auth_user_email_ci_uniq
                ON auth_user (LOWER(email))
                WHERE email <> '';
            """,
            reverse_sql="DROP INDEX gocabapp_auth_user_email_ci_uniq;",
        ),
    ]
