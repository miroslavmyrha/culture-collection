"""A restriction points at the entry of the official list it names, and a dual-use entry that
decree 474/2002 Sb. also lists needs that restriction too (#169).

The pairs of entries come from the lists themselves (`a_dual_use_entry_also_listed_as`), so no
test here states a legal fact about an organism of its own: it asks the data files what they
hold. The strains are of invented taxa, as the conventions ask.

Each rule twice: through the service, and against the database for a writer that skips it.
"""

from typing import Any

import pytest
from django.db import IntegrityError, transaction

from cultures.audit.context import audit_context
from cultures.audit.models import Channel
from cultures.biosafety.models import (
    AuthorisationKind,
    ListCode,
    RegulatoryListEntry,
    RestrictionKind,
)
from cultures.biosafety.selectors import DUAL_USE_ORGANISM, also_a_cz_agent, list_entry
from cultures.labs.access import Access, access_for
from cultures.labs.models import Lab
from cultures.strains import services
from cultures.strains.models import Strain, StrainRestriction
from cultures.strains.services import RestrictionInput
from cultures.users.models import User

from .conftest import (
    DUAL_USE,
    GMO,
    MakeStrain,
    at_commit,
    make_permit,
    new_strain,
    refused_at_commit,
)

pytestmark = pytest.mark.django_db

ACT = "(EU) 2025/2003"


def a_dual_use_entry_also_listed_as(kind: RestrictionKind) -> tuple[RegulatoryListEntry, str]:
    """A dual-use entry of 1C351.a, 1C351.c, 1C351.e or 1C354 that the current reading of
    decree 474/2002 Sb. lists as `kind`, with the code of that decree's entry."""
    candidates = (
        RegulatoryListEntry.objects.filter(
            list__code=ListCode.EU_2021_821_ANNEX_I, list__is_current=True
        )
        .exclude(match_name="")
        .order_by("code")
    )
    for entry in candidates:
        if not DUAL_USE_ORGANISM.match(entry.code):
            continue
        counterpart = also_a_cz_agent(entry)
        if counterpart is not None and counterpart.restriction_kind == kind:
            return entry, counterpart.code
    raise AssertionError(f"no dual-use entry of the lists is also a {kind}")


def row(strain: Strain, **fields: Any) -> StrainRestriction:
    """A restriction written straight to the table, as a writer that skips the service would."""
    values: dict[str, Any] = {"kind": RestrictionKind.CZ_RAT, "reference": "Annex 2, item 1"}
    return StrainRestriction.objects.create(lab=strain.lab, strain=strain, **{**values, **fields})


def add(
    access: Access, strain: Strain, restriction: RestrictionInput, reason: str = "Read in the list."
) -> StrainRestriction:
    return services.strain_restriction_add(
        access=access, strain=strain, restriction=restriction, reason=reason
    )


# A restriction points at its list entry (the second box of #169).


@pytest.mark.rule("R-KIND-10")
def test_a_dual_use_restriction_points_at_the_annex_entry_it_names(
    make_strain: MakeStrain, curator_access: Access, as_curator: Any
) -> None:
    added = add(curator_access, make_strain(), DUAL_USE)
    entry = list_entry(RestrictionKind.DUAL_USE, DUAL_USE.reference)
    assert entry is not None
    assert added.list_entry_id == entry.pk
    assert entry.code == DUAL_USE.reference
    assert entry.list.code == ListCode.EU_2021_821_ANNEX_I


@pytest.mark.rule("R-KIND-10")
def test_a_dual_use_reference_annex_i_does_not_hold_is_refused(
    make_strain: MakeStrain, curator_access: Access, as_curator: Any
) -> None:
    """1C351.a.99 has the shape of an Annex I entry, so the pattern of R-KIND-02 takes it, and
    the annex holds no such entry, so the list refuses it."""
    strain = make_strain()
    with pytest.raises(services.DualUseEntryUnknown) as refusal:
        add(
            curator_access,
            strain,
            RestrictionInput(RestrictionKind.DUAL_USE, "1C351.a.99", act=ACT),
        )
    assert (refusal.value.code, refusal.value.attr) == ("dual_use_entry_unknown", "reference")
    assert not StrainRestriction.objects.filter(strain=strain).exists()


@pytest.mark.rule("R-KIND-10")
def test_the_database_refuses_a_dual_use_row_with_no_entry(make_strain: MakeStrain) -> None:
    with pytest.raises(IntegrityError, match="names an entry Annex I"), transaction.atomic():
        row(make_strain(), kind=RestrictionKind.DUAL_USE, reference="1C351.c", act=ACT)


