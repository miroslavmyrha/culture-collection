"""The lab's media and the growth conditions of a strain change only through the services:
the role read under the lab lock, a medium of the lab and not retired, one event per change,
and refusals that change nothing and record nothing (#79)."""

from collections.abc import Callable
from typing import Any

import pytest

from cultures.audit.context import AuditContext, audit_context
from cultures.audit.models import AuditEvent, Channel, RowChange
from cultures.core.exceptions import DomainError, Forbidden, RuleViolation
from cultures.growth import services
from cultures.growth.models import Atmosphere, GrowthMedium
from cultures.growth.services import Growth
from cultures.labs.access import access_for
from cultures.labs.models import Lab
from cultures.labs.permissions import Role
from cultures.strains import services as strains
from cultures.strains.models import Strain
from cultures.users.models import User

from .conftest import MakeMedium

pytestmark = pytest.mark.django_db
REASON = "Moved to the type-strain conditions"


def snapshot() -> tuple[Any, ...]:
    return (
        list(GrowthMedium.objects.order_by("pk").values()),
        list(Strain.objects.order_by("pk").values()),
        AuditEvent.objects.count(),
        RowChange.objects.count(),
    )


def refused(
    error: type[DomainError], code: str, call: Callable[[], object], attr: str | None = None
) -> None:
    before = snapshot()
    with pytest.raises(error) as raised:
        call()
    assert (raised.value.code, raised.value.attr) == (code, attr)
    assert snapshot() == before


def set_growth(curator: User, strain: Strain, growth: Growth, reason: str = REASON) -> None:
    strains.strain_set_growth(
        access=access_for(curator), strain=strain, growth=growth, reason=reason
    )


# Media.


def test_a_curator_adds_a_medium_and_the_event_names_it(
    as_curator: AuditContext, curator: User, lab: Lab
) -> None:
    medium = services.medium_create(
        access=access_for(curator),
        lab=lab,
        name="  Nutrient   agar ",
        composition_reference="DSMZ 1",
    )
    assert (medium.name, medium.composition_reference, medium.lab) == (
        "Nutrient agar",
        "DSMZ 1",
        lab,
    )
    event = AuditEvent.objects.get()
    assert (event.event_type, event.subject_id, event.lab_id) == (
        "medium_created",
        medium.public_id,
        lab.pk,
    )
    assert event.changes == {
        "name": [None, "Nutrient agar"],
        "composition_reference": [None, "DSMZ 1"],
    }


@pytest.mark.parametrize("role", [Role.VIEWER, Role.TECHNICIAN])
def test_lower_roles_do_not_manage_media(
    role: Role, lab: Lab, team: dict[Role, User], as_curator: AuditContext, make_medium: MakeMedium
) -> None:
    medium = make_medium()
    actor = access_for(team[role])
    before = snapshot()
    calls: list[Callable[[], object]] = [
        lambda: services.medium_create(access=actor, lab=lab, name="Other"),
        lambda: services.medium_update(access=actor, medium=medium, name="Other"),
        lambda: services.medium_retire(access=actor, medium=medium, reason="x"),
    ]
    for call in calls:
        with pytest.raises(Forbidden):
            call()
    assert snapshot() == before


def test_a_manager_of_another_lab_cannot_manage_media(
    as_curator: AuditContext, lab: Lab, outsider: User
) -> None:
    with pytest.raises(Forbidden):
        services.medium_create(access=access_for(outsider), lab=lab, name="Nope")


def test_the_name_is_unique_in_the_lab_in_any_case_but_free_in_another_lab(  # noqa: PLR0917
    as_curator: AuditContext,
    curator: User,
    lab: Lab,
    other_lab: Lab,
    outsider: User,
    make_medium: MakeMedium,
) -> None:
    make_medium("Marine broth")
    refused(
        services.MediumNameTaken,
        "unique",
        lambda: services.medium_create(access=access_for(curator), lab=lab, name="marine BROTH"),
        "name",
    )
    other = services.medium_create(access=access_for(outsider), lab=other_lab, name="Marine broth")
    assert other.lab == other_lab


