"""Development data to work with by hand: labs, users in every role, taxa, permits, strains
and storage.

    DEV_PASSWORD=... python manage.py seed_dev [--password ...] [--force]

Refused unless DEBUG is on and the settings module is the development one
(config.settings.local sets DEV_DATA_ALLOWED, production sets it off), so it
never runs against production. Refused also when the database holds a lab that
neither this command nor seed_e2e created (its lab_created event names another
actor): that database holds someone's data. --force adds the development data
next to it. Nothing the command did not create is changed, except that a lab
with one of its codes is used as found.

What it creates (seed_dev.json holds the box types, labs, storage, taxa, strains,
depositors, MTA templates and deposits):
- four labs (BAC, MYC, REG, ENV) with a manager, a curator, a technician and a
  viewer each (`bac-manager` and so on);
- dev-admin, staff and superuser, created through User.objects.create_superuser
  with a reason. dev-two-labs, curator in BAC and viewer in MYC. dev-no-lab, in
  no lab. dev-inactive, a technician of ENV who was deactivated.
- the permits: MYC holds a valid ÚKZÚZ permit and an ended one, REG a valid
  SÚJB permit, ENV an expired SÚJB permit, so the gates can be tried in each;
- real taxa with their sources, and the invented ones the tests use;
- strains created through the strain services with the role of each lab's
  curator, some reclassified, some restricted (invented taxa only, a GMO lab
  strain aside);
- depositors (invented people at example.org), MTA versions (published by each
  lab's manager) and deposits in every intake state, three of them accepted, which
  makes their strains through the deposit services (the third, in BAC, an invented
  dual-use strain that goes out in two steps, #89);
- three box types and a storage tree per lab (freezers and LN2 tanks, racks,
  boxes), added through the storage services with the curator's role: REG has
  a box capped lower than its freezer, ENV a freezer out of service;
- batches of vials of the accepted deposits' strains, preserved by each lab's
  technician through the lineage services, most placed into a box in fill order,
  one from a subculture (passage 1); REG's strain from its deposit is regulated
  (a RAT, invented taxon), so its vials' places are masked, and reg-manager holds
  the lab's location grant to reveal them.
- checks of those batches, recorded by each lab's technician (some consume the
  vial they name), and releases by the lab's curator: two BAC batches released,
  one freeze-dried BAC batch with a reduced viability check and nothing else yet,
  the dual-use strain's batch released, and MYC's batch (invented taxon) held by a
  failed purity check.
- requesters with their permits (invented institutions and references) and three requests
  waiting for a decision (#18): in BAC one a curator may approve and one whose use is on
  request to the depositor, so a manager approves it; in REG one blocked by a legal gate (a
  RAT to a laboratory that never notified SÚJB, invented taxon). In BAC also one approved
  by the curator, ready to ship (#88), and one of the dual-use strain approved by
  bac-manager, ready for one person to prepare its shipment and another to confirm it (#89).
Every user gets the same password. Every write goes through the services in one
transaction, inside an audit context (channel command, actor kind system,
label command:seed_dev). A second run finds what exists and changes nothing.
Strains are never deleted, so a strain is found by its lab and name as received.
A depositor is found by its lab and contact name, an MTA version by its lab, code
and version, and a deposit by its lab and name as received; a deposit found is
never moved on. A storage unit is found by its lab, its parent and its name, and
is never changed again. A strain that has as many batches as the file lists gets
none, a batch that has as many checks as the file lists gets none, a release is
made only for a batch still pending its checks, and an open location grant is
kept as found.
"""

import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser

