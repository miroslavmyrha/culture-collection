"""The policy, gate by gate and both ways: each finding appears when its rule is broken and is
gone once the request meets it, with its stable code, its severity and a sentence that names
the strain. Regulated examples are the invented Mockia vulgaris with each restriction kind."""

from datetime import date, timedelta
from typing import Any

import pytest

from cultures.audit.context import AuditContext
from cultures.biosafety.models import RestrictionKind
from cultures.biosafety.policy import permit_today
from cultures.deposits import services as deposits
from cultures.deposits.models import AbsScope, Decision, Deposit, Use
from cultures.deposits.tests.support import ALL_PERMITTED, DUAL_USE, QUARANTINE, VRAT, terms
from cultures.distribution import policy, services
from cultures.distribution.models import DistributionRequest, PermitKind, Requester
from cultures.distribution.policy import GATES, Severity, evaluate, names
from cultures.labs.access import access_for
from cultures.labs.models import Lab
from cultures.strains.models import Strain
from cultures.strains.services import RestrictionInput
from cultures.taxonomy.models import Rank, Taxon
from cultures.taxonomy.tests.conftest import make_synonym
from cultures.users.models import User

from .support import MakeRequester, Supply, accept_mtas, add_permit, approve, as_actor, submit

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


def test_an_unknown_abs_scope_blocks(ask: Any, supply: Supply) -> None:
    assert codes(ask(supply(abs_scope=AbsScope.UNKNOWN))) == {"abs_scope_unknown": Severity.BLOCK}


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
def test_the_declared_containment_must_reach_the_risk_group(
    *, ask: Any, supply: Supply, requester: Requester, curator: User, level: int, blocked: bool
) -> None:
    add_permit(curator, requester, PermitKind.PATHOGEN_WORK_PERMIT)
    found = codes(ask(supply(risk_group=2), containment_level=level))
    assert ("containment_too_low" in found) == blocked


@pytest.mark.parametrize(
    ("permit_group", "expected"), [(None, True), (1, True), (2, False), (3, False)]
)
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


def test_risk_group_3_may_be_category_a(
    ask: Any, supply: Supply, requester: Requester, curator: User
) -> None:
    add_permit(curator, requester, PermitKind.PATHOGEN_WORK_PERMIT, risk_group=3)
    assert codes(ask(supply(risk_group=3), containment_level=3)) == {
        "category_a_possible": Severity.MANAGER
    }


def test_a_regulated_strain_needs_a_manager(ask: Any, supply: Supply, mockia: Taxon) -> None:
    found = evaluate(ask(supply(mockia, restrictions=[DUAL_USE])), permit_today()).findings
    assert [(f.code, f.severity) for f in found] == [("regulated", Severity.MANAGER)]
    assert "dual_use" in found[0].sentence


def test_a_vrat_goes_only_to_a_holder_of_a_permit_that_names_it(
    ask: Any, supply: Supply, mockia: Taxon, requester: Requester, curator: User
) -> None:
    strain = supply(mockia, restrictions=[VRAT])
    assert "vrat_permit_missing" in codes(ask(strain))
    add_permit(curator, requester, PermitKind.SUJB_VRAT, covers="Testella exempli")
    assert "vrat_permit_missing" in codes(ask(strain))  # names another agent
    add_permit(curator, requester, PermitKind.SUJB_VRAT, covers="Brucella; Mockia  VULGARIS")
    assert codes(ask(strain)) == {"regulated": Severity.MANAGER}


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


def test_a_rat_goes_only_to_a_requester_who_notified_sujb(
    ask: Any, supply: Supply, mockia: Taxon, requester: Requester, curator: User
) -> None:
    strain = supply(mockia, restrictions=[RAT])
    assert codes(ask(strain)) == {
        "regulated": Severity.MANAGER,
        "rat_notice_missing": Severity.BLOCK,
    }
    add_permit(curator, requester, PermitKind.SUJB_RAT_NOTICE)
    assert codes(ask(strain)) == {"regulated": Severity.MANAGER}


@pytest.mark.parametrize(
    ("entry", "blocked"),
    [("1C351.d.4", True), ("1C351.d.5", True), ("1C351.d.1", False), ("1C351.c", False)],
)
def test_only_ricin_and_saxitoxin_need_a_transfer_licence_inside_the_eu(
    ask: Any, supply: Supply, mockia: Taxon, entry: str, blocked: bool
) -> None:
    restriction = RestrictionInput(RestrictionKind.DUAL_USE, entry, act="(EU) 2025/2003")
    found = codes(ask(supply(mockia, restrictions=[restriction])))
    assert ("transfer_licence_required" in found) == blocked


