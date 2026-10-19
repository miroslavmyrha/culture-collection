"""Deposits change only through the services: the intake states, the strain and passage 0
at acceptance, the biosafety gates there, versioned terms, contacts kept out of every event,
and refusals that change nothing and record nothing."""

from collections.abc import Callable
from datetime import date, timedelta
from typing import Any

import pytest
from django.db.models import Model

from cultures.audit.context import AuditContext, MissingAuditContext
from cultures.audit.models import AuditEvent, RowChange
from cultures.biosafety.models import AuthorisationKind
from cultures.biosafety.policy import AuthorisationRequired, permit_today
from cultures.core.exceptions import DomainError, Forbidden, RuleViolation
from cultures.deposits import services
from cultures.deposits.models import (
    AbsScope,
    Condition,
    Contact,
    Decision,
    Deposit,
    Depositor,
    DepositStatus,
    DepositTerms,
    MtaTemplate,
    TermsUse,
    Use,
)
from cultures.deposits.services import ContactInput, NewDeposit
from cultures.labs.access import Access, access_for
from cultures.labs.models import Lab, Membership
from cultures.labs.permissions import Role
from cultures.labs.tests.test_lock_invariant import public_services
from cultures.lineage.models import Passage
from cultures.strains.models import Strain, StrainCounter, StrainStatus
from cultures.strains.services import RiskGroupRefused
from cultures.taxonomy.models import Taxon
from cultures.users.models import User

from .support import (
    ALL_PERMITTED,
    DUAL_USE,
    JANA,
    QUARANTINE,
    VRAT,
    MakeDeposit,
    MakeDepositor,
    facts,
    make_permit,
    terms,
)

pytestmark = pytest.mark.django_db

TABLES: tuple[type[Model], ...] = (
    Contact,
    Depositor,
    MtaTemplate,
    Deposit,
    DepositTerms,
    TermsUse,
    Strain,
    StrainCounter,
    Passage,
)


def snapshot() -> tuple[Any, ...]:
    """Every table the services write, every event and every row change."""
    rows = tuple(list(model._default_manager.order_by("pk").values()) for model in TABLES)
    return (*rows, AuditEvent.objects.count(), RowChange.objects.count())


def refused(
    error: type[DomainError], code: str, call: Callable[[], object], attr: str | None = None
) -> DomainError:
    before = snapshot()
    with pytest.raises(error) as raised:
        call()
    assert (raised.value.code, raised.value.attr) == (code, attr)
    assert snapshot() == before
    return raised.value


def receive(access: Access, lab: Lab, depositor: Depositor, **changes: Any) -> Deposit:
    values: dict[str, Any] = {
        "depositor": depositor,
        "received_on": date(2026, 10, 1),
        "condition": Condition.INTACT,
        "name_as_received": "Testella exempli D1",
        "terms": terms(),
        **changes,
    }
    return services.deposit_receive(access=access, lab=lab, data=NewDeposit(**values))


def events() -> list[tuple[str, Any, Any]]:
    return list(AuditEvent.objects.order_by("pk").values_list("event_type", "strain_id", "lab_id"))


# Depositors and their contacts.


def test_a_curator_adds_a_depositor_and_the_event_holds_no_personal_value(
    *, as_curator: AuditContext, curator: User, curator_access: Access, lab: Lab
) -> None:
    depositor = services.depositor_create(
        access=curator_access,
        lab=lab,
        contact=ContactInput("  Jana   Vzorová ", " jana@example.org ", " Vzorová 1 \n\n Brno "),
        institution=" Example  University ",
    )
    contact = depositor.contact
    assert (contact.name, contact.email, contact.postal_address, contact.lab_id) == (
        "Jana Vzorová",
        "jana@example.org",
        "Vzorová 1\nBrno",
        lab.pk,
    )
    assert (depositor.institution, depositor.lab_id) == ("Example University", lab.pk)
    event = AuditEvent.objects.get()
    assert (event.event_type, event.actor, event.lab, event.subject_id, event.strain_id) == (
        "depositor_created",
        curator,
        lab,
        depositor.public_id,
        None,
    )
    assert event.changes == {
        "contact": [None, str(contact.public_id)],
        "institution": [None, "Example University"],
        "name": "changed",
        "email": "changed",
        "postal_address": "changed",
    }
    # The contact table is outside the row audit: no row change holds the person.
    assert not RowChange.objects.filter(table_label__startswith="deposits.contact").exists()
    assert "Vzorov" not in str(list(RowChange.objects.values_list("new", flat=True)))


