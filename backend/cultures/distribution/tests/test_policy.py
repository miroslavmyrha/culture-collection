"""The policy, gate by gate and both ways: each finding appears when its rule is broken and is
gone once the request meets it, with its stable code, its severity and a sentence that names
the strain. Regulated examples are the invented Mockia vulgaris with each restriction kind."""

from datetime import date, timedelta
from typing import Any

import pytest
from django.db import connection
from django.utils import timezone

from cultures.audit.context import AuditContext
from cultures.biosafety.models import RestrictionKind
from cultures.biosafety.policy import permit_today
from cultures.core.testing import QueryBaseline
from cultures.deposits import services as deposits
from cultures.deposits.models import AbsScope, Decision, Deposit, Use
from cultures.deposits.tests.support import (
    ALL_PERMITTED,
    DUAL_USE,
    GMO,
    QUARANTINE,
    VRAT,
    terms,
)
from cultures.distribution import policy, services
from cultures.distribution.models import (
    DepositorAnswer,
    DistributionRequest,
    PermitKind,
    Requester,
)
from cultures.distribution.policy import (
    GATES,
    Finding,
    Severity,
    evaluate,
    finding_key,
    isolation_facility_recorded,
    names,
)
from cultures.labs.access import access_for
from cultures.labs.models import Lab
from cultures.lineage import services as lineage
from cultures.lineage.models import Batch
from cultures.strains.models import Strain
from cultures.strains.services import RestrictionInput
from cultures.taxonomy.models import Rank, Taxon
from cultures.taxonomy.tests.conftest import make_synonym
from cultures.users.models import User

from .support import (
    ON_REQUEST_USES,
    MakeRequester,
    Supply,
    accept_mtas,
    add_permit,
    answer,
    approve,
    as_actor,
    submit,
)

pytestmark = pytest.mark.django_db
RAT = RestrictionInput(RestrictionKind.CZ_RAT, "Příloha 2, bod 9")


def codes(request: DistributionRequest, day: date | None = None) -> dict[str, Severity]:
    found = evaluate(request, day or permit_today()).findings
    return {f.code: f.severity for f in found}


@pytest.fixture
def ask(as_curator: AuditContext, curator: User, lab: Lab, requester: Requester) -> Any:
    """A request for the strain, its MTA accepted unless told otherwise."""

    def make(
        strain: Strain, quantity: int = 1, *, accept: bool = True, **changes: Any
    ) -> DistributionRequest:
        request = submit(
            curator, lab, changes.pop("requester", requester), [(strain, quantity)], **changes
        )
        if accept:
            accept_mtas(curator, request)
        return request

    return make


def test_a_request_that_meets_every_rule_has_no_finding(ask: Any, supply: Supply) -> None:
    assert codes(ask(supply())) == {}


def test_every_gate_has_a_stable_code_and_one_severity() -> None:
    assert len({code for code, _ in GATES}) == len(GATES)
    assert policy.gate_codes()["regulated"] == Severity.MANAGER


def test_vials_short_block_until_enough_may_go_out(ask: Any, supply: Supply) -> None:
    strain = supply(vials=2)
    finding = evaluate(ask(strain, 3), permit_today()).findings[0]
    assert (finding.code, finding.severity) == ("not_enough_vials", Severity.BLOCK)
    assert (
        finding.sentence
        == f"{strain.accession_number}: 2 vials may go out now, the line asks for 3."
    )
    assert "not_enough_vials" not in codes(ask(strain, 2))


def test_vials_held_by_an_approved_request_do_not_count(
    ask: Any, supply: Supply, curator: User
) -> None:
    strain = supply(vials=3)
    approve(curator, ask(strain, 2))
    assert codes(ask(strain, 2)) == {"not_enough_vials": Severity.BLOCK}


def test_new_terms_after_entry_block(ask: Any, supply: Supply, curator: User) -> None:
    strain = supply()
    request = ask(strain)
    deposits.deposit_terms_replace(
        access=access_for(curator),
        deposit=Deposit.objects.get(strain=strain),
        terms=terms(mta=request.lines.get().mta),
        reason="corrected",
    )
    assert codes(request) == {"terms_replaced": Severity.BLOCK}


@pytest.mark.rule("R-DIST-13")
def test_an_unknown_abs_scope_blocks(ask: Any, supply: Supply) -> None:
    assert codes(ask(supply(abs_scope=AbsScope.UNKNOWN))) == {"abs_scope_unknown": Severity.BLOCK}


@pytest.mark.rule("R-DIST-13")
def test_material_in_scope_goes_out_only_for_uses_the_mat_covers(ask: Any, supply: Supply) -> None:
    in_scope = {"abs_scope": AbsScope.IN_SCOPE, "ircc": "ABSCH-IRCC-XX-1 (invented example)"}
    none = ask(supply(**in_scope))
    assert codes(none) == {"abs_use_not_covered": Severity.BLOCK}
    covered = ask(supply(**in_scope, mat_uses=[Use.RESEARCH_NONCOMMERCIAL]))
    assert codes(covered) == {}
    other = ask(supply(**in_scope, mat_uses=[Use.TEACHING]))
    assert codes(other) == {"abs_use_not_covered": Severity.BLOCK}


