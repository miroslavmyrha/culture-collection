"""Every write on taxa and their external ids. Staff call these from Django admin and commands.

Taxa are global (ADR 0008, D4): no lab, no lab lock. Each service locks the
taxa it checks a rule on, in pk order, so two staff edits cannot each pass a
check the other one breaks:
- a parent is an accepted taxon of a higher rank than its child, and a
  child's rank stays below its parent's when either changes. Ranks strictly
  fall from parent to child along every edge, so no cycle can form;
- a synonym points at an accepted taxon and has no parent. A taxon with
  children or with synonyms of its own does not become a synonym: staff move
  them first, so no chain of synonyms appears.
Names are compared the way the unique index does (upper() in PostgreSQL),
never with Python's upper(): the two disagree on some letters (django-patterns
traps, ORM and data).
"""

import unicodedata
from dataclasses import dataclass

from django.db import IntegrityError, transaction
from django.db.models import Model

from cultures.audit.context import audited_atomic
from cultures.audit.events import Change, record_event
from cultures.audit.registry import (
    TAXON_CHANGED,
    TAXON_CREATED,
    TAXON_IDENTIFIER_ADDED,
    TAXON_IDENTIFIER_REMOVED,
)
from cultures.core.exceptions import DomainError, NotFound

from .models import (
    IDENTIFIER_ONE_PER_SYSTEM,
    IDENTIFIER_UNIQUE,
    RANK_ORDER,
    TAXON_UNIQUE,
    IdentifierSystem,
    Rank,
    Taxon,
    TaxonIdentifier,
    TaxonStatus,
)

TAXON = "taxon"
TAXON_IDENTIFIER = "taxon_identifier"


class TaxonRuleBroken(DomainError):
    """A field error: the admin form shows it on the field, the API as a 400."""

    default_code = "invalid_taxon"


@dataclass(frozen=True)
class TaxonFields:
    name: str
    authority: str
    rank: Rank
    parent: Taxon | None = None
    accepted: Taxon | None = None  # set: the taxon is a synonym of this one

    @property
    def status(self) -> TaxonStatus:
        return TaxonStatus.SYNONYM if self.accepted is not None else TaxonStatus.ACCEPTED


def normalised(text: str) -> str:
    """One space between words, NFC: "Bacillus  subtilis" and a decomposed letter are one name."""
    return " ".join(unicodedata.normalize("NFC", text).split())


def check_taxon(fields: TaxonFields, *, taxon: Taxon | None = None) -> None:
    """The rules across rows, on the values given. Raises TaxonRuleBroken with the field.

    Callers that write hold locks on `taxon`, its parent and its accepted taxon.
    Forms call it without locks to show the error before saving.
    """
    if not fields.name:
        raise TaxonRuleBroken("Enter the name.", attr="name")
    if fields.accepted is not None:
        if fields.parent is not None:
            raise TaxonRuleBroken(
                "A synonym has no parent: the accepted taxon has one.", attr="parent"
            )
        if fields.accepted.status != TaxonStatus.ACCEPTED:
            raise TaxonRuleBroken(
                "The accepted taxon must be an accepted name, not a synonym.", attr="accepted"
            )
        if taxon is not None and fields.accepted.pk == taxon.pk:
            raise TaxonRuleBroken("A taxon is not its own synonym.", attr="accepted")
    if fields.parent is not None:
        if fields.parent.status != TaxonStatus.ACCEPTED:
            raise TaxonRuleBroken("The parent must be an accepted name.", attr="parent")
        if RANK_ORDER[fields.parent.rank] >= RANK_ORDER[fields.rank]:
            raise TaxonRuleBroken(
                f"The parent ({fields.parent.rank}) must rank above a {fields.rank}.",
                attr="parent",
            )
    if taxon is None or taxon.pk is None:
        return
    children = Taxon.objects.filter(parent=taxon)
    if fields.accepted is not None and children.exists():
        raise TaxonRuleBroken(
            "This taxon has children: move them before making it a synonym.", attr="accepted"
        )
    if fields.accepted is not None and Taxon.objects.filter(accepted=taxon).exists():
        raise TaxonRuleBroken(
            "Other names are synonyms of this taxon: point them at the new accepted name first.",
            attr="accepted",
        )
    below = [RANK_ORDER[rank] for rank in children.values_list("rank", flat=True)]
    if below and min(below) <= RANK_ORDER[fields.rank]:
        raise TaxonRuleBroken(
            f"A child of this taxon ranks at or above {fields.rank}.", attr="rank"
        )


def _lock(*taxa: Taxon | None) -> None:
    """The taxa a rule reads, by pk, so their status and rank cannot change meanwhile."""
    pks = sorted({t.pk for t in taxa if t is not None and t.pk is not None})
    if pks:
        list(Taxon.objects.select_for_update().filter(pk__in=pks).order_by("pk"))


