"""Checks of a batch and its release through the services (#17, ADR 0008, D16): one event per
check that names its strain, the vial checked consumed through the vial service, corrections
that supersede or enter a check in error, the release rule for every combination of the three
kinds, the moves the checks make on their own, and refusals that change nothing."""

import itertools
from collections.abc import Callable
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest
from django.db import IntegrityError, InternalError, connection, transaction

from cultures.audit.context import AuditContext, MissingAuditContext, audit_context
from cultures.audit.models import AuditEvent, Channel
from cultures.biosafety.policy import permit_today
from cultures.core.exceptions import DomainError, Forbidden, RuleViolation
from cultures.labs.access import Access, access_for
from cultures.labs.models import Lab, Membership
from cultures.labs.permissions import Role
from cultures.lineage import services
from cultures.lineage.models import (
    METHODS_BY_KIND,
    Batch,
    BatchCheck,
    BatchStatus,
    CheckKind,
    CheckMethod,
    CheckResult,
    CheckStatus,
    CheckUnit,
    Passage,
    Vial,
    VialPlacement,
    VialStatus,
)
from cultures.storage.tests.conftest import Tree
from cultures.strains.models import Strain
from cultures.users.models import User

from .support import (
    PLATE_COUNT,
    MakeBatch,
    new_check,
    open_place,
    pass_all,
    record,
    snapshot,
    vials_of,
)

pytestmark = pytest.mark.django_db
DB_ERRORS = (IntegrityError, InternalError)
REASON = "the identity and viability checks after preservation passed"


def refused(
    error: type[DomainError], code: str, call: Callable[[], object], attr: str | None = None
) -> DomainError:
    before = snapshot()
    with pytest.raises(error) as raised:
        call()
    assert (raised.value.code, raised.value.attr) == (code, attr)
    assert snapshot() == before
    return raised.value


def last_pk() -> int:
    return AuditEvent.objects.order_by("-pk").values_list("pk", flat=True).first() or 0


def events(since: int) -> list[AuditEvent]:
    return list(AuditEvent.objects.filter(pk__gt=since).order_by("pk"))


def fresh(batch: Batch) -> Batch:
    return Batch.objects.get(pk=batch.pk)


@pytest.fixture
def batch(make_batch: MakeBatch, passage0: Passage) -> Batch:
    """Three vials of distribution stock, preserved on 2026-10-01, pending its checks."""
    return make_batch(passage0)


def as_curator(curator: User) -> Any:
    return audit_context(channel=Channel.API, actor=curator, request_id="req-curator")


# Recording.


def test_a_technician_records_a_check_and_it_is_one_event(
    as_technician: AuditContext, technician: User, batch: Batch, strain: Strain
) -> None:
    start = last_pk()
    check = record(
        technician,
        batch,
        CheckKind.VIABILITY,
        method=CheckMethod.PLATE_COUNT,
        method_detail="  TSA,   30 °C ",
        note=" 2.5 x 10^8 CFU/mL after thawing ",
        **PLATE_COUNT,
    )
    assert (check.lab_id, check.batch, check.performed_by, check.status) == (
        batch.lab_id,
        batch,
        technician,
        CheckStatus.VALID,
    )
    assert (check.method_detail, check.note, check.value, check.unit) == (
        "TSA, 30 °C",
        "2.5 x 10^8 CFU/mL after thawing",
        Decimal("250000000"),
        CheckUnit.CFU_PER_ML,
    )
    recorded = events(start)
    assert [e.event_type for e in recorded] == ["batch_check_recorded"]
    event = recorded[0]
    assert (event.actor, event.lab_id, event.strain_id, event.subject_id) == (
        technician,
        batch.lab_id,
        strain.public_id,
        check.public_id,
    )
    assert event.changes == {
        "batch": [None, str(batch.public_id)],
        "kind": [None, "viability"],
        "stage": [None, "after_preservation"],
        "checked_on": [None, "2026-10-02"],
        "method": [None, "plate_count"],
        "method_detail": [None, "TSA, 30 °C"],
        "result": [None, "pass"],
        "value": [None, "250000000.0000"],
        "unit": [None, "cfu_per_ml"],
        "vial": [None, None],
        "note": [None, "2.5 x 10^8 CFU/mL after thawing"],
        "supersedes": [None, None],
    }
    assert fresh(batch).status == BatchStatus.PENDING_CHECK  # one kind is not a release


