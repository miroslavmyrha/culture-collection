"""The data the Playwright tests use, locally and in CI. Refused unless DEBUG is on.

    E2E_PASSWORD=... python manage.py seed_e2e

Brings the database to this state, whatever it was before:
- E2E_USERNAME (default e2e-user), active, with the password from E2E_PASSWORD
  (or E2E_PASSWORD_FILE);
- e2e-colleague, active, without a usable password and in no lab: the e2e test
  adds it as a member, changes its role and removes it again;
- the lab "E2E lab" (code E2E) with the e2e user as its manager;
- e2e-curator and e2e-viewer, members of the lab in those roles, with the same password:
  the strain tests create strains as the curator and check what a viewer may not do;
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
  The storage tests build their own freezers, racks and boxes next to it.
Strains and storage units the tests created stay: numbers are never reused, and neither a
strain nor a unit is ever deleted.
A second run changes nothing. Every user, lab and membership write goes
through the services with their audit events (channel command, actor kind
system).
"""

from datetime import date
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from config.env import env_secret, env_str
from cultures.audit.context import audit_context
from cultures.audit.models import ActorKind, Channel
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
from cultures.labs import services
from cultures.labs.access import access_for
from cultures.labs.models import Lab, Membership
from cultures.labs.permissions import Role
from cultures.storage import services as storage
from cultures.storage.models import BoxType, StorageUnit, UnitKind
from cultures.taxonomy import services as taxonomy
from cultures.taxonomy.models import IdentifierSystem, Rank, Taxon
from cultures.users import services as users
from cultures.users.models import User

LAB_NAME, LAB_CODE = "E2E lab", "E2E"
COLLEAGUE = "e2e-colleague"
DEPOSITOR = deposits.ContactInput("E2E Depositor", "e2e.depositor@example.org", "Example street 1")
SEEDED_DEPOSIT = "B. subtilis e2e seed"
CURATOR, VIEWER = "e2e-curator", "e2e-viewer"