@pytest.mark.parametrize(
    ("decision", "expected"),
    [
        (Decision.DENY, {"use_denied": Severity.BLOCK}),
        # #144: no answer of the depositor is recorded; tests/test_depositor_answer.py records one.
        (Decision.ON_REQUEST, {"use_on_request": Severity.BLOCK}),
        (Decision.PERMIT, {}),
    ],
)
def test_the_depositors_decision_on_the_use(
    ask: Any, supply: Supply, decision: Decision, expected: dict[str, Severity]
) -> None:
    uses = tuple(
        (use, decision if use == Use.RESEARCH_NONCOMMERCIAL else d) for use, d in ALL_PERMITTED
    )
    assert codes(ask(supply(uses=uses))) == expected


def test_terms_without_an_mta_block(ask: Any, supply: Supply) -> None:
    assert codes(ask(supply(mta=None), accept=False)) == {"mta_missing": Severity.BLOCK}


def test_the_mta_must_be_accepted_by_someone_who_may_bind_the_requester(
    ask: Any, supply: Supply, curator: User
) -> None:
    request = ask(supply(), accept=False)
    assert codes(request) == {"mta_not_accepted": Severity.BLOCK}
    accept_mtas(curator, request, authorised_signatory=False)
    assert codes(request) == {"mta_not_accepted": Severity.BLOCK}
    other = ask(supply(), accept=False)
    accept_mtas(curator, other)
    assert codes(other) == {}


@pytest.mark.parametrize(("level", "blocked"), [(1, True), (2, False), (3, False)])
@pytest.mark.rule("R-DIST-10")
def test_the_declared_containment_must_reach_the_risk_group(
    *, ask: Any, supply: Supply, requester: Requester, curator: User, level: int, blocked: bool
) -> None:
    add_permit(curator, requester, PermitKind.PATHOGEN_WORK_PERMIT)
    found = codes(ask(supply(risk_group=2), containment_level=level))
    assert ("containment_too_low" in found) == blocked


@pytest.mark.parametrize(
    ("permit_group", "expected"), [(None, True), (1, True), (2, False), (3, False)]
)
@pytest.mark.rule("R-DIST-11")
def test_a_pathogen_without_a_work_permit_needs_a_manager(
    *,
    ask: Any,
    supply: Supply,
    requester: Requester,
    curator: User,
    permit_group: int | None,
    expected: bool,
) -> None:
    if permit_group is not None:
        add_permit(curator, requester, PermitKind.PATHOGEN_WORK_PERMIT, risk_group=permit_group)
    found = codes(ask(supply(risk_group=2)))
    assert ("work_permit_missing" in found) == expected
    if expected:
        assert found["work_permit_missing"] == Severity.MANAGER


@pytest.mark.rule("R-DIST-12")
def test_risk_group_3_may_be_category_a(
    ask: Any, supply: Supply, requester: Requester, curator: User
) -> None:
    add_permit(curator, requester, PermitKind.PATHOGEN_WORK_PERMIT, risk_group=3)
    assert codes(ask(supply(risk_group=3), containment_level=3)) == {
        "category_a_possible": Severity.MANAGER
    }


@pytest.mark.rule("R-DIST-03")
def test_a_regulated_strain_needs_a_manager(ask: Any, supply: Supply, mockia: Taxon) -> None:
    found = evaluate(ask(supply(mockia, restrictions=[DUAL_USE])), permit_today()).findings
    assert [(f.code, f.severity) for f in found] == [("regulated", Severity.MANAGER)]
    assert "dual_use" in found[0].sentence


@pytest.mark.rule("R-DIST-04")
def test_a_vrat_goes_only_to_a_holder_of_a_permit_that_names_it(
    ask: Any, supply: Supply, mockia: Taxon, requester: Requester, curator: User
) -> None:
    strain = supply(mockia, restrictions=[VRAT])
    assert "vrat_permit_missing" in codes(ask(strain))
    add_permit(curator, requester, PermitKind.SUJB_VRAT, covers="Testella exempli")
    assert "vrat_permit_missing" in codes(ask(strain))  # names another agent
    add_permit(curator, requester, PermitKind.SUJB_VRAT, covers="Brucella; Mockia  VULGARIS")
    assert codes(ask(strain)) == {"regulated": Severity.MANAGER}


@pytest.mark.rule("R-DIST-04")
def test_an_sujb_exception_lets_a_vrat_go_to_a_non_holder(
    ask: Any, supply: Supply, mockia: Taxon, requester: Requester, curator: User
) -> None:
    strain = supply(mockia, restrictions=[VRAT])
    add_permit(curator, requester, PermitKind.SUJB_EXCEPTION, covers="Mockia vulgaris")
    assert codes(ask(strain)) == {"regulated": Severity.MANAGER}


@pytest.mark.parametrize(
    ("window", "valid"),
    [
        ({"valid_from": "tomorrow"}, False),
        ({"expires_on": "yesterday"}, False),
        ({"expires_on": "today"}, True),
        ({"ended": "today"}, False),
        ({"ended": "tomorrow"}, True),
    ],
)
@pytest.mark.rule("R-DIST-04")
def test_a_permit_counts_only_on_the_days_it_holds(
    *,
    ask: Any,
    supply: Supply,
    mockia: Taxon,
    requester: Requester,
    curator: User,
    window: dict[str, str],
    valid: bool,
) -> None:
    today = permit_today()
    day = {
        "today": today,
        "yesterday": today - timedelta(days=1),
        "tomorrow": today + timedelta(days=1),
    }
    start = day[window["valid_from"]] if "valid_from" in window else date(2026, 1, 1)
    expires = day[window["expires_on"]] if "expires_on" in window else None
    permit = add_permit(
        curator, requester, PermitKind.SUJB_RAT_NOTICE, valid_from=start, expires_on=expires
    )
    if "ended" in window:
        services.permit_end(
            access=access_for(curator),
            permit=permit,
            ended_on=day[window["ended"]],
            reason="revoked",
        )
    found = codes(ask(supply(mockia, restrictions=[RAT])))
    assert ("rat_notice_missing" not in found) == valid


