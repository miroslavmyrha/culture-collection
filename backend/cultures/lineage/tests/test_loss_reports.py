"""The report of a lost VRAT or RAT vial to the police (#159, act 281/2002 Sb., § 5(5)): who owes
one, that a manager records it once per loss with a reason, what the event holds, what the vial
list shows, and that the trigger (lineage 0012) and the Python definition
(selectors.reportable_loss) agree for every restriction kind."""

from datetime import date, timedelta
from typing import Any

import pytest
from django.db import IntegrityError, InternalError, connection, transaction

from cultures.audit.context import MissingAuditContext, audit_context
from cultures.audit.models import AuditEvent, Channel
from cultures.biosafety.models import AuthorisationKind, RestrictionKind
from cultures.biosafety.policy import permit_today
from cultures.core.exceptions import Forbidden, RuleViolation
from cultures.core.testing import Write, assert_problem, logged_in
from cultures.core.testing.contract import ViewsetContract
from cultures.labs.access import access_for
from cultures.labs.models import Lab, Membership
from cultures.labs.permissions import Role
from cultures.lineage import services
from cultures.lineage.api.views import VialViewSet
from cultures.lineage.models import Passage, Vial, VialLossReport, VialStatus
from cultures.lineage.selectors import reportable_loss
from cultures.strains import services as strains
from cultures.strains.models import Strain, StrainRestriction
from cultures.strains.services import RestrictionInput
from cultures.strains.tests.conftest import (
    DUAL_USE,
    GMO,
    QUARANTINE,
    VRAT,
    end_restriction,
    make_permit,
)
from cultures.users.models import User

from .support import VIALS_URL, MakeBatch, vials_of
from .test_contract import Readers

pytestmark = pytest.mark.django_db

RAT = RestrictionInput(RestrictionKind.CZ_RAT, "Příloha 2, bod 1")
RESTRICTIONS: dict[RestrictionKind, RestrictionInput] = {
    RestrictionKind.CZ_VRAT: VRAT,
    RestrictionKind.CZ_RAT: RAT,
    RestrictionKind.DUAL_USE: DUAL_USE,
    RestrictionKind.QUARANTINE_PEST: QUARANTINE,
    RestrictionKind.GMO: GMO,
}
REPORTED = {RestrictionKind.CZ_VRAT, RestrictionKind.CZ_RAT}


def restrict(strain: Strain, curator: User, restriction: RestrictionInput = RAT) -> None:
    make_permit(strain.lab, AuthorisationKind.CZ_VRAT)
    make_permit(strain.lab, AuthorisationKind.QUARANTINE_PEST)
    with audit_context(channel=Channel.API, actor=curator, request_id="req-restrict"):
        strains.strain_restriction_add(
            access=access_for(curator), strain=strain, restriction=restriction, reason="listed"
        )


def move(vial: Vial, status: VialStatus, actor: User) -> Vial:
    with audit_context(channel=Channel.API, actor=actor, request_id="req-move"):
        return services.vial_transition(
            access=access_for(actor), vial=vial, status=status, reason="moved in a test"
        )


def report(vial: Vial, actor: User, **changes: Any) -> VialLossReport:
    fresh = Vial.objects.get(pk=vial.pk)
    values: dict[str, Any] = {
        "lost_at": fresh.status_changed_at,
        "reported_on": permit_today(),
        "reference": "KRPB-1234-1/TČ-2026-060000",
        "reason": "Reported at the police station.",
        **changes,
    }
    with audit_context(channel=Channel.API, actor=actor, request_id="req-report"):
        return services.vial_loss_report(access=access_for(actor), vial=fresh, **values)


@pytest.fixture
def lost(
    strain: Strain, passage0: Passage, make_batch: MakeBatch, curator: User, technician: User
) -> Vial:
    """A vial of a RAT strain (invented Testella exempli), lost by a technician."""
    restrict(strain, curator)
    vial = vials_of(make_batch(passage0, vial_count=2))[0]
    return move(vial, VialStatus.LOST, technician)


