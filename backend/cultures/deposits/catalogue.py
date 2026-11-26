"""Catalogue import (#70): an existing catalogue enters the collection from one CSV file.

Each row becomes a deposit from a known depositor, received, checked and accepted through the
deposit services, so the strain gets its number, its biosafety gates and its passage 0 exactly
as a strain accepted by hand, and the distribution gates read its terms unchanged. Terms the
file does not state are "on request" for every use and ABS scope "unknown" until a curator
fills them in: nothing goes out without a decision.

A check runs every row in its own savepoint and rolls the whole file back: it reports every
row error and writes nothing. The import takes the same file, whose SHA-256 the check returned,
and applies all rows in one transaction or none.

A number of the lab's own "<code> <seq>" form is kept and the counter moves past it; any other
form is kept as the strain's former number and the strain takes the next number. Unknown
references (depositor, taxon, MTA, list entries) are errors, never created on the fly.
"""

import csv
import hashlib
import io
import re
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from typing import Any, cast

from django.db import transaction
from django.db.models.functions import Upper

from cultures.audit.context import audited_atomic
from cultures.audit.events import Change, record_event
from cultures.audit.registry import CATALOGUE_IMPORTED
from cultures.biosafety import selectors as biosafety_lists
from cultures.biosafety.models import RegulatoryListEntry, RestrictionKind
from cultures.core.exceptions import DomainError, RuleViolation
from cultures.labs.access import Access
from cultures.labs.locks import lock_lab, require_committed
from cultures.labs.models import Lab
from cultures.labs.permissions import Perm
from cultures.strains import services as strains
from cultures.strains.models import Pathogenicity, Strain
from cultures.taxonomy.models import Taxon

from . import services
from .models import AbsScope, Condition, Decision, Depositor, MtaTemplate, Use

# The columns of the template, in its order. Starred in the template's description: required.
COLUMNS = (
    "accession_number",
    "name_as_received",
    "depositor",
    "depositor_institution",
    "received_on",
    "condition",
    "note",
    "taxon",
    "taxon_authority",
    "identified_on",
    "identification_method",
    "risk_group",
    "risk_group_basis",
    "risk_group_entry",
    "animal_pathogenicity",
    "plant_pathogenicity",
    "isolation_source",
    "country_of_origin",
    "isolation_date",
    "restrictions",
    "abs_scope",
    "uses",
    "mta",
)
REQUIRED = (
    "name_as_received",
    "depositor",
    "received_on",
    "taxon",
    "identified_on",
    "identification_method",
    "risk_group",
    "risk_group_basis",
)
MAX_BYTES = 2 * 1024 * 1024
MAX_ROWS = 2000
IMPORTED = "Imported from the former catalogue."
LAB = "lab"

# What each column holds, for the template's second row and the README.
EXAMPLE = {
    "accession_number": "MYC 12",
    "name_as_received": "Mockia vulgaris strain 7",
    "depositor": "Jana Example",
    "depositor_institution": "Example University",
    "received_on": "2019-05-14",
    "condition": "",
    "note": "Received date estimated from the old card.",
    "taxon": "Mockia vulgaris",
    "taxon_authority": "",
    "identified_on": "2019-06-01",
    "identification_method": "16S rRNA gene sequence",
    "risk_group": "1",
    "risk_group_basis": "Invented example: the lab's own assessment.",
    "risk_group_entry": "",
    "animal_pathogenicity": "unknown",
    "plant_pathogenicity": "unknown",
    "isolation_source": "Forest soil",
    "country_of_origin": "CZ",
    "isolation_date": "2018",
    "restrictions": "",
    "abs_scope": "",
    "uses": "",
    "mta": "",
}

# A service's field names, as the file calls them.
_COLUMN_OF = {
    "risk_group_basis_entry": "risk_group_entry",
    "condition_note": "note",
    "terms": "uses",
}
_COLUMN_OF_CODE = {"accession_taken": "accession_number"}
_LAB_NUMBER = r"^{code}\s+(\d{{1,9}})$"