@pytest.mark.rule("R-DIST-05")
def test_a_rat_goes_only_to_a_requester_who_notified_sujb(
    ask: Any, supply: Supply, mockia: Taxon, requester: Requester, curator: User
) -> None:
    strain = supply(mockia, restrictions=[RAT])
    assert codes(ask(strain)) == {
        "regulated": Severity.MANAGER,
        "rat_notice_missing": Severity.BLOCK,
    }
    add_permit(curator, requester, PermitKind.SUJB_RAT_NOTICE, covers="Mockia vulgaris")
    assert codes(ask(strain)) == {"regulated": Severity.MANAGER}


@pytest.mark.rule("R-DIST-05")
def test_a_rat_notice_for_another_agent_does_not_let_this_one_go_out(
    ask: Any, supply: Supply, mockia: Taxon, requester: Requester, curator: User
) -> None:
    """The notice states the kind of agent (§ 17a(3) a)): one for another agent is none here."""
    strain = supply(mockia, restrictions=[RAT])
    add_permit(curator, requester, PermitKind.SUJB_RAT_NOTICE, covers="Testella exempli")
    found = evaluate(ask(strain), permit_today()).findings
    sentences = {f.code: f.sentence for f in found}
    assert sentences.keys() == {"regulated", "rat_notice_missing"}
    said = sentences["rat_notice_missing"]
    assert "no reference of a notice to SÚJB (§ 17a) that names Mockia vulgaris" in said


@pytest.mark.parametrize(
    ("entry", "blocked"),
    [("1C351.d.4", True), ("1C351.d.5", True), ("1C351.d.1", False), ("1C351.c", False)],
)
@pytest.mark.rule("R-DIST-06")
def test_only_ricin_and_saxitoxin_need_a_transfer_licence_inside_the_eu(
    ask: Any, supply: Supply, mockia: Taxon, entry: str, blocked: bool
) -> None:
    restriction = RestrictionInput(RestrictionKind.DUAL_USE, entry, act="(EU) 2025/2003")
    found = codes(ask(supply(mockia, restrictions=[restriction])))
    assert ("transfer_licence_required" in found) == blocked


@pytest.mark.rule("R-DIST-07")
def test_a_quarantine_pest_needs_a_letter_with_quantity_and_sendings_left(
    *, ask: Any, supply: Supply, mockia: Taxon, requester: Requester, curator: User, manager: User
) -> None:
    strain = supply(mockia, restrictions=[QUARANTINE], vials=10)
    add_permit(curator, requester, PermitKind.PLANT_HEALTH_ISOLATION)
    assert "loa_missing" in codes(ask(strain))
    add_permit(
        curator, requester, PermitKind.PLANT_HEALTH_LOA, quantity_allowed=3, sendings_allowed=2
    )
    first = ask(strain, 2)
    assert codes(first) == {"regulated": Severity.MANAGER}
    approve(manager, first, reason="letter in hand")
    assert codes(ask(strain, 2)) == {"regulated": Severity.MANAGER, "loa_exhausted": Severity.BLOCK}
    assert codes(ask(strain, 1)) == {"regulated": Severity.MANAGER}


@pytest.mark.rule("R-DIST-16")
def test_a_quarantine_pest_goes_only_to_a_recorded_isolation_facility(
    *, ask: Any, supply: Supply, mockia: Taxon, requester: Requester, curator: User
) -> None:
    """2019/829, Art. 5 c): the authorisation of the activity is granted only where the activity
    is performed in a quarantine station or confinement facility the competent authority
    designated, and the letter of Art. 6(1) follows that authorisation. A hard line with no
    override, as a § 17a notice is for a RAT (R-DIST-05)."""
    strain = supply(mockia, restrictions=[QUARANTINE], vials=10)
    letter = add_permit(curator, requester, PermitKind.PLANT_HEALTH_LOA)
    found = {f.code: f for f in evaluate(ask(strain), permit_today()).findings}
    assert found.keys() == {"regulated", "isolation_facility_missing"}
    missing = found["isolation_facility_missing"]
    assert missing.severity == Severity.BLOCK
    assert f"{strain.accession_number} is a quarantine pest" in missing.sentence
    assert "no authorisation of an isolation facility" in missing.sentence
    facility = add_permit(curator, requester, PermitKind.PLANT_HEALTH_ISOLATION)
    evaluation = evaluate(ask(strain), permit_today())
    assert {f.code for f in evaluation.findings} == {"regulated"}
    assert {permit.pk for _, permit in evaluation.used} == {facility.pk, letter.pk}


@pytest.mark.rule("R-DIST-16")
def test_a_letter_of_authority_is_no_authorisation_of_an_isolation_facility(
    *,
    ask: Any,
    supply: Supply,
    mockia: Taxon,
    requester: Requester,
    make_requester: MakeRequester,
    curator: User,
) -> None:
    """Each of the two documents counts for itself: a permit of the neighbouring kind, naming
    the very pest, does not stand in for the other."""
    strain = supply(mockia, restrictions=[QUARANTINE], vials=10)
    add_permit(curator, requester, PermitKind.PLANT_HEALTH_LOA, covers="Mockia vulgaris")
    assert "isolation_facility_missing" in codes(ask(strain))
    other = make_requester()
    add_permit(curator, other, PermitKind.PLANT_HEALTH_ISOLATION)
    found = codes(ask(strain, requester=other))
    assert "isolation_facility_missing" not in found
    assert "loa_missing" in found