@pytest.mark.rule("R-END-04")
def test_a_manager_records_the_report_once_with_its_event(lost: Vial, manager: User) -> None:
    made = report(lost, manager)
    assert (made.lab_id, made.vial_id, made.recorded_by_id) == (lost.lab_id, lost.pk, manager.pk)
    assert made.lost_at == Vial.objects.get(pk=lost.pk).status_changed_at
    event = AuditEvent.objects.get(event_type="vial_loss_reported")
    assert (event.subject_type, event.subject_id) == ("vial", lost.public_id)
    assert event.strain_id == lost.batch.strain.public_id
    assert event.lab_id == lost.lab_id
    assert event.reason == "Reported at the police station."
    assert event.actor_label == f"user:{manager.public_id}"
    assert event.changes == {
        "loss_report": [None, str(made.public_id)],
        "lost_at": [None, made.lost_at.isoformat()],
        "reported_on": [None, permit_today().isoformat()],
        "reference": [None, "KRPB-1234-1/TČ-2026-060000"],
    }
    # No value that names or reaches the person who recorded it (ADR 0005).
    personal = {manager.username, manager.email, manager.first_name, manager.last_name} - {""}
    values = {str(value) for pair in event.changes.values() for value in pair}
    assert not values & personal

    with pytest.raises(services.LossReported):
        report(lost, manager, reference="another")
    assert VialLossReport.objects.count() == 1
    assert AuditEvent.objects.filter(event_type="vial_loss_reported").count() == 1


@pytest.mark.parametrize("reason", ["", "   "])
def test_a_reason_is_required(lost: Vial, manager: User, reason: str) -> None:
    with pytest.raises(RuleViolation) as refused:
        report(lost, manager, reason=reason)
    assert refused.value.code == "reason_required"
    assert not VialLossReport.objects.exists()


@pytest.mark.parametrize("role", [Role.VIEWER, Role.TECHNICIAN, Role.CURATOR])
@pytest.mark.rule("R-END-04")
def test_only_a_manager_records_it(lost: Vial, team: dict[Role, User], role: Role) -> None:
    with pytest.raises(Forbidden):
        report(lost, team[role])
    assert not VialLossReport.objects.exists()


def test_a_manager_demoted_since_the_request_began_is_refused(
    lost: Vial, manager: User, lab: Lab
) -> None:
    access = access_for(manager)  # built while the manager was one
    Membership.objects.filter(user=manager, lab=lab).update(role=Role.CURATOR)
    fresh = Vial.objects.get(pk=lost.pk)
    assert fresh.status_changed_at is not None
    with (
        audit_context(channel=Channel.API, actor=manager, request_id="req-demoted"),
        pytest.raises(Forbidden),
    ):
        services.vial_loss_report(
            access=access,
            vial=fresh,
            lost_at=fresh.status_changed_at,
            reported_on=permit_today(),
            reference="KRPB-1",
            reason="Reported.",
        )
    assert not VialLossReport.objects.exists()


def test_the_report_needs_an_audit_context(lost: Vial, manager: User) -> None:
    fresh = Vial.objects.get(pk=lost.pk)
    assert fresh.status_changed_at is not None
    with pytest.raises(MissingAuditContext):
        services.vial_loss_report(
            access=access_for(manager),
            vial=fresh,
            lost_at=fresh.status_changed_at,
            reported_on=permit_today(),
            reference="KRPB-1",
            reason="Reported.",
        )
    assert not VialLossReport.objects.exists()


@pytest.mark.rule("R-END-04")
def test_the_reference_and_the_day_are_checked(lost: Vial, manager: User) -> None:
    lost_on = permit_today()
    for changes, attr in (
        ({"reference": "  "}, "reference"),
        ({"reference": "x" * 101}, "reference"),
        ({"reported_on": lost_on + timedelta(days=1)}, "reported_on"),
        ({"reported_on": lost_on - timedelta(days=1)}, "reported_on"),
    ):
        with pytest.raises(services.InvalidVial) as refused:
            report(lost, manager, **changes)
        assert refused.value.attr == attr, changes
    made = report(lost, manager, reference="  KRPB  1234  ")
    assert made.reference == "KRPB 1234"


def test_a_vial_found_before_the_report_owes_none(
    lost: Vial, manager: User, technician: User
) -> None:
    lost_at = Vial.objects.get(pk=lost.pk).status_changed_at
    assert Vial.objects.filter(reportable_loss()).count() == 1
    move(lost, VialStatus.AVAILABLE, technician)
    assert not Vial.objects.filter(reportable_loss()).exists()
    with pytest.raises(services.VialNotLost):
        report(lost, manager, lost_at=lost_at)


