"""Staff record and end permits through the services: under the lab lock, one event each,
and a refusal that changes nothing and records nothing."""

from datetime import date
from typing import Any

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from cultures.audit.context import AuditContext, MissingAuditContext
from cultures.audit.models import AuditEvent, RowChange
from cultures.biosafety import services
from cultures.biosafety.models import AuthorisationKind, Issuer, LabAuthorisation
from cultures.core.exceptions import DomainError, RuleViolation
from cultures.labs.models import Lab
from cultures.users.models import User

from .conftest import make_permit

pytestmark = pytest.mark.django_db


def snapshot() -> tuple[list[Any], int, int]:
    return (
        list(LabAuthorisation.objects.order_by("pk").values()),
        AuditEvent.objects.count(),
        RowChange.objects.count(),
    )


def refused(error: type[DomainError], code: str, call: Any) -> DomainError:
    before = snapshot()
    with pytest.raises(error) as raised:
        call()
    assert raised.value.code == code
    assert snapshot() == before
    return raised.value


def create(lab: Lab, **changes: Any) -> LabAuthorisation:
    values: dict[str, Any] = {
        "lab": lab,
        "kind": AuthorisationKind.QUARANTINE_PEST,
        "permit_reference": " ÚKZÚZ  2026/7 ",
        "valid_from": date(2026, 1, 1),
        "expires_on": date(2027, 12, 31),
        **changes,
    }
    return services.authorisation_create(**values)


def test_staff_record_a_permit_with_its_issuer(
    as_staff: AuditContext, staff: User, lab: Lab
) -> None:
    permit = create(lab)
    assert (permit.issuer, permit.permit_reference, permit.ended_on) == (
        Issuer.UKZUZ,
        "ÚKZÚZ 2026/7",
        None,
    )
    event = AuditEvent.objects.get()
    assert (event.event_type, event.actor, event.lab, event.strain_id, event.subject_id) == (
        "lab_authorisation_added",
        staff,
        lab,
        None,
        permit.public_id,
    )
    assert event.changes == {
        "kind": [None, "quarantine_pest"],
        "issuer": [None, "ukzuz"],
        "permit_reference": [None, "ÚKZÚZ 2026/7"],
        "valid_from": [None, "2026-01-01"],
        "expires_on": [None, "2027-12-31"],
    }


def test_a_permit_without_an_expiry(as_staff: AuditContext, lab: Lab) -> None:
    assert create(lab, expires_on=None).expires_on is None


def test_a_bad_permit_is_a_field_error(as_staff: AuditContext, lab: Lab) -> None:
    error = refused(
        services.InvalidAuthorisation,
        "invalid_authorisation",
        lambda: create(lab, expires_on=date(2025, 1, 1)),
    )
    assert error.attr == "expires_on"
    error = refused(
        services.InvalidAuthorisation,
        "invalid_authorisation",
        lambda: create(lab, permit_reference="  "),
    )
    assert error.attr == "permit_reference"
    create(lab)
    error = refused(services.InvalidAuthorisation, "unique", lambda: create(lab))
    assert error.attr == "permit_reference"


def test_staff_end_a_permit_with_a_reason(as_staff: AuditContext, lab: Lab) -> None:
    permit = make_permit(lab)
    ended = services.authorisation_end(
        authorisation=permit, ended_on=date(2026, 5, 1), reason=" revoked by decision 2026-114 "
    )
    assert (ended.ended_on, ended.end_reason) == (date(2026, 5, 1), "revoked by decision 2026-114")
    event = AuditEvent.objects.get()
    assert (event.event_type, event.lab, event.reason, event.changes) == (
        "lab_authorisation_ended",
        lab,
        " revoked by decision 2026-114 ",
        {"ended_on": [None, "2026-05-01"]},
    )


def test_ending_needs_a_reason(as_staff: AuditContext, lab: Lab) -> None:
    permit = make_permit(lab)
    refused(
        RuleViolation,
        "reason_required",
        lambda: services.authorisation_end(
            authorisation=permit, ended_on=date(2026, 5, 1), reason=" "
        ),
    )


def test_a_permit_ends_once_and_not_before_it_starts(as_staff: AuditContext, lab: Lab) -> None:
    permit = make_permit(lab)
    error = refused(
        services.InvalidAuthorisation,
        "invalid_authorisation",
        lambda: services.authorisation_end(
            authorisation=permit, ended_on=date(2025, 5, 1), reason="error"
        ),
    )
    assert error.attr == "ended_on"
    services.authorisation_end(authorisation=permit, ended_on=date(2026, 5, 1), reason="revoked")
    refused(
        services.AlreadyEnded,
        "already_ended",
        lambda: services.authorisation_end(
            authorisation=permit, ended_on=date(2026, 6, 1), reason="again"
        ),
    )


@pytest.mark.parametrize("service", ["create", "end"])
def test_both_services_take_the_lab_lock_before_they_write(
    as_staff: AuditContext, lab: Lab, service: str
) -> None:
    permit = make_permit(lab, AuthorisationKind.CZ_VRAT, permit_reference="other")
    with CaptureQueriesContext(connection) as captured:
        if service == "create":
            create(lab)
        else:
            services.authorisation_end(
                authorisation=permit, ended_on=date(2026, 5, 1), reason="revoked"
            )
    statements = [q["sql"] for q in captured.captured_queries]
    lock = next(
        i for i, sql in enumerate(statements) if 'FROM "labs_lab"' in sql and "FOR UPDATE" in sql
    )
    write = next(
        i
        for i, sql in enumerate(statements)
        if sql.startswith(('INSERT INTO "biosafety', 'UPDATE "biosafety'))
    )
    assert lock < write


def test_the_services_need_an_audit_context(lab: Lab) -> None:
    with pytest.raises(MissingAuditContext):
        create(lab)
    assert not LabAuthorisation.objects.exists()
