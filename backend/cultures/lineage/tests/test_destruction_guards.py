"""The triggers of the destruction record (lineage 0014) against every writer: QuerySet.update(),
the ORM past the services, raw SQL as the owner and as the runtime role (ADR 0005). And the
parity of #158 kept: "regulated" and the kinds' rules are written twice, in
services.destructions and in the record's trigger, and both agree for every restriction kind,
for an ended restriction and for none."""

from datetime import timedelta
from typing import Any

import pytest
import time_machine
from django.db import IntegrityError, InternalError, connection, transaction
from django.db.backends.utils import CursorWrapper
from django.utils import timezone

from cultures.audit.context import audit_context
from cultures.audit.models import Channel
from cultures.audit.tests.conftest import TEST_ROLES, refused
from cultures.biosafety.models import AuthorisationKind, DestructionMethod, LabAuthorisation
from cultures.biosafety.policy import permit_today
from cultures.core.exceptions import DomainError
from cultures.labs.access import access_for
from cultures.labs.models import Lab, Membership
from cultures.labs.permissions import Role
from cultures.labs.selectors import has_vrat_access
from cultures.labs.tests.conftest import member_of
from cultures.lineage import services
from cultures.lineage.models import DestructionRecord, DestructionVial, Passage, Vial, VialStatus
from cultures.lineage.services.destructions import _check_rules
from cultures.strains import services as strains
from cultures.strains.models import Strain, StrainRestriction
from cultures.strains.tests.conftest import GMO, end_restriction
from cultures.users.models import User

from .support import VERIFIED, MakeBatch, destroy, mark_to_destroy, new_destruction, vials_of
from .test_destructions import (
    RESTRICTIONS,
    _prague_noon,
    end_vrat_access,
    restrict,
    with_vrat_access,
)

pytestmark = pytest.mark.django_db
DB_ERRORS = (IntegrityError, InternalError)
CASES = ["none", "ended", *(f"active {kind}" for kind in RESTRICTIONS)]


def vial_check_now(cursor: Any) -> None:
    """The vial's deferred check fires now, as at commit; the caller's savepoint rolls back."""
    cursor.execute("SET CONSTRAINTS lineage_vial_destroyed_by_record IMMEDIATE")


def deferred_again() -> None:
    with connection.cursor() as cursor:
        cursor.execute("SET CONSTRAINTS ALL DEFERRED")


def rolled_back(make: Any) -> None:
    """Makes rows in a savepoint that always rolls back: a record without its vials would fail
    the deferred check at the end of the test."""
    with transaction.atomic():
        make()
        transaction.set_rollback(True)


def raw_record(strain: Strain, by: User, **fields: Any) -> DestructionRecord:
    """A record past the services, as a strain without restrictions takes it."""
    now = timezone.now()
    values: dict[str, Any] = {
        "lab_id": strain.lab_id,
        "strain": strain,
        "year": permit_today().year,
        "number": DestructionRecord.objects.count() + 1,
        "destroyed_on": permit_today(),
        "method": DestructionMethod.AUTOCLAVE,
        "verification": VERIFIED,
        "reason": "Contaminated.",
        "recorded_by": by,
        "recorded_at": now,
        "completed_at": now,
        **fields,
    }
    return DestructionRecord.objects.create(**values)


@pytest.fixture
def to_destroy(passage0: Passage, make_batch: MakeBatch, technician: User) -> list[Vial]:
    return mark_to_destroy(technician, vials_of(make_batch(passage0, vial_count=2)))


# A destroyed vial and its record.


@pytest.mark.rule("R-END-03")
def test_a_vial_is_destroyed_only_with_its_record(
    to_destroy: list[Vial], technician: User, runtime_role: CursorWrapper
) -> None:
    vial = to_destroy[0]
    update = "UPDATE lineage_vial SET status = 'destroyed', status_changed_at = now() WHERE id = %s"
    with (
        pytest.raises(DB_ERRORS, match="destroyed only with its destruction record"),
        transaction.atomic(),
    ):
        runtime_role.execute(update, [vial.pk])
        vial_check_now(runtime_role)
    deferred_again()
    # A record completed at another moment than the vial's change does not count either.
    with (
        pytest.raises(DB_ERRORS, match="destroyed only with its destruction record"),
        transaction.atomic(),
    ):
        made = raw_record(vial.batch.strain, technician)
        DestructionVial.objects.create(lab_id=vial.lab_id, record=made, vial=vial)
        runtime_role.execute(update, [vial.pk])
        vial_check_now(runtime_role)
    deferred_again()
    assert Vial.objects.get(pk=vial.pk).status == VialStatus.TO_DESTROY