@pytest.mark.rule("R-END-04")
def test_a_vial_found_and_lost_again_owes_a_new_report(
    lost: Vial, manager: User, technician: User
) -> None:
    first = Vial.objects.get(pk=lost.pk).status_changed_at
    report(lost, manager)
    assert not reported_due(lost)
    move(lost, VialStatus.AVAILABLE, technician)
    move(lost, VialStatus.LOST, technician)
    assert reported_due(lost)
    # A form read before the vial was found names the old loss: refused, not filed on the new.
    with pytest.raises(services.LossChanged):
        report(lost, manager, lost_at=first)
    report(lost, manager)
    assert VialLossReport.objects.filter(vial=lost).count() == 2
    assert not reported_due(lost)


def reported_due(vial: Vial) -> bool:
    """The vial is in a loss the police must be told of and no report of that loss exists."""
    when = Vial.objects.get(pk=vial.pk).status_changed_at
    assert when is not None
    return (
        Vial.objects.filter(pk=vial.pk).filter(reportable_loss()).exists()
        and not VialLossReport.objects.filter(vial=vial, lost_at=when).exists()
    )


CASES = [
    "none",
    *(f"active {kind}" for kind in RestrictionKind.values),
    "rat ended before the loss",
    "rat ended after the loss",
    "rat added after the loss",
]


@pytest.mark.parametrize("case", CASES)
@pytest.mark.rule("R-END-04")
def test_the_trigger_and_the_service_agree_with_the_python_definition(
    *,
    case: str,
    strain: Strain,
    passage0: Passage,
    make_batch: MakeBatch,
    curator: User,
    manager: User,
    technician: User,
) -> None:
    assert set(RESTRICTIONS) == set(RestrictionKind)  # a new kind needs a case here
    expected = case in ("active cz_vrat", "active cz_rat", "rat ended after the loss")
    if case.startswith("active"):
        restrict(strain, curator, RESTRICTIONS[RestrictionKind(case.split()[1])])
    elif case not in ("none", "rat added after the loss"):
        restrict(strain, curator)
    if case == "rat ended before the loss":
        end_restriction(
            StrainRestriction.objects.get(strain=strain), proposer=curator, confirmer=manager
        )
    raw, served = (
        move(v, VialStatus.LOST, technician) for v in vials_of(make_batch(passage0, vial_count=2))
    )
    if case == "rat ended after the loss":
        end_restriction(
            StrainRestriction.objects.get(strain=strain), proposer=curator, confirmer=manager
        )
    if case == "rat added after the loss":
        restrict(strain, curator)
    assert Vial.objects.filter(pk__in=[raw.pk, served.pk]).filter(reportable_loss()).count() == (
        2 if expected else 0
    ), case
    fresh = Vial.objects.get(pk=raw.pk)
    try:
        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO lineage_viallossreport (public_id, created_at, updated_at, lab_id,"
                " vial_id, lost_at, reported_on, reference, recorded_by_id, recorded_at)"
                " VALUES (gen_random_uuid(), now(), now(), %s, %s, %s, %s, 'KRPB-1', %s, now())",
                [fresh.lab_id, fresh.pk, fresh.status_changed_at, permit_today(), manager.pk],
            )
    except (IntegrityError, InternalError) as error:
        assert not expected, f"{case}: the trigger refused a loss the act asks a report of: {error}"
        assert "a loss is reported only for a strain that was a VRAT or RAT" in str(error)
    else:
        assert expected, f"{case}: the trigger took a report of a loss that owes none"
    try:
        report(served, manager)
    except services.LossNotReportable:
        assert not expected, f"{case}: the service refused a loss the act asks a report of"
    else:
        assert expected, f"{case}: the service recorded a report of a loss that owes none"


def test_the_trigger_holds_the_report_to_its_loss(
    lost: Vial, manager: User, technician: User
) -> None:
    made = report(lost, manager)
    statements = [
        ("UPDATE lineage_viallossreport SET reference = 'other' WHERE id = %s", [made.pk]),
        ("DELETE FROM lineage_viallossreport WHERE id = %s", [made.pk]),
    ]
    for sql, params in statements:
        with (
            pytest.raises(IntegrityError, match="a loss report never changes"),
            transaction.atomic(),
            connection.cursor() as cursor,
        ):
            cursor.execute(sql, params)
    other = move(vials_of(lost.batch)[1], VialStatus.LOST, technician)
    when = Vial.objects.get(pk=other.pk).status_changed_at
    assert when is not None
    insert = (
        "INSERT INTO lineage_viallossreport (public_id, created_at, updated_at, lab_id, vial_id,"
        " lost_at, reported_on, reference, recorded_by_id, recorded_at) VALUES"
        " (gen_random_uuid(), now(), now(), %s, %s, %s, %s, 'KRPB-2', %s, now())"
    )
    for lost_at, day, match in (
        (when - timedelta(seconds=1), permit_today(), "for the loss it is in"),
        (when, date(2020, 1, 1), "not dated before the loss"),
    ):
        with (
            pytest.raises(IntegrityError, match=match),
            transaction.atomic(),
            connection.cursor() as cursor,
        ):
            cursor.execute(insert, [other.lab_id, other.pk, lost_at, day, manager.pk])


