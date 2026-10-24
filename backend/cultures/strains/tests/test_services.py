"""Strains change only through the services: numbering under the lab lock, the biosafety
gates, the identification history, one event per call that names its strain, and refusals
that change nothing and record nothing."""

from collections.abc import Callable
from datetime import date, timedelta
from typing import Any

import pytest
from django.db.models import Model

from cultures.audit.context import AuditContext, MissingAuditContext
from cultures.audit.models import AuditEvent, RowChange
from cultures.biosafety.models import AuthorisationKind, RestrictionKind
from cultures.biosafety.policy import AuthorisationRequired, permit_today
from cultures.core.exceptions import DomainError, Forbidden, RuleViolation
from cultures.labs.access import Access, access_for
from cultures.labs.models import Lab, Membership
from cultures.labs.permissions import Role
from cultures.labs.tests.conftest import member_of
from cultures.labs.tests.test_lock_invariant import public_services
from cultures.strains import services
from cultures.strains.models import (
    Pathogenicity,
    RestrictionEndProposal,
    Strain,
    StrainCounter,
    StrainIdentification,
    StrainRestriction,
    StrainStatus,
)
from cultures.strains.services import RestrictionInput
from cultures.taxonomy.models import Taxon
from cultures.users.models import User

from .conftest import (
    DUAL_USE,
    GMO,
    QUARANTINE,
    VRAT,
    MakeStrain,
    end_restriction,
    make_permit,
    new_strain,
)

pytestmark = pytest.mark.django_db
REASON = "16S sequence of the deposit differs"

TABLES: tuple[type[Model], ...] = (
    Strain,
    StrainCounter,
    StrainIdentification,
    StrainRestriction,
    RestrictionEndProposal,
)


def snapshot() -> tuple[Any, ...]:
    """Every strain table, every event and every row change: a refusal leaves all as they were."""
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


def create(access: Access, lab: Lab, taxon: Taxon, **changes: Any) -> Strain:
    return services.strain_create(access=access, lab=lab, data=new_strain(taxon, **changes))


# Accession.


def test_a_curator_accessions_a_strain_with_its_first_identification(
    as_curator: AuditContext, curator: User, curator_access: Access, lab: Lab, exempli: Taxon
) -> None:
    strain = create(
        curator_access,
        lab,
        exempli,
        name_as_received="  Testella  exempli T1 ",
        risk_group=2,
        animal_pathogenicity=Pathogenicity.NONE_KNOWN,
        plant_pathogenicity=Pathogenicity.UNKNOWN,
        isolation_source="garden soil",
        country_of_origin="CZ",
        isolation_date="2019-05",
        restrictions=[DUAL_USE],
    )
    strain.refresh_from_db()
    assert (strain.accession_number, strain.accession_seq, strain.status) == (
        "MYC 1",
        1,
        StrainStatus.ACTIVE,
    )
    assert (strain.name_as_received, strain.taxon, strain.risk_group) == (
        "Testella exempli T1",
        exempli,
        2,
    )
    assert (strain.country_of_origin, strain.isolation_date, strain.isolation_source) == (
        "CZ",
        "2019-05",
        "garden soil",
    )
    (identification,) = StrainIdentification.objects.filter(strain=strain)
    assert (
        identification.taxon,
        identification.is_current,
        identification.method,
        identification.reason,
    ) == (
        exempli,
        True,
        "16S rRNA gene sequence",
        "Identification at accession",
    )
    assert identification.lab_id == lab.pk
    (restriction,) = StrainRestriction.objects.filter(strain=strain)
    assert (restriction.kind, restriction.reference, restriction.act, restriction.lab_id) == (
        "dual_use",
        "1C351.c",
        "(EU) 2025/2003",
        lab.pk,
    )
    event = AuditEvent.objects.get()
    assert (event.event_type, event.actor, event.lab, event.strain_id, event.subject_id) == (
        "strain_created",
        curator,
        lab,
        strain.public_id,
        strain.public_id,
    )
    assert event.changes == {
        "accession_number": [None, "MYC 1"],
        "status": [None, "active"],
        "name_as_received": [None, "Testella exempli T1"],
        "taxon": [None, str(exempli.public_id)],
        "risk_group": [None, 2],
        "animal_pathogenicity": [None, "none_known"],
        "plant_pathogenicity": [None, "unknown"],
        "isolation_source": [None, "garden soil"],
        "country_of_origin": [None, "CZ"],
        "isolation_date": [None, "2019-05"],
        "identification": [
            None,
            {
                "public_id": str(identification.public_id),
                "identified_on": "2026-01-10",
                "method": "16S rRNA gene sequence",
            },
        ],
        "restrictions": [
            None,
            [
                {
                    "kind": "dual_use",
                    "reference": "1C351.c",
                    "act": "(EU) 2025/2003",
                    "gmo_category": None,
                }
            ],
        ],
    }


