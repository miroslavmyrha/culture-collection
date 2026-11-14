"""What the strain workflows share (#234): their errors, their inputs, the checks of a value and
the locks of a row. The workflows are the modules beside this one.
"""

import re
import unicodedata
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from cultures.biosafety import selectors as biosafety_lists
from cultures.biosafety.models import RegulatoryListEntry, RestrictionKind
from cultures.biosafety.policy import permit_today
from cultures.core.exceptions import Conflict, DomainError, NotFound, RuleViolation

from ..models import (
    DUAL_USE_ENTRY,
    EU_ACT,
    PARTIAL_DATE,
    Strain,
    StrainRestriction,
    StrainStatus,
)

STRAIN = "strain"
RISK_GROUP_REFUSED = 4
ACCESSION_REASON = "Identification at accession"
MAX_RESTRICTIONS = 10
# How a refusal names the restriction decree 474/2002 Sb. asks for (#169).
_WHAT: dict[str, str] = {
    RestrictionKind.CZ_VRAT: "highly risky agent (VRAT)",
    RestrictionKind.CZ_RAT: "risky agent (RAT)",
}


class InvalidStrain(DomainError):
    """A field error (400 with the field): the form shows it there."""

    default_code = "invalid"


class RiskGroupRefused(DomainError):
    """A field error on purpose: the form shows it on the risk group."""

    default_code = "risk_group_4_refused"
    default_detail = "The collection does not hold risk group 4 agents."

    def __init__(self, detail: str | None = None, *, attr: str | None = "risk_group") -> None:
        super().__init__(detail, attr=attr)


class DualUseEntryUnknown(DomainError):
    """#169: the reference of a dual-use item is an entry the current reading of Annex I of
    Regulation (EU) 2021/821 holds, and nothing else."""

    default_code = "dual_use_entry_unknown"
    default_detail = "Annex I of Regulation (EU) 2021/821 has no entry with this code."


class RestrictionRequiredByEntry(RuleViolation):
    """#169: an Annex I entry of 1C351.a, 1C351.c, 1C351.e or 1C354 that decree 474/2002 Sb.
    also lists is a VRAT or a RAT, so the strain carries that restriction too."""

    default_code = "restriction_required_by_entry"
    default_detail = "Decree 474/2002 Sb. also lists this agent: record its restriction too."

    def __init__(self, kind: RestrictionKind | None = None, *, attr: str | None = None) -> None:
        self.kind = kind
        detail = (
            None
            if kind is None
            else f"Decree 474/2002 Sb. lists this agent as a {_WHAT[kind]}:"
            " record that restriction too."
        )
        super().__init__(detail, attr=attr)


class RestrictionHeldByDualUse(RuleViolation):
    """#169: a VRAT or RAT restriction does not end while a dual-use entry of the same strain
    names an agent decree 474/2002 Sb. lists as that agent."""

    default_code = "restriction_held_by_dual_use"
    default_detail = (
        "A dual-use entry of this strain names an agent decree 474/2002 Sb. lists: end that"
        " restriction first."
    )


class RiskGroupEntryMismatch(RuleViolation):
    """#169: a risk group that rests on a list entry rests on an entry of the current reading of
    annex 7 of government order 361/2007 Sb. that states that very group."""

    default_code = "risk_group_entry_mismatch"
    default_detail = (
        "This entry of annex 7 of government order 361/2007 Sb. does not state that risk group."
    )


class StrainDeaccessioned(Conflict):
    """#20: deaccessioned is terminal. The strain and its history stay; nothing of it changes."""

    default_code = "strain_deaccessioned"
    default_detail = "This strain has left the collection: it changes no more."


class StrainPending(Conflict):
    default_code = "strain_pending"
    default_detail = "This strain is not in the collection yet."


@dataclass(frozen=True)
class RestrictionInput:
    kind: RestrictionKind
    reference: str
    act: str = ""
    gmo_category: int | None = None


def normalised(text: str) -> str:
    """One space between words, NFC."""
    return " ".join(unicodedata.normalize("NFC", text).split())


# Checks on the input alone: no query, so they run before any lock.


def _check_risk_group(risk_group: int, attr: str = "risk_group") -> None:
    if risk_group == RISK_GROUP_REFUSED:
        raise RiskGroupRefused(attr=attr)
    if risk_group not in (1, 2, 3):
        raise InvalidStrain("A risk group is 1, 2 or 3.", attr=attr)


def _check_not_future(day: date, attr: str) -> None:
    if day > permit_today():
        raise InvalidStrain("This date is in the future.", attr=attr)


def check_partial_date(text: str, attr: str) -> None:
    """YYYY, YYYY-MM or YYYY-MM-DD, a real day, not after today."""
    if not text:
        return
    if not re.fullmatch(PARTIAL_DATE, text):
        raise InvalidStrain("Use YYYY, YYYY-MM or YYYY-MM-DD.", attr=attr)
    parts = [int(p) for p in text.split("-")]
    try:
        first = date(parts[0], parts[1] if len(parts) > 1 else 1, parts[2] if len(parts) > 2 else 1)  # noqa: PLR2004
    except ValueError:
        raise InvalidStrain("This day does not exist.", attr=attr) from None
    if first > permit_today():
        raise InvalidStrain("This date is in the future.", attr=attr)