def test_the_vial_checked_is_consumed_and_leaves_its_box(
    *,
    as_technician: AuditContext,
    technician: User,
    make_batch: MakeBatch,
    passage0: Passage,
    tree: Tree,
    strain: Strain,
) -> None:
    batch = make_batch(passage0, vial_count=2, box=tree.box)
    vial = vials_of(batch)[0]
    assert open_place(vial) is not None
    start = last_pk()
    check = record(technician, batch, vial=vial)
    used = Vial.objects.get(pk=vial.pk)
    assert (used.status, check.vial) == (VialStatus.CONSUMED, used)
    assert used.status_changed_at is not None
    assert open_place(vial) is None
    closed = VialPlacement.objects.get(vial=vial)
    assert (closed.removal_reason, closed.removed_by) == ("consumed", technician)
    recorded = events(start)
    assert [e.event_type for e in recorded] == ["vial_status_changed", "batch_check_recorded"]
    assert recorded[0].reason == "Used for a viability check of batch 1."
    assert recorded[0].changes["status"] == ["available", "consumed"]
    assert recorded[0].changes["location"][1] is None
    assert {e.strain_id for e in recorded} == {strain.public_id}
    assert recorded[1].changes["vial"] == [None, str(vial.public_id)]


def test_one_vial_serves_the_checks_of_several_kinds(
    as_technician: AuditContext, technician: User, batch: Batch
) -> None:
    vial = vials_of(batch)[0]
    record(technician, batch, CheckKind.VIABILITY, vial=vial)
    start = last_pk()
    purity = record(technician, batch, CheckKind.PURITY, vial=vial)
    assert purity.vial == vial
    assert [e.event_type for e in events(start)] == ["batch_check_recorded"]
    assert Vial.objects.filter(batch=batch, status=VialStatus.CONSUMED).count() == 1


@pytest.mark.parametrize("status", [VialStatus.LOST, VialStatus.QUARANTINED, VialStatus.CONSUMED])
def test_a_vial_that_is_not_available_is_not_checked(
    as_technician: AuditContext, technician: User, batch: Batch, status: VialStatus
) -> None:
    """Consumed by a revival is not consumed by a check: it never served this batch's checks."""
    vial = vials_of(batch)[0]
    if status == VialStatus.CONSUMED:
        services.vial_revive(access=access_for(technician), vial=vial)
    else:
        services.vial_transition(
            access=access_for(technician), vial=vial, status=status, reason="not in its place"
        )
    refused(
        services.VialNotAvailable,
        "vial_not_available",
        lambda: record(technician, batch, vial=vial),
    )


def test_a_vial_of_another_batch_is_unknown_here(
    as_technician: AuditContext, technician: User, batch: Batch, make_batch: MakeBatch
) -> None:
    other = vials_of(make_batch(batch.passage, vial_count=1))[0]
    refused(
        services.InvalidCheck,
        "does_not_exist",
        lambda: record(technician, batch, vial=other),
        attr="vial",
    )


