"""seed_dev: development data written through the services, refused outside development."""

import os
import re
import subprocess
import sys
from collections import Counter
from datetime import UTC, date, datetime
from io import StringIO
from typing import Any

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings

from cultures.audit.context import audit_context
from cultures.audit.models import ActorKind, AuditEvent, Channel, RowChange
from cultures.audit.reconcile import reconcile
from cultures.biosafety.models import AuthorisationKind, LabAuthorisation, RestrictionKind
from cultures.biosafety.policy import NEEDS_PERMIT, AuthorisationRequired, permit_today, valid_on
from cultures.core.tests.test_settings import BACKEND, GOOD_ENV, production_value
from cultures.deposits.models import Contact, Deposit, Depositor, DepositTerms, MtaTemplate
from cultures.distribution.documents import DUAL_USE_NOTICE
from cultures.distribution.models import (
    DistributionRequest,
    MtaAcceptance,
    RecipientPermit,
    Requester,
    Shipment,
    ShipmentDocument,
)
from cultures.distribution.policy import evaluate
from cultures.growth.models import GrowthMedium
from cultures.labs import services as labs
from cultures.labs.access import access_for
from cultures.labs.models import Lab, LocationGrant, Membership
from cultures.labs.permissions import Role
from cultures.lineage.models import Batch, BatchCheck, BatchStatus, Passage, Vial, VialPlacement
from cultures.storage.models import KIND_SPEC, BoxType, StorageUnit, UnitKind, may_hold
from cultures.storage.policy import may_store
from cultures.strains import services as strains
from cultures.strains.countries import COUNTRY_CODES
from cultures.strains.management.commands.seed_dev import (
    ADMIN,
    EXTRA_MEMBERS,
    INACTIVE,
    LAB_ROLES,
    NO_LAB,
    TWO_LABS,
    accepted_entry,
    final_taxon,
    lab_username,
    load,
)
from cultures.strains.models import (
    Strain,
    StrainCounter,
    StrainIdentification,
    StrainRestriction,
)
from cultures.taxonomy.models import Taxon, TaxonIdentifier
from cultures.users import services as users
from cultures.users.models import User

PASSWORD = "dev correct horse battery"  # noqa: S105 (a test value)
DATA = load()
TAXA: list[dict[str, Any]] = DATA["taxa"]
STRAINS: list[dict[str, Any]] = DATA["strains"]
DEPOSITS: list[dict[str, Any]] = DATA["deposits"]
ACCEPTED = [row for row in DEPOSITS if row["state"] == "accepted"]
LAB_CODES = [lab["code"] for lab in DATA["labs"]]
INVENTED_GENERA = ("Testella", "Mockia", "Fictivibrio")
EPOCH = datetime(2000, 1, 1, tzinfo=UTC)


def seed(*args: str) -> str:
    out = StringIO()
    with override_settings(DEBUG=True, DEV_DATA_ALLOWED=True):
        call_command("seed_dev", *args, stdout=out)
    return out.getvalue()


def entry(name: str) -> dict[str, Any]:
    return next(t for t in TAXA if t["name"] == name)


def names_of(row: dict[str, Any]) -> list[str]:
    """Every taxon a strain row is ever identified as."""
    later = [s["reclassify"]["taxon"] for s in row.get("history", []) if "reclassify" in s]
    return [row["taxon"], *later]


def restrictions_of(row: dict[str, Any]) -> list[dict[str, Any]]:
    added = [s["restriction_add"] for s in row.get("history", []) if "restriction_add" in s]
    return [*row.get("restrictions", []), *added]


def rows(model: Any, *fields: str) -> list[tuple[Any, ...]]:
    return list(model.objects.order_by("pk").values_list(*fields))


def state() -> dict[str, Any]:
    """Everything a run could change."""
    return {
        "events": AuditEvent.objects.count(),
        "row_changes": RowChange.objects.count(),
        "users": rows(User, "username", "is_active", "is_staff", "is_superuser", "password"),
        "memberships": rows(Membership, "user__username", "lab__code", "role"),
        "labs": rows(Lab, "code", "name"),
        "taxa": rows(Taxon, "name", "rank", "parent__name", "accepted__name", "updated_at"),
        "identifiers": rows(TaxonIdentifier, "system", "value"),
        "authorisations": rows(LabAuthorisation, "permit_reference", "ended_on"),
        "strains": rows(Strain, "accession_number", "taxon__name", "risk_group", "updated_at"),
        "identifications": rows(StrainIdentification, "taxon__name", "is_current"),
        "restrictions": rows(StrainRestriction, "reference", "ended_at"),
        "counters": rows(StrainCounter, "lab__code", "last_seq"),
        "contacts": rows(Contact, "name", "email", "updated_at"),
        "depositors": rows(Depositor, "institution", "updated_at"),
        "mta": rows(MtaTemplate, "code", "version"),
        "deposits": rows(Deposit, "name_as_received", "status", "updated_at"),
        "terms": rows(DepositTerms, "version", "is_active"),
        "box_types": rows(BoxType, "name", "rows", "cols"),
        "units": rows(StorageUnit, "lab__code", "name", "parent__name", "status", "updated_at"),
        "passages": rows(Passage, "strain__name_as_received", "number"),
        "batches": rows(Batch, "strain__name_as_received", "number", "status", "updated_at"),
        "checks": rows(BatchCheck, "batch__number", "kind", "result", "status"),
        "vials": rows(Vial, "batch__number", "seq", "status", "updated_at"),
        "placements": rows(VialPlacement, "box__name", "row", "col", "removed_at"),
        "grants": rows(LocationGrant, "user__username", "revoked_at"),
        "requesters": rows(Requester, "institution", "seat", "updated_at"),
        "permits": rows(RecipientPermit, "reference", "ended_on"),
        "requests": rows(DistributionRequest, "end_use", "status", "updated_at"),
        "acceptances": rows(MtaAcceptance, "request__end_use", "mta__version"),
        "documents": rows(ShipmentDocument, "kind", "text_sha256"),
    }


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEV_PASSWORD", PASSWORD)
    monkeypatch.delenv("DEV_PASSWORD_FILE", raising=False)