def test_a_depositor_change_records_which_fields_changed_never_the_values(
    *, as_curator: AuditContext, curator_access: Access, depositor: Depositor
) -> None:
    services.depositor_update(
        access=curator_access,
        depositor=depositor,
        contact=ContactInput(JANA.name, "new@example.org", JANA.postal_address),
        institution="Other University",
    )
    event = AuditEvent.objects.latest("pk")
    assert event.event_type == "depositor_changed"
    assert event.changes == {
        "email": "changed",
        "institution": ["Example University", "Other University"],
    }
    depositor.contact.refresh_from_db()
    assert depositor.contact.email == "new@example.org"
    count = AuditEvent.objects.count()
    services.depositor_update(
        access=curator_access,
        depositor=depositor,
        contact=ContactInput(JANA.name, "new@example.org", JANA.postal_address),
        institution="Other University",
    )
    assert AuditEvent.objects.count() == count  # the same values again record nothing


@pytest.mark.parametrize(
    ("contact", "attr"),
    [(ContactInput("  "), "name"), (ContactInput("Jana", "jana at example.org"), "email")],
)
def test_a_depositor_needs_a_name_and_a_real_address(
    *, as_curator: AuditContext, curator_access: Access, lab: Lab, contact: ContactInput, attr: str
) -> None:
    refused(
        services.InvalidDeposit,
        "invalid",
        lambda: services.depositor_create(access=curator_access, lab=lab, contact=contact),
        attr,
    )


def test_an_erasure_empties_the_contact_and_keeps_the_depositor(
    *, as_curator: AuditContext, curator_access: Access, depositor: Depositor
) -> None:
    contact = depositor.contact
    erased = services.contact_erase(contact=contact, reason="erasure request 2026-120")
    assert (erased.name, erased.email, erased.postal_address) == ("", "", "")
    assert erased.erased_at is not None
    assert Depositor.objects.get(pk=depositor.pk).contact_id == contact.pk
    event = AuditEvent.objects.latest("pk")
    assert (event.event_type, event.subject_id, event.reason) == (
        "contact_erased",
        contact.public_id,
        "erasure request 2026-120",
    )
    assert event.changes == {"name": "changed", "email": "changed", "postal_address": "changed"}
    count = AuditEvent.objects.count()
    services.contact_erase(contact=contact, reason="again")
    assert AuditEvent.objects.count() == count  # a second erasure records nothing
    refused(
        services.ContactErased,
        "contact_erased",
        lambda: services.depositor_update(access=curator_access, depositor=depositor, contact=JANA),
    )


def test_an_erasure_needs_a_reason(as_curator: AuditContext, depositor: Depositor) -> None:
    refused(
        RuleViolation,
        "reason_required",
        lambda: services.contact_erase(contact=depositor.contact, reason=" "),
        "reason",
    )


# MTA templates.


def test_a_manager_publishes_versions_with_the_hash_of_the_text(
    *, as_curator: AuditContext, manager: User, lab: Lab
) -> None:
    access = access_for(manager)
    first = services.mta_template_publish(
        access=access, lab=lab, code=" std ", title="Standard MTA", text="Line one\r\nLine two\n"
    )
    second = services.mta_template_publish(
        access=access, lab=lab, code="STD", title="Standard MTA", text="Line one, revised"
    )
    other = services.mta_template_publish(access=access, lab=lab, code="EDU", title="T", text="x")
    assert [(t.code, t.version) for t in (first, second, other)] == [
        ("STD", 1),
        ("STD", 2),
        ("EDU", 1),
    ]
    assert first.text == "Line one\nLine two"
    assert first.text_sha256 == services.sha256_of("Line one\nLine two")
    event = AuditEvent.objects.filter(event_type="mta_template_published").first()
    assert event is not None
    assert event.changes == {
        "code": [None, "STD"],
        "version": [None, 1],
        "title": [None, "Standard MTA"],
        "text_sha256": [None, first.text_sha256],
    }