@pytest.mark.rule("R-END-05")
def test_a_record_holds_vials_destroyed_with_it(to_destroy: list[Vial], technician: User) -> None:
    strain = to_destroy[0].batch.strain
    with pytest.raises(DB_ERRORS, match="holds at least one vial"), transaction.atomic():
        raw_record(strain, technician)
        connection.cursor().execute("SET CONSTRAINTS ALL IMMEDIATE")
    connection.cursor().execute("SET CONSTRAINTS ALL DEFERRED")
    with pytest.raises(DB_ERRORS, match="holds only vials destroyed with it"), transaction.atomic():
        made = raw_record(strain, technician)
        DestructionVial.objects.create(lab_id=made.lab_id, record=made, vial=to_destroy[0])
        connection.cursor().execute("SET CONSTRAINTS ALL IMMEDIATE")
    connection.cursor().execute("SET CONSTRAINTS ALL DEFERRED")


@pytest.mark.rule("R-END-05")
def test_a_record_never_changes_but_once_and_is_never_deleted(
    to_destroy: list[Vial], technician: User, runtime_role: CursorWrapper
) -> None:
    made = destroy(technician, to_destroy)
    where = f" WHERE id = {made.pk}"
    for change, message in (
        ("reason = 'other'", "changes once"),
        ("method = 'other', method_detail = 'x'", "changes once"),
        ("confirmed_by_id = recorded_by_id, confirmed_at = completed_at", "confirmed once"),
    ):
        statement = "UPDATE lineage_destructionrecord SET " + change + where  # noqa: S608 (constants)
        refused(runtime_role, statement, message)
    vials = f"UPDATE lineage_destructionvial SET vial_id = vial_id WHERE record_id = {made.pk}"  # noqa: S608 (a pk)
    refused(runtime_role, vials, "permission denied")
    refused(runtime_role, "DELETE FROM lineage_destructionrecord", "permission denied")
    refused(runtime_role, "DELETE FROM lineage_destructionvial", "permission denied")
    with connection.cursor() as owner:
        owner.execute("RESET ROLE")
        refused(owner, "DELETE FROM lineage_destructionrecord", "never deleted")
        refused(owner, "DELETE FROM lineage_destructionvial", "never change")
        refused(owner, vials, "never change")


@pytest.mark.rule("R-END-05")
def test_an_entry_in_error_is_once_and_then_nothing_changes(
    to_destroy: list[Vial], technician: User
) -> None:
    made = destroy(technician, to_destroy)
    DestructionRecord.objects.filter(pk=made.pk).update(
        status="entered_in_error",
        error_reason="Wrong vials.",
        entered_in_error_by=technician,
        entered_in_error_at=timezone.now(),
    )
    with pytest.raises(DB_ERRORS, match="changes once"), transaction.atomic():
        DestructionRecord.objects.filter(pk=made.pk).update(error_reason="Another reason.")


@pytest.mark.rule("R-END-06")
def test_the_recorder_never_confirms_also_past_the_service(
    *,
    strain: Strain,
    passage0: Passage,
    make_batch: MakeBatch,
    curator: User,
    technician: User,
) -> None:
    restrict(strain, curator, "cz_rat")
    made = destroy(technician, mark_to_destroy(technician, vials_of(make_batch(passage0))))
    now = timezone.now()
    with pytest.raises(DB_ERRORS, match="confirmer_not_recorder"), transaction.atomic():
        DestructionRecord.objects.filter(pk=made.pk).update(
            confirmed_by=technician, confirmed_at=now, completed_at=now
        )
    with pytest.raises(DB_ERRORS, match="witness_not_recorder"), transaction.atomic():
        raw_record(strain, technician, witness=technician, completed_at=None)


@pytest.mark.rule("R-END-05")
def test_a_record_takes_vials_to_destroy_of_its_strain_in_no_other_valid_record(
    *,
    to_destroy: list[Vial],
    regulated: Strain,
    make_batch: MakeBatch,
    technician: User,
) -> None:
    strain = to_destroy[0].batch.strain
    held = vials_of(make_batch(Passage.objects.get(strain=strain, number=0), vial_count=1))[0]
    foreign = mark_to_destroy(
        technician,
        vials_of(make_batch(Passage.objects.get(strain=regulated, number=0), vial_count=1)),
    )[0]
    with transaction.atomic():
        made = raw_record(strain, technician)
        for vial in (held, foreign):
            with (
                pytest.raises(DB_ERRORS, match="takes vials to destroy of its strain"),
                transaction.atomic(),
            ):
                DestructionVial.objects.create(lab_id=made.lab_id, record=made, vial=vial)
        DestructionVial.objects.create(lab_id=made.lab_id, record=made, vial=to_destroy[0])
        other = raw_record(strain, technician)
        with (
            pytest.raises(DB_ERRORS, match="in one valid destruction record"),
            transaction.atomic(),
        ):
            DestructionVial.objects.create(lab_id=made.lab_id, record=other, vial=to_destroy[0])
        transaction.set_rollback(True)  # the records hold vials still to destroy