@pytest.mark.parametrize(
    ("changes", "code", "attr"),
    [
        ({"kind": CheckKind.PURITY, "method": CheckMethod.PLATE_COUNT}, "invalid", "method"),
        ({"kind": CheckKind.IDENTITY, "method": CheckMethod.GROWTH}, "invalid", "method"),
        ({"method": CheckMethod.OTHER}, "required", "method_detail"),
        ({"method": CheckMethod.OTHER, "method_detail": "   "}, "required", "method_detail"),
        ({"value": Decimal(5)}, "required", "unit"),
        ({"unit": CheckUnit.PERCENT}, "required", "value"),
        ({"value": Decimal(-1), "unit": CheckUnit.CFU_PER_ML}, "invalid", "value"),
        ({"value": Decimal("100.5"), "unit": CheckUnit.PERCENT}, "invalid", "value"),
        ({"result": CheckResult.REDUCED, "note": "  "}, "required", "note"),
        ({"checked_on": date(2026, 9, 30)}, "invalid", "checked_on"),  # before preservation
    ],
)
def test_a_check_is_refused_on_its_field(
    *,
    as_technician: AuditContext,
    technician: User,
    batch: Batch,
    changes: dict[str, Any],
    code: str,
    attr: str,
) -> None:
    kind = changes.pop("kind", CheckKind.VIABILITY)
    refused(
        services.InvalidCheck,
        code,
        lambda: record(technician, batch, kind, **changes),
        attr=attr,
    )


def test_a_check_is_not_dated_in_the_future_but_today_is_fine(
    as_technician: AuditContext, technician: User, batch: Batch
) -> None:
    tomorrow = permit_today() + timedelta(days=1)
    refused(
        services.InvalidCheck,
        "invalid",
        lambda: record(technician, batch, checked_on=tomorrow),
        attr="checked_on",
    )
    assert record(technician, batch, checked_on=permit_today()).checked_on == permit_today()


def test_a_percentage_of_100_and_other_methods_described_are_fine(
    as_technician: AuditContext, technician: User, batch: Batch
) -> None:
    check = record(
        technician,
        batch,
        method=CheckMethod.OTHER,
        method_detail="Flow cytometry",
        value=Decimal(100),
        unit=CheckUnit.PERCENT,
    )
    assert (check.method, check.method_detail, check.value) == (
        "other",
        "Flow cytometry",
        Decimal(100),
    )


def put_status(batch: Batch, status: str, reason: str = "set for the test") -> None:
    """Past the services, along an allowed edge (the trigger still checks it)."""
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE lineage_batch SET status = %s, status_reason = %s, status_changed_at = now()"
            " WHERE id = %s",
            [status, reason, batch.pk],
        )


def test_an_exhausted_batch_is_not_checked_released_or_held(
    as_technician: AuditContext, technician: User, curator: User, batch: Batch
) -> None:
    put_status(batch, "exhausted", "the last vial was sent")
    refused(services.BatchExhausted, "batch_exhausted", lambda: record(technician, batch))
    for decide in (services.batch_release, services.batch_hold):
        refused(
            services.BatchExhausted,
            "batch_exhausted",
            lambda d=decide: d(access=access_for(curator), batch=batch, reason="r"),  # type: ignore[misc]
        )


# The release rule: the latest valid check of each kind passed (reduced counts as passed).

RESULTS = (None, CheckResult.PASS, CheckResult.REDUCED, CheckResult.FAIL)
COMBINATIONS = list(itertools.product(RESULTS, repeat=3))


class Rollback(Exception):
    pass


def trigger_releases(batch: Batch) -> bool:
    """Whether the batch trigger lets a writer that skips the services release it now."""
    try:
        with transaction.atomic():
            put_status(batch, "released")
            raise Rollback
    except Rollback:
        return True
    except DB_ERRORS as error:
        assert "released only after passed checks" in str(error), error
        return False


def test_every_combination_is_tried() -> None:
    assert len(COMBINATIONS) == 64
    assert len(set(COMBINATIONS)) == 64