@pytest.mark.rule("R-DIST-16")
def test_the_gate_and_the_trigger_agree_on_a_recorded_isolation_facility(
    *, make_requester: MakeRequester, curator: User
) -> None:
    """The one rule, both ways: `policy.isolation_facility_recorded` in Python and the SQL
    function the two shipment guards call. Remove either and the cases below disagree."""
    today = permit_today()
    yesterday, tomorrow = today - timedelta(days=1), today + timedelta(days=1)
    nothing = make_requester()
    valid = make_requester()
    add_permit(curator, valid, PermitKind.PLANT_HEALTH_ISOLATION, valid_from=yesterday)
    expired = make_requester()
    add_permit(
        curator,
        expired,
        PermitKind.PLANT_HEALTH_ISOLATION,
        valid_from=yesterday,
        expires_on=yesterday,
    )
    later = make_requester()
    add_permit(curator, later, PermitKind.PLANT_HEALTH_ISOLATION, valid_from=tomorrow)
    ended = make_requester()
    permit = add_permit(curator, ended, PermitKind.PLANT_HEALTH_ISOLATION, valid_from=yesterday)
    with as_actor(curator):
        services.permit_end(
            access=access_for(curator), permit=permit, ended_on=today, reason="revoked"
        )
    letter_only = make_requester()
    add_permit(curator, letter_only, PermitKind.PLANT_HEALTH_LOA)
    requesters = [nothing, valid, expired, later, ended, letter_only]
    with connection.cursor() as cursor:
        for one in requesters:
            for day in (yesterday, today, tomorrow):
                cursor.execute(
                    "SELECT distribution_isolation_facility_recorded(%s, %s, %s)",
                    ["public", one.pk, day],
                )
                (in_sql,) = cursor.fetchone()
                assert in_sql == isolation_facility_recorded(one.pk, day), (one.pk, day)


@pytest.mark.rule("R-DIST-15")
def test_a_letter_of_authority_without_its_endorsement_lets_nothing_out(
    *, ask: Any, supply: Supply, mockia: Taxon, requester: Requester, curator: User
) -> None:
    """Art. 6(2): the state of origin endorses the letter. It is stored, so it is read."""
    strain = supply(mockia, restrictions=[QUARANTINE], vials=10)
    add_permit(curator, requester, PermitKind.PLANT_HEALTH_ISOLATION)
    add_permit(
        curator,
        requester,
        PermitKind.PLANT_HEALTH_LOA,
        endorsement_reference="",
        endorsed_on=None,
    )
    found = {f.code: f.sentence for f in evaluate(ask(strain), permit_today()).findings}
    assert found.keys() == {"regulated", "loa_not_endorsed"}
    assert "endorsement of the member state of origin" in found["loa_not_endorsed"]


@pytest.mark.rule("R-DIST-15")
def test_the_pest_goes_out_on_the_endorsed_letter_beside_an_unendorsed_one(
    *, ask: Any, supply: Supply, mockia: Taxon, requester: Requester, curator: User
) -> None:
    strain = supply(mockia, restrictions=[QUARANTINE], vials=10)
    facility = add_permit(curator, requester, PermitKind.PLANT_HEALTH_ISOLATION)
    add_permit(
        curator,
        requester,
        PermitKind.PLANT_HEALTH_LOA,
        reference="LoA/DEV/not-endorsed (invented example)",
        endorsement_reference="",
        endorsed_on=None,
    )
    endorsed = add_permit(curator, requester, PermitKind.PLANT_HEALTH_LOA)
    evaluation = evaluate(ask(strain), permit_today())
    assert {f.code for f in evaluation.findings} == {"regulated"}
    assert {permit.pk for _, permit in evaluation.used} == {facility.pk, endorsed.pk}


@pytest.mark.rule("R-DIST-07")
def test_a_letter_runs_out_of_sendings(
    *, ask: Any, supply: Supply, mockia: Taxon, requester: Requester, curator: User, manager: User
) -> None:
    strain = supply(mockia, restrictions=[QUARANTINE], vials=10)
    add_permit(curator, requester, PermitKind.PLANT_HEALTH_ISOLATION)
    add_permit(
        curator, requester, PermitKind.PLANT_HEALTH_LOA, quantity_allowed=10, sendings_allowed=1
    )
    approve(manager, ask(strain, 1), reason="letter in hand")
    assert codes(ask(strain, 1)) == {"regulated": Severity.MANAGER, "loa_exhausted": Severity.BLOCK}


@pytest.mark.rule("R-DIST-07")
def test_a_cancelled_request_gives_its_quantity_back_to_the_letter(
    *, ask: Any, supply: Supply, mockia: Taxon, requester: Requester, curator: User, manager: User
) -> None:
    strain = supply(mockia, restrictions=[QUARANTINE], vials=10)
    add_permit(curator, requester, PermitKind.PLANT_HEALTH_ISOLATION)
    add_permit(
        curator, requester, PermitKind.PLANT_HEALTH_LOA, quantity_allowed=2, sendings_allowed=1
    )
    first = approve(manager, ask(strain, 2), reason="letter in hand")
    with as_actor(curator):
        services.request_cancel(access=access_for(curator), request=first, reason="withdrawn")
    assert codes(ask(strain, 2)) == {"regulated": Severity.MANAGER}