from config.env import env_secret
from cultures.audit.context import audit_context, audited_atomic
from cultures.audit.models import ActorKind, AuditEvent, Channel
from cultures.audit.registry import LAB_CREATED
from cultures.biosafety import seeding as seed_biosafety
from cultures.biosafety.models import AuthorisationKind, RestrictionKind
from cultures.deposits import services as deposits
from cultures.deposits.models import (
    AbsScope,
    Condition,
    Decision,
    Deposit,
    Depositor,
    MtaTemplate,
    Use,
)
from cultures.distribution import seeding
from cultures.distribution import services as distribution
from cultures.distribution.models import LegalForm, PermitKind
from cultures.labs import seeding as seed_labs
from cultures.labs.access import Access, access_for
from cultures.labs.models import Lab, Membership
from cultures.labs.permissions import Role
from cultures.lineage import services as lineage
from cultures.lineage.models import (
    Batch,
    BatchCheck,
    BatchStatus,
    CheckKind,
    CheckMethod,
    CheckResult,
    CheckStage,
    CheckUnit,
    Method,
    Passage,
    Purpose,
    Vial,
)
from cultures.storage import services as storage
from cultures.storage.models import BoxType, StorageUnit, UnitKind, UnitStatus
from cultures.strains import seeding as seed_strains
from cultures.strains import services as strains
from cultures.strains.models import Pathogenicity, Strain
from cultures.taxonomy import seeding as seed_taxa
from cultures.taxonomy.models import Rank, Taxon
from cultures.users import seeding as seed_users
from cultures.users import services as users
from cultures.users.models import User

DATA = Path(__file__).with_name("seed_dev.json")
LABEL = "command:seed_dev"
# Labs these commands created are development data. Any other lab is somebody's.
SEED_LABELS = frozenset({LABEL, "command:seed_e2e"})
REASON = "development data"
LAB_ROLES = (Role.MANAGER, Role.CURATOR, Role.TECHNICIAN, Role.VIEWER)
ADMIN, TWO_LABS, NO_LAB, INACTIVE = "dev-admin", "dev-two-labs", "dev-no-lab", "dev-inactive"
# (username, lab code, role)
EXTRA_MEMBERS = (
    (TWO_LABS, "BAC", Role.CURATOR),
    (TWO_LABS, "MYC", Role.VIEWER),
    (INACTIVE, "ENV", Role.TECHNICIAN),
)


def refusal() -> str | None:
    """Why the settings forbid development data, or None. Checked before anything else."""
    if not settings.DEBUG:
        return "seed_dev creates users with a known password: it runs only with DEBUG on."
    if getattr(settings, "DEV_DATA_ALLOWED", False) is not True:
        return (
            "seed_dev runs only with the development settings (config.settings.local), "
            f"not {settings.SETTINGS_MODULE}."
        )
    return None


def load() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(DATA.read_text(encoding="utf-8"))
    return data


def lab_username(code: str, role: Role) -> str:
    return f"{code.lower()}-{role}"


def foreign_labs() -> list[Lab]:
    """Labs whose creation no seed command recorded."""
    created_by = dict(
        AuditEvent.objects.filter(event_type=LAB_CREATED.code).values_list(
            "subject_id", "actor_label"
        )
    )
    return [
        lab
        for lab in Lab.objects.order_by("code")
        if created_by.get(lab.public_id) not in SEED_LABELS
    ]


def staff(code: str, role: Role) -> Access:
    """The access of the lab's member in this role."""
    return access_for(User.objects.get(username=lab_username(code, role)))


def day(text: str | None) -> date | None:
    return date.fromisoformat(text) if text else None


@dataclass
class Counts:
    created: int = 0
    found: int = 0

    def add(self, created: bool) -> None:
        if created:
            self.created += 1
        else:
            self.found += 1