@pytest.mark.parametrize("results", COMBINATIONS, ids=lambda r: "-".join(str(x) for x in r))
def test_the_release_rule_for_every_combination(
    *,
    as_technician: AuditContext,
    technician: User,
    curator: User,
    batch: Batch,
    results: tuple[CheckResult | None, ...],
) -> None:
    for kind, result in zip(CheckKind, results, strict=True):
        if result is not None:
            record(technician, batch, kind, result=result)
    failed = CheckResult.FAIL in results
    passes = not failed and None not in results
    assert fresh(batch).status == (BatchStatus.ON_HOLD if failed else BatchStatus.PENDING_CHECK)
    assert trigger_releases(fresh(batch)) == passes
    with as_curator(curator):
        if passes:
            released = services.batch_release(
                access=access_for(curator), batch=batch, reason=REASON
            )
            assert (released.status, released.status_reason) == (BatchStatus.RELEASED, REASON)
        else:
            error = refused(
                services.ChecksNotPassed,
                "checks_not_passed",
                lambda: services.batch_release(
                    access=access_for(curator), batch=batch, reason=REASON
                ),
            )
            missing = [
                kind
                for kind, result in zip(CheckKind, results, strict=True)
                if result not in (CheckResult.PASS, CheckResult.REDUCED)
            ]
            assert str(error.detail).endswith(f"Not passed yet: {services.kinds_text(missing)}.")


def test_the_latest_check_of_a_kind_counts_by_its_day(
    as_technician: AuditContext, technician: User, curator: User, batch: Batch
) -> None:
    """A pass after a failure clears the way for a release; a failure recorded later but dated
    before a pass is history, not the latest."""
    record(technician, batch, CheckKind.VIABILITY, result=CheckResult.FAIL)
    assert fresh(batch).status == BatchStatus.ON_HOLD
    record(technician, batch, CheckKind.VIABILITY, checked_on=date(2026, 10, 3))
    record(technician, batch, CheckKind.IDENTITY, checked_on=date(2026, 10, 3))
    record(technician, batch, CheckKind.PURITY, checked_on=date(2026, 10, 3))
    assert fresh(batch).status == BatchStatus.ON_HOLD  # a hold is lifted by a curator only
    record(technician, batch, CheckKind.PURITY, result=CheckResult.FAIL)  # dated 2026-10-02
    assert services.not_passed(services.latest_checks(batch)) == []
    with as_curator(curator):
        services.batch_release(access=access_for(curator), batch=batch, reason=REASON)
    assert fresh(batch).status == BatchStatus.RELEASED


def test_the_same_day_takes_the_check_recorded_last(
    as_technician: AuditContext, technician: User, batch: Batch
) -> None:
    record(technician, batch, CheckKind.PURITY)
    record(technician, batch, CheckKind.PURITY, result=CheckResult.FAIL)
    latest = services.latest_checks(batch)
    assert latest[CheckKind.PURITY].result == CheckResult.FAIL
    assert CheckKind.IDENTITY not in latest


# What the checks move on their own.


def test_a_failed_check_holds_a_released_batch_with_its_words(
    as_technician: AuditContext, technician: User, curator: User, batch: Batch, strain: Strain
) -> None:
    pass_all(technician, batch)
    with as_curator(curator):
        services.batch_release(access=access_for(curator), batch=batch, reason=REASON)
    start = last_pk()
    record(
        technician,
        batch,
        CheckKind.VIABILITY,
        stage="periodic",
        checked_on=date(2026, 10, 9),
        result=CheckResult.FAIL,
    )
    held = fresh(batch)
    reason = "The viability check of 2026-10-09 failed."
    assert (held.status, held.status_reason) == (BatchStatus.ON_HOLD, reason)
    recorded = events(start)
    assert [e.event_type for e in recorded] == ["batch_check_recorded", "batch_status_changed"]
    moved = recorded[1]
    assert (moved.actor, moved.reason, moved.strain_id, moved.subject_id) == (
        technician,
        reason,
        strain.public_id,
        batch.public_id,
    )
    assert moved.changes == {"status": ["released", "on_hold"]}


def test_two_failed_kinds_are_named_in_one_reason(
    as_technician: AuditContext, technician: User, batch: Batch
) -> None:
    record(technician, batch, CheckKind.PURITY, result=CheckResult.FAIL)
    record(
        technician, batch, CheckKind.IDENTITY, result=CheckResult.FAIL, checked_on=date(2026, 10, 4)
    )
    held = fresh(batch)
    assert held.status_reason == "The purity check of 2026-10-02 failed."  # held at the first
    assert held.status_changed_at is not None