class CatalogueRefused(RuleViolation):
    default_code = "catalogue_refused"
    default_detail = "This file cannot be imported."


class CatalogueChanged(RuleViolation):
    default_code = "catalogue_changed"
    default_detail = "The file is not the one that was checked. Check it again, then import it."


class CatalogueHasErrors(RuleViolation):
    default_code = "catalogue_has_errors"
    default_detail = "Some rows have errors: nothing was imported."

    def __init__(self, errors: list["RowError"] | None = None) -> None:
        super().__init__()
        self.errors = errors or []


class _RowFault(Exception):
    def __init__(self, column: str, message: str) -> None:
        super().__init__(message)
        self.column, self.message = column, message


@dataclass(frozen=True)
class RowError:
    row: int  # the line of the file, the header being line 1
    column: str
    message: str


@dataclass(frozen=True)
class Checked:
    sha256: str
    rows: int
    errors: list[RowError]


@dataclass(frozen=True)
class _Row:
    line: int
    values: dict[str, str]


def template() -> str:
    """The file to fill in: the header and one invented example row."""
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(COLUMNS)
    writer.writerow([EXAMPLE[c] for c in COLUMNS])
    return out.getvalue()


def sha256_of(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


# Reading the file: no query.


def _text(content: bytes) -> str:
    if len(content) > MAX_BYTES:
        raise CatalogueRefused(f"The file is larger than {MAX_BYTES // (1024 * 1024)} MB.")
    try:
        return content.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise CatalogueRefused("Save the file as CSV UTF-8.") from None


def _cells(raw: dict[str | None, Any]) -> dict[str, str]:
    """The named cells, trimmed; a cell past the header (key None) or missing (None) is dropped
    or empty."""
    return {k.strip(): (v or "").strip() for k, v in raw.items() if isinstance(k, str)}


def read_rows(content: bytes) -> list[_Row]:
    """The rows of a UTF-8 CSV file with the template's header, or CatalogueRefused."""
    reader = csv.DictReader(io.StringIO(_text(content)))
    if sorted(name.strip() for name in reader.fieldnames or []) != sorted(COLUMNS):
        raise CatalogueRefused("Use the columns of the template, each once.")
    rows = [_Row(reader.line_num, cells) for cells in map(_cells, reader) if any(cells.values())]
    if not rows:
        raise CatalogueRefused("The file has no rows.")
    if len(rows) > MAX_ROWS:
        raise CatalogueRefused(f"At most {MAX_ROWS} rows in one file.")
    return rows


# One row to the services' inputs: queries, no writes.


def _required(row: _Row) -> None:
    for column in REQUIRED:
        if not row.values[column]:
            raise _RowFault(column, "Required.")


def _day(row: _Row, column: str) -> date:
    try:
        return date.fromisoformat(row.values[column])
    except ValueError:
        raise _RowFault(column, "Write the date as YYYY-MM-DD.") from None


def _choice[T: str](row: _Row, column: str, choices: type[T], default: T) -> T:
    value = row.values[column]
    if not value:
        return default
    allowed = getattr(choices, "values", [])
    if value not in allowed:
        raise _RowFault(column, f"One of: {', '.join(allowed)}.")
    return choices(value)


def _one[T](found: list[T], column: str, what: str) -> T:
    if not found:
        raise _RowFault(column, f"No {what} has this name here.")
    if len(found) > 1:
        raise _RowFault(column, f"More than one {what} has this name: say which.")
    return found[0]


def _depositor(lab: Lab, row: _Row) -> Depositor:
    found = Depositor.objects.filter(
        lab=lab, contact__name__iexact=row.values["depositor"], contact__erased_at__isnull=True
    )
    if row.values["depositor_institution"]:
        found = found.filter(institution__iexact=row.values["depositor_institution"])
    return _one(list(found[:2]), "depositor", "depositor")


def _taxon(row: _Row) -> Taxon:
    found = Taxon.objects.annotate(upper=Upper("name")).filter(upper=row.values["taxon"].upper())
    if row.values["taxon_authority"]:
        found = found.filter(authority__iexact=row.values["taxon_authority"])
    return _one(list(found[:2]), "taxon", "taxon")


def _mta(lab: Lab, row: _Row) -> MtaTemplate | None:
    code = row.values["mta"]
    if not code:
        return None
    found = MtaTemplate.objects.filter(lab=lab, code__iexact=code).order_by("-version").first()
    if found is None:
        raise _RowFault("mta", "No MTA of the lab has this code.")
    return found


def _risk_group(row: _Row) -> int:
    value = row.values["risk_group"]
    if value not in ("1", "2", "3", "4"):
        raise _RowFault("risk_group", "A risk group of 1 to 4.")
    return int(value)


def _risk_group_entry(row: _Row) -> RegulatoryListEntry | None:
    code = row.values["risk_group_entry"]
    if not code:
        return None
    found = biosafety_lists.risk_group_entries().filter(code=code).first()
    if found is None:
        raise _RowFault("risk_group_entry", "No entry of annex 7 of 361/2007 Sb. has this code.")
    return found


def _restriction(text: str) -> strains.RestrictionInput:
    """kind|reference, a dual-use item with |act, a GMO with |act|category (an empty act)."""
    kind, reference, act, category = ([p.strip() for p in text.split("|")] + ["", "", ""])[:4]
    if kind not in RestrictionKind.values:
        raise _RowFault("restrictions", f"A kind of: {', '.join(RestrictionKind.values)}.")
    restriction = strains.RestrictionInput(
        kind=RestrictionKind(kind),
        reference=reference,
        act=act,
        gmo_category=int(category) if category.isdigit() else None,
    )
    # #70: a reference names an entry of the kind's current list, never words of one's own.
    if kind != RestrictionKind.GMO and biosafety_lists.list_entry(kind, reference) is None:
        raise _RowFault("restrictions", f"No entry of the {kind} list has the code {reference}.")
    return restriction


def _restrictions(row: _Row) -> tuple[strains.RestrictionInput, ...]:
    text = row.values["restrictions"]
    return tuple(_restriction(item) for item in text.split(";") if item.strip()) if text else ()


def _uses(row: _Row) -> list[tuple[Use, Decision]]:
    """Every use, "on request" unless the file decides it: kind=decision; kind=decision."""
    decided: dict[str, str] = {}
    for item in filter(None, (i.strip() for i in row.values["uses"].split(";"))):
        use, _, decision = (p.strip() for p in item.partition("="))
        if use not in Use.values or decision not in Decision.values:
            raise _RowFault("uses", "Write use=decision; for example teaching=permit.")
        decided[use] = decision
    return [(Use(u), Decision(decided.get(u, Decision.ON_REQUEST))) for u in Use.values]


def _number(lab: Lab, row: _Row) -> tuple[int | None, str]:
    """The lab's own "<code> <seq>" keeps its sequence; any other form is a former number."""
    number = row.values["accession_number"]
    found = re.match(_LAB_NUMBER.format(code=re.escape(lab.code)), number, re.IGNORECASE)
    if found:
        return int(found.group(1)), ""
    return None, number


def _condition(row: _Row) -> tuple[Condition, str]:
    """The note says the strain came from the former catalogue, with the file's own remark."""
    condition = _choice(row, "condition", Condition, Condition.OTHER)
    note = " ".join(filter(None, (IMPORTED, row.values["note"])))
    return condition, note


def _inputs(lab: Lab, row: _Row) -> tuple[services.NewDeposit, services.StrainFacts]:
    _required(row)
    legacy_seq, former_number = _number(lab, row)
    condition, note = _condition(row)
    deposit = services.NewDeposit(
        depositor=_depositor(lab, row),
        received_on=_day(row, "received_on"),
        condition=condition,
        condition_note=note,
        name_as_received=row.values["name_as_received"],
        terms=services.TermsInput(
            abs_scope=_choice(row, "abs_scope", AbsScope, AbsScope.UNKNOWN),
            uses=_uses(row),
            mta=_mta(lab, row),
            country_of_origin=row.values["country_of_origin"],
        ),
    )
    facts = services.StrainFacts(
        taxon=_taxon(row),
        identified_on=_day(row, "identified_on"),
        identification_method=row.values["identification_method"],
        risk_group=_risk_group(row),
        risk_group_basis=row.values["risk_group_basis"],
        risk_group_entry=_risk_group_entry(row),
        animal_pathogenicity=_choice(
            row, "animal_pathogenicity", Pathogenicity, Pathogenicity.UNKNOWN
        ),
        plant_pathogenicity=_choice(
            row, "plant_pathogenicity", Pathogenicity, Pathogenicity.UNKNOWN
        ),
        isolation_source=row.values["isolation_source"],
        country_of_origin=row.values["country_of_origin"],
        isolation_date=row.values["isolation_date"],
        restrictions=_restrictions(row),
        legacy_seq=legacy_seq,
        former_number=former_number,
    )
    return deposit, facts


# Writing.


def _column(error: DomainError) -> str:
    """The file's column a service's error is about."""
    if error.attr:
        field = error.attr.split(".", maxsplit=1)[0]
        field = _COLUMN_OF.get(field, field)
        return field if field in COLUMNS else ""
    return _COLUMN_OF_CODE.get(error.code, "")


def _accept(access: Access, lab: Lab, row: _Row) -> Strain:
    """One row through the deposit services, as a curator would by hand."""
    deposit_input, facts = _inputs(lab, row)
    deposit = services.deposit_receive(access=access, lab=lab, data=deposit_input)
    deposit = services.deposit_start_check(access=access, deposit=deposit)
    accepted = services.deposit_accept(access=access, deposit=deposit, facts=facts)
    return cast(Strain, accepted.strain)  # an accepted deposit has its strain (a check)


def _each_row(
    access: Access, lab: Lab, rows: list[_Row], on_strain: Callable[[Strain], None]
) -> list[RowError]:
    """Every row in its own savepoint: a refused row leaves no trace, the others go on."""
    errors: list[RowError] = []
    for row in rows:
        try:
            with transaction.atomic():
                on_strain(_accept(access, lab, row))
        except _RowFault as fault:
            errors.append(RowError(row.line, fault.column, fault.message))
        except DomainError as error:
            errors.append(RowError(row.line, _column(error), error.detail))
    return errors


@contextmanager
def _locked(access: Access, lab: Lab) -> Iterator[Lab]:
    with audited_atomic():
        locked = lock_lab(lab.pk)
        require_committed(access, locked.pk, Perm.IMPORT_CATALOGUE)
        yield locked


def catalogue_check(*, access: Access, lab: Lab, content: bytes) -> Checked:
    """Every row tried and every error reported; nothing stays written."""
    rows = read_rows(content)
    with _locked(access, lab) as locked:
        errors = _each_row(access, locked, rows, lambda _strain: None)
        transaction.set_rollback(True)
    return Checked(sha256_of(content), len(rows), errors)


def catalogue_import(
    *, access: Access, lab: Lab, content: bytes, sha256: str, reason: str
) -> list[Strain]:
    """The checked file, all rows or none, as one audited operation with a reason."""
    reason = reason.strip()
    if not reason:
        raise RuleViolation("A reason is required.", code="reason_required", attr="reason")
    if sha256_of(content) != sha256:
        raise CatalogueChanged
    rows = read_rows(content)
    created: list[Strain] = []
    with _locked(access, lab) as locked:
        errors = _each_row(access, locked, rows, created.append)
        if errors:
            raise CatalogueHasErrors(errors)
        record_event(
            CATALOGUE_IMPORTED,
            Change(
                LAB,
                locked.public_id,
                {
                    "file_sha256": [None, sha256],
                    "rows": [None, len(rows)],
                    "strains": [None, [s.accession_number for s in created]],
                },
                lab_id=locked.pk,
            ),
            reason=reason,
        )
    return created