def test_a_curator_does_not_publish_an_mta(
    *, as_curator: AuditContext, curator_access: Access, lab: Lab
) -> None:
    refused(
        Forbidden,
        "permission_denied",
        lambda: services.mta_template_publish(
            access=curator_access, lab=lab, code="STD", title="T", text="x"
        ),
    )


@pytest.mark.parametrize(
    ("code", "title", "text", "attr"),
    [("S T D", "T", "x", "code"), ("STD", " ", "x", "title"), ("STD", "T", " \n ", "text")],
)
def test_an_mta_needs_a_code_a_title_and_a_text(
    *,
    as_curator: AuditContext,
    manager: User,
    lab: Lab,
    code: str,
    title: str,
    text: str,
    attr: str,
) -> None:
    refused(
        services.InvalidDeposit,
        "invalid",
        lambda: services.mta_template_publish(
            access=access_for(manager), lab=lab, code=code, title=title, text=text
        ),
        attr,
    )


# Receipt and terms.


def test_a_curator_receives_a_deposit_with_its_terms_as_version_1(
    *,
    as_curator: AuditContext,
    curator: User,
    curator_access: Access,
    lab: Lab,
    depositor: Depositor,
    mta: MtaTemplate,
) -> None:
    uses = (*ALL_PERMITTED[:-1], (Use.REDISTRIBUTION, Decision.DENY))
    deposit = receive(
        curator_access,
        lab,
        depositor,
        condition=Condition.DAMAGED,
        condition_note=" cracked ampoule ",
        name_as_received=" Testella  exempli D1 ",
        depositor_passages=3,
        terms=terms(
            mta=mta,
            abs_scope=AbsScope.IN_SCOPE,
            ircc=" ABSCH-IRCC-XX-1 ",
            country_of_origin="CZ",
            collection_date="2019-05",
            uses=uses,
        ),
    )
    deposit.refresh_from_db()
    assert (deposit.status, deposit.name_as_received, deposit.condition_note) == (
        DepositStatus.RECEIVED,
        "Testella exempli D1",
        "cracked ampoule",
    )
    assert (deposit.depositor_passages, deposit.strain, deposit.decided_at) == (3, None, None)
    version = deposit.terms.get()
    assert (version.version, version.is_active, version.mta, version.ircc, version.reason) == (
        1,
        True,
        mta,
        "ABSCH-IRCC-XX-1",
        "",
    )
    assert dict(version.uses.values_list("use", "decision")) == dict(uses)
    event = AuditEvent.objects.latest("pk")
    assert (event.event_type, event.actor, event.lab, event.strain_id) == (
        "deposit_received",
        curator,
        lab,
        None,
    )
    assert event.changes["status"] == [None, "received"]
    assert event.changes["terms"][1]["version"] == 1
    assert event.changes["terms"][1]["uses"]["redistribution"] == "deny"
    assert event.changes["terms"][1]["mta"] == str(mta.public_id)


@pytest.mark.parametrize(
    ("changes", "attr"),
    [
        ({"name_as_received": " "}, "name_as_received"),
        ({"condition": Condition.OTHER}, "condition_note"),
        ({"terms": terms(uses=ALL_PERMITTED[:-1])}, "terms.uses"),
        ({"terms": terms(uses=(*ALL_PERMITTED, ALL_PERMITTED[0]))}, "terms.uses.8.use"),
        ({"terms": terms(abs_scope=AbsScope.IN_SCOPE)}, "terms.ircc"),
        ({"terms": terms(country_of_origin="XX")}, "terms.country_of_origin"),
        ({"terms": terms(collection_date="2019-02-30")}, "terms.collection_date"),
    ],
)
def test_bad_receipts_are_field_errors_and_change_nothing(
    *,
    as_curator: AuditContext,
    curator_access: Access,
    lab: Lab,
    depositor: Depositor,
    changes: dict[str, Any],
    attr: str,
) -> None:
    refused(
        services.InvalidDeposit,
        "invalid",
        lambda: receive(curator_access, lab, depositor, **changes),
        attr,
    )


