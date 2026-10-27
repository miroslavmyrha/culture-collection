"""The database holds the growth rules on its own, written past the services (#79): the
temperature range, the atmosphere vocabulary, the medium's lab, no delete of a medium."""

from typing import Any

import pytest
from django.db import IntegrityError, InternalError, connection, transaction

from cultures.growth.models import GrowthMedium
from cultures.labs.models import Lab
from cultures.strains.models import Strain

from .conftest import MakeMedium

pytestmark = pytest.mark.django_db
DB_ERRORS = (IntegrityError, InternalError)


def update(strain: Strain, **fields: Any) -> None:
    with transaction.atomic():
        Strain.objects.filter(pk=strain.pk).update(**fields)


@pytest.mark.parametrize(
    "fields",
    [
        {"growth_temperature_low_c": 30},  # one end alone
        {"growth_temperature_high_c": 30},
        {"growth_temperature_low_c": -1, "growth_temperature_high_c": 5},
        {"growth_temperature_low_c": 20, "growth_temperature_high_c": 126},
        {"growth_temperature_low_c": 30, "growth_temperature_high_c": 25},
    ],
)
def test_the_temperature_range_is_held_by_the_database(
    fields: dict[str, int], make_strain: Any
) -> None:
    strain = make_strain()
    with pytest.raises(IntegrityError, match="growth_temperature_range"):
        update(strain, **fields)


def test_a_range_within_the_limits_is_accepted(make_strain: Any) -> None:
    strain = make_strain()
    update(strain, growth_temperature_low_c=0, growth_temperature_high_c=125)
    update(strain, growth_temperature_low_c=None, growth_temperature_high_c=None)


def test_the_atmosphere_vocabulary_is_held_by_the_database(make_strain: Any) -> None:
    strain = make_strain()
    with pytest.raises(IntegrityError, match="growth_atmosphere_valid"):
        update(strain, growth_atmosphere="martian")
    update(strain, growth_atmosphere="anaerobic")


def test_a_medium_of_another_lab_cannot_be_named_by_a_strain(
    make_strain: Any, other_lab: Lab, make_medium: MakeMedium, outsider: Any
) -> None:
    strain = make_strain()
    foreign = make_medium("Foreign", lab=other_lab, actor=outsider)
    with pytest.raises(DB_ERRORS):
        update(strain, growth_medium=foreign)


def test_a_medium_is_never_deleted_and_a_retired_one_never_changes(
    make_medium: MakeMedium,
) -> None:
    medium = make_medium()
    with pytest.raises(DB_ERRORS), transaction.atomic():
        medium.delete()
    with pytest.raises(DB_ERRORS), transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(
            "UPDATE growth_growthmedium SET lab_id = lab_id + 1 WHERE id = %s", [medium.pk]
        )
    assert GrowthMedium.objects.filter(pk=medium.pk).exists()


def test_the_name_is_unique_per_lab_in_the_database(make_medium: MakeMedium, lab: Lab) -> None:
    make_medium("Broth")
    with pytest.raises(IntegrityError, match="growth_medium_lab_name_uniq"), transaction.atomic():
        GrowthMedium.objects.create(lab=lab, name="BROTH")