# The API.


def vial_row(user: User, vial: Vial) -> dict[str, Any]:
    response = logged_in(user).get(f"{VIALS_URL}?vial={vial.public_id}")
    assert response.status_code == 200, response.content
    [row] = response.json()["results"]
    assert isinstance(row, dict)
    return row


def test_the_vial_list_shows_the_loss_and_its_report(
    *,
    lost: Vial,
    manager: User,
    viewer: User,
    technician: User,
    make_batch: MakeBatch,
    regulated: Strain,
) -> None:
    assert vial_row(viewer, lost)["police_report"] == {"reported_on": None, "reference": None}
    # Lost from a strain that is regulated, but not a VRAT or RAT (dual use): no report.
    other = vials_of(make_batch(Passage.objects.get(strain=regulated, number=0), vial_count=1))[0]
    move(other, VialStatus.LOST, technician)
    assert vial_row(viewer, other)["police_report"] is None
    # Not lost: none either.
    assert vial_row(viewer, vials_of(lost.batch)[1])["police_report"] is None

    fresh = Vial.objects.get(pk=lost.pk)
    response = logged_in(manager).post(
        f"{VIALS_URL}{lost.public_id}/loss-report/",
        {
            "lost_at": fresh.status_changed_at.isoformat() if fresh.status_changed_at else None,
            "reported_on": permit_today().isoformat(),
            "reference": "KRPB-1234-1/TČ-2026-060000",
            "reason": "Reported at the police station.",
        },
        content_type="application/json",
    )
    assert response.status_code == 200, response.content
    expected = {
        "reported_on": permit_today().isoformat(),
        "reference": "KRPB-1234-1/TČ-2026-060000",
    }
    assert response.json()["police_report"] == expected
    assert vial_row(viewer, lost)["police_report"] == expected

    again = logged_in(manager).post(
        f"{VIALS_URL}{lost.public_id}/loss-report/",
        {
            "lost_at": fresh.status_changed_at.isoformat() if fresh.status_changed_at else None,
            "reported_on": permit_today().isoformat(),
            "reference": "KRPB-2",
            "reason": "Twice.",
        },
        content_type="application/json",
    )
    assert_problem(again, 409, "loss_reported")


def test_the_api_names_a_missing_reason_and_reference(lost: Vial, manager: User) -> None:
    fresh = Vial.objects.get(pk=lost.pk)
    response = logged_in(manager).post(
        f"{VIALS_URL}{lost.public_id}/loss-report/",
        {
            "lost_at": fresh.status_changed_at.isoformat() if fresh.status_changed_at else None,
            "reported_on": permit_today().isoformat(),
            "reference": "",
            "reason": "",
        },
        content_type="application/json",
    )
    body = assert_problem(response, 400, "invalid")
    assert {error["attr"] for error in body["errors"]} == {"reference", "reason"}
    assert not VialLossReport.objects.exists()


class TestLossReportContract(Readers, ViewsetContract):
    """Recording the report is the managers': a curator reads the vial and is refused (403)."""

    viewset = VialViewSet
    url = VIALS_URL
    audit_model = AuditEvent
    writes = (Write("loss-report/", {}, changes=VialLossReport, status=200),)

    def send(self, user: User | None, obj: Any, write: Write) -> Any:
        fresh = Vial.objects.get(pk=obj.pk)
        assert fresh.status_changed_at is not None
        payload = {
            "lost_at": fresh.status_changed_at.isoformat(),
            "reported_on": permit_today().isoformat(),
            "reference": "KRPB-1",
            "reason": "Reported.",
        }
        return logged_in(user).post(
            f"{self.detail(obj)}{write.action}", payload, content_type="application/json"
        )

    @pytest.fixture
    def obj(self, lost: Vial) -> Vial:
        return lost

    @pytest.fixture
    def reader(self, curator: User) -> User:
        return curator

    @pytest.fixture
    def writer(self, manager: User) -> User:
        return manager