def test_numbers_follow_each_other_per_lab_and_carry_the_lab_code(
    make_strain: MakeStrain, other_lab: Lab, outsider: User
) -> None:
    numbers = [make_strain().accession_number for _ in range(3)]
    assert numbers == ["MYC 1", "MYC 2", "MYC 3"]
    assert make_strain(lab=other_lab, actor=outsider).accession_number == "BAC 1"
    assert dict(StrainCounter.objects.values_list("lab__code", "last_seq")) == {"MYC": 3, "BAC": 1}


def test_a_number_is_never_given_again(make_strain: MakeStrain, lab: Lab) -> None:
    """Even after the counter row is gone (by SQL, say), the unique sequence refuses a reuse."""
    make_strain()
    StrainCounter.objects.filter(lab=lab).update(last_seq=0)
    before = snapshot()
    with pytest.raises(services.AccessionTaken):
        make_strain()
    assert snapshot() == before


def test_a_refused_accession_burns_no_number(
    as_curator: AuditContext,
    curator_access: Access,
    lab: Lab,
    exempli: Taxon,
    make_strain: MakeStrain,
) -> None:
    with pytest.raises(AuthorisationRequired):
        create(curator_access, lab, exempli, restrictions=[VRAT])
    assert make_strain().accession_number == "MYC 1"


@pytest.mark.parametrize("risk_group", [4])
def test_a_risk_group_4_agent_is_refused_on_its_field(
    as_curator: AuditContext, curator_access: Access, lab: Lab, exempli: Taxon, risk_group: int
) -> None:
    error = refused(
        services.RiskGroupRefused,
        "risk_group_4_refused",
        lambda: create(curator_access, lab, exempli, risk_group=risk_group),
        attr="risk_group",
    )
    assert error.status_code == 400
    assert not StrainCounter.objects.exists()


@pytest.mark.parametrize(
    ("changes", "attr"),
    [
        ({"name_as_received": "   "}, "name_as_received"),
        ({"identification_method": ""}, "identification_method"),
        ({"risk_group": 0}, "risk_group"),
        ({"identified_on": date(2999, 1, 1)}, "identified_on"),
        ({"country_of_origin": "XK"}, "country_of_origin"),
        ({"isolation_date": "2019-13"}, "isolation_date"),
        ({"isolation_date": "2019-02-30"}, "isolation_date"),
        ({"isolation_date": "2999"}, "isolation_date"),
        (
            {"restrictions": [RestrictionInput(RestrictionKind.DUAL_USE, "1C351.c")]},
            "restrictions.0.act",
        ),
        (
            {
                "restrictions": [
                    DUAL_USE,
                    RestrictionInput(RestrictionKind.DUAL_USE, "2B352", act="(EU) 2025/2003"),
                ]
            },
            "restrictions.1.reference",
        ),
        (
            {"restrictions": [RestrictionInput(RestrictionKind.GMO, "notification 1")]},
            "restrictions.0.gmo_category",
        ),
        (
            {"restrictions": [RestrictionInput(RestrictionKind.CZ_RAT, "x", gmo_category=2)]},
            "restrictions.0.gmo_category",
        ),
        (
            {"restrictions": [RestrictionInput(RestrictionKind.CZ_RAT, "x", act="(EU) 2025/2003")]},
            "restrictions.0.act",
        ),
        (
            {"restrictions": [RestrictionInput(RestrictionKind.CZ_RAT, "  ")]},
            "restrictions.0.reference",
        ),
        (
            {
                "restrictions": [
                    GMO,
                    RestrictionInput(
                        RestrictionKind.GMO, "mžp NOTIFICATION 2026/12", gmo_category=2
                    ),
                ]
            },
            "restrictions.1.reference",
        ),
        ({"restrictions": [GMO] * 11}, "restrictions"),
    ],
)
def test_bad_input_is_a_field_error_and_changes_nothing(
    *,
    as_curator: AuditContext,
    curator_access: Access,
    lab: Lab,
    exempli: Taxon,
    changes: dict[str, Any],
    attr: str,
) -> None:
    refused(
        services.InvalidStrain,
        "invalid",
        lambda: create(curator_access, lab, exempli, **changes),
        attr=attr,
    )