# (name, authority, rank, parent name, accepted name, NCBI Taxonomy id). Facts from LPSN and
# NCBI Taxonomy: Bacillus Cohn 1872 (taxid 1386), B. subtilis (Ehrenberg 1835) Cohn 1872 (1423),
# basionym Vibrio subtilis Ehrenberg 1835; Escherichia Castellani and Chalmers 1919 (561),
# E. coli (Migula 1895) Castellani and Chalmers 1919 (562), basionym Bacillus coli Migula 1895.
TAXA: tuple[tuple[str, str, Rank, str | None, str | None, str | None], ...] = (
    ("Bacillus", "Cohn 1872", Rank.GENUS, None, None, "1386"),
    ("Bacillus subtilis", "(Ehrenberg 1835) Cohn 1872", Rank.SPECIES, "Bacillus", None, "1423"),
    ("Vibrio subtilis", "Ehrenberg 1835", Rank.SPECIES, None, "Bacillus subtilis", None),
    ("Escherichia", "Castellani and Chalmers 1919", Rank.GENUS, None, None, "561"),
    (
        "Escherichia coli",
        "(Migula 1895) Castellani and Chalmers 1919",
        Rank.SPECIES,
        "Escherichia",
        None,
        "562",
    ),
    ("Bacillus coli", "Migula 1895", Rank.SPECIES, None, "Escherichia coli", None),
    # Invented: the e2e tests pair it with restrictions to exercise the gates.
    ("Testella", "", Rank.GENUS, None, None, None),
    ("Testella exempli", "", Rank.SPECIES, "Testella", None, None),
)
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
            user = self._user(username, password)
            colleague = self._user(COLLEAGUE, None)
            lab = Lab.objects.filter(code=LAB_CODE).first() or services.lab_create(
                name=LAB_NAME, code=LAB_CODE
            )
            self._role(lab, user, Role.MANAGER)
            for membership in Membership.objects.filter(lab=lab, user=colleague):
                services.membership_delete(membership=membership)
            self._role(lab, self._user(CURATOR, password), Role.CURATOR)
            self._role(lab, self._user(VIEWER, password), Role.VIEWER)
            for row in TAXA:
                self._taxon(*row)
            self._deposit(lab, curator=User.objects.get(username=CURATOR), manager=user)
            for name, rows, cols in BOX_TYPES:
                if not BoxType.objects.filter(name__iexact=name).exists():
                    storage.box_type_create(name=name, rows=rows, cols=cols)
            self._storage(lab, User.objects.get(username=CURATOR))
        self.stdout.write(
            f"{username} manages {lab.name}; {CURATOR} and {VIEWER} are its curator and viewer;"
            f" {COLLEAGUE} is in no lab; {len(TAXA)} taxa; a depositor, MTA STD and"
            f" one accepted deposit; {len(BOX_TYPES)} box types; {FREEZER} > Rack 1 > Box 1"
        )

    def _taxon(  # noqa: PLR0917 (one row of TAXA, spread)
        self,
        name: str,
        authority: str,
        rank: Rank,
        parent: str | None,
        accepted: str | None,
        ncbi: str | None,
    ) -> None:
        """Created when missing, never changed: staff may have edited the seed's taxa."""
        if Taxon.objects.filter(name=name, rank=rank).exists():
            return
        taxon = taxonomy.taxon_create(
            fields=taxonomy.TaxonFields(
                name=name,
                authority=authority,
                rank=rank,
                parent=Taxon.objects.get(name=parent) if parent else None,
                accepted=Taxon.objects.get(name=accepted) if accepted else None,
            )
        )
        if ncbi:
            taxonomy.taxon_identifier_add(taxon=taxon, system=IdentifierSystem.NCBI, value=ncbi)

    def _deposit(self, lab: Lab, *, curator: User, manager: User) -> None:
        """The depositor, the MTA and one accepted deposit, created through the services."""
        access = access_for(curator)
        depositor = Depositor.objects.filter(lab=lab, contact__name=DEPOSITOR.name).first()
        if depositor is None:
            depositor = deposits.depositor_create(
                access=access, lab=lab, contact=DEPOSITOR, institution="Example University"
            )
        if not MtaTemplate.objects.filter(lab=lab, code="STD").exists():
            deposits.mta_template_publish(
                access=access_for(manager),
                lab=lab,
                code="STD",
                title="Standard MTA (invented example)",
                text="The recipient uses the material for research only. (Invented example.)",
            )
        if Deposit.objects.filter(lab=lab, name_as_received=SEEDED_DEPOSIT).exists():
            return
        deposit = deposits.deposit_receive(
            access=access,
            lab=lab,
            data=deposits.NewDeposit(
                depositor=depositor,
                received_on=date(2026, 10, 1),
                condition=Condition.INTACT,
                name_as_received=SEEDED_DEPOSIT,
                terms=deposits.TermsInput(
                    abs_scope=AbsScope.NOT_IN_SCOPE,
                    uses=[(Use(use), Decision.PERMIT) for use in Use.values],
                ),
            ),
        )
        deposit = deposits.deposit_start_check(access=access, deposit=deposit)
        deposits.deposit_accept(
            access=access,
            deposit=deposit,
            facts=deposits.StrainFacts(
                taxon=Taxon.objects.get(name="Bacillus subtilis"),
                identified_on=date(2026, 10, 2),
                identification_method="16S rRNA gene sequence",
                risk_group=1,
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

    def _user(self, username: str, password: str | None) -> User:
        """An active user with this password (None: no usable one), changed only where needed."""
        user = User.objects.filter(username=username).first()
        if user is None:
            return users.user_create(username=username, password=password)
        if not user.is_active:
            user = users.user_activate(user=user)
        wrong = (
            user.has_usable_password() if password is None else not user.check_password(password)
        )
        if wrong:
            user = users.user_set_password(user=user, raw_password=password)
        return user

    def _role(self, lab: Lab, user: User, role: Role) -> None:
        membership = Membership.objects.filter(lab=lab, user=user).first()
        if membership is None:
            services.membership_create(lab=lab, user=user, role=role)
        elif membership.role != role:
            services.membership_set_role(membership=membership, role=role)
