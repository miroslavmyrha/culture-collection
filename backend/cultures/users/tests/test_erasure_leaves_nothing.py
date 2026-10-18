"""After an erasure no value of the person is left anywhere in the database (#37).

One person gets a unique marker in every personal field, is renamed twice
through the services, acts through a command, the API and the admin, has a
session and a failed login, and is changed by staff in the admin. The marker
goes into nothing else. Then staff erase the person through the admin page,
and every text, varchar, char and json(b) column of every table, in every
schema the project writes (from information_schema.columns), is searched for
the marker. Every step commits its own transaction (transaction=True), as in
production, so audit_reconcile sees real transactions.
"""

from contextlib import AbstractContextManager

import pytest
from django.core.management import call_command
from django.db import connection
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from cultures.audit.context import AuditContext, audit_context
from cultures.audit.models import ActorKind, Channel
from cultures.audit.reconcile import reconcile
from cultures.core.testing import logged_in
from cultures.labs import services as labs
from cultures.labs.models import Lab
from cultures.labs.permissions import Role
from cultures.users import services
from cultures.users.models import User

from .test_admin import form_of
from .test_login_limits import HOME, admin, api

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.slow]

MARK = "Zq7erase"
PASSWORD = "a long password of the person"  # noqa: S105 (a test password)
REASON = "erasure request 2026-115, checked by the data protection office"
TEXT_TYPES = ("text", "varchar", "bpchar", "json", "jsonb", "_text", "_varchar")


def marker_hits() -> list[str]:
    """schema.table.column for every column that holds the marker, in any letter case."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT table_schema, table_name, column_name FROM information_schema.columns"
            " JOIN information_schema.tables USING (table_catalog, table_schema, table_name)"
            " WHERE table_type = 'BASE TABLE' AND udt_name = ANY(%s)"
            " AND table_schema NOT IN ('pg_catalog', 'information_schema')"
            " ORDER BY 1, 2, 3",
            [list(TEXT_TYPES)],
        )
        columns = cursor.fetchall()
        assert len(columns) > 30  # the walk read the real catalogue, audit tables included
        assert ("public", "audit_rowchange", "new") in columns
        assert ("public", "audit_auditevent", "reason") in columns
        hits = []
        for schema, table, column in columns:
            cursor.execute(
                f'SELECT count(*) FROM "{schema}"."{table}"'  # noqa: S608 (names from the catalogue)
                f' WHERE strpos(lower("{column}"::text), lower(%s)) > 0',
                [MARK],
            )
            ((count,),) = cursor.fetchall()
            if count:
                hits.append(f"{schema}.{table}.{column}")
    return hits


def system() -> AbstractContextManager[AuditContext]:
    return audit_context(
        channel=Channel.COMMAND, actor_kind=ActorKind.SYSTEM, actor_label="command:test"
    )


def test_an_erased_person_leaves_no_value_in_any_column() -> None:
    since = timezone.now()
    with system():
        root = services.superuser_create(username="root", password=PASSWORD, reason="first admin")
        colleague = services.user_create(username="colleague", password=None)
        third = services.user_create(username="third", password=None)
        person = services.superuser_create(
            username=f"{MARK}-user",
            password=PASSWORD,
            email=f"{MARK}@example.org",
            reason="second admin",
        )
    with audit_context(channel=Channel.COMMAND, actor=root):
        services.user_update(
            user=person,
            changes={"first_name": f"{MARK} Ada", "last_name": f"{MARK} Lovelace"},
        )
        for n in (1, 2):  # renamed twice through the services
            services.user_update(
                user=person,
                changes={
                    "username": f"{MARK}-user-{n}",
                    "first_name": f"{MARK} Ada {n}",
                    "last_name": f"{MARK} Lovelace {n}",
                    "email": f"{MARK}.{n}@example.org",
                },
            )
    person.refresh_from_db()
    username = person.username

    # The person acts: a command, the API as a lab manager, the admin as staff.
    with audit_context(channel=Channel.COMMAND, actor=person, reason="lab set-up"):
        lab = labs.lab_create(name="Mycology", code="MYC")
        labs.membership_create(lab=lab, user=person, role=Role.MANAGER)
        labs.membership_create(lab=lab, user=colleague, role=Role.MANAGER)
    browser = Client()
    assert api(browser, username, PASSWORD, HOME) == "in"  # a real session row
    added = browser.post(
        f"/api/v1/labs/{lab.public_id}/members/",
        {"username": "third", "role": "viewer"},
        content_type="application/json",
    )
    assert added.status_code == 201, added.content
    staff_browser = logged_in(person)
    changed = staff_browser.post(
        reverse("admin:users_user_change", args=[third.pk]), form_of(third, last_name="Third")
    )
    assert changed.status_code == 302, changed.content
    assert api(Client(), username, "a wrong password", HOME) == "wrong"  # a login counter

    # Staff change the person in the admin: Django's log copies the username.
    root_browser = logged_in(root)
    response = root_browser.post(
        reverse("admin:users_user_change", args=[person.pk]),
        form_of(person, email=f"{MARK}.3@example.org"),
    )
    assert response.status_code == 302, response.content
    assert marker_hits() != []  # the search finds the values before the erasure

    response = root_browser.post(
        reverse("admin:users_user_erase", args=[person.pk]),
        {"confirm": username, "reason": REASON},
    )
    assert response.status_code == 302, response.content

    assert marker_hits() == []

    # The trail still joins: every row change has its event and its actor.
    assert [f for f in reconcile(since) if f.alarm] == []
    # Exits 1 (CommandError) on an alarm. Only this test's window: the flush of an earlier
    # transactional test leaves TRUNCATE rows without an event.
    call_command("audit_reconcile", "--since", since.isoformat())

    # Signing in fails with the old name and with the tombstone's.
    person.refresh_from_db()
    for name in (username, person.username):
        assert api(Client(), name, PASSWORD, HOME) == "wrong"
        assert admin(Client(), name, PASSWORD, HOME) == "wrong"
    assert browser.get("/api/v1/auth/me/").status_code == 401  # the session ended

    # Reactivation is refused.
    with audit_context(channel=Channel.COMMAND, actor=root), pytest.raises(services.UserErased):
        services.user_activate(user=person, reason="undo")
    assert User.objects.get(pk=person.pk).is_active is False

    # Where the person was shown as an actor, the tombstone is shown now.
    tombstone = f"erased-{person.public_id}"
    history = root_browser.get(reverse("admin:users_user_history", args=[third.pk]))
    assert tombstone in history.content.decode()
    members = logged_in(colleague).get(f"/api/v1/labs/{lab.public_id}/members/").json()
    assert sorted(m["username"] for m in members["results"]) == ["colleague", "third"]
    assert Lab.objects.get(pk=lab.pk).memberships.count() == 2