@pytest.mark.rule("R-KIND-10")
def test_the_database_refuses_an_entry_that_is_not_the_reference(make_strain: MakeStrain) -> None:
    other = list_entry(RestrictionKind.DUAL_USE, "1C353")
    assert other is not None
    with pytest.raises(IntegrityError, match="names an entry Annex I"), transaction.atomic():
        row(
            make_strain(),
            kind=RestrictionKind.DUAL_USE,
            reference="1C351.c",
            act=ACT,
            list_entry=other,
        )


@pytest.mark.rule("R-KIND-10")
def test_the_database_refuses_an_entry_of_another_list(make_strain: MakeStrain) -> None:
    dual_use = list_entry(RestrictionKind.DUAL_USE, "1C351.c")
    assert dual_use is not None
    with pytest.raises(IntegrityError, match="its own list"), transaction.atomic():
        row(make_strain(), kind=RestrictionKind.CZ_RAT, reference="x", list_entry=dual_use)


@pytest.mark.rule("R-KIND-10")
def test_the_database_refuses_an_entry_on_a_gmo(make_strain: MakeStrain) -> None:
    dual_use = list_entry(RestrictionKind.DUAL_USE, "1C351.c")
    assert dual_use is not None
    with pytest.raises(IntegrityError, match="its own list"), transaction.atomic():
        row(
            make_strain(),
            kind=RestrictionKind.GMO,
            reference="notification 1",
            gmo_category=1,
            list_entry=dual_use,
        )


@pytest.mark.rule("R-KIND-10")
def test_a_gmo_and_a_restriction_of_words_the_list_does_not_hold_keep_no_entry(
    make_strain: MakeStrain, curator_access: Access, as_curator: Any
) -> None:
    """A GMO is on no official list. A VRAT, a RAT and a quarantine pest are referred to by the
    words of their annex, so an entry is attached where the reference is an entry code of the
    list and not demanded where it is not."""
    strain = make_strain()
    assert add(curator_access, strain, GMO).list_entry_id is None
    make_permit(strain.lab, AuthorisationKind.CZ_VRAT)
    typed = RestrictionInput(RestrictionKind.CZ_VRAT, "Annex 1, item 2")
    assert add(curator_access, strain, typed).list_entry_id is None


@pytest.mark.rule("R-KIND-10")
def test_a_vrat_reference_that_is_an_entry_code_of_the_decree_gets_its_entry(
    make_strain: MakeStrain, curator_access: Access, as_curator: Any
) -> None:
    entry = (
        RegulatoryListEntry.objects.filter(
            list__code=ListCode.CZ_474_2002,
            list__is_current=True,
            restriction_kind=RestrictionKind.CZ_RAT,
        )
        .order_by("code")
        .first()
    )
    assert entry is not None
    added = add(curator_access, make_strain(), RestrictionInput(RestrictionKind.CZ_RAT, entry.code))
    assert added.list_entry_id == entry.pk


# A dual-use entry that decree 474/2002 Sb. also lists (the last box of #169).


@pytest.mark.rule("R-KIND-11")
@pytest.mark.parametrize("kind", [RestrictionKind.CZ_VRAT, RestrictionKind.CZ_RAT])
def test_a_dual_use_entry_the_decree_also_lists_needs_that_restriction(
    make_strain: MakeStrain, curator_access: Access, as_curator: Any, kind: RestrictionKind
) -> None:
    entry, _ = a_dual_use_entry_also_listed_as(kind)
    strain = make_strain()
    dual_use = RestrictionInput(RestrictionKind.DUAL_USE, entry.code, act=ACT)
    with pytest.raises(services.RestrictionRequiredByEntry) as refusal:
        add(curator_access, strain, dual_use)
    assert refusal.value.code == "restriction_required_by_entry"
    assert refusal.value.attr == "reference"
    assert refusal.value.kind == kind
    assert not StrainRestriction.objects.filter(strain=strain).exists()


@pytest.mark.rule("R-KIND-11")
def test_the_dual_use_restriction_is_taken_once_the_decrees_restriction_is_there(
    make_strain: MakeStrain, curator_access: Access, as_curator: Any
) -> None:
    entry, cz_code = a_dual_use_entry_also_listed_as(RestrictionKind.CZ_VRAT)
    strain = make_strain()
    make_permit(strain.lab, AuthorisationKind.CZ_VRAT)
    with at_commit():
        add(curator_access, strain, RestrictionInput(RestrictionKind.CZ_VRAT, cz_code))
        added = add(
            curator_access, strain, RestrictionInput(RestrictionKind.DUAL_USE, entry.code, act=ACT)
        )
    assert added.list_entry_id == entry.pk