@pytest.mark.parametrize(("category", "blocked"), [(None, True), (1, True), (2, False), (3, False)])
@pytest.mark.rule("R-DIST-08")
def test_a_gmo_needs_a_contained_use_authorisation_of_its_category_or_higher(
    *,
    ask: Any,
    supply: Supply,
    mockia: Taxon,
    requester: Requester,
    curator: User,
    category: int | None,
    blocked: bool,
) -> None:
    gmo = RestrictionInput(RestrictionKind.GMO, "MŽP DEV/2 (invented example)", gmo_category=2)
    if category is not None:
        add_permit(curator, requester, PermitKind.GMO_CONTAINED_USE, gmo_category=category)
    found = codes(ask(supply(mockia, restrictions=[gmo])))
    assert ("gmo_authorisation_missing" in found) == blocked


@pytest.mark.rule("R-DIST-09")
def test_one_strain_with_several_kinds_meets_each(
    ask: Any, supply: Supply, mockia: Taxon, requester: Requester, curator: User
) -> None:
    strain = supply(mockia, restrictions=[DUAL_USE, RAT, QUARANTINE])
    assert codes(ask(strain)) == {
        "regulated": Severity.MANAGER,
        "rat_notice_missing": Severity.BLOCK,
        "isolation_facility_missing": Severity.BLOCK,
        "loa_missing": Severity.BLOCK,
    }
    rat = add_permit(curator, requester, PermitKind.SUJB_RAT_NOTICE)
    facility = add_permit(curator, requester, PermitKind.PLANT_HEALTH_ISOLATION)
    loa = add_permit(curator, requester, PermitKind.PLANT_HEALTH_LOA)
    request = ask(strain)
    evaluation = evaluate(request, permit_today())
    assert {f.code for f in evaluation.findings} == {"regulated"}
    assert {p.pk for _, p in evaluation.used} == {rat.pk, facility.pk, loa.pk}


@pytest.mark.rule("R-DIST-01")
def test_the_destination_and_an_erased_contact_block_the_whole_request(
    ask: Any, supply: Supply, requester: Requester
) -> None:
    request = ask(supply())
    # As if the requester had been abroad: the row itself never changes (its trigger).
    request.destination_country = "NO"
    assert codes(request) == {"export_not_supported": Severity.BLOCK}
    deposits.contact_erase(contact=requester.contact, reason="erasure request 2026-2")
    request.requester.contact.refresh_from_db()
    assert codes(request) == {
        "export_not_supported": Severity.BLOCK,
        "contact_erased": Severity.BLOCK,
    }


@pytest.mark.rule("R-DIST-01")
def test_the_eu_is_its_27_member_states() -> None:
    assert len(policy.EU_MEMBER_STATES) == 27
    assert policy.in_eu("CZ") and policy.in_eu("SE") and not policy.in_eu("GB")
    assert not policy.in_eu("NO") and not policy.in_eu("CH")


@pytest.mark.rule("R-DIST-04")
def test_a_permit_names_a_synonym_through_its_accepted_name(exempli: Taxon) -> None:
    old = make_synonym("Fictivibrio exempli", Rank.SPECIES, exempli)
    assert names("Testella exempli (formerly Fictivibrio exempli)", exempli)
    assert names("fictivibrio  exempli", old)  # the synonym itself
    assert names("Testella exempli", old)  # its accepted name
    assert not names("Testella exemplii", exempli)  # whole words only
    assert not names("Testella", exempli)


def test_findings_are_request_wide_first_then_by_line(
    *,
    as_curator: AuditContext,
    curator: User,
    lab: Lab,
    make_requester: MakeRequester,
    supply: Supply,
    mockia: Taxon,
) -> None:
    abroad_ok = make_requester()
    first, second = supply(vials=1), supply(mockia, vials=1)
    request = submit(curator, lab, abroad_ok, [(first, 2), (second, 2)])
    request.destination_country = "US"
    found = evaluate(request, permit_today()).findings
    assert found[0].code == "export_not_supported" and found[0].line is None
    lines = [f.line.strain_id for f in found if f.line is not None]
    assert lines == sorted(lines, key=[first.pk, second.pk].index)


@pytest.mark.rule("R-DIST-05")
def test_only_a_section_17a_notice_lets_a_rat_go_out(
    *, ask: Any, supply: Supply, mockia: Taxon, requester: Requester, curator: User
) -> None:
    """Other documents of the requester (a VRAT permit, a work permit) are no notice to SÚJB."""
    strain = supply(mockia, restrictions=[RAT])
    add_permit(curator, requester, PermitKind.SUJB_VRAT, covers="Mockia vulgaris")
    add_permit(curator, requester, PermitKind.PATHOGEN_WORK_PERMIT, risk_group=2)
    assert "rat_notice_missing" in codes(ask(strain))


@pytest.mark.rule("R-DIST-05")
def test_a_rat_notice_that_names_a_highly_risky_agent_does_not_let_it_go_out(
    *, ask: Any, supply: Supply, mockia: Taxon, requester: Requester, curator: User
) -> None:
    """The notice covers a RAT only: a VRAT needs a permit or an exception, whatever it names."""
    strain = supply(mockia, restrictions=[VRAT])
    add_permit(curator, requester, PermitKind.SUJB_RAT_NOTICE, covers="Mockia vulgaris")
    assert "vrat_permit_missing" in codes(ask(strain))