def test_a_quarantine_pest_needs_a_letter_with_quantity_and_sendings_left(
    *, ask: Any, supply: Supply, mockia: Taxon, requester: Requester, curator: User, manager: User
) -> None:
    strain = supply(mockia, restrictions=[QUARANTINE], vials=10)
    assert "loa_missing" in codes(ask(strain))
    add_permit(
        curator, requester, PermitKind.PLANT_HEALTH_LOA, quantity_allowed=3, sendings_allowed=2
    )
    first = ask(strain, 2)
    assert codes(first) == {"regulated": Severity.MANAGER}
    approve(manager, first, reason="letter in hand")
    assert codes(ask(strain, 2)) == {"regulated": Severity.MANAGER, "loa_exhausted": Severity.BLOCK}
    assert codes(ask(strain, 1)) == {"regulated": Severity.MANAGER}


def test_a_letter_runs_out_of_sendings(
    *, ask: Any, supply: Supply, mockia: Taxon, requester: Requester, curator: User, manager: User
) -> None:
    strain = supply(mockia, restrictions=[QUARANTINE], vials=10)
    add_permit(
        curator, requester, PermitKind.PLANT_HEALTH_LOA, quantity_allowed=10, sendings_allowed=1
    )
    approve(manager, ask(strain, 1), reason="letter in hand")
    assert codes(ask(strain, 1)) == {"regulated": Severity.MANAGER, "loa_exhausted": Severity.BLOCK}


def test_a_cancelled_request_gives_its_quantity_back_to_the_letter(
    *, ask: Any, supply: Supply, mockia: Taxon, requester: Requester, curator: User, manager: User
) -> None:
    strain = supply(mockia, restrictions=[QUARANTINE], vials=10)
    add_permit(
        curator, requester, PermitKind.PLANT_HEALTH_LOA, quantity_allowed=2, sendings_allowed=1
    )
    first = approve(manager, ask(strain, 2), reason="letter in hand")
    with as_actor(curator):
        services.request_cancel(access=access_for(curator), request=first, reason="withdrawn")
    assert codes(ask(strain, 2)) == {"regulated": Severity.MANAGER}


@pytest.mark.parametrize(("category", "blocked"), [(None, True), (1, True), (2, False), (3, False)])
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


def test_one_strain_with_several_kinds_meets_each(
    ask: Any, supply: Supply, mockia: Taxon, requester: Requester, curator: User
) -> None:
    strain = supply(mockia, restrictions=[DUAL_USE, RAT, QUARANTINE])
    assert codes(ask(strain)) == {
        "regulated": Severity.MANAGER,
        "rat_notice_missing": Severity.BLOCK,
        "loa_missing": Severity.BLOCK,
    }
    rat = add_permit(curator, requester, PermitKind.SUJB_RAT_NOTICE)
    loa = add_permit(curator, requester, PermitKind.PLANT_HEALTH_LOA)
    request = ask(strain)
    evaluation = evaluate(request, permit_today())
    assert {f.code for f in evaluation.findings} == {"regulated"}
    assert {p.pk for _, p in evaluation.used} == {rat.pk, loa.pk}


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


def test_the_eu_is_its_27_member_states() -> None:
    assert len(policy.EU_MEMBER_STATES) == 27
    assert policy.in_eu("CZ") and policy.in_eu("SE") and not policy.in_eu("GB")
    assert not policy.in_eu("NO") and not policy.in_eu("CH")


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


def test_only_a_section_17a_notice_lets_a_rat_go_out(
    *, ask: Any, supply: Supply, mockia: Taxon, requester: Requester, curator: User
) -> None:
    """Other documents of the requester (a VRAT permit, a work permit) are no notice to SÚJB."""
    strain = supply(mockia, restrictions=[RAT])
    add_permit(curator, requester, PermitKind.SUJB_VRAT, covers="Mockia vulgaris")
    add_permit(curator, requester, PermitKind.PATHOGEN_WORK_PERMIT, risk_group=2)
    assert "rat_notice_missing" in codes(ask(strain))


def test_a_rat_notice_that_names_a_highly_risky_agent_does_not_let_it_go_out(
    *, ask: Any, supply: Supply, mockia: Taxon, requester: Requester, curator: User
) -> None:
    """The notice covers a RAT only: a VRAT needs a permit or an exception, whatever it names."""
    strain = supply(mockia, restrictions=[VRAT])
    add_permit(curator, requester, PermitKind.SUJB_RAT_NOTICE, covers="Mockia vulgaris")
    assert "vrat_permit_missing" in codes(ask(strain))


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
    add_permit(
        curator, requester, PermitKind.PLANT_HEALTH_LOA, quantity_allowed=3, sendings_allowed=1
    )
    request = submit(curator, lab, requester, [(first, 2), (second, 2)])
    accept_mtas(curator, request)
    found = evaluate(request, permit_today()).findings
    assert [
        (f.code, f.line.strain_id if f.line else None) for f in found if f.code.startswith("loa")
    ] == [("loa_exhausted", second.pk)]