def test_a_released_batch_that_loses_a_passed_check_waits_again(
    as_technician: AuditContext, technician: User, curator: User, batch: Batch
) -> None:
    identity, _, _ = pass_all(technician, batch)
    with as_curator(curator):
        services.batch_release(access=access_for(curator), batch=batch, reason=REASON)
    start = last_pk()
    services.check_enter_in_error(
        access=access_for(technician), check=identity, reason="recorded on the wrong batch"
    )
    waiting = fresh(batch)
    assert (waiting.status, waiting.status_reason) == (
        BatchStatus.PENDING_CHECK,
        "No valid identity check is left after a correction.",
    )
    assert [e.event_type for e in events(start)] == [
        "batch_check_entered_in_error",
        "batch_status_changed",
    ]
    row = BatchCheck.objects.get(pk=identity.pk)
    assert (row.status, row.reason) == (CheckStatus.ENTERED_IN_ERROR, "recorded on the wrong batch")


def test_an_older_failure_holds_a_released_batch_when_the_pass_after_it_goes(
    as_technician: AuditContext, technician: User, curator: User, batch: Batch
) -> None:
    record(technician, batch, CheckKind.PURITY, result=CheckResult.FAIL)
    _, purity, _ = pass_all(technician, batch, checked_on=date(2026, 10, 3))
    with as_curator(curator):
        services.batch_release(access=access_for(curator), batch=batch, reason=REASON)
    services.check_enter_in_error(
        access=access_for(technician), check=purity, reason="typing error"
    )
    assert fresh(batch).status == BatchStatus.ON_HOLD
    assert fresh(batch).status_reason == "The purity check of 2026-10-02 failed."


def test_entering_a_failure_in_error_never_releases(
    as_technician: AuditContext, technician: User, batch: Batch
) -> None:
    pass_all(technician, batch)
    failure = record(technician, batch, CheckKind.IDENTITY, result=CheckResult.FAIL)
    assert fresh(batch).status == BatchStatus.ON_HOLD
    start = last_pk()
    services.check_enter_in_error(access=access_for(technician), check=failure, reason="mix-up")
    assert fresh(batch).status == BatchStatus.ON_HOLD
    assert [e.event_type for e in events(start)] == ["batch_check_entered_in_error"]


# Corrections.


def test_a_correction_supersedes_the_wrong_check_in_one_step(
    as_technician: AuditContext, technician: User, curator: User, batch: Batch, strain: Strain
) -> None:
    pass_all(technician, batch)
    with as_curator(curator):
        services.batch_release(access=access_for(curator), batch=batch, reason=REASON)
    wrong = BatchCheck.objects.get(batch=batch, kind=CheckKind.VIABILITY)
    start = last_pk()
    right = record(
        technician,
        batch,
        CheckKind.VIABILITY,
        supersedes=wrong,
        reason=" the count was typed with a wrong exponent ",
        **PLATE_COUNT,
    )
    assert right.supersedes == wrong
    old = BatchCheck.objects.get(pk=wrong.pk)
    assert (old.status, old.reason) == (
        CheckStatus.ENTERED_IN_ERROR,
        "the count was typed with a wrong exponent",
    )
    recorded = events(start)
    assert [e.event_type for e in recorded] == [
        "batch_check_recorded",
        "batch_check_entered_in_error",
    ]
    assert recorded[0].changes["supersedes"] == [None, str(wrong.public_id)]
    assert recorded[1].subject_id == wrong.public_id
    assert recorded[1].changes == {"status": ["valid", "entered_in_error"]}
    assert {e.strain_id for e in recorded} == {strain.public_id}
    assert fresh(batch).status == BatchStatus.RELEASED  # a passed correction keeps it released


