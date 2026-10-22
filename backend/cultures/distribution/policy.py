"""The gates on a request (s10, section 8, limited to part A's scope): one function, run at
approval and again at shipment on the ship day (#88), because permits expire in between. At
shipment the stock gate reads the vials the approval reserved, not the free ones.

Scope (decided by the owner, ADR 0009 amendment of 2026-10-20): Category B (UN 3373) and exempt
shipments to member states of the EU. Nothing leaves the EU: a destination outside it is
refused, for regulated strains because their export needs licences this app does not record,
for the others until export is built. Category A is not shipped.

Every finding has a stable code and a sentence for a person. A blocker stops the approval and
has no override: the legal gates (a recipient permit, a Letter of Authority with quantity left,
a contained-use authorisation, a § 17a notice) and the collection's own (terms, MTA, stock,
containment). A manager finding lets a manager approve with a reason (ADR 0009: a regulated line
needs a manager). What may go out is only lineage.selectors.distributable().

Reads only: the caller holds the lab lock when it acts on the answer.
"""

import re
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from django.db.models import Count, Sum

from cultures.biosafety.models import RestrictionKind
from cultures.biosafety.policy import valid_on
from cultures.deposits.models import AbsScope, Decision, DepositTerms, TermsUse, Use
from cultures.lineage.models import Vial, VialStatus
from cultures.lineage.selectors import distributable
from cultures.strains.models import Strain, StrainRestriction
from cultures.strains.selectors import regulating_restrictions
from cultures.taxonomy.models import Taxon

from .models import (
    DistributionRequest,
    LinePermit,
    MtaAcceptance,
    PermitKind,
    RecipientPermit,
    RequestLine,
    RequestStatus,
    VialReservation,
)

# The member states of the European Union, ISO 3166-1 alpha-2 (27, read on
# https://european-union.europa.eu/principles-countries-history/eu-countries_en, 2026-10-20).
# Their outermost regions with codes of their own (GF, RE, ...) are not listed: such a request
# is refused, the safe side, until someone needs it.
EU_MEMBER_STATES: frozenset[str] = frozenset(
    {
        "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR", "HU", "IE",
        "IT", "LV", "LT", "LU", "MT", "NL", "PL", "PT", "RO", "SK", "SI", "ES", "SE",
    }
)  # fmt: skip
# Annex IV Part II of 2021/821: within the EU only ricin and saxitoxin need a transfer licence.
TRANSFER_LICENCE_ENTRIES = ("1C351.d.4", "1C351.d.5")
# Requests whose approval counts against a Letter of Authority, also once shipped.
COUNTING = (RequestStatus.APPROVED, RequestStatus.SHIPPED)


class Severity(StrEnum):
    BLOCK = "block"  # no approval, no override
    MANAGER = "manager"  # a manager approves with a reason


@dataclass(frozen=True)
class Finding:
    code: str
    severity: Severity
    sentence: str
    line: RequestLine | None = None


@dataclass(frozen=True)
class Evaluation:
    findings: tuple[Finding, ...]
    # The permits each line passed its gates with: written as LinePermit at approval.
    used: tuple[tuple[RequestLine, RecipientPermit], ...]

    @property
    def blockers(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == Severity.BLOCK]

    @property
    def needs_manager(self) -> bool:
        return any(f.severity == Severity.MANAGER for f in self.findings)


def in_eu(country: str) -> bool:
    return country in EU_MEMBER_STATES


def destination_finding(country: str, *, regulated: bool) -> Finding | None:
    """The destination gate, also asked when a request is entered."""
    if in_eu(country):
        return None
    if regulated:
        return Finding(
            "export_of_regulated_strain",
            Severity.BLOCK,
            f"The destination ({country}) is outside the EU: regulated strains are not exported"
            " from this collection.",
        )
    return Finding(
        "export_not_supported",
        Severity.BLOCK,
        f"The destination ({country}) is outside the EU: this collection does not ship outside"
        " the EU yet.",
    )


def names(covers: str, taxon: Taxon) -> bool:
    """The permit names the taxon, or the accepted name of a synonym, as whole words, ignoring
    case and spacing. A permit that names an older name blocks: the safe side."""
    text = " ".join(covers.split()).casefold()
    wanted = {taxon.name} | ({taxon.accepted.name} if taxon.accepted is not None else set())
    return any(
        re.search(rf"(?<!\w){re.escape(' '.join(name.split()).casefold())}(?!\w)", text)
        for name in wanted
    )