def test_a_receipt_dated_tomorrow_is_refused(
    *, as_curator: AuditContext, curator_access: Access, lab: Lab, depositor: Depositor
) -> None:
    tomorrow = permit_today() + timedelta(days=1)
    refused(
        services.InvalidDeposit,
        "invalid",
        lambda: receive(curator_access, lab, depositor, received_on=tomorrow),
        "received_on",
    )


def test_a_depositor_or_mta_of_another_lab_is_refused(
    *,
    as_curator: AuditContext,
    curator_access: Access,
    lab: Lab,
    other_lab: Lab,
    outsider: User,
    make_depositor: MakeDepositor,
    depositor: Depositor,
) -> None:
    elsewhere = make_depositor(lab=other_lab, actor=outsider)
    refused(
        services.InvalidDeposit,
        "invalid",
        lambda: receive(curator_access, lab, elsewhere),
        "depositor",
    )
    foreign = services.mta_template_publish(
        access=access_for(outsider), lab=other_lab, code="STD", title="T", text="x"
    )
    refused(
        services.InvalidDeposit,
        "invalid",
        lambda: receive(curator_access, lab, depositor, terms=terms(mta=foreign)),
        "terms.mta",
    )


def test_a_depositor_whose_contact_was_erased_deposits_nothing(
    *, as_curator: AuditContext, curator_access: Access, lab: Lab, depositor: Depositor
) -> None:
    services.contact_erase(contact=depositor.contact, reason="erasure request")
    refused(
        services.InvalidDeposit,
        "invalid",
        lambda: receive(curator_access, lab, depositor),
        "depositor",
    )


def test_new_terms_become_the_active_version_and_the_old_one_stays(
    *, as_curator: AuditContext, curator_access: Access, make_deposit: MakeDeposit
) -> None:
    deposit = make_deposit()
    first = deposit.terms.get()
    added = services.deposit_terms_replace(
        access=curator_access,
        deposit=deposit,
        terms=terms(abs_scope=AbsScope.UNKNOWN),
        reason="the depositor corrected the scope",
    )
    first.refresh_from_db()
    assert (first.is_active, first.abs_scope, first.version) == (False, AbsScope.NOT_IN_SCOPE, 1)
    assert (added.is_active, added.version, added.reason) == (
        True,
        2,
        "the depositor corrected the scope",
    )
    assert TermsUse.objects.filter(terms=first).count() == len(Use)
    event = AuditEvent.objects.latest("pk")
    assert (event.event_type, event.reason, event.strain_id) == (
        "deposit_terms_replaced",
        "the depositor corrected the scope",
        None,
    )
    assert event.changes["terms"][0] == {"version": 1, "public_id": str(first.public_id)}


def test_new_terms_need_a_reason_and_a_rejected_deposit_keeps_its_own(
    *, as_curator: AuditContext, curator_access: Access, make_deposit: MakeDeposit
) -> None:
    deposit = make_deposit()
    refused(
        RuleViolation,
        "reason_required",
        lambda: services.deposit_terms_replace(
            access=curator_access, deposit=deposit, terms=terms(), reason=""
        ),
        "reason",
    )
    rejected = make_deposit("rejected")
    refused(
        services.WrongState,
        "deposit_state",
        lambda: services.deposit_terms_replace(
            access=curator_access, deposit=rejected, terms=terms(), reason="r"
        ),
    )


# Checking and the decision.