@pytest.mark.rule("R-DIST-07")
def test_two_lines_of_one_request_draw_on_one_letter_together(
    *,
    as_curator: AuditContext,
    curator: User,
    lab: Lab,
    requester: Requester,
    supply: Supply,
    mockia: Taxon,
) -> None:
    """2019/829 Art. 6: the quantity a letter allows is for the whole sending, not per line."""
    first = supply(mockia, restrictions=[QUARANTINE])
    second = supply(mockia, restrictions=[QUARANTINE])
    add_permit(curator, requester, PermitKind.PLANT_HEALTH_ISOLATION)
    add_permit(
        curator, requester, PermitKind.PLANT_HEALTH_LOA, quantity_allowed=3, sendings_allowed=1
    )
    request = submit(curator, lab, requester, [(first, 2), (second, 2)])
    accept_mtas(curator, request)
    found = evaluate(request, permit_today()).findings
    assert [
        (f.code, f.line.strain_id if f.line else None) for f in found if f.code.startswith("loa")
    ] == [("loa_exhausted", second.pk)]


# What each finding says, word for word (#308): the sentence is what a curator and a manager
# read, so a lost or changed one fails here, not in front of them.


def said(request: DistributionRequest) -> dict[str, str]:
    return {f.code: f.sentence for f in evaluate(request, permit_today()).findings}


def deciding(decision: Decision) -> tuple[tuple[Use, Decision], ...]:
    """Terms that decide non-commercial research, the use `ask` requests, and permit the rest."""
    return tuple(
        (use, decision if use == Use.RESEARCH_NONCOMMERCIAL else d) for use, d in ALL_PERMITTED
    )


@pytest.mark.rule("R-DIST-01")
def test_a_destination_outside_the_eu_says_why_it_blocks(
    ask: Any, supply: Supply, mockia: Taxon
) -> None:
    plain = ask(supply())
    plain.destination_country = "NO"
    assert said(plain) == {
        "export_not_supported": "The destination (NO) is outside the EU: this collection does"
        " not ship outside the EU yet."
    }
    regulated = ask(supply(mockia, restrictions=[DUAL_USE]))
    regulated.destination_country = "US"
    first = evaluate(regulated, permit_today()).findings[0]
    assert (first.code, first.severity, first.line) == (
        "export_of_regulated_strain",
        Severity.BLOCK,
        None,
    )
    assert first.sentence == (
        "The destination (US) is outside the EU: regulated strains are not exported from this"
        " collection."
    )


def test_an_erased_contact_says_why_it_blocks(
    ask: Any, supply: Supply, requester: Requester
) -> None:
    request = ask(supply())
    deposits.contact_erase(contact=requester.contact, reason="erasure request 2026-3")
    request.requester.contact.refresh_from_db()
    assert said(request) == {
        "contact_erased": "The requester's contact was erased: there is no responsible scientist"
        " and no delivery address."
    }


def test_a_strain_with_no_vial_that_may_go_out_blocks(ask: Any, supply: Supply) -> None:
    strain = supply(release=False)
    assert said(ask(strain)) == {
        "not_enough_vials": f"{strain.accession_number}: 0 vials may go out now, the line asks"
        " for 1."
    }


def test_reserved_vials_of_a_batch_held_after_the_approval_block(
    ask: Any, supply: Supply, curator: User
) -> None:
    strain = supply(vials=2)
    request = approve(curator, ask(strain, 2))
    assert said(request) == {}
    with as_actor(curator):
        lineage.batch_hold(
            access=access_for(curator),
            batch=Batch.objects.get(strain=strain),
            reason="contamination suspected",
        )
    found = evaluate(request, permit_today()).findings
    assert [(f.code, f.severity, f.sentence) for f in found] == [
        (
            "reserved_vials_not_distributable",
            Severity.BLOCK,
            f"{strain.accession_number}: 0 of its 2 reserved vials may still go out. A batch was"
            " held or exhausted, or the strain stopped supplying.",
        )
    ]


@pytest.mark.rule("R-DIST-13")
def test_the_terms_gates_say_what_the_terms_do_not_allow(
    ask: Any, supply: Supply, curator: User
) -> None:
    unknown = supply(abs_scope=AbsScope.UNKNOWN)
    assert said(ask(unknown)) == {
        "abs_scope_unknown": f"{unknown.accession_number}: whether the ABS regulation applies is"
        " unknown. Nothing goes out until the terms say."
    }
    in_scope = supply(abs_scope=AbsScope.IN_SCOPE, ircc="ABSCH-IRCC-XX-1 (invented example)")
    assert said(ask(in_scope)) == {
        "abs_use_not_covered": f"{in_scope.accession_number}: the mutually agreed terms do not"
        " cover non-commercial research."
    }
    denied = supply(uses=deciding(Decision.DENY))
    assert said(ask(denied)) == {
        "use_denied": f"{denied.accession_number}: the depositor's terms do not permit"
        " non-commercial research."
    }
    replaced = supply()
    request = ask(replaced)
    deposits.deposit_terms_replace(
        access=access_for(curator),
        deposit=Deposit.objects.get(strain=replaced),
        terms=terms(mta=request.lines.get().mta),
        reason="corrected",
    )
    assert said(request) == {
        "terms_replaced": f"{replaced.accession_number}: its terms changed after the request was"
        " entered. Cancel the request and enter it again under the new terms."
    }