@pytest.mark.rule("R-END-07")
def test_the_trigger_reads_the_witness_access_of_the_records_own_lab_and_day(
    *,
    strain: Strain,
    lab: Lab,
    other_lab: Lab,
    curator: User,
    manager: User,
    technician: User,
) -> None:
    """The record's guard reads labs_vrataccess of the record's lab as it was at the end of the
    Czech day of the destruction: an entry of another lab, one that ended before the day was
    over, and no entry at all are all refused."""
    restrict(strain, curator, "cz_vrat")
    elsewhere = member_of(other_lab, Role.TECHNICIAN, "elsewhere")
    Membership.objects.create(lab=lab, user=elsewhere, role=Role.TECHNICIAN)
    with_vrat_access(elsewhere, other_lab, member_of(other_lab, Role.MANAGER, "other-manager"))
    ended = member_of(lab, Role.TECHNICIAN, "was-on-the-list")
    end_vrat_access(with_vrat_access(ended, lab, manager), manager)
    none = member_of(lab, Role.TECHNICIAN, "never-on-the-list")
    for person in (elsewhere, ended, none):
        with pytest.raises(DB_ERRORS, match="was on the lab's VRAT access list on that day"):
            rolled_back(
                lambda who=person: raw_record(strain, technician, witness=who, completed_at=None)
            )
    allowed = member_of(lab, Role.TECHNICIAN, "on-the-list")
    with_vrat_access(allowed, lab, manager)
    rolled_back(lambda: raw_record(strain, technician, witness=allowed, completed_at=None))


@pytest.mark.rule("R-END-07")
@pytest.mark.parametrize("had_access_then", [True, False])
def test_the_trigger_reads_the_access_list_of_the_day_of_the_destruction_not_of_today(
    *,
    had_access_then: bool,
    strain: Strain,
    lab: Lab,
    curator: User,
    manager: User,
    technician: User,
    database_roles: CursorWrapper,
) -> None:
    """A record is entered after the fact, so `destroyed_on` and the day of the record differ.
    The guard's `(NEW.destroyed_on + 1)::timestamp AT TIME ZONE 'Europe/Prague'` reads the list
    as it was at the end of the day of the destruction, never as it is now: an access that ended
    after that day passes, one granted after it does not. Written as the runtime role, past
    every service."""
    restrict(strain, curator, "cz_vrat")
    person = member_of(lab, Role.TECHNICIAN, "then-or-now")
    day = permit_today() - timedelta(days=5)
    if had_access_then:
        with time_machine.travel(_prague_noon(day - timedelta(days=1)), tick=False):
            entry = with_vrat_access(person, lab, manager)
        with time_machine.travel(_prague_noon(day + timedelta(days=1)), tick=False):
            end_vrat_access(entry, manager)
    else:
        with time_machine.travel(_prague_noon(day + timedelta(days=1)), tick=False):
            with_vrat_access(person, lab, manager)
    assert has_vrat_access(user=person, lab=lab, at=timezone.now()) is not had_access_then
    database_roles.execute(f"SET LOCAL ROLE {TEST_ROLES.runtime}")
    # The roles fixture made the constraints immediate so it could change the owners; the
    # record's own deferred checks go back to the commit, as every service sets them.
    deferred_again()

    def write() -> DestructionRecord:
        return raw_record(strain, technician, witness=person, destroyed_on=day, completed_at=None)

    if had_access_then:
        rolled_back(write)
    else:
        with pytest.raises(DB_ERRORS, match="was on the lab's VRAT access list on that day"):
            rolled_back(write)
    database_roles.execute("RESET ROLE")


# The parity: Python and the trigger agree, case by case.


@pytest.fixture
def case_strain(
    request: pytest.FixtureRequest, strain: Strain, curator: User, manager: User
) -> Strain:
    case: str = request.param
    if case == "none":
        restrict(strain, curator, "none")
    elif case == "ended":
        restrict(strain, curator, "none")
        with audit_context(channel=Channel.API, actor=curator, request_id="req-gmo"):
            strains.strain_restriction_add(
                access=access_for(curator), strain=strain, restriction=GMO, reason="listed"
            )
        end_restriction(
            StrainRestriction.objects.get(strain=strain), proposer=curator, confirmer=manager
        )
    else:
        restrict(strain, curator, case.split()[1])
    return strain


