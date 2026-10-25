"""The data the Playwright tests use, locally and in CI. Refused unless DEBUG is on.

    E2E_PASSWORD=... python manage.py seed_e2e

Brings the database to this state, whatever it was before:
- E2E_USERNAME (default e2e-user), active, with the password from E2E_PASSWORD
  (or E2E_PASSWORD_FILE);
- e2e-colleague, active, without a usable password and in no lab: the e2e test
  adds it as a member, changes its role and removes it again;
- the lab "E2E lab" (code E2E) with the e2e user as its manager;
- e2e-curator, e2e-technician and e2e-viewer, members of the lab in those roles, with the
  same password: the strain tests create strains as the curator and check what a viewer may
  not do, the box grid tests move vials as the technician;
- e2e-manager, active, with the same password and in no lab: made a manager of the lab only
  for the moment it approves a regulated request (here for the one below, in distribution.spec.ts
  for the one that test enters), then removed again, so the e2e user, who did not approve it,
  may confirm its shipment (#89), and stays the lab's only manager (labs.spec.ts refuses to
  remove the last one);
- the lab "E2E other lab" (code E2O), with e2e-outsider as its viewer (the same password) and
  e2e-other-manager as its manager (no usable password): the search test (#76) shows that a
  viewer finds nothing of a lab they are not in;
- a few taxa for the strain form: two genera, a species in each with its NCBI id, and a
  synonym of each species (its basionym), plus an invented genus and species (Testella
  exempli) for the tests of the restriction gates, so no real organism is entered with a
  legal status it does not have. The lab holds no permit, so a VRAT strain is refused there;
- for the deposit tests: a depositor (an invented person at example.org), the lab's MTA
  "STD" version 1, and one deposit accepted as a Bacillus subtilis strain (risk group 1,
  as LPSN and the DSMZ catalogue state for the species), so the strain pages have a row
  before any test adds one. The depositor and the MTA are found by name and code, the
  deposit by its name as received;
- two box types, and a small storage tree that never changes (E2E freezer > Rack 1 > Box 1),
  added by e2e-curator: the keyboard walk and the focus ring checks need a tree to stand on.
  The storage tests build their own freezers, racks and boxes next to it;
- for the vial tests (#16): a second accepted deposit, Testella exempli (invented) with a RAT
  restriction (invented reference), whose two vials lie in E2E freezer > Rack 1 > Box R, so
  their places are masked; the e2e user holds the lab's location grant and reveals them,
  e2e-curator does not. The batch is made once, found by its strain.
- for the check tests (#17): a released batch of the seeded B. subtilis strain, two vials of
  distribution stock, with a passed identity, purity and viability check recorded by
  e2e-technician on its first vial and released by e2e-curator. Made once, found by its status.
- for the distribution tests (#18): two invented strains that may go out, each from a deposit
  whose terms name MTA STD, with a released batch of distribution stock (topped up with a new
  batch when fewer than ten vials are free): Testella exempli e2e supply (risk group 1, no
  restriction) and Mockia vulgaris e2e supply (invented, a dual-use restriction, so a manager
  approves it). Two requesters, invented institutions: E2E Institute of Microbiology, which
  holds an invented § 17a notice and has an invented registered office, and E2E Unnotified
  Laboratory, which holds none and whose registered office is not known. Four
  requests, found by their end use: one a curator may approve, one a manager must approve, one
  blocked by a legal gate (a RAT to the unnotified laboratory), and one approved, ready to ship
  (#88; shipped once, it stays shipped). A fifth, of the dual-use strain, approved by
  e2e-manager and ready to prepare (#89): entered again by a run that finds none approved, as
  the test prepares and confirms it each run.
Strains and storage units the tests created stay: numbers are never reused, and neither a
strain nor a unit is ever deleted.
A second run changes nothing. Every user, lab and membership write goes
through the services with their audit events (channel command, actor kind
system).
"""