class Command(BaseCommand):
    help = "Fill a development database with labs, users, taxa, permits, strains and storage."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--password",
            help="The password of every user (default: DEV_PASSWORD or DEV_PASSWORD_FILE).",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Run although the database holds labs no seed command created.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        reason = refusal()
        if reason:
            raise CommandError(reason)
        password = options["password"] or env_secret("DEV_PASSWORD", "")
        if not password.strip():
            raise CommandError("Give the password in DEV_PASSWORD (or --password).")
        data = load()
        with audit_context(
            channel=Channel.COMMAND, actor_kind=ActorKind.SYSTEM, actor_label=LABEL, reason=REASON
        ):
            foreign = foreign_labs()
            if foreign and not options["force"]:
                codes = ", ".join(lab.code for lab in foreign)
                raise CommandError(
                    f"The database holds labs no seed command created ({codes}). "
                    "Use a development database, or pass --force to add the data next to them."
                )
            with audited_atomic():
                self.taxa = Counts()
                self.strains = Counts()
                self.units = Counts()
                for row in data["box_types"]:
                    self._box_type(row)
                for row in data["taxa"]:
                    self.taxa.add(seed_taxa.taxon_filling_parent(taxon(row)))
                seed_users.superuser(ADMIN, password)
                lab_by_code = {row["code"]: self._lab(row, password) for row in data["labs"]}
                self._extra_users(lab_by_code, password)
                for row in data["strains"]:
                    # Entered with the curator's role, never changed afterwards.
                    created = seed_strains.strain(
                        staff(row["lab"], Role.CURATOR),
                        staff(row["lab"], Role.MANAGER),
                        lab_by_code[row["lab"]],
                        seed_strain(row, data["taxa"]),
                    )
                    self.strains.add(created)
                self.deposits = Counts()
                self._intake(data, lab_by_code)
                for row in data["labs"]:
                    self._storage(lab_by_code[row["code"]], row["storage"], parent=None)
                self.batches = Counts()
                for (code, deposit), rows in _by_deposit(data["batches"]).items():
                    self._batches(lab_by_code[code], deposit, rows)
                self.checks = Counts()
                for (code, deposit, number), rows in _by_batch(data["checks"]).items():
                    self._checks(lab_by_code[code], deposit, number, rows)
                for row in data["releases"]:
                    self._release(lab_by_code[row["lab"]], row)
                for row in data["location_grants"]:
                    self._location_grant(lab_by_code[row["lab"]], row)
                self._distribution(data, lab_by_code)
        self._report(data)

    # Users and labs.

    def _lab(self, row: dict[str, Any], password: str) -> Lab:
        lab = seed_labs.lab(row["name"], row["code"])
        for role in LAB_ROLES:
            seed_labs.member(lab, seed_users.user(lab_username(lab.code, role), password), role)
        for permit in row["authorisations"]:
            seed_biosafety.authorisation(lab, authorisation(permit))
        return lab

    def _extra_users(self, lab_by_code: dict[str, Lab], password: str) -> None:
        seed_users.user(TWO_LABS, password)
        seed_users.user(NO_LAB, password)
        inactive = User.objects.filter(username=INACTIVE).first() or seed_users.user(
            INACTIVE, password
        )
        for username, code, role in EXTRA_MEMBERS:
            user = User.objects.get(username=username)
            missing = not Membership.objects.filter(lab=lab_by_code[code], user=user).exists()
            if missing and not user.is_active:
                user = users.user_activate(user=user)  # memberships need an active user
            seed_labs.member(lab_by_code[code], user, role)
        inactive.refresh_from_db()
        if inactive.is_active:
            users.user_deactivate(user=inactive)
        if not inactive.check_password(password):
            users.user_set_password(user=inactive, raw_password=password)

    # Depositors, MTA versions and deposits, through the deposit services.

    def _intake(self, data: dict[str, Any], lab_by_code: dict[str, Lab]) -> None:
        def staff(code: str, role: Role) -> Access:
            return access_for(User.objects.get(username=lab_username(code, role)))

        for row in data["depositors"]:
            lab = lab_by_code[row["lab"]]
            if not Depositor.objects.filter(lab=lab, contact__name=row["name"]).exists():
                deposits.depositor_create(
                    access=staff(lab.code, Role.CURATOR),
                    lab=lab,
                    contact=deposits.ContactInput(row["name"], row["email"], row["postal_address"]),
                    institution=row["institution"],
                )
        for (code, mta_code), rows in _grouped(data["mta_templates"]).items():
            lab = lab_by_code[code]
            published = MtaTemplate.objects.filter(lab=lab, code=mta_code).count()
            for row in rows[published:]:
                deposits.mta_template_publish(
                    access=staff(code, Role.MANAGER),
                    lab=lab,
                    code=mta_code,
                    title=row["title"],
                    text=row["text"],
                )
        for row in data["deposits"]:
            self._deposit(row, lab_by_code[row["lab"]], staff(row["lab"], Role.CURATOR), data)

    def _deposit(self, row: dict[str, Any], lab: Lab, access: Access, data: dict[str, Any]) -> None:
        if Deposit.objects.filter(lab=lab, name_as_received=row["name_as_received"]).exists():
            self.deposits.found += 1
            return
        terms = row["terms"]
        mta = (
            MtaTemplate.objects.get(lab=lab, code=row["mta"][0], version=row["mta"][1])
            if row["mta"]
            else None
        )
        deposit = deposits.deposit_receive(
            access=access,
            lab=lab,
            data=deposits.NewDeposit(
                depositor=Depositor.objects.get(lab=lab, contact__name=row["depositor"]),
                received_on=date.fromisoformat(row["received_on"]),
                condition=Condition(row["condition"]),
                condition_note=row.get("condition_note", ""),
                name_as_received=row["name_as_received"],
                depositor_passages=row.get("depositor_passages"),
                terms=deposits.TermsInput(
                    abs_scope=AbsScope(terms["abs_scope"]),
                    uses=[(Use(u), Decision(d)) for u, d in terms["uses"].items()],
                    mta=mta,
                    country_of_origin=terms.get("country_of_origin", ""),
                    collection_date=terms.get("collection_date", ""),
                    pic_reference=terms.get("pic_reference", ""),
                    mat_reference=terms.get("mat_reference", ""),
                    permit_reference=terms.get("permit_reference", ""),
                ),
            ),
        )
        self.deposits.created += 1
        if row["state"] == "received":
            return
        deposit = deposits.deposit_start_check(access=access, deposit=deposit)
        if row["state"] == "rejected":
            deposits.deposit_reject(access=access, deposit=deposit, reason=row["rejection_reason"])
        if row["state"] != "accepted":
            return
        strain = row["strain"]
        facts = strain_facts(
            {**strain, "history": [], "name_as_received": row["name_as_received"]}, data["taxa"]
        )
        deposits.deposit_accept(
            access=access,
            deposit=deposit,
            facts=deposits.StrainFacts(
                taxon=Taxon.objects.get(name=strain["taxon"]),
                identified_on=date.fromisoformat(strain["identified_on"]),
                identification_method=strain["method"],
                risk_group=facts.risk_group,
                animal_pathogenicity=facts.animal,
                plant_pathogenicity=facts.plant,
                isolation_source=strain["isolation_source"],
                country_of_origin=strain["country_of_origin"],
                isolation_date=strain["isolation_date"],
                restrictions=[restriction(r) for r in strain.get("restrictions", [])],
            ),
        )

    # Storage: box types and units created when missing, never changed afterwards.

    def _box_type(self, row: dict[str, Any]) -> None:
        if not BoxType.objects.filter(name__iexact=row["name"]).exists():
            storage.box_type_create(name=row["name"], rows=row["rows"], cols=row["cols"])

    def _storage(self, lab: Lab, rows: list[dict[str, Any]], parent: StorageUnit | None) -> None:
        curator = User.objects.get(username=lab_username(lab.code, Role.CURATOR))
        for row in rows:
            unit = StorageUnit.objects.filter(lab=lab, parent=parent, name=row["name"]).first()
            access = access_for(curator)
            created = unit is None
            if unit is None:
                unit = storage.unit_create(
                    access=access,
                    lab=lab,
                    data=storage.NewUnit(
                        kind=UnitKind(row["kind"]),
                        name=row["name"],
                        parent=parent,
                        slot=row.get("slot"),
                        barcode=row.get("barcode", ""),
                        temperature_c=row.get("temperature_c"),
                        max_risk_group=row.get("max_risk_group"),
                        box_type=BoxType.objects.get(name=row["box_type"])
                        if "box_type" in row
                        else None,
                    ),
                )
                self.units.created += 1
            else:
                self.units.found += 1
            self._storage(lab, row.get("children", []), parent=unit)
            # After what it holds: nothing goes into a unit out of service.
            if created and "status" in row:
                storage.unit_set_status(
                    access=access, unit=unit, status=UnitStatus(row["status"]), reason=row["reason"]
                )

    # Passages, batches and vials (#16), through the lineage services with the technician's role:
    # the bench work. A strain's batches are created in the order of the file; a strain that
    # has as many as the file lists gets no more.

    def _batches(self, lab: Lab, deposit_name: str, rows: list[dict[str, Any]]) -> None:
        technician = User.objects.get(username=lab_username(lab.code, Role.TECHNICIAN))
        access = access_for(technician)
        strain = Deposit.objects.get(lab=lab, name_as_received=deposit_name).strain
        assert strain is not None  # noqa: S101 (the file lists accepted deposits only)
        made = Batch.objects.filter(strain=strain).count()
        self.batches.found += min(made, len(rows))
        for row in rows[made:]:
            passage = self._passage(access, strain, row["passage"])
            box = None
            if row["box"]:
                box = self._unit_at(lab, row["box"])
            lineage.batch_preserve(
                access=access,
                passage=passage,
                data=lineage.NewBatch(
                    method=Method(row["method"]),
                    purpose=Purpose(row["purpose"]),
                    preserved_on=date.fromisoformat(row["preserved_on"]),
                    vial_count=row["vial_count"],
                    cryoprotectant=row["cryoprotectant"],
                    box=box,
                ),
            )
            self.batches.created += 1

    # Checks of batches and their release (#17): checks by the technician (the bench work), in
    # the order of the file; a release by the curator.

    def _batch(self, lab: Lab, deposit_name: str, number: int) -> Batch:
        return Batch.objects.get(
            lab=lab, strain__deposit__name_as_received=deposit_name, number=number
        )

    def _checks(self, lab: Lab, deposit_name: str, number: int, rows: list[dict[str, Any]]) -> None:
        technician = User.objects.get(username=lab_username(lab.code, Role.TECHNICIAN))
        access = access_for(technician)
        batch = self._batch(lab, deposit_name, number)
        made = BatchCheck.objects.filter(batch=batch).count()
        self.checks.found += min(made, len(rows))
        for row in rows[made:]:
            vial = Vial.objects.get(batch=batch, seq=row["vial"]) if row["vial"] else None
            lineage.check_record(
                access=access,
                batch=batch,
                data=lineage.NewCheck(
                    kind=CheckKind(row["kind"]),
                    stage=CheckStage(row["stage"]),
                    checked_on=date.fromisoformat(row["checked_on"]),
                    method=CheckMethod(row["method"]),
                    result=CheckResult(row["result"]),
                    method_detail=row["method_detail"],
                    value=None if row["value"] is None else Decimal(row["value"]),
                    unit=None if row["unit"] is None else CheckUnit(row["unit"]),
                    vial=vial,
                    note=row["note"],
                ),
            )
            self.checks.created += 1

    def _release(self, lab: Lab, row: dict[str, Any]) -> None:
        batch = self._batch(lab, row["deposit"], row["batch"])
        if batch.status != BatchStatus.PENDING_CHECK:
            return
        curator = User.objects.get(username=lab_username(lab.code, Role.CURATOR))
        lineage.batch_release(access=access_for(curator), batch=batch, reason=row["reason"])

    def _passage(self, access: Access, strain: Strain, number: int) -> Passage:
        """The strain's passage with this number, grown by subculture from the one before."""
        found = Passage.objects.filter(strain=strain, number=number).order_by("pk").first()
        if found is not None:
            return found
        parent = self._passage(access, strain, number - 1)
        return lineage.passage_subculture(access=access, parent=parent)

    def _unit_at(self, lab: Lab, names: list[str]) -> StorageUnit:
        unit = None
        for name in names:
            unit = StorageUnit.objects.get(lab=lab, parent=unit, name=name)
        assert unit is not None  # noqa: S101 (a path names at least the box)
        return unit

    def _location_grant(self, lab: Lab, row: dict[str, Any]) -> None:
        """ADR 0009: who may see where the lab's regulated strains are, granted by its manager."""
        seed_labs.location_grant(
            lab,
            User.objects.get(username=row["user"]),
            granted_by=User.objects.get(username=lab_username(lab.code, Role.MANAGER)),
            reason=row["reason"],
        )

    def _distribution(self, data: dict[str, Any], lab_by_code: dict[str, Lab]) -> None:
        for row in data["requesters"]:
            self._requester(lab_by_code[row["lab"]], row)
        for row in data["requests"]:
            self._request(lab_by_code[row["lab"]], row)

    def _requester(self, lab: Lab, row: dict[str, Any]) -> None:
        """#18: an institution that may receive material, entered by the lab's curator."""
        curator = access_for(User.objects.get(username=lab_username(lab.code, Role.CURATOR)))
        scientist = row["scientist"]
        seeding.requester(
            curator,
            lab,
            seeding.SeedRequester(
                institution=row["institution"],
                country=row["country"],
                lab_evidence=row["lab_evidence"],
                scientist=distribution.ContactInput(
                    scientist["name"], scientist["email"], scientist["postal_address"]
                ),
                legal_form=LegalForm(row["legal_form"]),
                registration_number=row["registration_number"],
                seat=row["seat"],
                lab_confirmed_on=date.fromisoformat(row["lab_confirmed_on"]),
                permits=tuple(
                    seeding.SeedPermit(
                        kind=PermitKind(permit["kind"]),
                        issuer=permit["issuer"],
                        issuer_country=permit["issuer_country"],
                        reference=permit["reference"],
                        valid_from=date.fromisoformat(permit["valid_from"]),
                        covers=permit.get("covers", ""),
                        risk_group=permit.get("risk_group"),
                        gmo_category=permit.get("gmo_category"),
                    )
                    for permit in row["permits"]
                ),
            ),
        )

    def _request(self, lab: Lab, row: dict[str, Any]) -> None:
        """#18: a request as entered by the lab's curator, waiting for a decision, or approved by
        the curator and ready to ship (#88), or, regulated, approved by the manager with a reason
        and ready to prepare for a second person (#89); or shipped, in one step by the curator or
        prepared by `prepared_by` and confirmed by `confirmed_by`, with its documents (#90)."""
        curator = access_for(User.objects.get(username=lab_username(lab.code, Role.CURATOR)))

        def member(role: str | None) -> Access | None:
            if not role:
                return None
            return access_for(User.objects.get(username=lab_username(lab.code, Role(role))))

        approver = member(row.get("approved_by"))
        lines = []
        for line in row["lines"]:
            strain = Deposit.objects.get(lab=lab, name_as_received=line["deposit"]).strain
            assert strain is not None  # noqa: S101 (an accepted deposit)
            lines.append((strain, line["quantity"]))
        seeding.request(
            curator,
            lab,
            seeding.SeedRequest(
                institution=row["requester"],
                end_use=row["end_use"],
                use=Use(row["use"]),
                containment_level=row["containment_level"],
                lines=tuple(lines),
                accept=row["accept"],
                approve=row.get("approve", False),
                reason=row.get("reason", ""),
                ship=row.get("ship", False),
            ),
            approver=approver,
            shipper=member(row.get("prepared_by")),
            confirmer=member(row.get("confirmed_by")),
        )

    def _report(self, data: dict[str, Any]) -> None:
        out = self.stdout.write
        out(f"Taxa: {self.taxa.created} created, {self.taxa.found} found.")
        out(f"Strains: {self.strains.created} created, {self.strains.found} found.")
        out(f"Deposits: {self.deposits.created} created, {self.deposits.found} found.")
        out(f"Storage units: {self.units.created} created, {self.units.found} found.")
        out(f"Batches: {self.batches.created} created, {self.batches.found} found.")
        out(f"Checks: {self.checks.created} created, {self.checks.found} found.")
        out("Logins, all with the password you gave:")
        out(f"  {ADMIN:<16} staff and superuser (Django admin), in no lab")
        for row in data["labs"]:
            for role in LAB_ROLES:
                username = lab_username(row["code"], role)
                out(f"  {username:<16} {role} of {row['name']} ({row['code']})")
        out(f"  {TWO_LABS:<16} curator of BAC, viewer of MYC")
        out(f"  {NO_LAB:<16} in no lab")
        out(f"  {INACTIVE:<16} technician of ENV, deactivated: cannot sign in")