# The permit gate (ADR 0009, Lab authorisation).


@pytest.mark.parametrize(
    ("restriction", "kind"),
    [(VRAT, AuthorisationKind.CZ_VRAT), (QUARANTINE, AuthorisationKind.QUARANTINE_PEST)],
)
def test_a_vrat_or_quarantine_strain_enters_with_a_valid_permit(
    *,
    as_curator: AuditContext,
    curator_access: Access,
    lab: Lab,
    exempli: Taxon,
    restriction: RestrictionInput,
    kind: AuthorisationKind,
) -> None:
    make_permit(lab, kind)
    strain = create(curator_access, lab, exempli, restrictions=[restriction])
    assert StrainRestriction.objects.get(strain=strain).kind == kind


@pytest.mark.parametrize(
    "permit",
    [
        "none",
        "expired",
        "not_yet",
        "ended",
        "other_kind",
        "other_lab",
    ],
)
def test_without_a_valid_permit_of_its_kind_in_its_lab_the_strain_is_refused(
    *,
    as_curator: AuditContext,
    curator_access: Access,
    lab: Lab,
    other_lab: Lab,
    exempli: Taxon,
    permit: str,
) -> None:
    today = permit_today()
    match permit:
        case "expired":
            make_permit(lab, AuthorisationKind.CZ_VRAT, expires_on=today - timedelta(days=1))
        case "not_yet":
            make_permit(lab, AuthorisationKind.CZ_VRAT, valid_from=today + timedelta(days=1))
        case "ended":
            make_permit(lab, AuthorisationKind.CZ_VRAT, ended_on=today, end_reason="revoked")
        case "other_kind":
            make_permit(lab, AuthorisationKind.QUARANTINE_PEST)
        case "other_lab":
            make_permit(other_lab, AuthorisationKind.CZ_VRAT)
        case _:
            pass
    error = refused(
        AuthorisationRequired,
        "lab_authorisation_required",
        lambda: create(curator_access, lab, exempli, restrictions=[DUAL_USE, VRAT]),
        attr="restrictions.1.kind",
    )
    assert error.status_code == 422


def test_kinds_without_a_permit_need_none(
    as_curator: AuditContext, curator_access: Access, lab: Lab, exempli: Taxon
) -> None:
    rat = RestrictionInput(RestrictionKind.CZ_RAT, "Příloha 2, bod 1")
    strain = create(curator_access, lab, exempli, restrictions=[rat, DUAL_USE, GMO])
    assert sorted(
        StrainRestriction.objects.filter(strain=strain).values_list("kind", flat=True)
    ) == [
        "cz_rat",
        "dual_use",
        "gmo",
    ]


# Who may write: the role in the lab as committed now, not as the request began.


@pytest.mark.parametrize("role", [Role.VIEWER, Role.TECHNICIAN])
def test_below_curator_nobody_accessions(
    *,
    as_curator: AuditContext,
    curator: User,
    curator_access: Access,
    lab: Lab,
    exempli: Taxon,
    role: Role,
) -> None:
    Membership.objects.filter(user=curator, lab=lab).update(role=role)
    refused(Forbidden, "permission_denied", lambda: create(curator_access, lab, exempli))