def test_acceptance_numbers_the_strain_and_makes_passage_0(
    *,
    as_curator: AuditContext,
    curator: User,
    curator_access: Access,
    make_deposit: MakeDeposit,
    exempli: Taxon,
    lab: Lab,
) -> None:
    deposit = make_deposit("checking", name_as_received="Testella exempli K3")
    before = AuditEvent.objects.count()
    services.deposit_accept(
        access=curator_access,
        deposit=deposit,
        facts=facts(exempli, risk_group=2, country_of_origin="CZ", restrictions=[DUAL_USE]),
    )
    deposit.refresh_from_db()
    strain = deposit.strain
    assert strain is not None
    assert (strain.accession_number, strain.status, strain.name_as_received) == (
        "MYC 1",
        StrainStatus.ACTIVE,
        "Testella exempli K3",
    )
    assert (strain.taxon, strain.risk_group, strain.country_of_origin) == (exempli, 2, "CZ")
    assert (deposit.status, deposit.decided_at is not None) == (DepositStatus.ACCEPTED, True)
    passage = Passage.objects.get()
    assert (passage.number, passage.strain, passage.source_deposit) == (0, strain, deposit)
    new = list(
        AuditEvent.objects.filter(pk__gt=AuditEvent.objects.order_by("pk")[before - 1].pk)
        .order_by("pk")
        .values_list("event_type", "strain_id", "actor", "lab")
    )
    assert new == [
        ("strain_created", strain.public_id, curator.pk, lab.pk),
        ("deposit_accepted", strain.public_id, curator.pk, lab.pk),
        ("passage_created", strain.public_id, curator.pk, lab.pk),
    ]
    accepted = AuditEvent.objects.get(event_type="deposit_accepted")
    assert accepted.changes == {
        "status": ["checking", "accepted"],
        "strain": [None, str(strain.public_id)],
        "accession_number": [None, "MYC 1"],
    }


def test_a_rejected_deposit_burns_no_number(
    *, as_curator: AuditContext, curator_access: Access, make_deposit: MakeDeposit, exempli: Taxon
) -> None:
    rejected = make_deposit("rejected")
    assert (rejected.status, rejected.rejection_reason, rejected.strain) == (
        DepositStatus.REJECTED,
        "mixed",
        None,
    )
    assert AuditEvent.objects.get(event_type="deposit_rejected").reason == "mixed"
    accepted = make_deposit("accepted", taxon=exempli)
    assert accepted.strain is not None
    assert accepted.strain.accession_number == "MYC 1"


def test_a_rejection_needs_a_reason(
    *, as_curator: AuditContext, curator_access: Access, make_deposit: MakeDeposit
) -> None:
    deposit = make_deposit("checking")
    refused(
        RuleViolation,
        "reason_required",
        lambda: services.deposit_reject(access=curator_access, deposit=deposit, reason=" "),
        "reason",
    )


@pytest.mark.parametrize(
    ("state", "action"),
    [
        ("checking", "start_check"),
        ("accepted", "start_check"),
        ("received", "accept"),
        ("received", "reject"),
        ("accepted", "accept"),
        ("accepted", "reject"),
        ("rejected", "accept"),
        ("rejected", "reject"),
    ],
)
def test_each_step_starts_only_from_its_state(
    *,
    as_curator: AuditContext,
    curator_access: Access,
    make_deposit: MakeDeposit,
    exempli: Taxon,
    state: str,
    action: str,
) -> None:
    deposit = make_deposit(state, taxon=exempli)
    calls: dict[str, Callable[[], object]] = {
        "start_check": lambda: services.deposit_start_check(access=curator_access, deposit=deposit),
        "accept": lambda: services.deposit_accept(
            access=curator_access, deposit=deposit, facts=facts(exempli)
        ),
        "reject": lambda: services.deposit_reject(
            access=curator_access, deposit=deposit, reason="r"
        ),
    }
    refused(services.WrongState, "deposit_state", calls[action])


# The biosafety gates of #11 at acceptance.


def test_a_risk_group_4_agent_is_refused_at_acceptance(
    *, as_curator: AuditContext, curator_access: Access, make_deposit: MakeDeposit, exempli: Taxon
) -> None:
    deposit = make_deposit("checking")
    refused(
        RiskGroupRefused,
        "risk_group_4_refused",
        lambda: services.deposit_accept(
            access=curator_access, deposit=deposit, facts=facts(exempli, risk_group=4)
        ),
        "risk_group",
    )
    assert Deposit.objects.get(pk=deposit.pk).status == DepositStatus.CHECKING


@pytest.mark.parametrize(
    ("restriction", "kind"),
    [(VRAT, AuthorisationKind.CZ_VRAT), (QUARANTINE, AuthorisationKind.QUARANTINE_PEST)],
)
def test_a_permit_kind_is_accepted_only_with_the_labs_valid_permit(
    *,
    as_curator: AuditContext,
    curator_access: Access,
    make_deposit: MakeDeposit,
    exempli: Taxon,
    lab: Lab,
    restriction: Any,
    kind: AuthorisationKind,
) -> None:
    deposit = make_deposit("checking")

    def accept() -> Deposit:
        return services.deposit_accept(
            access=curator_access, deposit=deposit, facts=facts(exempli, restrictions=[restriction])
        )

    make_permit(lab, kind, expires_on=permit_today() - timedelta(days=1))  # expired yesterday
    refused(AuthorisationRequired, "lab_authorisation_required", accept, "restrictions.0.kind")
    make_permit(lab, kind, permit_reference="valid", expires_on=permit_today())
    accept()
    assert Deposit.objects.get(pk=deposit.pk).status == DepositStatus.ACCEPTED