def check_restriction(restriction: RestrictionInput, prefix: str = "") -> RestrictionInput:
    """The fields a kind needs, and only those. Returns it normalised."""
    reference = normalised(restriction.reference)
    act = normalised(restriction.act)
    if not reference:
        raise InvalidStrain("Enter the list entry.", attr=f"{prefix}reference")
    if restriction.kind == RestrictionKind.DUAL_USE:
        if not re.fullmatch(DUAL_USE_ENTRY, reference):
            raise InvalidStrain(
                "Enter an Annex I entry of 1C351, 1C353 or 1C354, for example 1C351.c.",
                attr=f"{prefix}reference",
            )
        if not re.fullmatch(EU_ACT, act):
            raise InvalidStrain(
                "Enter the act Annex I was read in, for example (EU) 2025/2003.",
                attr=f"{prefix}act",
            )
    elif act:
        raise InvalidStrain("Only a dual-use item names an act.", attr=f"{prefix}act")
    if restriction.kind == RestrictionKind.GMO:
        if restriction.gmo_category not in (1, 2, 3, 4):
            raise InvalidStrain("Choose the category, I to IV.", attr=f"{prefix}gmo_category")
    elif restriction.gmo_category is not None:
        raise InvalidStrain("Only a GMO has a category.", attr=f"{prefix}gmo_category")
    return RestrictionInput(restriction.kind, reference, act, restriction.gmo_category)


def _check_reason(reason: str) -> str:
    """Before any write: the identification row and the event both need one."""
    if not reason.strip():
        raise RuleViolation("A reason is required.", code="reason_required", attr="reason")
    return reason.strip()


def _check_basis(basis: str, attr: str = "basis") -> str:
    """Before any write: every risk group states what it rests on, in words (#174, #169).

    The words are the person's (a list entry, a catalogue, a publication) and are required even
    where the group was read from an official list. Government order 361/2007 Sb., Annex 7,
    Part A: an agent that is not in groups 2 to 4 of the list is not thereby in group 1, so no
    group follows from a list alone.
    """
    if not basis.strip():
        raise RuleViolation(
            "A basis is required: name the list entry or the source.",
            code="basis_required",
            attr=attr,
        )
    return basis.strip()


def _check_basis_entry(
    entry: RegulatoryListEntry | None, risk_group: int, attr: str = "basis_entry"
) -> RegulatoryListEntry | None:
    """#169: where a basis points at a list entry, the entry is one of the current reading of
    annex 7 of government order 361/2007 Sb. that states the very group being recorded.

    No query: the entry was read with its list. `biosafety.selectors.states_risk_group` is the
    one definition, and the guard of migration 0018 asks the same of every writer.
    """
    if entry is not None and not biosafety_lists.states_risk_group(entry, risk_group):
        raise RiskGroupEntryMismatch(attr=attr)
    return entry


def _restriction_values(r: StrainRestriction | RestrictionInput) -> dict[str, Any]:
    return {"kind": r.kind, "reference": r.reference, "act": r.act, "gmo_category": r.gmo_category}


def _entry_of(restriction: RestrictionInput, prefix: str = "") -> RegulatoryListEntry | None:
    """The official list entry the reference names (#169), or None when no list holds it.

    A dual-use item must have one: its reference is an Annex I entry code of Regulation (EU)
    2021/821 and nothing else, and the database refuses a reference the current reading of the
    annex does not hold (migration 0016).
    """
    entry = biosafety_lists.list_entry(restriction.kind, restriction.reference)
    if entry is None and restriction.kind in biosafety_lists.ENTRY_REQUIRED:
        raise DualUseEntryUnknown(attr=f"{prefix}reference")
    return entry


def _require_cz_agent(
    entries: Sequence[RegulatoryListEntry | None], held: Collection[str], prefix: str = ""
) -> None:
    """#169, the last box: a dual-use entry of 1C351.a, 1C351.c, 1C351.e or 1C354 that decree
    474/2002 Sb. also lists needs that restriction on the same strain. `held` is the kinds the
    strain has active, the ones being written included. The deferred trigger of migration 0016
    asks the same at commit, for every writer."""
    for index, entry in enumerate(entries):
        if entry is None:
            continue
        counterpart = biosafety_lists.also_a_cz_agent(entry)
        if counterpart is None or counterpart.restriction_kind in held:
            continue
        raise RestrictionRequiredByEntry(
            RestrictionKind(counterpart.restriction_kind),
            attr=f"{prefix}{index}.reference" if prefix else "reference",
        )


def _active_kinds(strain: Strain) -> set[str]:
    """The restriction kinds the strain has active now. Caller holds the strain's row."""
    return set(
        StrainRestriction.objects.filter(strain=strain, ended_at__isnull=True).values_list(
            "kind", flat=True
        )
    )


def _locked_strain(strain: Strain) -> Strain:
    """The strain locked, in the collection: a deaccessioned one changes no more (#20)."""
    locked = Strain.objects.select_for_update().filter(pk=strain.pk).select_related("lab").first()
    if locked is None:
        raise NotFound
    if locked.status == StrainStatus.DEACCESSIONED:
        raise StrainDeaccessioned
    if locked.status == StrainStatus.PENDING:
        raise StrainPending
    return locked


def _entry_code(entry: RegulatoryListEntry | None) -> str | None:
    """How an event names a list entry (#169): its code in its list, never its row id."""
    return None if entry is None else entry.code