def test_a_curator_deactivated_meanwhile_is_refused(
    as_curator: AuditContext, curator: User, curator_access: Access, lab: Lab, exempli: Taxon
) -> None:
    User.objects.filter(pk=curator.pk).update(is_active=False)
    refused(Forbidden, "permission_denied", lambda: create(curator_access, lab, exempli))


def test_a_curator_of_another_lab_is_refused(
    as_curator: AuditContext, curator_access: Access, other_lab: Lab, exempli: Taxon
) -> None:
    refused(Forbidden, "permission_denied", lambda: create(curator_access, other_lab, exempli))


def test_the_services_need_an_audit_context(
    curator_access: Access, lab: Lab, exempli: Taxon
) -> None:
    with pytest.raises(MissingAuditContext):
        create(curator_access, lab, exempli)
    assert not Strain.objects.exists()


# Reclassification: a new identification, the old one stays as history.


def test_reclassification_adds_the_current_identification_and_moves_the_cached_taxon(
    make_strain: MakeStrain,
    as_curator: AuditContext,
    curator_access: Access,
    mockia: Taxon,
    exempli: Taxon,
) -> None:
    strain = make_strain()
    first = StrainIdentification.objects.get(strain=strain)
    services.strain_reclassify(
        access=curator_access,
        strain=strain,
        taxon=mockia,
        identified_on=date(2026, 3, 1),
        method=" MALDI-TOF  MS",
        reason=REASON,
    )
    strain.refresh_from_db()
    assert strain.taxon == mockia
    rows = list(
        StrainIdentification.objects.filter(strain=strain)
        .order_by("pk")
        .values_list("taxon", "is_current", "method", "reason")
    )
    assert rows == [
        (exempli.pk, False, "16S rRNA gene sequence", "Identification at accession"),
        (mockia.pk, True, "MALDI-TOF MS", REASON),
    ]
    event = AuditEvent.objects.filter(event_type="strain_reclassified").get()
    assert (event.strain_id, event.lab_id, event.reason) == (
        strain.public_id,
        strain.lab_id,
        REASON,
    )
    second = StrainIdentification.objects.get(strain=strain, is_current=True)
    assert event.changes == {
        "taxon": [str(exempli.public_id), str(mockia.public_id)],
        "identification": [str(first.public_id), str(second.public_id)],
        "identified_on": [None, "2026-03-01"],
        "method": [None, "MALDI-TOF MS"],
    }


def test_after_two_reclassifications_one_identification_is_current(
    make_strain: MakeStrain,
    as_curator: AuditContext,
    curator_access: Access,
    mockia: Taxon,
    exempli: Taxon,
) -> None:
    strain = make_strain()
    for taxon in (mockia, exempli):
        services.strain_reclassify(
            access=curator_access,
            strain=strain,
            taxon=taxon,
            identified_on=date(2026, 3, 1),
            method="m",
            reason=REASON,
        )
    assert StrainIdentification.objects.filter(strain=strain).count() == 3
    assert list(
        StrainIdentification.objects.filter(strain=strain, is_current=True).values_list(
            "taxon", flat=True
        )
    ) == [exempli.pk]


@pytest.mark.parametrize(
    ("changes", "error", "code", "attr"),
    [
        ({"reason": "  "}, RuleViolation, "reason_required", "reason"),
        ({"method": " "}, services.InvalidStrain, "invalid", "method"),
        ({"identified_on": date(2999, 1, 1)}, services.InvalidStrain, "invalid", "identified_on"),
    ],
)
def test_a_reclassification_needs_a_reason_a_method_and_a_past_date(
    *,
    make_strain: MakeStrain,
    as_curator: AuditContext,
    curator_access: Access,
    mockia: Taxon,
    changes: dict[str, Any],
    error: type[DomainError],
    code: str,
    attr: str,
) -> None:
    strain = make_strain()
    values: dict[str, Any] = {
        "taxon": mockia,
        "identified_on": date(2026, 3, 1),
        "method": "m",
        "reason": REASON,
        **changes,
    }
    refused(
        error,
        code,
        lambda: services.strain_reclassify(access=curator_access, strain=strain, **values),
        attr=attr,
    )