@pytest.fixture
def witness(lab: Lab, manager: User) -> User:
    """A technician on the lab's VRAT access list, as a VRAT's witness must be (#167)."""
    person = member_of(lab, Role.TECHNICIAN, "w")
    with_vrat_access(person, lab, manager)
    return person


@pytest.mark.rule("R-END-06", "R-KIND-09")
@pytest.mark.parametrize("case_strain", CASES, indirect=True)
def test_the_trigger_asks_a_second_person_exactly_when_python_does(
    *,
    case_strain: Strain,
    passage0: Passage,
    make_batch: MakeBatch,
    technician: User,
    witness: User,
    lab: Lab,
) -> None:
    """The record's guard (a completed record at recording) and the vial's deferred trigger (a
    destroyed vial of a completed record nobody confirmed), each against required_for."""
    required = services.required_for(case_strain)
    extra: dict[str, Any] = {"witness": witness}
    if required.authorised_method:
        extra["authorisation"] = LabAuthorisation.objects.get(
            lab=lab, kind=AuthorisationKind.QUARANTINE_PEST
        )
    try:
        rolled_back(lambda: raw_record(case_strain, technician, **extra))
        guard_refused = False
    except DB_ERRORS as error:
        assert "only when a second person confirms" in str(error)
        guard_refused = True
    assert guard_refused == required.confirmation
    # The vial's trigger alone: the record's guard is off in this test's transaction. PostgreSQL
    # refuses ALTER TABLE while trigger events are pending, so they run first.
    vial = mark_to_destroy(technician, vials_of(make_batch(passage0, vial_count=1)))[0]
    with connection.cursor() as cursor:
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
        cursor.execute(
            "ALTER TABLE lineage_destructionrecord DISABLE TRIGGER lineage_destructionrecord_guard"
        )
    deferred_again()
    try:
        with transaction.atomic(), connection.cursor() as cursor:
            made = raw_record(case_strain, technician, **extra)
            DestructionVial.objects.create(lab_id=made.lab_id, record=made, vial=vial)
            cursor.execute(
                "UPDATE lineage_vial SET status = 'destroyed', status_changed_at = %s"
                " WHERE id = %s",
                [made.completed_at, vial.pk],
            )
            vial_check_now(cursor)
        vial_refused = False
    except DB_ERRORS as error:
        assert "confirmed by a second person for a regulated strain" in str(error)
        vial_refused = True
    deferred_again()
    assert vial_refused == required.confirmation


RULES: dict[str, dict[str, Any]] = {
    "no verification": {"verification": ""},
    "no witness": {"witness": None},
    # The witness is replaced by a member who is on no VRAT access list (#167, the owner's
    # decision of 2026-11-03).
    "a witness without VRAT access": {"witness": "no access"},
    "alive to a firm": {
        "contractor": "Firm s.r.o.",
        "handover_document": "PP-1",
        "inactivated_in_lab": False,
    },
    "another method than the permit's": {"method": DestructionMethod.CHEMICAL},
}


@pytest.mark.rule("R-END-07", "R-END-08", "R-END-09", "R-END-10")
@pytest.mark.parametrize("rule", sorted(RULES))
@pytest.mark.parametrize("case_strain", CASES, indirect=True)
def test_the_trigger_holds_each_kinds_rule_exactly_when_python_does(
    *, case_strain: Strain, rule: str, technician: User, witness: User, lab: Lab
) -> None:
    required = services.required_for(case_strain)
    permit = LabAuthorisation.objects.get(lab=lab, kind=AuthorisationKind.QUARANTINE_PEST)
    changes = dict(RULES[rule])
    if changes.get("witness") == "no access":
        changes["witness"] = member_of(lab, Role.TECHNICIAN, "no-access")
    data = new_destruction([], **{"witness": witness, **changes})
    try:
        authorisation = _check_rules(required, data, technician, lab)
        python_refused = False
    except DomainError:
        authorisation = permit if required.authorised_method else None
        python_refused = True
    fields: dict[str, Any] = {
        "method": data.method,
        "verification": data.verification,
        "witness": data.witness,
        "contractor": data.contractor,
        "handover_document": data.handover_document,
        "inactivated_in_lab": data.inactivated_in_lab,
        "authorisation": authorisation,
    }
    if required.confirmation:
        fields["completed_at"] = None
    try:
        rolled_back(lambda: raw_record(case_strain, technician, **fields))
        trigger_refused = False
    except DB_ERRORS:
        trigger_refused = True
    assert trigger_refused == python_refused, (rule, required.kinds)