from dataclasses import replace
from datetime import date
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from config.env import env_secret, env_str
from cultures.audit.context import audit_context
from cultures.audit.models import ActorKind, Channel
from cultures.biosafety.models import RestrictionKind
from cultures.deposits import seeding as seed_deposits
from cultures.deposits import services as deposits
from cultures.deposits.models import (
    AbsScope,
    Condition,
    Decision,
    Use,
)
from cultures.distribution import seeding
from cultures.distribution import services as distribution
from cultures.distribution.models import DistributionRequest, PermitKind, RequestStatus
from cultures.labs import seeding as seed_labs
from cultures.labs.access import access_for
from cultures.labs.models import Lab
from cultures.labs.permissions import Role
from cultures.lineage import services as lineage
from cultures.lineage.models import (
    Batch,
    BatchStatus,
    CheckKind,
    CheckMethod,
    CheckResult,
    CheckStage,
    Method,
    Passage,
    Purpose,
    Vial,
)
from cultures.lineage.selectors import distributable
from cultures.storage import services as storage
from cultures.storage.models import BoxType, StorageUnit, UnitKind
from cultures.strains import services as strains
from cultures.strains.models import Strain
from cultures.strains.seeding import SeedFacts
from cultures.taxonomy import seeding as seed_taxa
from cultures.taxonomy.models import Rank
from cultures.taxonomy.seeding import SeedTaxon
from cultures.users import seeding as seed_users
from cultures.users.models import User

LAB_NAME, LAB_CODE = "E2E lab", "E2E"
COLLEAGUE = "e2e-colleague"
DEPOSITOR = deposits.ContactInput("E2E Depositor", "e2e.depositor@example.org", "Example street 1")
SEEDED_DEPOSIT = "B. subtilis e2e seed"
REGULATED_DEPOSIT = "Testella exempli e2e regulated"
REGULATED_BOX = "Box R"
CURATOR, TECHNICIAN, VIEWER = "e2e-curator", "e2e-technician", "e2e-viewer"
APPROVER = "e2e-manager"
OTHER_LAB_NAME, OTHER_LAB_CODE = "E2E other lab", "E2O"
OUTSIDER, OTHER_MANAGER = "e2e-outsider", "e2e-other-manager"
SUPPLY = "Testella exempli e2e supply"
REGULATED_SUPPLY = "Mockia vulgaris e2e supply"
INSTITUTE, UNNOTIFIED = "E2E Institute of Microbiology", "E2E Unnotified Laboratory"
READY_TO_PREPARE = "E2E seed: research on a dual-use strain, approved and ready to prepare."
# Fewer free vials than this, and the next run releases another batch: the tests reserve some.
MIN_FREE = 10