# Risk group.


def test_a_risk_group_change_records_old_new_and_the_reason(
    make_strain: MakeStrain, as_curator: AuditContext, curator_access: Access
) -> None:
    strain = make_strain()
    services.strain_set_risk_group(
        access=curator_access, strain=strain, risk_group=2, reason="reassessed under 361/2007"
    )
    strain.refresh_from_db()
    assert strain.risk_group == 2
    event = AuditEvent.objects.filter(event_type="strain_risk_group_changed").get()
    assert (event.changes, event.reason, event.strain_id) == (
        {"risk_group": [1, 2]},
        "reassessed under 361/2007",
        strain.public_id,
    )


def test_the_same_risk_group_again_records_nothing(
    make_strain: MakeStrain, as_curator: AuditContext, curator_access: Access
) -> None:
    strain = make_strain()
    before = snapshot()
    services.strain_set_risk_group(
        access=curator_access, strain=strain, risk_group=1, reason="checked"
    )
    assert snapshot() == before


def test_a_change_to_risk_group_4_is_refused(
    make_strain: MakeStrain, as_curator: AuditContext, curator_access: Access
) -> None:
    strain = make_strain()
    refused(
        services.RiskGroupRefused,
        "risk_group_4_refused",
        lambda: services.strain_set_risk_group(
            access=curator_access, strain=strain, risk_group=4, reason="x"
        ),
        attr="risk_group",
    )


def test_a_risk_group_change_needs_a_reason(
    make_strain: MakeStrain, as_curator: AuditContext, curator_access: Access
) -> None:
    strain = make_strain()
    refused(
        RuleViolation,
        "reason_required",
        lambda: services.strain_set_risk_group(
            access=curator_access, strain=strain, risk_group=2, reason=" "
        ),
        attr="reason",
    )


# Restrictions after accession.


def test_a_curator_adds_a_restriction_and_it_ends_by_two_people(
    make_strain: MakeStrain,
    as_curator: AuditContext,
    curator: User,
    manager: User,
    curator_access: Access,
) -> None:
    strain = make_strain()
    added = services.strain_restriction_add(
        access=curator_access, strain=strain, restriction=DUAL_USE, reason="Annex I 2025"
    )
    ended = end_restriction(added, proposer=curator, confirmer=manager, reason="no longer listed")
    assert ended.ended_at is not None
    assert ended.end_reason == "no longer listed"
    events = list(
        AuditEvent.objects.filter(strain_id=strain.public_id)
        .order_by("pk")
        .values_list("event_type", "reason")
    )
    assert events == [
        ("strain_created", ""),
        ("strain_restriction_added", "Annex I 2025"),
        ("strain_restriction_end_proposed", "no longer listed"),
        ("strain_restriction_ended", "no longer listed"),
    ]


def test_an_added_vrat_restriction_needs_the_permit_too(
    make_strain: MakeStrain, as_curator: AuditContext, curator_access: Access, lab: Lab
) -> None:
    strain = make_strain()
    refused(
        AuthorisationRequired,
        "lab_authorisation_required",
        lambda: services.strain_restriction_add(
            access=curator_access, strain=strain, restriction=VRAT, reason="listed"
        ),
        attr="kind",
    )
    make_permit(lab, AuthorisationKind.CZ_VRAT)
    services.strain_restriction_add(
        access=curator_access, strain=strain, restriction=VRAT, reason="listed"
    )


def test_a_restriction_twice_is_a_field_error(
    make_strain: MakeStrain, as_curator: AuditContext, curator_access: Access
) -> None:
    strain = make_strain(restrictions=[GMO])
    same = RestrictionInput(RestrictionKind.GMO, "MŽP notification 2026/12", gmo_category=2)
    refused(
        services.InvalidStrain,
        "unique",
        lambda: services.strain_restriction_add(
            access=curator_access, strain=strain, restriction=same, reason="again"
        ),
        attr="reference",
    )