@dataclass(frozen=True)
class StrainFacts:
    risk_group: int
    animal: Pathogenicity
    plant: Pathogenicity


def accepted_entry(name: str, taxa: list[dict[str, Any]]) -> dict[str, Any]:
    """The data entry of a name, or of its accepted name when it is a synonym."""
    entry = next(t for t in taxa if t["name"] == name)
    if entry["accepted"]:
        return accepted_entry(entry["accepted"], taxa)
    return entry


def final_taxon(row: dict[str, Any]) -> str:
    """The taxon of the strain's last identification."""
    names: list[str] = [row["taxon"]]
    names += [s["reclassify"]["taxon"] for s in row.get("history", []) if "reclassify" in s]
    return names[-1]


def strain_facts(row: dict[str, Any], taxa: list[dict[str, Any]]) -> StrainFacts:
    """A strain of a real taxon takes the risk group and pathogenicity verified for its
    final taxon in the data file. Only an invented taxon's strain states its own."""
    entry = accepted_entry(final_taxon(row), taxa)
    if entry.get("invented"):
        return StrainFacts(
            row["risk_group"],
            Pathogenicity(row["animal_pathogenicity"]),
            Pathogenicity(row["plant_pathogenicity"]),
        )
    return StrainFacts(
        entry["risk_group"],
        Pathogenicity(entry.get("animal_pathogenicity", Pathogenicity.UNKNOWN)),
        Pathogenicity(entry.get("plant_pathogenicity", Pathogenicity.UNKNOWN)),
    )


