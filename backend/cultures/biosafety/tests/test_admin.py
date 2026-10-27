"""Staff record and end permits in Django admin, through the services, and never delete them."""

from datetime import date

import pytest
from django.test import Client
from django.urls import reverse

from cultures.audit.models import AuditEvent, Channel
from cultures.biosafety.models import Issuer, LabAuthorisation
from cultures.core.testing import logged_in
from cultures.labs.models import Lab
from cultures.users.models import User

from .support import make_permit

pytestmark = pytest.mark.django_db


@pytest.fixture
def admin_client(staff: User) -> Client:
    return logged_in(staff)


def test_staff_record_a_permit(admin_client: Client, staff: User, lab: Lab) -> None:
    body = {
        "lab": lab.pk,
        "kind": "cz_vrat",
        "permit_reference": "SÚJB/2026/5",
        "valid_from": "2026-01-01",
        "expires_on": "",
    }
    response = admin_client.post(reverse("admin:biosafety_labauthorisation_add"), body)
    assert response.status_code == 302, response.content
    permit = LabAuthorisation.objects.get()
    assert (permit.issuer, permit.expires_on) == (Issuer.SUJB, None)
    assert list(AuditEvent.objects.values_list("event_type", "channel", "actor")) == [
        ("lab_authorisation_added", Channel.WEB, staff.pk)
    ]


def test_staff_end_a_permit_and_then_it_is_read_only(admin_client: Client, lab: Lab) -> None:
    permit = make_permit(lab)
    url = reverse("admin:biosafety_labauthorisation_change", args=[permit.pk])
    response = admin_client.post(url, {"ended_on": "2026-05-01", "end_reason": ""})
    assert response.status_code == 200
    assert response.context["adminform"].form.errors == {
        "end_reason": ["Say why the permit ended."]
    }
    assert AuditEvent.objects.count() == 0
    response = admin_client.post(
        url, {"ended_on": "2026-05-01", "end_reason": "revoked by decision 2026-114"}
    )
    assert response.status_code == 302, response.content
    permit.refresh_from_db()
    assert permit.end_reason == "revoked by decision 2026-114"
    assert list(AuditEvent.objects.values_list("event_type", "reason")) == [
        ("lab_authorisation_ended", "revoked by decision 2026-114")
    ]
    # Ended: nothing is editable any more, a second post changes nothing.
    admin_client.post(url, {"ended_on": "2026-06-01", "end_reason": "again"})
    permit.refresh_from_db()
    assert permit.ended_on == date(2026, 5, 1)
    assert AuditEvent.objects.count() == 1


def test_a_recorded_permit_keeps_its_reference_and_dates(admin_client: Client, lab: Lab) -> None:
    permit = make_permit(lab)
    url = reverse("admin:biosafety_labauthorisation_change", args=[permit.pk])
    admin_client.post(
        url,
        {
            "permit_reference": "changed",
            "valid_from": "2020-01-01",
            "ended_on": "",
            "end_reason": "",
        },
    )
    permit.refresh_from_db()
    assert (permit.permit_reference, permit.valid_from.isoformat()) == (
        "SÚJB/2026/001",
        "2026-01-01",
    )
    assert AuditEvent.objects.count() == 0


def test_the_admin_offers_no_delete(admin_client: Client, lab: Lab) -> None:
    permit = make_permit(lab)
    response = admin_client.post(
        reverse("admin:biosafety_labauthorisation_delete", args=[permit.pk]), {"post": "yes"}
    )
    assert response.status_code == 403
    assert LabAuthorisation.objects.filter(pk=permit.pk).exists()