def test_a_failed_correction_holds_the_batch(
    as_technician: AuditContext, technician: User, batch: Batch
) -> None:
    wrong = record(technician, batch, CheckKind.PURITY)
    record(
        technician,
        batch,
        CheckKind.PURITY,
        supersedes=wrong,
        reason="a contaminant was seen on the second plate",
        result=CheckResult.FAIL,
    )
    assert fresh(batch).status == BatchStatus.ON_HOLD


@pytest.mark.parametrize("other", ["kind", "batch"])
def test_a_correction_replaces_a_check_of_the_same_batch_and_kind(
    as_technician: AuditContext,
    technician: User,
    batch: Batch,
    make_batch: MakeBatch,
    other: str,
) -> None:
    target = batch if other == "kind" else make_batch(batch.passage, vial_count=1)
    wrong = record(technician, target, CheckKind.PURITY)
    refused(
        services.InvalidCheck,
        "does_not_exist",
        lambda: record(
            technician,
            batch,
            CheckKind.IDENTITY if other == "kind" else CheckKind.PURITY,
            supersedes=wrong,
            reason="wrong",
        ),
        attr="supersedes",
    )


def test_a_correction_needs_a_reason_and_a_valid_check(
    as_technician: AuditContext, technician: User, batch: Batch
) -> None:
    wrong = record(technician, batch)
    refused(
        RuleViolation,
        "reason_required",
        lambda: record(technician, batch, supersedes=wrong, reason="  "),
        attr="reason",
    )
    services.check_enter_in_error(access=access_for(technician), check=wrong, reason="mix-up")
    refused(
        services.CheckEnteredInError,
        "check_entered_in_error",
        lambda: record(technician, batch, supersedes=wrong, reason="again"),
    )
    refused(
        services.CheckEnteredInError,
        "check_entered_in_error",
        lambda: services.check_enter_in_error(
            access=access_for(technician), check=wrong, reason="again"
        ),
    )
    valid = record(technician, batch)
    refused(
        RuleViolation,
        "reason_required",
        lambda: services.check_enter_in_error(
            access=access_for(technician), check=valid, reason=""
        ),
        attr="reason",
    )


# Release and hold.


def test_a_curator_holds_and_releases_with_a_reason(
    as_technician: AuditContext, technician: User, curator: User, batch: Batch, strain: Strain
) -> None:
    access = access_for(curator)
    with as_curator(curator):
        start = last_pk()
        held = services.batch_hold(access=access, batch=batch, reason="the freezer alarm rang")
        assert (held.status, held.status_reason) == (BatchStatus.ON_HOLD, "the freezer alarm rang")
        again = last_pk()
        services.batch_hold(access=access, batch=batch, reason="still")  # held again: nothing
        assert last_pk() == again
    pass_all(technician, batch)
    with as_curator(curator):
        services.batch_release(access=access, batch=batch, reason=REASON)
        again = last_pk()
        services.batch_release(access=access, batch=batch, reason="again")
        assert last_pk() == again
        services.batch_hold(access=access, batch=batch, reason="a complaint from a recipient")
    recorded = [e for e in events(start) if e.event_type == "batch_status_changed"]
    assert [(e.changes["status"], e.reason, e.actor) for e in recorded] == [
        (["pending_check", "on_hold"], "the freezer alarm rang", curator),
        (["on_hold", "released"], REASON, curator),
        (["released", "on_hold"], "a complaint from a recipient", curator),
    ]
    assert {e.strain_id for e in recorded} == {strain.public_id}


@pytest.mark.parametrize("decide", ["batch_release", "batch_hold"])
def test_a_decision_needs_a_reason(curator: User, batch: Batch, decide: str) -> None:
    with as_curator(curator):
        refused(
            RuleViolation,
            "reason_required",
            lambda: getattr(services, decide)(access=access_for(curator), batch=batch, reason=" "),
            attr="reason",
        )