@dataclass
class _Facts:
    """What the gates read, in a fixed number of queries whatever the number of lines."""

    restrictions: dict[int, list[StrainRestriction]]
    decisions: dict[int, str]
    active_terms: set[int]
    mat_uses: dict[int, list[str]]
    abs_scope: dict[int, str]
    accepted_mtas: set[int]
    permits: list[RecipientPermit]
    loa_used: dict[int, tuple[int, int]]
    available: dict[int, int]
    # At shipment: per line, its open reservations whose vial may still go out.
    reserved: dict[int, int]


def _facts(request: DistributionRequest, lines: list[RequestLine], day: date) -> _Facts:
    strain_ids = [line.strain_id for line in lines]
    terms_ids = [line.terms_id for line in lines]
    restrictions: dict[int, list[StrainRestriction]] = defaultdict(list)
    for row in regulating_restrictions().filter(strain_id__in=strain_ids).order_by("kind", "pk"):
        restrictions[row.strain_id].append(row)
    terms = DepositTerms.objects.filter(pk__in=terms_ids).values_list(
        "pk", "is_active", "abs_scope", "mat_uses"
    )
    permits = list(
        RecipientPermit.objects.filter(valid_on(day), requester_id=request.requester_id).order_by(
            "valid_from", "pk"
        )
    )
    loa = [p.pk for p in permits if p.kind == PermitKind.PLANT_HEALTH_LOA]
    usage = (
        LinePermit.objects.filter(permit_id__in=loa, line__request__status__in=COUNTING)
        .exclude(line__request=request)
        .values("permit_id")
        .annotate(quantity=Sum("line__quantity"), sendings=Count("line__request", distinct=True))
    )
    available = (
        Vial.objects.filter(
            distributable("batch__"),
            lab_id=request.lab_id,
            status=VialStatus.AVAILABLE,
            batch__strain_id__in=strain_ids,
        )
        .values("batch__strain_id")
        .annotate(n=Count("pk"))
    )
    return _Facts(
        restrictions=restrictions,
        decisions=dict(
            TermsUse.objects.filter(terms_id__in=terms_ids, use=request.use).values_list(
                "terms_id", "decision"
            )
        ),
        active_terms={pk for pk, active, _, _ in terms if active},
        mat_uses={pk: uses for pk, _, _, uses in terms},
        abs_scope={pk: scope for pk, _, scope, _ in terms},
        accepted_mtas=set(
            MtaAcceptance.objects.filter(request=request, authorised_signatory=True).values_list(
                "mta_id", flat=True
            )
        ),
        permits=permits,
        loa_used={row["permit_id"]: (row["quantity"], row["sendings"]) for row in usage},
        available={row["batch__strain_id"]: row["n"] for row in available},
        reserved=_reserved(request) if request.status == RequestStatus.APPROVED else {},
    )


def _reserved(request: DistributionRequest) -> dict[int, int]:
    rows = (
        VialReservation.objects.filter(
            distributable("vial__batch__"),
            line__request=request,
            ended_at__isnull=True,
            vial__status=VialStatus.RESERVED,
        )
        .values("line_id")
        .annotate(n=Count("pk"))
    )
    return {row["line_id"]: row["n"] for row in rows}


def _naming(
    permits: Iterable[RecipientPermit], kinds: set[PermitKind], taxon: Taxon
) -> list[RecipientPermit]:
    return [p for p in permits if p.kind in kinds and names(p.covers, taxon)]


def evaluate(request: DistributionRequest, day: date) -> Evaluation:
    """Every finding on the request, request-wide first, then line by line in their order."""
    lines = list(request.lines.select_related("strain__taxon__accepted", "mta").order_by("pk"))
    facts = _facts(request, lines, day)
    findings: list[Finding] = []
    used: list[tuple[RequestLine, RecipientPermit]] = []
    regulated = any(facts.restrictions.get(line.strain_id) for line in lines)
    destination = destination_finding(request.destination_country, regulated=regulated)
    if destination is not None:
        findings.append(destination)
    if request.requester.contact.erased_at is not None:
        findings.append(
            Finding(
                "contact_erased",
                Severity.BLOCK,
                "The requester's contact was erased: there is no responsible scientist and no"
                " delivery address.",
            )
        )
    # A Letter of Authority used by two lines of this request counts once as a sending.
    planned: dict[int, int] = defaultdict(int)
    for line in lines:
        check = _LineCheck(request, line, facts, planned)
        check.run()
        findings.extend(check.found)
        used.extend((line, permit) for permit in check.used)
    return Evaluation(tuple(findings), tuple(used))