def test_a_blank_or_long_name_is_a_field_error(
    as_curator: AuditContext, curator: User, lab: Lab
) -> None:
    access = access_for(curator)
    refused(
        services.InvalidGrowth,
        "invalid",
        lambda: services.medium_create(access=access, lab=lab, name="  "),
        "name",
    )
    refused(
        services.InvalidGrowth,
        "invalid",
        lambda: services.medium_create(access=access, lab=lab, name="x" * 101),
        "name",
    )
    refused(
        services.InvalidGrowth,
        "invalid",
        lambda: services.medium_create(
            access=access, lab=lab, name="ok", composition_reference="x" * 201
        ),
        "composition_reference",
    )


def test_an_update_records_what_changed_and_nothing_when_nothing_did(
    as_curator: AuditContext, curator: User, make_medium: MakeMedium
) -> None:
    medium = make_medium("Broth", composition_reference="DSMZ 1")
    access = access_for(curator)
    before = snapshot()
    services.medium_update(
        access=access, medium=medium, name="Broth", composition_reference="DSMZ 1"
    )
    assert snapshot() == before
    services.medium_update(
        access=access, medium=medium, name="Broth", composition_reference="DSMZ 220"
    )
    event = AuditEvent.objects.latest("pk")
    assert (event.event_type, event.changes) == (
        "medium_changed",
        {"composition_reference": ["DSMZ 1", "DSMZ 220"]},
    )


def test_a_retired_medium_needs_a_reason_and_changes_no_more(
    as_curator: AuditContext, curator: User, make_medium: MakeMedium
) -> None:
    medium = make_medium()
    access = access_for(curator)
    refused(
        RuleViolation,
        "reason_required",
        lambda: services.medium_retire(access=access, medium=medium, reason=" "),
        "reason",
    )
    retired = services.medium_retire(access=access, medium=medium, reason="Recipe withdrawn")
    assert retired.is_retired
    event = AuditEvent.objects.latest("pk")
    assert (event.event_type, event.reason) == ("medium_retired", "Recipe withdrawn")
    before = snapshot()
    services.medium_retire(access=access, medium=medium, reason="again")
    assert snapshot() == before
    refused(
        services.MediumRetired,
        "medium_retired",
        lambda: services.medium_update(access=access, medium=medium, name="Renamed"),
    )


# Growth conditions of a strain.


def test_a_curator_sets_how_a_strain_is_grown(
    as_curator: AuditContext,
    curator: User,
    make_strain: Callable[..., Strain],
    make_medium: MakeMedium,
) -> None:
    strain = make_strain()
    medium = make_medium()
    set_growth(curator, strain, Growth(medium, 25, 30, Atmosphere.AEROBIC))
    strain.refresh_from_db()
    assert (
        strain.growth_medium,
        strain.growth_temperature_low_c,
        strain.growth_temperature_high_c,
    ) == (
        medium,
        25,
        30,
    )
    assert strain.growth_atmosphere == "aerobic"
    event = AuditEvent.objects.latest("pk")
    assert (event.event_type, event.strain_id, event.reason) == (
        "strain_growth_changed",
        strain.public_id,
        REASON,
    )
    assert event.changes == {
        "growth_medium": [None, str(medium.public_id)],
        "growth_temperature_low_c": [None, 25],
        "growth_temperature_high_c": [None, 30],
        "growth_atmosphere": ["", "aerobic"],
    }


def test_a_single_temperature_is_a_range_of_one_value(
    as_curator: AuditContext, curator: User, make_strain: Callable[..., Strain]
) -> None:
    strain = make_strain()
    set_growth(curator, strain, Growth(temperature_low_c=37))
    strain.refresh_from_db()
    assert (strain.growth_temperature_low_c, strain.growth_temperature_high_c) == (37, 37)