def _by_deposit(rows: list[dict[str, Any]]) -> dict[tuple[str, str], list[dict[str, Any]]]:
    """Batch rows by lab and deposit, in the order of the file: that order is the batch order."""
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault((row["lab"], row["deposit"]), []).append(row)
    return groups


def _by_batch(rows: list[dict[str, Any]]) -> dict[tuple[str, str, int], list[dict[str, Any]]]:
    """Check rows by lab, deposit and batch number, in the order of the file."""
    groups: dict[tuple[str, str, int], list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault((row["lab"], row["deposit"], row["batch"]), []).append(row)
    return groups


def _grouped(rows: list[dict[str, Any]]) -> dict[tuple[str, str], list[dict[str, Any]]]:
    """MTA rows by lab and code, in the order of the file: that order is the version order."""
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault((row["lab"], row["code"]), []).append(row)
    return groups


def taxon(row: dict[str, Any]) -> seed_taxa.SeedTaxon:
    return seed_taxa.SeedTaxon(
        name=row["name"],
        authority=row["authority"],
        rank=Rank(row["rank"]),
        parent=row["parent"],
        accepted=row["accepted"],
        ncbi=row["ncbi"],
    )


def authorisation(row: dict[str, Any]) -> seed_biosafety.SeedAuthorisation:
    ended_on = day(row.get("ended_on"))
    return seed_biosafety.SeedAuthorisation(
        kind=AuthorisationKind(row["kind"]),
        permit_reference=row["permit_reference"],
        valid_from=date.fromisoformat(row["valid_from"]),
        expires_on=day(row["expires_on"]),
        ended_on=ended_on,
        end_reason=row["end_reason"] if ended_on is not None else "",
    )


def facts(row: dict[str, Any], taxa: list[dict[str, Any]]) -> seed_strains.SeedFacts:
    known = strain_facts(row, taxa)
    return seed_strains.SeedFacts(
        taxon=row["taxon"],
        identified_on=date.fromisoformat(row["identified_on"]),
        identification_method=row["method"],
        risk_group=known.risk_group,
        animal_pathogenicity=known.animal,
        plant_pathogenicity=known.plant,
        isolation_source=row["isolation_source"],
        country_of_origin=row["country_of_origin"],
        isolation_date=row["isolation_date"],
        restrictions=tuple(restriction(r) for r in row.get("restrictions", [])),
    )


def seed_strain(row: dict[str, Any], taxa: list[dict[str, Any]]) -> seed_strains.SeedStrain:
    return seed_strains.SeedStrain(
        name_as_received=row["name_as_received"],
        facts=facts(row, taxa),
        history=tuple(step(s) for s in row.get("history", [])),
    )


def step(row: dict[str, Any]) -> seed_strains.Step:
    if "reclassify" in row:
        change = row["reclassify"]
        return seed_strains.Reclassify(
            taxon=change["taxon"],
            identified_on=date.fromisoformat(change["identified_on"]),
            method=change["method"],
            reason=change["reason"],
        )
    if "risk_group" in row:
        return seed_strains.SetRiskGroup(risk_group=row["risk_group"], reason=row["reason"])
    if "restriction_add" in row:
        return seed_strains.AddRestriction(
            restriction=restriction(row["restriction_add"]), reason=row["reason"]
        )
    if "restriction_end" in row:
        ending = row["restriction_end"]
        return seed_strains.EndRestriction(
            kind=ending["kind"], reference=ending["reference"], reason=row["reason"]
        )
    raise CommandError(f"Unknown step in {DATA.name}: {sorted(row)}")


def restriction(row: dict[str, Any]) -> strains.RestrictionInput:
    return strains.RestrictionInput(
        kind=RestrictionKind(row["kind"]),
        reference=row["reference"],
        act=row.get("act", ""),
        gmo_category=row.get("gmo_category"),
    )