# Created when missing, never changed: staff may have edited the seed's taxa. Facts from LPSN
# and NCBI Taxonomy: Bacillus Cohn 1872 (taxid 1386), B. subtilis (Ehrenberg 1835) Cohn 1872
# (1423), basionym Vibrio subtilis Ehrenberg 1835; Escherichia Castellani and Chalmers 1919 (561),
# E. coli (Migula 1895) Castellani and Chalmers 1919 (562), basionym Bacillus coli Migula 1895.
TAXA: tuple[SeedTaxon, ...] = (
    SeedTaxon("Bacillus", "Cohn 1872", Rank.GENUS, ncbi="1386"),
    SeedTaxon(
        "Bacillus subtilis", "(Ehrenberg 1835) Cohn 1872", Rank.SPECIES, "Bacillus", ncbi="1423"
    ),
    SeedTaxon("Vibrio subtilis", "Ehrenberg 1835", Rank.SPECIES, accepted="Bacillus subtilis"),
    SeedTaxon("Escherichia", "Castellani and Chalmers 1919", Rank.GENUS, ncbi="561"),
    SeedTaxon(
        "Escherichia coli",
        "(Migula 1895) Castellani and Chalmers 1919",
        Rank.SPECIES,
        "Escherichia",
        ncbi="562",
    ),
    SeedTaxon("Bacillus coli", "Migula 1895", Rank.SPECIES, accepted="Escherichia coli"),
    # Invented: the e2e tests pair it with restrictions to exercise the gates.
    SeedTaxon("Testella", "", Rank.GENUS),
    SeedTaxon("Testella exempli", "", Rank.SPECIES, "Testella"),
    SeedTaxon("Mockia", "", Rank.GENUS),
    SeedTaxon("Mockia vulgaris", "", Rank.SPECIES, "Mockia"),
)
MTA = seed_deposits.SeedMta(
    "Standard MTA (invented example)",
    "The recipient uses the material for research only. (Invented example.)",
)
# Every use permitted, outside the ABS scope; the supply strains' terms also name MTA STD.
ALL_PERMITTED = seed_deposits.SeedTerms(
    AbsScope.NOT_IN_SCOPE, tuple((Use(use), Decision.PERMIT) for use in Use.values)
)
SEQUENCED = "16S rRNA gene sequence"
# (name, rows, cols), the names seed_dev uses too.
BOX_TYPES = (("81-place cryobox (9 x 9)", 9, 9), ("100-place cryobox (10 x 10)", 10, 10))
FREEZER = "E2E freezer"