# Who may act.


@pytest.mark.parametrize("role", [Role.VIEWER, Role.TECHNICIAN])
def test_below_curator_nobody_receives_or_decides(
    *,
    as_curator: AuditContext,
    team: dict[Role, User],
    lab: Lab,
    depositor: Depositor,
    make_deposit: MakeDeposit,
    exempli: Taxon,
    role: Role,
) -> None:
    access = access_for(team[role])
    checking = make_deposit("checking")
    for call in (
        lambda: receive(access, lab, depositor),
        lambda: services.deposit_accept(access=access, deposit=checking, facts=facts(exempli)),
        lambda: services.deposit_reject(access=access, deposit=checking, reason="r"),
        lambda: services.depositor_create(access=access, lab=lab, contact=JANA),
    ):
        refused(Forbidden, "permission_denied", call)


def test_a_curator_demoted_after_the_request_began_is_refused(
    *, as_curator: AuditContext, curator: User, make_deposit: MakeDeposit, exempli: Taxon
) -> None:
    """The access object says curator; the committed role, read under the lab lock, does not."""
    deposit = make_deposit("checking")
    access = access_for(curator)
    Membership.objects.filter(user=curator).update(role=Role.VIEWER)
    refused(
        Forbidden,
        "permission_denied",
        lambda: services.deposit_accept(access=access, deposit=deposit, facts=facts(exempli)),
    )


def test_the_services_need_an_audit_context(
    *, curator_access: Access, lab: Lab, depositor: Depositor
) -> None:
    with pytest.raises(MissingAuditContext):
        receive(curator_access, lab, depositor)


# Every event of a deposit names its strain once there is one (ADR 0008, D13).

Scenario = Callable[[Deposit, Access, Taxon], object]
AFTER_ACCEPTANCE: dict[str, Scenario] = {
    "deposit_terms_replace": lambda deposit, access, taxon: services.deposit_terms_replace(
        access=access, deposit=deposit, terms=terms(), reason="corrected"
    ),
}
# Services whose events precede any strain, or concern no deposit: reviewed one by one.
NO_STRAIN_YET = {
    "deposit_receive": "before acceptance there is no strain",
    "deposit_start_check": "before acceptance there is no strain",
    "deposit_reject": "a rejected deposit never gets a strain",
    # Its events: test_acceptance_numbers_the_strain_and_makes_passage_0.
    "deposit_accept": "creates the strain its events name",
    "depositor_create": "a depositor is no deposit",
    "depositor_update": "a depositor is no deposit",
    "contact_erase": "a contact is no deposit",
    "mta_template_publish": "a template is no deposit",
}
HELPERS = {"mta_text", "sha256_of"}


def test_every_public_deposit_service_is_sorted_by_strain() -> None:
    found = public_services(services)
    assert {"deposit_accept", "deposit_receive"} <= found  # the walk found the services
    assert found - HELPERS == set(AFTER_ACCEPTANCE) | set(NO_STRAIN_YET)


@pytest.mark.parametrize("name", sorted(AFTER_ACCEPTANCE))
def test_after_acceptance_every_deposit_event_names_its_strain(
    *,
    name: str,
    make_deposit: MakeDeposit,
    as_curator: AuditContext,
    curator_access: Access,
    exempli: Taxon,
) -> None:
    deposit = make_deposit("accepted", taxon=exempli)
    assert deposit.strain is not None
    before = AuditEvent.objects.count()
    AFTER_ACCEPTANCE[name](deposit, curator_access, exempli)
    added = AuditEvent.objects.order_by("pk")[before:]
    assert [(e.strain_id, e.lab_id) for e in added] == [(deposit.strain.public_id, deposit.lab_id)]