# The guard: development settings only.


@pytest.mark.django_db
@pytest.mark.usefixtures("env")
def test_it_refuses_without_debug() -> None:
    with (
        override_settings(DEBUG=False, DEV_DATA_ALLOWED=True),
        pytest.raises(CommandError, match="only with DEBUG on"),
    ):
        call_command("seed_dev", stdout=StringIO())
    assert not User.objects.exists()


@pytest.mark.django_db
@pytest.mark.usefixtures("env")
@pytest.mark.parametrize("marker", [None, False, "yes"])
def test_it_refuses_settings_that_are_not_the_development_ones(marker: object) -> None:
    """The test settings themselves set no marker: only config.settings.local does."""
    overrides: dict[str, Any] = {"DEBUG": True}
    if marker is not None:
        overrides["DEV_DATA_ALLOWED"] = marker
    with (
        override_settings(**overrides),
        pytest.raises(CommandError, match="only with the development settings"),
    ):
        call_command("seed_dev", stdout=StringIO())
    assert not User.objects.exists()


def test_production_settings_refuse_it_in_a_fresh_process() -> None:
    """DEBUG asked for in the environment and a password given: refused before any query
    (the database address is unreachable, so a query would fail with another message)."""
    result = subprocess.run(
        [sys.executable, "manage.py", "seed_dev"],
        cwd=BACKEND,
        env={
            "PATH": os.environ["PATH"],
            "PYTHONDONTWRITEBYTECODE": "1",
            **GOOD_ENV,
            "DJANGO_SETTINGS_MODULE": "config.settings.production",
            "DJANGO_DEBUG": "true",
            "DEV_PASSWORD": PASSWORD,
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert result.returncode != 0
    assert result.stderr.strip().splitlines()[-1] == (
        "CommandError: seed_dev creates users with a known password: it runs only with DEBUG on."
    )


def test_only_the_development_settings_allow_it() -> None:
    assert production_value({**GOOD_ENV, "DJANGO_DEBUG": "true"}, "s.DEV_DATA_ALLOWED") == "False"
    local = subprocess.run(
        [sys.executable, "-c", "import config.settings.local as s; print(s.DEV_DATA_ALLOWED)"],
        cwd=BACKEND,
        env={
            "PATH": os.environ["PATH"],
            "PYTHONDONTWRITEBYTECODE": "1",
            "DATABASE_URL": GOOD_ENV["DATABASE_URL"],
        },
        capture_output=True,
        text=True,
        check=True,
    )
    assert local.stdout.strip() == "True"


@pytest.mark.django_db
@pytest.mark.parametrize("value", [None, " "])
def test_it_refuses_without_a_password(monkeypatch: pytest.MonkeyPatch, value: str | None) -> None:
    monkeypatch.delenv("DEV_PASSWORD_FILE", raising=False)
    if value is None:
        monkeypatch.delenv("DEV_PASSWORD", raising=False)
    else:
        monkeypatch.setenv("DEV_PASSWORD", value)
    with pytest.raises(CommandError, match="DEV_PASSWORD"):
        seed()
    assert not User.objects.exists()


@pytest.mark.django_db
def test_the_password_can_come_from_the_option(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEV_PASSWORD", raising=False)
    monkeypatch.delenv("DEV_PASSWORD_FILE", raising=False)
    seed("--password", "from the option")
    assert User.objects.get(username="bac-viewer").check_password("from the option")


# Someone's data.


def _lab_by_someone_else() -> Lab:
    with audit_context(
        channel=Channel.COMMAND, actor_kind=ActorKind.SYSTEM, actor_label="command:other"
    ):
        return labs.lab_create(name="Someone's lab", code="OWN")


@pytest.mark.django_db
@pytest.mark.usefixtures("env")
def test_it_refuses_a_database_with_labs_it_did_not_create() -> None:
    _lab_by_someone_else()
    before = state()
    with pytest.raises(CommandError, match=r"labs no seed command created \(OWN\)"):
        seed()
    assert state() == before


@pytest.mark.django_db
@pytest.mark.usefixtures("env")
def test_force_adds_the_data_next_to_them() -> None:
    own = _lab_by_someone_else()
    seed("--force")
    assert Strain.objects.count() == len(STRAINS) + len(ACCEPTED)
    assert not Membership.objects.filter(lab=own).exists()


@pytest.mark.django_db
@pytest.mark.usefixtures("env")
def test_the_e2e_seed_is_not_someone_elses_data(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("E2E_PASSWORD", PASSWORD)
    with override_settings(DEBUG=True):
        call_command("seed_e2e", stdout=StringIO())
    seed()
    # seed_e2e makes its genera roots. The tree puts them under their domain.
    assert Taxon.objects.get(name="Bacillus").parent == Taxon.objects.get(name="Bacteria")
    before = state()
    seed()
    with override_settings(DEBUG=True):
        call_command("seed_e2e", stdout=StringIO())
    assert state() == before


# What it creates.


@pytest.mark.django_db
@pytest.mark.usefixtures("env")
def test_it_creates_every_role_with_the_password() -> None:
    out = seed()
    for code in LAB_CODES:
        for role in LAB_ROLES:
            username = lab_username(code, role)
            assert Membership.objects.get(lab__code=code, user__username=username).role == role
            assert username in out
    memberships = Counter(Membership.objects.values_list("user__username", "lab__code", "role"))
    assert memberships[TWO_LABS, "BAC", "curator"] == memberships[TWO_LABS, "MYC", "viewer"] == 1
    assert Membership.objects.filter(user__username=TWO_LABS).count() == 2
    assert not Membership.objects.filter(user__username__in=[NO_LAB, ADMIN]).exists()
    admin = User.objects.get(username=ADMIN)
    assert (admin.is_staff, admin.is_superuser, admin.is_active) == (True, True, True)
    inactive = User.objects.get(username=INACTIVE)
    assert not inactive.is_active
    assert Membership.objects.get(user=inactive).role == Role.TECHNICIAN
    assert all(u.check_password(PASSWORD) for u in User.objects.all())
    assert User.objects.filter(is_superuser=True).count() == 1
    # The admin came through the superuser path, each privilege with the reason.
    granted = AuditEvent.objects.filter(subject_id=admin.public_id).order_by("pk")
    assert [(e.event_type, e.reason) for e in granted] == [
        ("user_created", "development data"),
        ("user_staff_changed", "development data"),
        ("user_superuser_changed", "development data"),
    ]


@pytest.mark.django_db
@pytest.mark.usefixtures("env")
def test_lab_roles_are_exact() -> None:
    seed()
    for code in LAB_CODES:
        by_role = Counter(Membership.objects.filter(lab__code=code).values_list("role", flat=True))
        extra = Counter(role for user, lab, role in _extra() if lab == code)
        assert by_role == Counter(LAB_ROLES) + extra, code


def _extra() -> list[tuple[str, str, str]]:
    return [(u, lab, str(role)) for u, lab, role in EXTRA_MEMBERS]


@pytest.mark.django_db
@pytest.mark.usefixtures("env")
def test_it_creates_the_labs_permits_taxa_and_strains() -> None:
    out = seed()
    assert sorted(Lab.objects.values_list("code", flat=True)) == sorted(LAB_CODES)
    assert Taxon.objects.count() == len(TAXA)
    assert Strain.objects.count() == len(STRAINS) + len(ACCEPTED)
    assert f"Strains: {len(STRAINS)} created, 0 found." in out
    per_lab = Counter(Strain.objects.values_list("lab__code", flat=True))
    assert per_lab == Counter(row["lab"] for row in [*STRAINS, *ACCEPTED])
    assert max(per_lab.values()) > 25  # more than one page of the strain list
    reclassified = Counter(
        StrainIdentification.objects.values_list("strain_id", flat=True)
    ).most_common(1)
    assert reclassified[0][1] == 3
    today = permit_today()
    valid = {
        (code, kind)
        for code, kind in LabAuthorisation.objects.filter(valid_on(today)).values_list(
            "lab__code", "kind"
        )
    }
    assert valid == {("MYC", "quarantine_pest"), ("REG", "cz_vrat")}
    assert LabAuthorisation.objects.filter(lab__code="ENV", expires_on__lt=today).exists()
    assert LabAuthorisation.objects.filter(lab__code="MYC", ended_on__isnull=False).exists()


@pytest.mark.django_db
@pytest.mark.usefixtures("env")
def test_a_second_run_changes_nothing() -> None:
    seed()
    before = state()
    out = seed()
    assert state() == before
    assert "Strains: 0 created" in out
    assert "Taxa: 0 created" in out
    assert "Storage units: 0 created" in out


@pytest.mark.django_db
@pytest.mark.usefixtures("env")
def test_a_second_run_restores_users_changed_by_hand() -> None:
    seed()
    with audit_context(channel=Channel.COMMAND, actor_kind=ActorKind.SYSTEM, reason="test"):
        viewer = User.objects.get(username="bac-viewer")
        users.user_set_password(user=viewer, raw_password="changed")
        users.user_deactivate(user=viewer)
        users.user_activate(user=User.objects.get(username=INACTIVE))
    seed()
    viewer.refresh_from_db()
    assert (viewer.is_active, viewer.check_password(PASSWORD)) == (True, True)
    assert not User.objects.get(username=INACTIVE).is_active


@pytest.mark.django_db
@pytest.mark.usefixtures("env")
def test_its_writes_are_audited_as_the_command() -> None:
    seed()
    events = list(AuditEvent.objects.order_by("pk"))
    assert {(e.channel, e.actor_kind, e.actor_label, e.actor_id) for e in events} == {
        (Channel.COMMAND, ActorKind.SYSTEM, "command:seed_dev", None)
    }
    assert set(RowChange.objects.values_list("request_id", flat=True)) == {events[0].request_id}
    assert [f for f in reconcile(EPOCH) if f.alarm] == []


@pytest.mark.django_db
@pytest.mark.usefixtures("env")
def test_every_strain_row_comes_from_a_strain_service() -> None:
    """A row written past the services has no event that explains it, and takes no number
    from the lab's counter."""
    seed()
    events = Counter(AuditEvent.objects.values_list("event_type", flat=True))
    created = AuditEvent.objects.filter(event_type="strain_created")
    assert set(created.values_list("strain_id", flat=True)) == set(
        Strain.objects.values_list("public_id", flat=True)
    )
    assert created.count() == Strain.objects.count()
    assert (
        StrainIdentification.objects.count()
        == events["strain_created"] + events["strain_reclassified"]
    )
    at_accession = sum(len(e.changes["restrictions"][1]) for e in created)
    assert StrainRestriction.objects.count() == at_accession + events["strain_restriction_added"]
    assert (
        StrainRestriction.objects.filter(ended_at__isnull=False).count()
        == events["strain_restriction_ended"]
    )
    assert events["strain_risk_group_changed"] == sum(
        1 for row in STRAINS for s in row.get("history", []) if "risk_group" in s
    )
    assert LabAuthorisation.objects.count() == events["lab_authorisation_added"]
    for counter in StrainCounter.objects.all():
        assert counter.last_seq == Strain.objects.filter(lab_id=counter.lab_id).count()
    assert events["taxon_created"] == Taxon.objects.count()


@pytest.mark.django_db
@pytest.mark.usefixtures("env")
def test_every_regulated_strain_lies_in_a_lab_that_holds_the_permit() -> None:
    seed()
    today = permit_today()
    regulated = StrainRestriction.objects.filter(ended_at__isnull=True, kind__in=NEEDS_PERMIT)
    assert regulated.filter(kind=RestrictionKind.CZ_VRAT).exists()
    assert regulated.filter(kind=RestrictionKind.QUARANTINE_PEST).exists()
    for restriction in regulated:
        held = LabAuthorisation.objects.filter(
            valid_on(today), lab_id=restriction.lab_id, kind=restriction.kind
        )
        assert held.exists(), restriction


@pytest.mark.django_db
@pytest.mark.usefixtures("env")
def test_the_lab_with_the_expired_permit_refuses_a_vrat_strain() -> None:
    seed()
    env_lab = Lab.objects.get(code="ENV")
    curator = access_for(User.objects.get(username="env-curator"))
    data = strains.NewStrain(
        name_as_received="Testella exempli",
        taxon=Taxon.objects.get(name="Testella exempli"),
        identified_on=date(2025, 1, 1),
        identification_method="Morphology",
        risk_group=3,
        restrictions=[strains.RestrictionInput(RestrictionKind.CZ_VRAT, "Příloha 1")],
    )
    with (
        audit_context(channel=Channel.COMMAND, actor_kind=ActorKind.SYSTEM),
        pytest.raises(AuthorisationRequired) as refused,
    ):
        strains.strain_create(access=curator, lab=env_lab, data=data)
    assert refused.value.kind == AuthorisationKind.CZ_VRAT


@pytest.mark.django_db
@pytest.mark.usefixtures("env")
def test_strains_of_real_taxa_carry_the_verified_facts() -> None:
    seed()
    for strain in Strain.objects.select_related("taxon", "lab"):
        found = accepted_entry(strain.taxon.name, TAXA)
        if found.get("invented"):
            continue
        assert strain.risk_group == found["risk_group"], strain
        assert (
            not StrainRestriction.objects.filter(strain=strain)
            .exclude(kind=RestrictionKind.GMO, gmo_category=1)
            .exists()
        ), strain


@pytest.mark.django_db
@pytest.mark.usefixtures("env")
def test_it_creates_depositors_mta_versions_and_deposits_in_every_state() -> None:
    out = seed()
    assert f"Deposits: {len(DEPOSITS)} created, 0 found." in out
    assert Counter(Deposit.objects.values_list("status", flat=True)) == Counter(
        row["state"] for row in DEPOSITS
    )
    assert {"received", "checking", "accepted", "rejected"} == {r["state"] for r in DEPOSITS}
    assert Depositor.objects.count() == len(DATA["depositors"])
    assert sorted(MtaTemplate.objects.values_list("lab__code", "code", "version")) == [
        ("BAC", "STD", 1),
        ("BAC", "STD", 2),
        ("MYC", "STD", 1),
    ]
    for deposit in Deposit.objects.filter(status="accepted").select_related("strain"):
        assert deposit.strain is not None
        assert deposit.strain.name_as_received == deposit.name_as_received
        assert deposit.first_passage.number == 0
    events = Counter(AuditEvent.objects.values_list("event_type", flat=True))
    assert events["deposit_received"] == len(DEPOSITS)
    assert events["deposit_accepted"] == len(ACCEPTED)
    assert out.count("Deposits:") == 1
    again = seed()
    assert f"Deposits: 0 created, {len(DEPOSITS)} found." in again


def test_requesters_and_their_permits_are_clearly_invented() -> None:
    for row in DATA["requesters"]:
        assert "(invented example)" in row["lab_evidence"], row["institution"]
        scientist = row["scientist"]
        assert scientist["email"].endswith("@example.org"), row["institution"]
        assert "(invented example)" in scientist["postal_address"], row["institution"]
        assert "(invented example)" in row["seat"], row["institution"]
        for permit in row["permits"]:
            assert re.search(r"invented example|/DEV/", permit["reference"]), permit


@pytest.mark.django_db
@pytest.mark.usefixtures("env")
def test_requesters_get_their_registered_office() -> None:
    seed()
    seats = dict(Requester.objects.values_list("institution", "seat"))
    assert seats == {row["institution"]: row["seat"] for row in DATA["requesters"]}
    assert all(seats.values())


@pytest.mark.django_db
@pytest.mark.usefixtures("env")
def test_the_requests_one_approvable_one_on_request_one_blocked_two_ready_two_shipped() -> None:
    seed()
    found = {
        r.end_use: {f.code: f.severity for f in evaluate(r, permit_today()).findings}
        for r in DistributionRequest.objects.all()
    }
    approvable, on_request, blocked, ready, regulated, shipped, confirmed = (
        row["end_use"] for row in DATA["requests"]
    )
    assert found[approvable] == {}
    # Commercial research on request to the depositor, no answer recorded yet (#144).
    assert found[on_request] == {"use_on_request": "block"}
    assert found[blocked]["rat_notice_missing"] == "block"
    # Approved, its vial reserved: the gates on the ship day find nothing, it is not regulated.
    assert found[ready] == {}
    # Regulated (dual-use): no blocker, the manager finding was decided by bac-manager, so its
    # shipment is prepared by one person and confirmed by another (#89).
    assert found[regulated] == {"regulated": "manager"}
    statuses = dict(DistributionRequest.objects.values_list("end_use", "status"))
    assert statuses == {
        approvable: "submitted",
        on_request: "submitted",
        blocked: "submitted",
        ready: "approved",
        regulated: "approved",
        shipped: "shipped",
        confirmed: "shipped",
    }
    approver = DistributionRequest.objects.get(end_use=regulated).decided_by
    assert approver is not None and approver.username == "bac-manager"
    # Shipped through the services, so each has its documents (#90): one in one step, one
    # prepared by the manager and confirmed by the curator, its dual-use line with the notice.
    one_step = Shipment.objects.get(request__end_use=shipped)
    two_step = Shipment.objects.get(request__end_use=confirmed)
    assert one_step.preparation is None
    assert two_step.preparation is not None
    assert (two_step.classified_by.username, two_step.shipped_by.username) == (
        "bac-manager",
        "bac-curator",
    )
    for shipment in (one_step, two_step):
        assert list(shipment.documents.values_list("kind", flat=True)) == ["delivery_note"]
    assert DUAL_USE_NOTICE in two_step.documents.get().text
    assert DUAL_USE_NOTICE not in one_step.documents.get().text


def test_contacts_and_references_of_the_intake_are_clearly_invented() -> None:
    for person in DATA["depositors"]:
        assert person["email"] == "" or person["email"].endswith("@example.org"), person
        assert person["postal_address"] == "" or "(invented example)" in person["postal_address"]
    for template in DATA["mta_templates"]:
        assert "invented example" in template["text"].lower()
    for row in DEPOSITS:
        for name in ("pic_reference", "mat_reference", "permit_reference", "ircc"):
            value = row["terms"].get(name, "")
            assert value == "" or "/DEV/" in value, (row["name_as_received"], name)
        for note in (row.get("condition_note", ""), row.get("rejection_reason", "")):
            assert note == "" or "(Invented example.)" in note
    # A strain of a real taxon states nothing of its own: strain_facts reads its taxon entry.
    for row in ACCEPTED:
        invented = accepted_entry(row["strain"]["taxon"], TAXA).get("invented")
        assert invented or not {"risk_group", "animal_pathogenicity"} & set(row["strain"]), row


def test_help_builds() -> None:
    with pytest.raises(SystemExit):
        call_command("seed_dev", "--help", stdout=StringIO())


# The data file, checked without a database: the facts it states about real organisms.

REAL = [t for t in TAXA if not t.get("invented")]
SOURCE = re.compile(r"^https://(lpsn\.dsmz\.de|www\.indexfungorum\.org)/")


@pytest.mark.parametrize("taxon", REAL, ids=lambda t: t["name"])
def test_every_real_taxon_names_its_source(taxon: dict[str, Any]) -> None:
    sources = taxon["source"]
    assert any(SOURCE.match(s) for s in sources), sources
    if taxon["ncbi"]:
        assert f"https://www.ncbi.nlm.nih.gov/Taxonomy/Browser/wwwtax.cgi?id={taxon['ncbi']}" in (
            sources
        )
    assert not taxon["name"].startswith(INVENTED_GENERA)


def test_invented_taxa_are_the_invented_genera_and_claim_no_source() -> None:
    invented = [t for t in TAXA if t.get("invented")]
    assert invented
    for taxon in invented:
        assert taxon["name"].startswith(INVENTED_GENERA)
        assert (taxon["ncbi"], taxon.get("source"), taxon["authority"]) == (None, None, "")


def test_every_identified_real_species_has_a_verified_risk_group() -> None:
    for row in STRAINS:
        found = accepted_entry(final_taxon(row), TAXA)
        if found.get("invented"):
            assert row["risk_group"] in (1, 2, 3)
            continue
        assert found["risk_group"] in (1, 2), found["name"]
        rg_source = " ".join(found["risk_group_source"])
        assert "361/2007" in rg_source
        assert "DSMZ" in rg_source
        annex = found["risk_group_source"][0]
        # Not listed, or listed with its non-pathogenic strains excepted (E. coli K-12).
        if annex.endswith(("not listed", "except non-pathogenic strains")):
            assert found["risk_group"] == 1, found["name"]
        else:
            assert annex == f"NV 361/2007 Sb., Příloha 7: {found['name']}, group 2", annex
            assert found["risk_group"] == 2, found["name"]
        dsmz = next(s for s in found["risk_group_source"] if "DSMZ DSM" in s)
        assert f"risk group {found['risk_group']}" in dsmz, found["name"]
        if found.get("plant_pathogenicity") or found.get("animal_pathogenicity"):
            assert found["pathogenicity_source"]


def test_a_real_taxon_is_never_paired_with_a_restriction() -> None:
    """Only a GMO lab strain (category 1) of a real taxon. Every list entry, risk group
    and pathogenicity a row states itself is on an invented taxon."""
    for row in STRAINS:
        real = [n for n in names_of(row) if not accepted_entry(n, TAXA).get("invented")]
        if not real:
            continue
        assert len(real) == len(names_of(row)), row["name_as_received"]
        for restriction in restrictions_of(row):
            assert (restriction["kind"], restriction.get("gmo_category")) == ("gmo", 1), row
        assert not {"risk_group", "animal_pathogenicity", "plant_pathogenicity"} & set(row)
        assert not any("risk_group" in step for step in row.get("history", []))
        rule = accepted_entry(final_taxon(row), TAXA).get("strain_name_contains")
        if rule:
            assert rule in row["name_as_received"]


def test_references_and_permits_are_clearly_invented() -> None:
    for lab in DATA["labs"]:
        for permit in lab["authorisations"]:
            assert "/DEV/" in permit["permit_reference"]
            if permit.get("end_reason"):
                assert "invented example" in permit["end_reason"]
    for row in STRAINS:
        for restriction in restrictions_of(row):
            if restriction["kind"] == "dual_use":
                continue  # a format only: the entry is checked by its pattern
            assert re.search(r"invented example|/DEV/", restriction["reference"]), restriction


def test_the_strain_rows_are_valid() -> None:
    names = {t["name"] for t in TAXA}
    seen: set[tuple[str, str]] = set()
    for row in STRAINS:
        assert row["lab"] in LAB_CODES
        assert set(names_of(row)) <= names
        assert row["country_of_origin"] in COUNTRY_CODES | {""}
        assert date.fromisoformat(row["identified_on"]) <= date(2026, 10, 1)
        key = (row["lab"], row["name_as_received"])
        assert key not in seen, key
        seen.add(key)
    assert 30 <= len(STRAINS) <= 60
    assert 20 <= len([t for t in REAL if t["rank"] == "species" and not t["accepted"]]) <= 40


# Storage.


def walk(rows: list[dict[str, Any]], parent: dict[str, Any] | None = None) -> list[tuple[Any, ...]]:
    """(parent row, row) for every unit of a lab's storage in seed_dev.json."""
    found: list[tuple[Any, ...]] = []
    for row in rows:
        found.append((parent, row))
        found += walk(row.get("children", []), row)
    return found


UNITS = [(lab["code"], parent, row) for lab in DATA["labs"] for parent, row in walk(lab["storage"])]


def test_the_storage_data_keeps_the_kind_spec_and_names_known_box_types() -> None:
    box_types = {t["name"] for t in DATA["box_types"]}
    for code, parent, row in UNITS:
        kind = UnitKind(row["kind"])
        if parent is None:
            assert not KIND_SPEC[kind].held_by and row["max_risk_group"] in (1, 2, 3), row
        else:
            assert may_hold(UnitKind(parent["kind"]), kind), (code, row)
        assert (row.get("box_type") in box_types) == (kind == UnitKind.BOX), row
    for lab in DATA["labs"]:  # every lab has a freezer or tank with a rack with a box
        pairs = {(p["kind"], row["kind"]) for p, row in walk(lab["storage"]) if p}
        assert ("rack", "box") in pairs, lab["code"]


@pytest.mark.django_db
@pytest.mark.usefixtures("env")
def test_it_builds_a_storage_tree_per_lab_through_the_storage_services() -> None:
    out = seed()
    assert StorageUnit.objects.count() == len(UNITS)
    assert f"Storage units: {len(UNITS)} created, 0 found." in out
    assert Counter(StorageUnit.objects.values_list("lab__code", flat=True)) == Counter(
        code for code, _, _ in UNITS
    )
    events = Counter(AuditEvent.objects.values_list("event_type", flat=True))
    assert events["storage_unit_created"] == StorageUnit.objects.count()
    assert events["box_type_created"] == BoxType.objects.count() == len(DATA["box_types"])
    assert events["storage_unit_status_changed"] == 1
    old = StorageUnit.objects.get(name="Freezer -80 old")
    assert old.status == "out_of_service"
    capped = StorageUnit.objects.get(name="Box 2, group 2 at most")
    assert may_store(unit=capped, risk_group=3).code == "risk_group_above_cap"
    assert may_store(
        unit=StorageUnit.objects.get(lab__code="REG", name="Box 1"), risk_group=3
    ).allowed


BATCHES: list[dict[str, Any]] = DATA["batches"]


@pytest.mark.django_db
@pytest.mark.usefixtures("env")
def test_it_preserves_batches_and_places_their_vials_through_the_lineage_services() -> None:
    out = seed()
    assert f"Batches: {len(BATCHES)} created, 0 found." in out
    assert Batch.objects.count() == len(BATCHES)
    assert Vial.objects.count() == sum(row["vial_count"] for row in BATCHES)
    # Every vial of a batch with a box was placed; the checks used some up since, and the
    # shipped requests sent some (#90): those placements are closed.
    placed = VialPlacement.objects.all()
    assert placed.count() == sum(row["vial_count"] for row in BATCHES if row["box"])
    assert set(
        placed.filter(removed_at__isnull=False).values_list("removal_reason", flat=True)
    ) <= {"consumed", "distributed"}
    for row in BATCHES:
        if not row["box"]:
            continue
        box = StorageUnit.objects.get(
            lab__code=row["lab"], name=row["box"][-1], parent__name=row["box"][-2]
        )
        assert box.placements.filter(removed_at__isnull=True).exists(), row
    # A batch of passage 1 comes from a subculture, made through its service.
    assert Passage.objects.filter(number=1, source_passage__isnull=False).count() == len(
        {(row["lab"], row["deposit"]) for row in BATCHES if row["passage"] == 1}
    )
    events = Counter(AuditEvent.objects.values_list("event_type", flat=True))
    assert events["batch_created"] == len(BATCHES)
    assert events["vial_created"] == Vial.objects.count()
    assert events["vial_placed"] == placed.count()
    from_deposits = set(Deposit.objects.filter(status="accepted").values_list("strain", flat=True))
    assert set(Vial.objects.values_list("batch__strain", flat=True)) <= from_deposits
    again = seed()
    assert f"Batches: 0 created, {len(BATCHES)} found." in again


CHECKS: list[dict[str, Any]] = DATA["checks"]


@pytest.mark.django_db
@pytest.mark.usefixtures("env")
def test_it_records_checks_and_releases_through_the_lineage_services() -> None:
    out = seed()
    assert f"Checks: {len(CHECKS)} created, 0 found." in out
    assert BatchCheck.objects.count() == len(CHECKS)
    assert set(BatchCheck.objects.values_list("performed_by__username", flat=True)) == {
        "bac-technician",
        "myc-technician",
    }
    statuses = {
        (b.lab.code, b.strain.name_as_received, b.number): b.status
        for b in Batch.objects.filter(lab__code__in=["BAC", "MYC"]).select_related("strain")
    }
    assert statuses == {
        ("BAC", "Bacillus subtilis soil isolate DEP-1", 1): BatchStatus.RELEASED,
        ("BAC", "Bacillus subtilis soil isolate DEP-1", 2): BatchStatus.RELEASED,
        ("BAC", "Bacillus subtilis soil isolate DEP-1", 3): BatchStatus.PENDING_CHECK,
        ("BAC", "Mockia vulgaris DEP-8", 1): BatchStatus.RELEASED,
        ("MYC", "Testella cerea DEP-5", 1): BatchStatus.ON_HOLD,
        ("MYC", "Testella cerea DEP-5", 2): BatchStatus.PENDING_CHECK,
    }
    events = Counter(AuditEvent.objects.values_list("event_type", flat=True))
    assert events["batch_check_recorded"] == len(CHECKS)
    assert events["batch_status_changed"] == 4  # three releases and the hold by a failed check
    named = {(row["lab"], row["batch"], row["vial"]) for row in CHECKS if row["vial"]}
    used = set(
        BatchCheck.objects.filter(vial__isnull=False).values_list(
            "lab__code", "batch__number", "vial__seq"
        )
    )
    assert used == named
    assert set(Vial.objects.filter(checks__isnull=False).values_list("status", flat=True)) == {
        "consumed"
    }
    again = seed()
    assert f"Checks: 0 created, {len(CHECKS)} found." in again
    assert (
        Counter(AuditEvent.objects.values_list("event_type", flat=True))["batch_status_changed"]
        == 4
    )


@pytest.mark.django_db
@pytest.mark.usefixtures("env")
def test_it_seeds_media_and_growth_conditions_through_the_growth_services() -> None:
    out = seed()
    media = DATA["media"]
    assert f"Media: {len(media)} created, 0 found." in out
    assert GrowthMedium.objects.count() == len(media)
    retired = {row["name"] for row in media if row.get("retire_reason")}
    assert (
        set(GrowthMedium.objects.filter(retired_at__isnull=False).values_list("name", flat=True))
        == retired
    )
    # A strain is grown as its history says; its passage 0 predates that and records nothing.
    cerea = Strain.objects.get(name_as_received="Testella cerea DEP-5")
    assert cerea.growth_medium is not None
    assert (cerea.growth_medium.name, cerea.growth_temperature_low_c, cerea.growth_atmosphere) == (
        "Malt extract agar",
        25,
        "aerobic",
    )
    zero, one = cerea.passages.order_by("number")
    assert zero.growth_medium is None
    # The subculture batch records its own conditions, not the strain's.
    assert one.growth_medium is not None
    assert (one.growth_medium.name, one.growth_temperature_low_c) == ("Potato dextrose agar", 22)
    # A real taxon gets none: no citable type-strain entry was checked for it.
    real = Strain.objects.get(name_as_received="Bacillus subtilis soil isolate DEP-1")
    assert real.growth_medium is None
    assert not any(
        row["lab"] == "BAC" and "growth" in row
        for row in DEPOSITS
        if row["name_as_received"].startswith("Bacillus")
    )
    assert AuditEvent.objects.filter(event_type="strain_growth_changed").exists()
    again = seed()
    assert f"Media: 0 created, {len(media)} found." in again


def test_every_check_names_a_listed_batch_and_a_vial_it_has() -> None:
    batches: dict[tuple[str, str], list[dict[str, Any]]] = {
        (row["lab"], row["deposit"]): [] for row in BATCHES
    }
    for row in BATCHES:
        batches[(row["lab"], row["deposit"])].append(row)
    for row in [*CHECKS, *DATA["releases"]]:
        listed = batches[(row["lab"], row["deposit"])]
        assert 1 <= row["batch"] <= len(listed), row
    for row in CHECKS:
        batch = batches[(row["lab"], row["deposit"])][row["batch"] - 1]
        assert row["checked_on"] >= batch["preserved_on"], row
        assert row["vial"] is None or 1 <= row["vial"] <= batch["vial_count"], row
        # Checks name no real organism's results as facts: a failure only on invented taxa.
        if row["result"] == "fail":
            assert row["deposit"].startswith(("Testella", "Mockia", "Fictivibrio")), row


@pytest.mark.django_db
@pytest.mark.usefixtures("env")
def test_the_regulated_lab_has_masked_vials_and_one_holder_of_the_grant() -> None:
    seed()
    reg = Lab.objects.get(code="REG")
    regulated = Vial.objects.filter(lab=reg, batch__strain__restrictions__ended_at__isnull=True)
    assert regulated.exists()
    (grant,) = LocationGrant.objects.filter(lab=reg, revoked_at__isnull=True)
    assert grant.user.username == "reg-manager"
    assert "(invented example)" in grant.reason
    seed()
    assert LocationGrant.objects.filter(lab=reg).count() == 1


def test_every_batch_names_an_accepted_deposit_and_a_box_of_its_lab() -> None:
    accepted = {(row["lab"], row["name_as_received"]) for row in ACCEPTED}
    boxes = {(code, *path) for code, *path in _box_paths()}
    for row in BATCHES:
        assert (row["lab"], row["deposit"]) in accepted, row
        assert row["box"] is None or (row["lab"], *row["box"]) in boxes, row


def _box_paths() -> list[tuple[str, ...]]:
    found: list[tuple[str, ...]] = []

    def walk(code: str, units: list[dict[str, Any]], above: tuple[str, ...]) -> None:
        for unit in units:
            path = (*above, unit["name"])
            if unit["kind"] == "box":
                found.append((code, *path))
            walk(code, unit.get("children", []), path)

    for lab in DATA["labs"]:
        walk(lab["code"], lab["storage"], ())
    return found
