"""Staff change taxa in Django admin, through the audited services, and never delete them."""

from typing import Any

import pytest
from django.test import Client
from django.urls import reverse

from cultures.audit.models import AuditEvent, Channel
from cultures.core.testing import logged_in
from cultures.taxonomy.models import Taxon, TaxonIdentifier, TaxonStatus
from cultures.users.models import User

pytestmark = pytest.mark.django_db
PREFIX = "identifiers"


@pytest.fixture
def admin_client(staff: User) -> Client:
    return logged_in(staff)


def inline(rows: list[dict[str, Any]], initial: int = 0) -> dict[str, Any]:
    data: dict[str, Any] = {
        f"{PREFIX}-TOTAL_FORMS": len(rows),
        f"{PREFIX}-INITIAL_FORMS": initial,
        f"{PREFIX}-MIN_NUM_FORMS": 0,
        f"{PREFIX}-MAX_NUM_FORMS": 1000,
    }
    for i, row in enumerate(rows):
        data.update({f"{PREFIX}-{i}-{key}": value for key, value in row.items()})
    return data


def taxon_form(**values: Any) -> dict[str, Any]:
    return {"name": "", "authority": "", "rank": "species", "parent": "", "accepted": "", **values}


def test_staff_add_a_species_with_an_ncbi_id(
    admin_client: Client, staff: User, bacillus: Taxon
) -> None:
    body = {
        **taxon_form(name="Bacillus cereus", parent=bacillus.pk),
        **inline([{"system": "ncbi", "value": "1396"}]),
    }
    response = admin_client.post(reverse("admin:taxonomy_taxon_add"), body)
    assert response.status_code == 302, response.content
    taxon = Taxon.objects.get(name="Bacillus cereus")
    assert (taxon.parent, taxon.status) == (bacillus, TaxonStatus.ACCEPTED)
    assert list(taxon.identifiers.values_list("system", "value")) == [("ncbi", "1396")]
    events = list(AuditEvent.objects.order_by("pk").values_list("event_type", "channel", "actor"))
    assert events == [
        ("taxon_created", Channel.WEB, staff.pk),
        ("taxon_identifier_added", Channel.WEB, staff.pk),
    ]


def test_a_broken_rule_is_a_form_error_and_saves_nothing(
    admin_client: Client, subtilis: Taxon
) -> None:
    response = admin_client.post(
        reverse("admin:taxonomy_taxon_add"),
        {**taxon_form(name="Bacillus", rank="genus", parent=subtilis.pk), **inline([])},
    )
    assert response.status_code == 200
    assert "must rank above a genus" in response.content.decode()
    assert Taxon.objects.count() == 2
    assert AuditEvent.objects.count() == 0


def test_staff_make_a_name_a_synonym_and_replace_its_id(
    admin_client: Client, staff: User, bacillus: Taxon, coli: Taxon
) -> None:
    old = Taxon.objects.create(
        name="Bacillus coli", rank="species", parent=bacillus, status=TaxonStatus.ACCEPTED
    )
    ident = TaxonIdentifier.objects.create(taxon=old, system="lpsn", value="old")
    body = {
        **taxon_form(name="Bacillus coli", authority="Migula 1895", accepted=coli.pk),
        **inline([{"id": ident.pk, "taxon": old.pk, "system": "lpsn", "value": "new"}], initial=1),
    }
    response = admin_client.post(reverse("admin:taxonomy_taxon_change", args=[old.pk]), body)
    assert response.status_code == 302, response.content
    old.refresh_from_db()
    assert (old.status, old.accepted, old.parent, old.authority) == (
        TaxonStatus.SYNONYM,
        coli,
        None,
        "Migula 1895",
    )
    assert list(old.identifiers.values_list("value", flat=True)) == ["new"]
    assert list(AuditEvent.objects.order_by("pk").values_list("event_type", flat=True)) == [
        "taxon_changed",
        "taxon_identifier_removed",
        "taxon_identifier_added",
    ]


def test_the_admin_offers_no_delete(admin_client: Client, subtilis: Taxon) -> None:
    response = admin_client.post(
        reverse("admin:taxonomy_taxon_delete", args=[subtilis.pk]), {"post": "yes"}
    )
    assert response.status_code == 403
    assert Taxon.objects.filter(pk=subtilis.pk).exists()