def test_the_depositors_answer_decides_a_use_on_request(
    ask: Any, supply: Supply, curator: User, lab: Lab
) -> None:
    """#144: a yes lets the line out, a no blocks it with the day of the answer."""
    strain = supply(uses=ON_REQUEST_USES)
    name = strain.accession_number
    agreed = ask(strain, use=Use.RESEARCH_COMMERCIAL)
    assert said(agreed) == {
        "use_on_request": f"{name}: the terms allow commercial research only on request to the"
        " depositor, and no answer of the depositor is recorded. Record it on the strain's line."
    }
    answer(curator, agreed)
    assert said(agreed) == {}
    declined = ask(strain, use=Use.RESEARCH_COMMERCIAL)
    # The service rejects a request with a no; a no written beside it still blocks.
    DepositorAnswer.objects.create(
        lab=lab,
        line=declined.lines.get(),
        agreed=False,
        answered_on=date(2026, 10, 3),
        note="Declined.",
        recorded_by=curator,
        recorded_at=timezone.now(),
    )
    assert said(declined) == {
        "use_declined_by_depositor": f"{name}: the depositor declined commercial research"
        " (answer of 2026-10-03)."
    }


def test_the_mta_gates_name_the_mta_and_an_acceptance_counts_for_its_request(
    ask: Any, supply: Supply
) -> None:
    missing = supply(mta=None)
    assert said(ask(missing, accept=False)) == {
        "mta_missing": f"{missing.accession_number}: its terms name no MTA, and nothing goes out"
        " without one."
    }
    strain = supply()
    request = ask(strain, accept=False)
    assert said(ask(strain)) == {}  # another request, the same MTA version accepted for it
    mta = request.lines.get().mta
    assert mta is not None
    assert said(request) == {
        "mta_not_accepted": f"{strain.accession_number}: no acceptance of MTA {mta.code} version"
        f" {mta.version} signed by someone who may bind the requester is recorded."
    }


def test_the_biosafety_gates_say_the_group_and_the_level(
    ask: Any, supply: Supply, requester: Requester, curator: User
) -> None:
    group_2 = supply(risk_group=2)
    name = group_2.accession_number
    assert said(ask(group_2, containment_level=1)) == {
        "containment_too_low": f"{name} is risk group 2; the requester declares containment"
        " level 1.",
        "work_permit_missing": f"{name} is risk group 2 and the requester shows no permit to work"
        " with it. A manager approves when the destination needs none.",
    }
    add_permit(curator, requester, PermitKind.PATHOGEN_WORK_PERMIT, risk_group=3)
    group_3 = supply(risk_group=3)
    assert said(ask(group_3, containment_level=3)) == {
        "category_a_possible": f"{group_3.accession_number} is risk group 3: its culture may be"
        " Category A (UN 2814), which this collection does not ship. The shipper classifies it."
    }


def test_the_gates_of_restrictions_say_what_the_requester_lacks(
    ask: Any, supply: Supply, mockia: Taxon
) -> None:
    ricin = RestrictionInput(RestrictionKind.DUAL_USE, "1C351.d.4", act="(EU) 2025/2003")
    cases = {
        "cz_vrat": (VRAT, "{} is a highly risky agent: the requester shows no valid SÚJB permit"
                    " or exception that names Mockia vulgaris."),
        "cz_rat": (RAT, "{} is a risky agent: the requester shows no reference of a notice to"
                   " SÚJB (§ 17a) that names Mockia vulgaris."),
        "dual_use": (ricin, "{} (1C351.d.4) needs a licence for a transfer within the EU, which"
                     " this collection does not hold."),
        "gmo": (GMO, "{} is a GMO of category 1: the requester shows no authorisation for"
                " contained use of category 1 or higher (act 78/2004 Sb.)."),
    }  # fmt: skip
    for kind, (restriction, sentence) in cases.items():
        strain = supply(mockia, restrictions=[restriction])
        name = strain.accession_number
        missing = sentence.format(name)
        found = list(said(ask(strain)).items())
        assert found == [("regulated", f"{name} is regulated ({kind}): a manager approves it.")] + [
            (code, missing) for code in GATE_OF[kind]
        ]
    pest = supply(mockia, restrictions=[QUARANTINE])
    assert said(ask(pest)) == {
        "regulated": f"{pest.accession_number} is regulated (quarantine_pest): a manager approves"
        " it.",
        "isolation_facility_missing": f"{pest.accession_number} is a quarantine pest: the"
        " requester shows no authorisation of an isolation facility (a quarantine station or"
        " confinement facility designated by the competent authority) under Implementing"
        " Regulation (EU) 2019/829.",
        "loa_missing": f"{pest.accession_number} is a quarantine pest: the requester shows no"
        " valid Letter of Authority that names Mockia vulgaris.",
    }


GATE_OF = {
    "cz_vrat": ["vrat_permit_missing"],
    "cz_rat": ["rat_notice_missing"],
    "dual_use": ["transfer_licence_required"],
    "gmo": ["gmo_authorisation_missing"],
}


@pytest.mark.rule("R-DIST-15")
def test_the_letter_gates_say_what_the_letters_lack(
    *, ask: Any, supply: Supply, mockia: Taxon, make_requester: MakeRequester, curator: User
) -> None:
    strain = supply(mockia, restrictions=[QUARANTINE], vials=10)
    name = strain.accession_number
    unendorsed = make_requester()
    add_permit(curator, unendorsed, PermitKind.PLANT_HEALTH_ISOLATION)
    add_permit(
        curator,
        unendorsed,
        PermitKind.PLANT_HEALTH_LOA,
        endorsement_reference="",
        endorsed_on=None,
    )
    assert said(ask(strain, requester=unendorsed))["loa_not_endorsed"] == (
        f"{name}: no Letter of Authority of the requester that names Mockia vulgaris carries the"
        " endorsement of the member state of origin (Regulation (EU) 2019/829, Art. 6(2))."
    )
    short = make_requester()
    add_permit(curator, short, PermitKind.PLANT_HEALTH_ISOLATION)
    add_permit(curator, short, PermitKind.PLANT_HEALTH_LOA, quantity_allowed=1)
    assert said(ask(strain, 2, requester=short))["loa_exhausted"] == (
        f"{name}: no Letter of Authority of the requester has the quantity or a sending left for"
        " this line."
    )