class Command(BaseCommand):
    help = "Create or reset the e2e users, lab and membership (development and CI only)."

    def handle(self, *args: Any, **options: Any) -> None:
        if not settings.DEBUG:
            raise CommandError("seed_e2e creates a known password: it runs only with DEBUG on.")
        username = env_str("E2E_USERNAME", "e2e-user")
        password = env_secret("E2E_PASSWORD")
        if not password.strip():
            raise CommandError("E2E_PASSWORD is empty.")
        with audit_context(
            channel=Channel.COMMAND,
            actor_kind=ActorKind.SYSTEM,
            actor_label="command:seed_e2e",
            reason="reset the e2e data",  # reactivating a user needs one
        ):
            user = seed_users.user(username, password)
            colleague = seed_users.user(COLLEAGUE, None)
            lab = seed_labs.lab(LAB_NAME, LAB_CODE)
            seed_labs.member(lab, user, Role.MANAGER)
            seed_labs.no_member(lab, colleague)
            seed_labs.member(lab, seed_users.user(CURATOR, password), Role.CURATOR)
            seed_labs.member(lab, seed_users.user(TECHNICIAN, password), Role.TECHNICIAN)
            seed_labs.member(lab, seed_users.user(VIEWER, password), Role.VIEWER)
            approver = seed_users.user(APPROVER, password)
            seed_labs.no_member(lab, approver)
            other = seed_labs.lab(OTHER_LAB_NAME, OTHER_LAB_CODE)
            seed_labs.member(other, seed_users.user(OTHER_MANAGER, None), Role.MANAGER)
            seed_labs.member(other, seed_users.user(OUTSIDER, password), Role.VIEWER)
            for row in TAXA:
                seed_taxa.taxon(row)
            self._deposit(lab, curator=User.objects.get(username=CURATOR), manager=user)
            for name, rows, cols in BOX_TYPES:
                if not BoxType.objects.filter(name__iexact=name).exists():
                    storage.box_type_create(name=name, rows=rows, cols=cols)
            self._storage(lab, User.objects.get(username=CURATOR))
            self._regulated(lab, curator=User.objects.get(username=CURATOR), manager=user)
            self._released(
                lab,
                curator=User.objects.get(username=CURATOR),
                technician=User.objects.get(username=TECHNICIAN),
            )
            self._distribution(
                lab,
                curator=User.objects.get(username=CURATOR),
                technician=User.objects.get(username=TECHNICIAN),
                approver=approver,
            )
        self.stdout.write(
            f"{username} manages {lab.name}; {CURATOR}, {TECHNICIAN} and {VIEWER} are its"
            " curator, technician and viewer;"
            f" {COLLEAGUE} is in no lab; {len(TAXA)} taxa; a depositor, MTA STD and"
            f" one accepted deposit; {len(BOX_TYPES)} box types; {FREEZER} > Rack 1 > Box 1;"
            f" a regulated strain with two vials in {REGULATED_BOX}, revealed by {username};"
            " a released batch of the seeded strain; two strains that may go out, two"
            f" requesters and five requests, two approved, one of them regulated and approved"
            f" by {APPROVER}, who is in no lab; {OUTSIDER} views {OTHER_LAB_NAME}, which"
            f" {OTHER_MANAGER} manages"
        )

    def _deposit(self, lab: Lab, *, curator: User, manager: User) -> None:
        """The depositor, the MTA and one accepted deposit, created through the services."""
        access = access_for(curator)
        seed_deposits.depositor(access, lab, DEPOSITOR, "Example University")
        seed_deposits.mta_versions(access_for(manager), lab, "STD", (MTA,))
        seed_deposits.deposit(
            access,
            lab,
            seed_deposits.SeedDeposit(
                SEEDED_DEPOSIT,
                DEPOSITOR.name,
                date(2026, 10, 1),
                Condition.INTACT,
                ALL_PERMITTED,
                "accepted",
                strain=SeedFacts("Bacillus subtilis", date(2026, 10, 2), SEQUENCED, risk_group=1),
            ),
        )

    def _storage(self, lab: Lab, curator: User) -> None:
        """The fixed tree, created when missing and never changed."""
        access = access_for(curator)

        def unit(name: str, parent: StorageUnit | None, data: storage.NewUnit) -> StorageUnit:
            found = StorageUnit.objects.filter(lab=lab, parent=parent, name=name).first()
            return found or storage.unit_create(access=access, lab=lab, data=data)

        freezer = unit(
            FREEZER,
            None,
            storage.NewUnit(UnitKind.FREEZER, FREEZER, temperature_c=-20, max_risk_group=1),
        )
        rack = unit("Rack 1", freezer, storage.NewUnit(UnitKind.RACK, "Rack 1", freezer, slot=1))
        box_type = BoxType.objects.get(name=BOX_TYPES[0][0])
        unit("Box 1", rack, storage.NewUnit(UnitKind.BOX, "Box 1", rack, slot=1, box_type=box_type))

    def _regulated(self, lab: Lab, *, curator: User, manager: User) -> None:
        """A regulated strain with two placed vials, and the manager's location grant."""
        access = access_for(curator)
        deposit, _ = seed_deposits.deposit(
            access,
            lab,
            seed_deposits.SeedDeposit(
                REGULATED_DEPOSIT,
                DEPOSITOR.name,
                date(2026, 10, 3),
                Condition.INTACT,
                ALL_PERMITTED,
                "accepted",
                strain=SeedFacts(
                    "Testella exempli",
                    date(2026, 10, 4),
                    SEQUENCED,
                    risk_group=1,
                    restrictions=(
                        strains.RestrictionInput(
                            RestrictionKind.CZ_RAT, "Příloha 2 (invented example)"
                        ),
                    ),
                ),
            ),
        )
        strain = deposit.strain
        assert strain is not None  # noqa: S101 (accepted above)
        rack = StorageUnit.objects.get(lab=lab, parent__name=FREEZER, name="Rack 1")
        box = StorageUnit.objects.filter(lab=lab, parent=rack, name=REGULATED_BOX).first()
        if box is None:
            box = storage.unit_create(
                access=access,
                lab=lab,
                data=storage.NewUnit(
                    UnitKind.BOX,
                    REGULATED_BOX,
                    rack,
                    slot=2,
                    box_type=BoxType.objects.get(name=BOX_TYPES[0][0]),
                ),
            )
        if not Batch.objects.filter(strain=strain).exists():
            lineage.batch_preserve(
                access=access,
                passage=Passage.objects.get(strain=strain, number=0),
                data=lineage.NewBatch(
                    method=Method.CRYO_MINUS80,
                    purpose=Purpose.SEED,
                    preserved_on=date(2026, 10, 5),
                    vial_count=2,
                    cryoprotectant="10 % glycerol",
                    box=box,
                ),
            )
        seed_labs.location_grant(
            lab,
            manager,
            granted_by=manager,
            reason="Keeps the register of the e2e lab (invented example).",
        )

    def _released(self, lab: Lab, *, curator: User, technician: User) -> None:
        """A batch of the seeded strain, checked by the technician and released by the curator."""
        strain = seed_deposits.accepted_strain(lab, SEEDED_DEPOSIT)
        if Batch.objects.filter(strain=strain, status=BatchStatus.RELEASED).exists():
            return
        bench = access_for(technician)
        batch = lineage.batch_preserve(
            access=bench,
            passage=Passage.objects.get(strain=strain, number=0),
            data=lineage.NewBatch(
                method=Method.CRYO_MINUS80,
                purpose=Purpose.DISTRIBUTION,
                preserved_on=date(2026, 10, 3),
                vial_count=2,
                cryoprotectant="10 % glycerol",
            ),
        )
        vial = Vial.objects.get(batch=batch, seq=1)
        for kind, method in (
            (CheckKind.IDENTITY, CheckMethod.SEQUENCING),
            (CheckKind.PURITY, CheckMethod.STREAK_PLATE),
            (CheckKind.VIABILITY, CheckMethod.GROWTH),
        ):
            lineage.check_record(
                access=bench,
                batch=batch,
                data=lineage.NewCheck(
                    kind=kind,
                    stage=CheckStage.AFTER_PRESERVATION,
                    checked_on=date(2026, 10, 5),
                    method=method,
                    result=CheckResult.PASS,
                    vial=vial,
                ),
            )
        lineage.batch_release(
            access=access_for(curator), batch=batch, reason="All three checks passed."
        )

    def _distribution(self, lab: Lab, *, curator: User, technician: User, approver: User) -> None:
        """Strains that may go out, the requesters and the five requests (#18, #88, #89)."""
        access = access_for(curator)
        supply = self._supply(lab, SUPPLY, "Testella exempli", (), curator, technician)
        regulated = self._supply(
            lab,
            REGULATED_SUPPLY,
            "Mockia vulgaris",
            (strains.RestrictionInput(RestrictionKind.DUAL_USE, "1C351.c", act="(EU) 2025/2003"),),
            curator,
            technician,
        )
        rat = seed_deposits.accepted_strain(lab, REGULATED_DEPOSIT)
        scientist = distribution.ContactInput(
            "E2E Scientist", "e2e.scientist@example.org", "Microbiology laboratory\nE2E street 2"
        )
        seeding.requester(
            access,
            lab,
            seeding.SeedRequester(
                institution=INSTITUTE,
                country="CZ",
                seat="E2E street 1, 602 00 Brno (invented example)",
                lab_evidence="The institute's page lists a BSL-2 microbiology laboratory"
                " (invented example).",
                scientist=scientist,
                permits=(
                    seeding.SeedPermit(
                        PermitKind.SUJB_RAT_NOTICE,
                        "SÚJB",
                        "SÚJB/DEV/17a/1 (invented example)",
                        date(2026, 1, 1),
                    ),
                ),
            ),
        )
        seeding.requester(
            access,
            lab,
            seeding.SeedRequester(
                institution=UNNOTIFIED,
                country="SK",
                lab_evidence="A letter of the faculty names its microbiology laboratory"
                " (invented example).",
                scientist=distribution.ContactInput(
                    "E2E Second Scientist", "", "Laboratory 3\nE2E street 3"
                ),
            ),
        )
        for request in (
            seeding.SeedRequest(
                INSTITUTE, "E2E seed: teaching, approvable.", Use.TEACHING, 1, ((supply, 1),)
            ),
            seeding.SeedRequest(
                INSTITUTE,
                "E2E seed: research on a dual-use strain.",
                Use.RESEARCH_NONCOMMERCIAL,
                2,
                ((regulated, 1),),
            ),
            seeding.SeedRequest(
                UNNOTIFIED,
                "E2E seed: a risky agent to an unnotified laboratory.",
                Use.RESEARCH_NONCOMMERCIAL,
                2,
                ((rat, 1),),
            ),
            seeding.SeedRequest(
                INSTITUTE,
                "E2E seed: teaching, approved and ready to ship.",
                Use.TEACHING,
                1,
                ((supply, 1),),
                approve=True,
            ),
        ):
            seeding.request(access, lab, request)
        if DistributionRequest.objects.filter(
            lab=lab, end_use=READY_TO_PREPARE, status=RequestStatus.APPROVED
        ).exists():
            return
        # A manager for this one approval: the lab keeps the e2e user as its only manager.
        seed_labs.member(lab, approver, Role.MANAGER)
        seeding.request(
            access,
            lab,
            seeding.SeedRequest(
                INSTITUTE,
                READY_TO_PREPARE,
                Use.RESEARCH_NONCOMMERCIAL,
                2,
                ((regulated, 1),),
                approve=True,
                reason="Dual-use inside the EU needs no licence (invented example).",
                renew=True,
            ),
            approver=access_for(approver),
        )
        seed_labs.no_member(lab, approver)

    def _supply(  # noqa: PLR0917 (one strain of the seed, spread)
        self,
        lab: Lab,
        name: str,
        taxon: str,
        restrictions: tuple[strains.RestrictionInput, ...],
        curator: User,
        technician: User,
    ) -> Strain:
        """An accepted deposit whose terms name the MTA, with released distribution stock."""
        access = access_for(curator)
        deposit, _ = seed_deposits.deposit(
            access,
            lab,
            seed_deposits.SeedDeposit(
                name,
                DEPOSITOR.name,
                date(2026, 10, 3),
                Condition.INTACT,
                replace(ALL_PERMITTED, mta=("STD", 1)),
                "accepted",
                strain=SeedFacts(
                    taxon, date(2026, 10, 4), SEQUENCED, risk_group=1, restrictions=restrictions
                ),
            ),
        )
        strain = deposit.strain
        assert strain is not None  # noqa: S101 (accepted above)
        free = Vial.objects.filter(
            distributable("batch__"), batch__strain=strain, status="available"
        ).count()
        if free < MIN_FREE:
            self._release_stock(strain, curator, technician)
        return strain

    def _release_stock(self, strain: Strain, curator: User, technician: User) -> None:
        bench = access_for(technician)
        batch = lineage.batch_preserve(
            access=bench,
            passage=Passage.objects.get(strain=strain, number=0),
            data=lineage.NewBatch(
                method=Method.CRYO_MINUS80,
                purpose=Purpose.DISTRIBUTION,
                preserved_on=date(2026, 10, 5),
                vial_count=21,
                cryoprotectant="10 % glycerol",
            ),
        )
        vial = Vial.objects.get(batch=batch, seq=1)
        for kind, method in (
            (CheckKind.IDENTITY, CheckMethod.SEQUENCING),
            (CheckKind.PURITY, CheckMethod.STREAK_PLATE),
            (CheckKind.VIABILITY, CheckMethod.GROWTH),
        ):
            lineage.check_record(
                access=bench,
                batch=batch,
                data=lineage.NewCheck(
                    kind=kind,
                    stage=CheckStage.AFTER_PRESERVATION,
                    checked_on=date(2026, 10, 6),
                    method=method,
                    result=CheckResult.PASS,
                    vial=vial,
                ),
            )
        lineage.batch_release(
            access=access_for(curator), batch=batch, reason="All three checks passed."
        )