@pytest.mark.parametrize("decide", ["batch_release", "batch_hold"])
def test_a_technician_does_not_decide(
    as_technician: AuditContext, technician: User, batch: Batch, decide: str
) -> None:
    pass_all(technician, batch)
    refused(
        Forbidden,
        "permission_denied",
        lambda: getattr(services, decide)(access=access_for(technician), batch=batch, reason="r"),
    )


# Who may, and the audit context, for every check service (test_services.py has the others).

Scenario = Callable[[User, User, Batch], Callable[[], object]]


def _check_scenario(t: User, c: User, b: Batch) -> Callable[[], object]:
    return lambda: record(t, b)


def _error_scenario(t: User, c: User, b: Batch) -> Callable[[], object]:
    check = record(t, b)
    return lambda: services.check_enter_in_error(access=access_for(t), check=check, reason="r")


def _release_scenario(t: User, c: User, b: Batch) -> Callable[[], object]:
    pass_all(t, b)
    return lambda: services.batch_release(access=access_for(c), batch=b, reason=REASON)


def _hold_scenario(t: User, c: User, b: Batch) -> Callable[[], object]:
    return lambda: services.batch_hold(access=access_for(c), batch=b, reason="a doubt")


# Each one: set up as the technician, then the call (as the technician, or the curator for a
# decision). The setup runs inside the technician's audit context.
CHECK_SCENARIOS: dict[str, Scenario] = {
    "check_record": _check_scenario,
    "check_enter_in_error": _error_scenario,
    "batch_release": _release_scenario,
    "batch_hold": _hold_scenario,
}
DECISIONS = {"batch_release", "batch_hold"}


@pytest.mark.parametrize("name", sorted(CHECK_SCENARIOS))
def test_every_check_event_names_the_strain(
    *,
    name: str,
    as_technician: AuditContext,
    technician: User,
    curator: User,
    batch: Batch,
    strain: Strain,
) -> None:
    call = CHECK_SCENARIOS[name](technician, curator, batch)
    start = last_pk()
    call()
    recorded = events(start)
    assert recorded, name
    assert {e.strain_id for e in recorded} == {strain.public_id}, name
    assert {e.lab_id for e in recorded} == {batch.lab_id}, name


@pytest.mark.parametrize("name", sorted(CHECK_SCENARIOS))
def test_a_member_demoted_since_the_request_began_is_refused(
    *,
    name: str,
    as_technician: AuditContext,
    technician: User,
    curator: User,
    lab: Lab,
    batch: Batch,
) -> None:
    call = CHECK_SCENARIOS[name](technician, curator, batch)
    actor = curator if name in DECISIONS else technician
    lower = Role.TECHNICIAN if name in DECISIONS else Role.VIEWER
    Membership.objects.filter(user=actor, lab=lab).update(role=lower)
    refused(Forbidden, "permission_denied", call)


@pytest.mark.parametrize("name", sorted(CHECK_SCENARIOS))
def test_every_check_service_needs_an_audit_context(
    name: str, technician: User, curator: User, batch: Batch
) -> None:
    with audit_context(channel=Channel.API, actor=technician, request_id="req-setup"):
        call = CHECK_SCENARIOS[name](technician, curator, batch)
    before = snapshot()
    with pytest.raises(MissingAuditContext):
        call()
    assert snapshot() == before


def test_the_access_object_is_not_trusted_for_the_role(
    as_technician: AuditContext, technician: User, curator: User, batch: Batch
) -> None:
    """An access object built while the curator was one; the role is read again under the lock."""
    pass_all(technician, batch)
    access: Access = access_for(curator)
    Membership.objects.filter(user=curator).update(role=Role.VIEWER)
    with as_curator(curator):
        refused(
            Forbidden,
            "permission_denied",
            lambda: services.batch_release(access=access, batch=batch, reason=REASON),
        )


def test_new_check_defaults_name_a_method_of_each_kind() -> None:
    for kind in CheckKind:
        assert new_check(kind).method in METHODS_BY_KIND[kind]