def _fresh(taxon: Taxon | None) -> Taxon | None:
    """The committed row (after the lock), so a rule never reads a stale status."""
    if taxon is None:
        return None
    found = Taxon.objects.filter(pk=taxon.pk).first()
    if found is None:
        raise NotFound
    return found


def _save(obj: Model, errors: dict[str, DomainError]) -> None:
    """The unique constraints are the final arbiter: a check before saving can race."""
    try:
        with transaction.atomic():
            obj.save()
    except IntegrityError as exc:
        diag = getattr(exc.__cause__, "diag", None)
        error = errors.get(str(getattr(diag, "constraint_name", "")))
        if error is not None:
            raise error from exc
        raise


def _duplicate() -> dict[str, DomainError]:
    return {
        TAXON_UNIQUE: TaxonRuleBroken(
            "A taxon with this name, authority and rank exists already.", code="unique", attr="name"
        )
    }


def _id(taxon: Taxon | None) -> str | None:
    return str(taxon.public_id) if taxon is not None else None


def _values(taxon: Taxon) -> dict[str, str | None]:
    return {
        "name": taxon.name,
        "authority": taxon.authority,
        "rank": taxon.rank,
        "status": taxon.status,
        "parent": _id(taxon.parent),
        "accepted": _id(taxon.accepted),
    }


def taxon_create(*, fields: TaxonFields) -> Taxon:
    with audited_atomic():
        _lock(fields.parent, fields.accepted)
        fields = TaxonFields(
            name=normalised(fields.name),
            authority=normalised(fields.authority),
            rank=fields.rank,
            parent=_fresh(fields.parent),
            accepted=_fresh(fields.accepted),
        )
        check_taxon(fields)
        taxon = Taxon(
            name=fields.name,
            authority=fields.authority,
            rank=fields.rank,
            parent=fields.parent,
            status=fields.status,
            accepted=fields.accepted,
        )
        _save(taxon, _duplicate())
        record_event(
            TAXON_CREATED,
            Change(TAXON, taxon.public_id, {k: [None, v] for k, v in _values(taxon).items()}),
        )
    return taxon


def taxon_update(*, taxon: Taxon, fields: TaxonFields) -> Taxon:
    """Changes name, authority, rank, parent and synonymy. Nothing to change: no event."""
    with audited_atomic():
        _lock(taxon, fields.parent, fields.accepted)
        locked = _fresh(taxon)
        assert locked is not None  # noqa: S101 (_fresh raised NotFound otherwise)
        fields = TaxonFields(
            name=normalised(fields.name),
            authority=normalised(fields.authority),
            rank=fields.rank,
            parent=_fresh(fields.parent),
            accepted=_fresh(fields.accepted),
        )
        check_taxon(fields, taxon=locked)
        before = _values(locked)
        locked.name, locked.authority, locked.rank = fields.name, fields.authority, fields.rank
        locked.parent, locked.accepted, locked.status = (
            fields.parent,
            fields.accepted,
            fields.status,
        )
        after = _values(locked)
        changes = {k: [before[k], after[k]] for k in before if before[k] != after[k]}
        if not changes:
            return locked
        _save(locked, _duplicate())
        record_event(TAXON_CHANGED, Change(TAXON, locked.public_id, changes))
    return locked


def taxon_identifier_add(*, taxon: Taxon, system: IdentifierSystem, value: str) -> TaxonIdentifier:
    with audited_atomic():
        _lock(taxon)
        identifier = TaxonIdentifier(taxon=taxon, system=system, value=value.strip())
        _save(
            identifier,
            {
                IDENTIFIER_UNIQUE: TaxonRuleBroken(
                    "Another taxon has this id.", code="unique", attr="value"
                ),
                IDENTIFIER_ONE_PER_SYSTEM: TaxonRuleBroken(
                    "This taxon has an id in this system already.", code="unique", attr="system"
                ),
            },
        )
        record_event(
            TAXON_IDENTIFIER_ADDED,
            Change(
                TAXON_IDENTIFIER,
                identifier.public_id,
                {
                    "taxon": [None, str(taxon.public_id)],
                    "system": [None, system],
                    "value": [None, identifier.value],
                },
            ),
        )
    return identifier


def taxon_identifier_remove(*, identifier: TaxonIdentifier) -> None:
    with audited_atomic():
        _lock(identifier.taxon)
        locked = TaxonIdentifier.objects.select_for_update().filter(pk=identifier.pk).first()
        if locked is None:
            raise NotFound
        public_id, taxon_id = locked.public_id, str(identifier.taxon.public_id)
        system, value = locked.system, locked.value
        locked.delete()
        record_event(
            TAXON_IDENTIFIER_REMOVED,
            Change(
                TAXON_IDENTIFIER,
                public_id,
                {"taxon": [taxon_id, None], "system": [system, None], "value": [value, None]},
            ),
        )