@pytest.mark.rule("R-DIST-09")
def test_a_strains_restrictions_are_met_in_the_order_of_their_kinds(
    ask: Any, supply: Supply, mockia: Taxon
) -> None:
    """Entered as a pest first, the strain is still read as a RAT first: kinds in their order."""
    strain = supply(mockia, restrictions=[QUARANTINE, RAT])
    found = evaluate(ask(strain), permit_today()).findings
    assert [f.code for f in found] == [
        "regulated",
        "rat_notice_missing",
        "isolation_facility_missing",
        "loa_missing",
    ]
    assert found[0].sentence == (
        f"{strain.accession_number} is regulated (cz_rat, quarantine_pest): a manager approves it."
    )


@pytest.mark.rule("R-DIST-16")
def test_a_line_goes_out_on_the_oldest_permits_that_hold(
    *, ask: Any, supply: Supply, mockia: Taxon, requester: Requester, curator: User
) -> None:
    """The line records the permit it went out on: of several that hold, the oldest."""
    later, earlier = date(2026, 3, 1), date(2026, 1, 1)
    add_permit(curator, requester, PermitKind.PATHOGEN_WORK_PERMIT, valid_from=later)
    work = add_permit(curator, requester, PermitKind.PATHOGEN_WORK_PERMIT, valid_from=earlier)
    add_permit(curator, requester, PermitKind.PLANT_HEALTH_ISOLATION, valid_from=later)
    facility = add_permit(curator, requester, PermitKind.PLANT_HEALTH_ISOLATION, valid_from=earlier)
    letter = add_permit(curator, requester, PermitKind.PLANT_HEALTH_LOA)
    strain = supply(mockia, restrictions=[QUARANTINE], risk_group=2)
    evaluation = evaluate(ask(strain), permit_today())
    assert [f.code for f in evaluation.findings] == ["regulated"]
    assert [permit.pk for _, permit in evaluation.used] == [work.pk, facility.pk, letter.pk]


@pytest.mark.rule("R-DIST-07")
def test_three_lines_of_one_request_add_up_on_one_letter(
    *,
    as_curator: AuditContext,
    curator: User,
    lab: Lab,
    requester: Requester,
    supply: Supply,
    mockia: Taxon,
) -> None:
    strains = [supply(mockia, restrictions=[QUARANTINE]) for _ in range(3)]
    add_permit(curator, requester, PermitKind.PLANT_HEALTH_ISOLATION)
    add_permit(
        curator, requester, PermitKind.PLANT_HEALTH_LOA, quantity_allowed=2, sendings_allowed=1
    )
    request = submit(curator, lab, requester, [(strain, 1) for strain in strains])
    accept_mtas(curator, request)
    found = evaluate(request, permit_today()).findings
    assert [
        (f.code, f.line.strain_id if f.line else None) for f in found if f.code.startswith("loa")
    ] == [("loa_exhausted", strains[2].pk)]


@pytest.mark.rule("R-DIST-07")
def test_a_sending_is_one_request_however_many_lines_it_has(
    *,
    as_curator: AuditContext,
    curator: User,
    manager: User,
    lab: Lab,
    requester: Requester,
    supply: Supply,
    mockia: Taxon,
) -> None:
    first, second = (supply(mockia, restrictions=[QUARANTINE]) for _ in range(2))
    add_permit(curator, requester, PermitKind.PLANT_HEALTH_ISOLATION)
    add_permit(
        curator, requester, PermitKind.PLANT_HEALTH_LOA, quantity_allowed=10, sendings_allowed=2
    )
    request = submit(curator, lab, requester, [(first, 1), (second, 1)])
    accept_mtas(curator, request)
    approve(manager, request, reason="letter in hand")
    again = submit(curator, lab, requester, [(first, 1)])
    accept_mtas(curator, again)
    assert codes(again) == {"regulated": Severity.MANAGER}


@pytest.mark.rule("R-DIST-03")
def test_a_finding_is_decided_by_its_code_and_its_line(ask: Any, supply: Supply) -> None:
    line = ask(supply()).lines.get()
    assert finding_key(Finding("contact_erased", Severity.BLOCK, "Erased.")) == "contact_erased"
    in_line = Finding("regulated", Severity.MANAGER, "Regulated.", line)
    assert finding_key(in_line) == f"regulated:{line.public_id}"


@pytest.mark.parametrize("lines", [1, 3])
def test_the_gates_read_in_a_fixed_number_of_queries(
    *,
    as_curator: AuditContext,
    curator: User,
    lab: Lab,
    requester: Requester,
    supply: Supply,
    query_baseline: QueryBaseline,
    lines: int,
) -> None:
    """Whatever the number of lines: one step per source (_Facts), none per line."""
    request = submit(curator, lab, requester, [(supply(), 1) for _ in range(lines)])
    accept_mtas(curator, request)
    fresh = DistributionRequest.objects.get(pk=request.pk)
    with query_baseline("policy_evaluate"):
        evaluation = evaluate(fresh, permit_today())
    assert evaluation.findings == ()