class _LineCheck:
    """The gates of one line. Each group is a method; findings and used permits collect here."""

    def __init__(
        self,
        request: DistributionRequest,
        line: RequestLine,
        facts: _Facts,
        planned: dict[int, int],
    ) -> None:
        self.request, self.line, self.facts, self.planned = request, line, facts, planned
        self.strain: Strain = line.strain
        self.name = str(self.strain.accession_number)
        self.found: list[Finding] = []
        self.used: list[RecipientPermit] = []

    def block(self, code: str, sentence: str) -> None:
        self.found.append(Finding(code, Severity.BLOCK, sentence, self.line))

    def manager(self, code: str, sentence: str) -> None:
        self.found.append(Finding(code, Severity.MANAGER, sentence, self.line))

    def run(self) -> None:
        self.stock()
        self.terms()
        self.mta()
        self.biosafety()
        restrictions = self.facts.restrictions.get(self.strain.pk, [])
        if restrictions:
            kinds = ", ".join(sorted({r.kind for r in restrictions}))
            self.manager("regulated", f"{self.name} is regulated ({kinds}): a manager approves it.")
        for restriction in restrictions:
            self.restriction(restriction)

    def stock(self) -> None:
        if self.request.status == RequestStatus.APPROVED:
            held = self.facts.reserved.get(self.line.pk, 0)
            if held < self.line.quantity:
                self.block(
                    "reserved_vials_not_distributable",
                    f"{self.name}: {held} of its {self.line.quantity} reserved vials may still go"
                    " out. A batch was held or exhausted, or the strain stopped supplying.",
                )
            return
        available = self.facts.available.get(self.strain.pk, 0)
        if available < self.line.quantity:
            self.block(
                "not_enough_vials",
                f"{self.name}: {available} vials may go out now, the line asks for"
                f" {self.line.quantity}.",
            )

    def terms(self) -> None:
        terms_id = self.line.terms_id
        if terms_id not in self.facts.active_terms:
            self.block(
                "terms_replaced",
                f"{self.name}: its terms changed after the request was entered. Cancel the"
                " request and enter it again under the new terms.",
            )
        use = Use(self.request.use).label.lower()
        scope = self.facts.abs_scope.get(terms_id)
        if scope == AbsScope.UNKNOWN:
            self.block(
                "abs_scope_unknown",
                f"{self.name}: whether the ABS regulation applies is unknown. Nothing goes out"
                " until the terms say.",
            )
        if scope == AbsScope.IN_SCOPE and self.request.use not in self.facts.mat_uses.get(
            terms_id, []
        ):
            self.block(
                "abs_use_not_covered", f"{self.name}: the mutually agreed terms do not cover {use}."
            )
        decision = self.facts.decisions.get(terms_id)
        if decision == Decision.DENY:
            self.block("use_denied", f"{self.name}: the depositor's terms do not permit {use}.")
        elif decision == Decision.ON_REQUEST:
            self.manager(
                "use_on_request",
                f"{self.name}: the terms allow {use} only on request to the depositor. A manager"
                " approves once the depositor agreed, and says so in the reason.",
            )

    def mta(self) -> None:
        mta = self.line.mta
        if mta is None:
            self.block(
                "mta_missing",
                f"{self.name}: its terms name no MTA, and nothing goes out without one.",
            )
        elif mta.pk not in self.facts.accepted_mtas:
            self.block(
                "mta_not_accepted",
                f"{self.name}: no acceptance of MTA {mta.code} version {mta.version} signed by"
                " someone who may bind the requester is recorded.",
            )

    def biosafety(self) -> None:
        group = self.strain.risk_group
        if self.request.containment_level < group:
            self.block(
                "containment_too_low",
                f"{self.name} is risk group {group}; the requester declares containment level"
                f" {self.request.containment_level}.",
            )
        if group >= 3:  # noqa: PLR2004 (risk group 3, Directive 2000/54/EC)
            self.manager(
                "category_a_possible",
                f"{self.name} is risk group 3: its culture may be Category A (UN 2814), which"
                " this collection does not ship. The shipper classifies it.",
            )
        if group < 2:  # noqa: PLR2004
            return
        permits = [
            p
            for p in self.facts.permits
            if p.kind == PermitKind.PATHOGEN_WORK_PERMIT
            and p.risk_group is not None
            and p.risk_group >= group
        ]
        if permits:
            self.used.append(permits[0])
        else:
            self.manager(
                "work_permit_missing",
                f"{self.name} is risk group {group} and the requester shows no permit to work"
                " with it. A manager approves when the destination needs none.",
            )

    def restriction(self, restriction: StrainRestriction) -> None:
        taxon = self.strain.taxon
        kind = restriction.kind
        if kind == RestrictionKind.CZ_VRAT:
            # 281/2002 Sb., § 13 h): only to a permit holder, unless SÚJB decided otherwise.
            self.need(
                _naming(
                    self.facts.permits, {PermitKind.SUJB_VRAT, PermitKind.SUJB_EXCEPTION}, taxon
                ),
                "vrat_permit_missing",
                f"{self.name} is a highly risky agent: the requester shows no valid SÚJB permit"
                f" or exception that names {taxon.name}.",
            )
        elif kind == RestrictionKind.CZ_RAT:
            # § 17a(1): the recipient notified SÚJB; SÚJB asks senders to supply only them.
            self.need(
                [p for p in self.facts.permits if p.kind == PermitKind.SUJB_RAT_NOTICE],
                "rat_notice_missing",
                f"{self.name} is a risky agent: the requester shows no reference of its notice"
                " to SÚJB (§ 17a).",
            )
        elif kind == RestrictionKind.DUAL_USE:
            if restriction.reference.startswith(TRANSFER_LICENCE_ENTRIES):
                self.block(
                    "transfer_licence_required",
                    f"{self.name} ({restriction.reference}) needs a licence for a transfer"
                    " within the EU, which this collection does not hold.",
                )
        elif kind == RestrictionKind.QUARANTINE_PEST:
            self.letter_of_authority()
        elif kind == RestrictionKind.GMO:
            category = restriction.gmo_category or 0
            self.need(
                [
                    p
                    for p in self.facts.permits
                    if p.kind == PermitKind.GMO_CONTAINED_USE
                    and p.gmo_category is not None
                    and p.gmo_category >= category
                ],
                "gmo_authorisation_missing",
                f"{self.name} is a GMO of category {category}: the requester shows no"
                f" authorisation for contained use of category {category} or higher"
                " (act 78/2004 Sb.).",
            )

    def need(self, permits: list[RecipientPermit], code: str, sentence: str) -> None:
        if permits:
            self.used.append(permits[0])
        else:
            self.block(code, sentence)

    def letter_of_authority(self) -> None:
        """2019/829 Art. 6: a letter naming the pest, in date, with quantity and sendings left."""
        taxon = self.strain.taxon
        letters = _naming(self.facts.permits, {PermitKind.PLANT_HEALTH_LOA}, taxon)
        if not letters:
            self.block(
                "loa_missing",
                f"{self.name} is a quarantine pest: the requester shows no valid Letter of"
                f" Authority that names {taxon.name}.",
            )
            return
        for letter in letters:
            quantity, sendings = self.facts.loa_used.get(letter.pk, (0, 0))
            allowed_quantity = letter.quantity_allowed or 0
            allowed_sendings = letter.sendings_allowed or 0
            if (
                quantity + self.planned[letter.pk] + self.line.quantity <= allowed_quantity
                and sendings < allowed_sendings
            ):
                self.planned[letter.pk] += self.line.quantity
                self.used.append(letter)
                return
        self.block(
            "loa_exhausted",
            f"{self.name}: no Letter of Authority of the requester has the quantity or a sending"
            " left for this line.",
        )