def test_the_same_conditions_again_record_nothing(
    as_curator: AuditContext, curator: User, make_strain: Callable[..., Strain]
) -> None:
    strain = make_strain()
    growth = Growth(temperature_low_c=30, atmosphere="anaerobic")
    set_growth(curator, strain, growth)
    before = snapshot()
    set_growth(curator, strain, growth)
    assert snapshot() == before


def test_only_the_changed_fields_are_recorded(
    as_curator: AuditContext, curator: User, make_strain: Callable[..., Strain]
) -> None:
    strain = make_strain()
    set_growth(curator, strain, Growth(temperature_low_c=30, atmosphere="anaerobic"))
    set_growth(curator, strain, Growth(temperature_low_c=30, atmosphere="aerobic"))
    assert AuditEvent.objects.latest("pk").changes == {
        "growth_atmosphere": ["anaerobic", "aerobic"]
    }


def test_a_reason_is_required(
    as_curator: AuditContext, curator: User, make_strain: Callable[..., Strain]
) -> None:
    strain = make_strain()
    refused(
        RuleViolation,
        "reason_required",
        lambda: set_growth(curator, strain, Growth(temperature_low_c=30), reason=" "),
        "reason",
    )


@pytest.mark.parametrize(
    ("growth", "attr"),
    [
        (Growth(temperature_high_c=30), "temperature_low_c"),
        (Growth(temperature_low_c=-1), "temperature_low_c"),
        (Growth(temperature_low_c=20, temperature_high_c=126), "temperature_high_c"),
        (Growth(temperature_low_c=30, temperature_high_c=25), "temperature_high_c"),
        (Growth(atmosphere="martian"), "atmosphere"),
    ],
)
def test_impossible_conditions_are_field_errors(
    growth: Growth,
    attr: str,
    as_curator: AuditContext,
    curator: User,
    make_strain: Callable[..., Strain],
) -> None:
    strain = make_strain()
    refused(services.InvalidGrowth, "invalid", lambda: set_growth(curator, strain, growth), attr)


def test_a_medium_of_another_lab_is_refused(
    as_curator: AuditContext,
    curator: User,
    outsider: User,
    other_lab: Lab,
    make_strain: Callable[..., Strain],
) -> None:
    strain = make_strain()
    with audit_context(channel=Channel.API, actor=outsider, request_id="req-o"):
        foreign = services.medium_create(access=access_for(outsider), lab=other_lab, name="Foreign")
    refused(
        services.InvalidGrowth,
        "invalid",
        lambda: set_growth(curator, strain, Growth(medium=foreign)),
        "medium",
    )


def test_a_retired_medium_is_not_given_but_a_strain_keeps_it(
    as_curator: AuditContext,
    curator: User,
    make_strain: Callable[..., Strain],
    make_medium: MakeMedium,
) -> None:
    strain = make_strain()
    medium = make_medium()
    set_growth(curator, strain, Growth(medium, 30, 30))
    services.medium_retire(access=access_for(curator), medium=medium, reason="Withdrawn")
    other = make_strain(name_as_received="Testella exempli T2")
    refused(
        services.InvalidGrowth,
        "invalid",
        lambda: set_growth(curator, other, Growth(medium=medium)),
        "medium",
    )
    set_growth(curator, strain, Growth(medium, 25, 30))
    strain.refresh_from_db()
    assert (strain.growth_medium, strain.growth_temperature_low_c) == (medium, 25)


def test_lower_roles_do_not_set_growth(
    as_curator: AuditContext, technician: User, make_strain: Callable[..., Strain]
) -> None:
    strain = make_strain()
    before = snapshot()
    with pytest.raises(Forbidden):
        set_growth(technician, strain, Growth(temperature_low_c=30))
    assert snapshot() == before