def test_a_restriction_ends_once(
    make_strain: MakeStrain,
    as_curator: AuditContext,
    curator: User,
    manager: User,
    curator_access: Access,
) -> None:
    strain = make_strain(restrictions=[GMO])
    restriction = StrainRestriction.objects.get(strain=strain)
    end_restriction(restriction, proposer=curator, confirmer=manager, reason="destroyed")
    refused(
        services.RestrictionEnded,
        "restriction_ended",
        lambda: services.strain_restriction_end_propose(
            access=curator_access, restriction=restriction, reason="again"
        ),
    )


# Every event of every strain service names its strain (ADR 0008, D13).

Scenario = Callable[[Strain, Access, Taxon], object]
SCENARIOS: dict[str, Scenario] = {
    "strain_create": lambda strain, access, taxon: None,  # the fixture's own accession
    "strain_reclassify": lambda strain, access, taxon: services.strain_reclassify(
        access=access,
        strain=strain,
        taxon=taxon,
        identified_on=date(2026, 3, 1),
        method="m",
        reason=REASON,
    ),
    "strain_set_risk_group": lambda strain, access, taxon: services.strain_set_risk_group(
        access=access, strain=strain, risk_group=3, reason="reassessed"
    ),
    "strain_restriction_add": lambda strain, access, taxon: services.strain_restriction_add(
        access=access, strain=strain, restriction=DUAL_USE, reason="listed"
    ),
    "strain_restriction_end_propose": lambda strain, access, taxon: (
        services.strain_restriction_end_propose(
            access=access, restriction=StrainRestriction.objects.get(strain=strain), reason="gone"
        )
    ),
    "strain_restriction_end_confirm": lambda strain, access, taxon: (
        services.strain_restriction_end_confirm(
            access=access_for(member_of(strain.lab, Role.MANAGER, "confirmer")),
            restriction=StrainRestriction.objects.get(strain=strain),
            proposal=proposed(strain, access).public_id,
        )
    ),
    "strain_restriction_end_withdraw": lambda strain, access, taxon: (
        services.strain_restriction_end_withdraw(
            access=access,
            restriction=StrainRestriction.objects.get(strain=strain),
            proposal=proposed(strain, access).public_id,
            reason="still listed",
        )
    ),
}
# The scenarios that propose first: the proposal's event names the strain too.
EVENTS_OF = {
    "strain_create": 1,
    "strain_restriction_end_confirm": 3,
    "strain_restriction_end_withdraw": 3,
}


def proposed(strain: Strain, access: Access) -> RestrictionEndProposal:
    return services.strain_restriction_end_propose(
        access=access, restriction=StrainRestriction.objects.get(strain=strain), reason="gone"
    )


def test_every_public_strain_service_has_a_strain_id_scenario() -> None:
    found = public_services(services)
    assert {"strain_create", "strain_reclassify"} <= found  # the walk found the services
    assert found - {"check_partial_date", "check_restriction", "normalised"} == set(SCENARIOS)


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_every_event_of_a_strain_service_names_its_strain(
    name: str,
    make_strain: MakeStrain,
    as_curator: AuditContext,
    curator_access: Access,
    mockia: Taxon,
) -> None:
    strain = make_strain(restrictions=[GMO])
    SCENARIOS[name](strain, curator_access, mockia)
    events = list(AuditEvent.objects.values_list("event_type", "strain_id", "lab_id"))
    assert len(events) == EVENTS_OF.get(name, 2)
    assert {(strain_id, lab_id) for _, strain_id, lab_id in events} == {
        (strain.public_id, strain.lab_id)
    }


def test_a_viewer_access_object_is_not_enough(
    make_strain: MakeStrain, viewer: User, as_curator: AuditContext, exempli: Taxon
) -> None:
    strain = make_strain()
    refused(
        Forbidden,
        "permission_denied",
        lambda: services.strain_set_risk_group(
            access=access_for(viewer), strain=strain, risk_group=2, reason="x"
        ),
    )