def gate_codes() -> dict[str, Severity]:
    """Every code the policy may answer, for the tests and the documentation."""
    return dict(GATES)


GATES: tuple[tuple[str, Severity], ...] = (
    ("export_of_regulated_strain", Severity.BLOCK),
    ("export_not_supported", Severity.BLOCK),
    ("contact_erased", Severity.BLOCK),
    ("not_enough_vials", Severity.BLOCK),
    ("reserved_vials_not_distributable", Severity.BLOCK),
    ("terms_replaced", Severity.BLOCK),
    ("abs_scope_unknown", Severity.BLOCK),
    ("abs_use_not_covered", Severity.BLOCK),
    ("use_denied", Severity.BLOCK),
    ("use_on_request", Severity.MANAGER),
    ("mta_missing", Severity.BLOCK),
    ("mta_not_accepted", Severity.BLOCK),
    ("containment_too_low", Severity.BLOCK),
    ("category_a_possible", Severity.MANAGER),
    ("work_permit_missing", Severity.MANAGER),
    ("regulated", Severity.MANAGER),
    ("vrat_permit_missing", Severity.BLOCK),
    ("rat_notice_missing", Severity.BLOCK),
    ("transfer_licence_required", Severity.BLOCK),
    ("loa_missing", Severity.BLOCK),
    ("loa_exhausted", Severity.BLOCK),
    ("gmo_authorisation_missing", Severity.BLOCK),
)