@pytest.mark.rule("R-KIND-11")
def test_one_accession_may_record_both_restrictions_at_once(
    lab: Lab, curator: User, curator_access: Access, exempli: Any, as_curator: Any
) -> None:
    entry, cz_code = a_dual_use_entry_also_listed_as(RestrictionKind.CZ_VRAT)
    make_permit(lab, AuthorisationKind.CZ_VRAT)
    with at_commit():
        strain = services.strain_create(
            access=curator_access,
            lab=lab,
            data=new_strain(
                exempli,
                restrictions=[
                    RestrictionInput(RestrictionKind.DUAL_USE, entry.code, act=ACT),
                    RestrictionInput(RestrictionKind.CZ_VRAT, cz_code),
                ],
            ),
        )
    assert set(strain.restrictions.values_list("kind", flat=True)) == {"dual_use", "cz_vrat"}


@pytest.mark.rule("R-KIND-11")
def test_an_accession_of_the_dual_use_entry_alone_is_refused(
    lab: Lab, curator_access: Access, exempli: Any, as_curator: Any
) -> None:
    entry, _ = a_dual_use_entry_also_listed_as(RestrictionKind.CZ_VRAT)
    with pytest.raises(services.RestrictionRequiredByEntry) as refusal:
        services.strain_create(
            access=curator_access,
            lab=lab,
            data=new_strain(
                exempli,
                restrictions=[RestrictionInput(RestrictionKind.DUAL_USE, entry.code, act=ACT)],
            ),
        )
    assert refusal.value.attr == "restrictions.0.reference"
    assert not Strain.objects.filter(lab=lab).exists()


@pytest.mark.rule("R-KIND-11")
def test_the_database_asks_for_the_decrees_restriction_at_the_commit(
    make_strain: MakeStrain,
) -> None:
    entry, _ = a_dual_use_entry_also_listed_as(RestrictionKind.CZ_VRAT)
    strain = make_strain()
    with refused_at_commit("needs its own restriction"):
        row(
            strain,
            kind=RestrictionKind.DUAL_USE,
            reference=entry.code,
            act=ACT,
            list_entry=entry,
        )


@pytest.mark.rule("R-KIND-11")
def test_the_database_takes_both_restrictions_in_one_transaction(
    make_strain: MakeStrain,
) -> None:
    """Deferred to the commit on purpose: the order the two rows are written in is the
    service's business, and in between the rule does not hold yet."""
    entry, cz_code = a_dual_use_entry_also_listed_as(RestrictionKind.CZ_VRAT)
    strain = make_strain()
    with at_commit():
        row(
            strain,
            kind=RestrictionKind.DUAL_USE,
            reference=entry.code,
            act=ACT,
            list_entry=entry,
        )
        row(strain, kind=RestrictionKind.CZ_VRAT, reference=cz_code)


@pytest.mark.rule("R-KIND-11")
def test_a_dual_use_entry_the_decree_does_not_list_asks_for_nothing(
    make_strain: MakeStrain, curator_access: Access, as_curator: Any
) -> None:
    """1C351.c itself heads a group of entries and names no organism, so nothing pairs with it."""
    entry = list_entry(RestrictionKind.DUAL_USE, DUAL_USE.reference)
    assert entry is not None
    assert entry.match_name == ""
    with at_commit():
        add(curator_access, make_strain(), DUAL_USE)


@pytest.mark.rule("R-KIND-11")
def test_the_decrees_restriction_does_not_end_while_the_dual_use_entry_asks_for_it(
    make_strain: MakeStrain, curator_access: Access, manager: User, as_curator: Any
) -> None:
    entry, cz_code = a_dual_use_entry_also_listed_as(RestrictionKind.CZ_VRAT)
    strain = make_strain()
    make_permit(strain.lab, AuthorisationKind.CZ_VRAT)
    with at_commit():
        vrat = add(curator_access, strain, RestrictionInput(RestrictionKind.CZ_VRAT, cz_code))
        add(curator_access, strain, RestrictionInput(RestrictionKind.DUAL_USE, entry.code, act=ACT))
    with pytest.raises(services.RestrictionHeldByDualUse):
        services.strain_restriction_end_propose(
            access=curator_access, restriction=vrat, reason="No longer needed."
        )
    with (
        audit_context(channel=Channel.API, actor=manager, request_id="req-x"),
        pytest.raises(services.RestrictionHeldByDualUse),
    ):
        services.strain_restriction_end_propose(
            access=access_for(manager), restriction=vrat, reason="No longer needed."
        )
    vrat.refresh_from_db()
    assert vrat.ended_at is None
