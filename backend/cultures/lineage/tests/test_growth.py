"""A passage records how it was grown (#79): the strain's conditions unless the call gives
others, a medium of the lab, frozen with the passage (the passage table is insert-only)."""

import pytest
from django.db import IntegrityError, connection, transaction

from cultures.audit.context import AuditContext, audit_context
from cultures.audit.models import AuditEvent, Channel
from cultures.growth import services as growth
from cultures.growth.models import GrowthMedium
from cultures.growth.services import Growth
from cultures.labs.access import access_for
from cultures.labs.models import Lab
from cultures.lineage import services
from cultures.lineage.models import Passage
from cultures.storage.tests.conftest import Tree
from cultures.strains import services as strains
from cultures.strains.models import Strain
from cultures.users.models import User

from .support import preserve, vials_of

pytestmark = pytest.mark.django_db


def medium_for(curator: User, strain: Strain, name: str = "Broth") -> GrowthMedium:
    with audit_context(channel=Channel.API, actor=curator, request_id="req-m"):
        return growth.medium_create(access=access_for(curator), lab=strain.lab, name=name)


def grown(curator: User, strain: Strain, conditions: Growth) -> None:
    with audit_context(channel=Channel.API, actor=curator, request_id="req-g"):
        strains.strain_set_growth(
            access=access_for(curator), strain=strain, growth=conditions, reason="From the sheet"
        )


def test_a_subculture_takes_the_strains_conditions(
    as_technician: AuditContext, technician: User, curator: User, passage0: Passage, strain: Strain
) -> None:
    medium = medium_for(curator, strain)
    grown(curator, strain, Growth(medium, 25, 30, "aerobic"))
    strain.refresh_from_db()
    passage = services.passage_subculture(access=access_for(technician), parent=passage0)
    assert (
        passage.growth_medium,
        passage.growth_temperature_low_c,
        passage.growth_temperature_high_c,
        passage.growth_atmosphere,
    ) == (medium, 25, 30, "aerobic")


def test_a_subculture_may_override_the_conditions(
    as_technician: AuditContext, technician: User, curator: User, passage0: Passage, strain: Strain
) -> None:
    medium = medium_for(curator, strain)
    grown(curator, strain, Growth(medium, 25, 30, "aerobic"))
    other = medium_for(curator, strain, "Agar")
    passage = services.passage_subculture(
        access=access_for(technician), parent=passage0, growth=Growth(other, 37, None, "anaerobic")
    )
    assert (passage.growth_medium, passage.growth_temperature_low_c) == (other, 37)
    assert (passage.growth_temperature_high_c, passage.growth_atmosphere) == (37, "anaerobic")
    strain.refresh_from_db()
    assert strain.growth_medium == medium  # the strain's own conditions stay


def test_a_revival_records_the_conditions_it_used(  # noqa: PLR0917
    as_technician: AuditContext,
    technician: User,
    curator: User,
    passage0: Passage,
    strain: Strain,
    tree: Tree,
) -> None:
    medium = medium_for(curator, strain)
    grown(curator, strain, Growth(medium, 30, 30))
    access = access_for(technician)
    one = services.passage_subculture(access=access, parent=passage0)
    vials = vials_of(preserve(technician, one, vial_count=2, box=tree.box))
    default = services.vial_revive(access=access, vial=vials[0])
    assert (default.growth_medium, default.growth_temperature_low_c) == (medium, 30)
    changed = services.vial_revive(
        access=access, vial=vials[1], growth=Growth(medium, 28, 32, "microaerophilic")
    )
    assert (changed.growth_temperature_low_c, changed.growth_atmosphere) == (28, "microaerophilic")


def test_the_conditions_are_in_the_event(
    as_technician: AuditContext, technician: User, curator: User, passage0: Passage, strain: Strain
) -> None:
    medium = medium_for(curator, strain)
    services.passage_subculture(
        access=access_for(technician), parent=passage0, growth=Growth(medium, 30, 30)
    )
    event = AuditEvent.objects.filter(event_type="passage_created").latest("pk")
    assert event.changes["growth_medium"] == [None, str(medium.public_id)]
    assert event.changes["growth_temperature_low_c"] == [None, 30]


def test_impossible_or_foreign_conditions_are_refused_and_nothing_is_made(  # noqa: PLR0917
    as_technician: AuditContext,
    technician: User,
    curator: User,
    outsider: User,
    passage0: Passage,
    strain: Strain,
    other_lab: Lab,
) -> None:
    with audit_context(channel=Channel.API, actor=outsider, request_id="req-o"):
        foreign = growth.medium_create(access=access_for(outsider), lab=other_lab, name="Foreign")
    access = access_for(technician)
    before = Passage.objects.count()
    for bad, attr in (
        (Growth(foreign), "medium"),
        (Growth(temperature_low_c=300), "temperature_low_c"),
        (Growth(atmosphere="martian"), "atmosphere"),
    ):
        with pytest.raises(growth.InvalidGrowth) as raised:
            services.passage_subculture(access=access, parent=passage0, growth=bad)
        assert raised.value.attr == attr
    assert Passage.objects.count() == before


def test_a_retired_medium_is_not_given_to_a_new_passage_unless_the_strain_has_it(
    as_technician: AuditContext, technician: User, curator: User, passage0: Passage, strain: Strain
) -> None:
    medium = medium_for(curator, strain)
    grown(curator, strain, Growth(medium, 30, 30))
    with audit_context(channel=Channel.API, actor=curator, request_id="req-r"):
        growth.medium_retire(access=access_for(curator), medium=medium, reason="Withdrawn")
    access = access_for(technician)
    kept = services.passage_subculture(access=access, parent=passage0)
    assert kept.growth_medium == medium
    other = medium_for(curator, strain, "Other")
    with audit_context(channel=Channel.API, actor=curator, request_id="req-r2"):
        growth.medium_retire(access=access_for(curator), medium=other, reason="Withdrawn")
    with pytest.raises(growth.InvalidGrowth):
        services.passage_subculture(access=access, parent=passage0, growth=Growth(other))


def test_the_database_refuses_a_medium_of_another_lab_on_a_passage(
    passage0: Passage, other_lab: Lab, outsider: User
) -> None:
    with audit_context(channel=Channel.API, actor=outsider, request_id="req-o"):
        foreign = growth.medium_create(access=access_for(outsider), lab=other_lab, name="Foreign")
    with pytest.raises(IntegrityError, match="medium"), transaction.atomic():
        Passage.objects.create(
            lab_id=passage0.lab_id,
            strain=passage0.strain,
            number=1,
            source_passage=passage0,
            growth_medium=foreign,
        )
    assert connection.in_atomic_block
