"""What the seeds read out of the official list data files, by entry code (#211).

A seed names entry codes and nothing else about a classification. This module reads the
taxon, the risk group, the restriction kind and the act out of ``data/`` (the files
``tools/fetch_regulatory_lists.py`` wrote from the official sources, checked against the
manifest by ``lists.read_list``), so no risk group, restriction kind or entry title is typed by
hand beside a code.

Two things the lists cannot answer are said in words, and never by a group of this module's own:

- Annex 7 of government order 361/2007 Sb. holds no entry at risk group 1 and does not make an
  unlisted agent group 1 by itself (Part A, notes to Table 1). The standard laboratory organisms
  of ``STANDARD`` are recorded at group 1 with a basis that says annex 7 does not list them, or,
  for Escherichia coli K-12, that annex 7 lists the species "except non-pathogenic strains".
- An entry that names a genus with "spp." covers other species only where they are known human
  pathogens (the same notes, Directive 2000/54/EC Annex III). A named species under such an entry
  is recorded at the group the entry states, with that said in the basis.

``tools/seed_classification.py`` prints what a seed's codes come to.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import lists
from .models import RISK_GROUP_LIST, MatchScope, RestrictionKind


class SeedEntryError(Exception):
    """A seed names a code the data files do not hold, or entries that do not fit together."""


@dataclass(frozen=True)
class SeedEntry:
    """One entry of one data file, as the seeds need it."""

    list_code: str
    act: str
    code: str
    name: str
    restriction_kind: str
    risk_group: int | None
    match_name: str
    match_scope: str
    version: str = ""  # the reading of the act the entry was read in

    @property
    def taxon(self) -> str:
        """The scientific name the entry names, as a taxon is written. Only an entry that names
        one taxon has one: an entry for a whole genus names no species to seed."""
        if not self.match_name or self.match_scope != MatchScope.EXACT:
            raise SeedEntryError(f"{self.code} ({self.list_code}) names no one taxon")
        return self.match_name[0].upper() + self.match_name[1:]


@dataclass(frozen=True)
class SeedRestriction:
    kind: str
    reference: str  # the entry's code, which the strain service resolves to the entry
    act: str  # only a dual-use item names one: the regulation Annex I was read in, "(EU) 2025/2003"


@dataclass(frozen=True)
class Classified:
    """What a strain of these entries carries: the taxon, and where annex 7 states a group,
    that group and the entry it was read in, and the restrictions the other lists give."""

    taxon: str
    risk_group: int | None
    risk_group_entry: str | None
    basis: str
    restrictions: tuple[SeedRestriction, ...]


def read_entries(data_dir: Path = lists.DATA_DIR) -> dict[str, list[SeedEntry]]:
    """Every entry of every list, by entry code. One code may stand in more than one list; a
    seed that names such a code says which with ``list_code:code``."""
    found: dict[str, list[SeedEntry]] = {}
    for list_code, source in lists.read_manifest(data_dir).items():
        payload = lists.read_list(list_code, source, data_dir)
        for row in lists.entry_rows(list_code, payload):
            entry = SeedEntry(
                list_code=list_code,
                act=payload["act"],
                code=row["code"],
                name=row["name"],
                restriction_kind=row["restriction_kind"],
                risk_group=row["risk_group"],
                match_name=row["match_name"],
                match_scope=row["match_scope"],
                version=payload["version"],
            )
            found.setdefault(entry.code, []).append(entry)
    return found


def entry(code: str, data_dir: Path = lists.DATA_DIR) -> SeedEntry:
    """The entry of this code. ``list_code:code`` when two lists hold the code."""
    list_code, _, bare = code.rpartition(":")
    rows = read_entries(data_dir).get(bare, [])
    if list_code:
        rows = [row for row in rows if row.list_code == list_code]
    if not rows:
        raise SeedEntryError(f"no entry {code!r} in the data files")
    if len(rows) > 1:
        raise SeedEntryError(f"entry {code!r} is in {[row.list_code for row in rows]}: say which")
    return rows[0]


def entries_matching(
    taxon: str, data_dir: Path = lists.DATA_DIR
) -> list[SeedEntry]:  # the same match the app makes: the name, or the genus of a genus entry
    """The entries a taxon of this name matches, as the Classification view reads them."""
    name = lists.normalised(taxon)
    genus = name.split(" ")[0]
    return [
        row
        for rows in read_entries(data_dir).values()
        for row in rows
        if row.match_name
        and (
            (row.match_scope == MatchScope.EXACT and row.match_name == name)
            or (row.match_scope == MatchScope.GENUS and row.match_name == genus)
        )
    ]


def _where(row: SeedEntry) -> str:
    return f"{row.act}, entry {row.code} ({row.name})"


def _is_dual_use(row: SeedEntry) -> bool:
    return row.restriction_kind == RestrictionKind.DUAL_USE


def _eu_act(version: str) -> str:
    """The act Annex I was read in, as the strain service wants it, from the CELEX number the
    data file records as its version: 32025R2003 is "(EU) 2025/2003"."""
    found = re.fullmatch(r"3(\d{4})R(\d{4})", version)
    if found is None:
        raise SeedEntryError(f"the version {version!r} is no CELEX number of a regulation")
    return f"(EU) {found[1]}/{found[2]}"


def listed(codes: Sequence[str], data_dir: Path = lists.DATA_DIR) -> Classified:
    """A strain of the entries these codes name. All name one taxon. The entry of annex 7, where
    there is one, gives the group and the basis points at it; every other list gives the
    restriction its entries carry. No group follows when no code is an annex 7 entry."""
    rows = [entry(code, data_dir) for code in codes]
    taxa = {row.taxon for row in rows}
    if len(taxa) != 1:
        raise SeedEntryError(f"entries {list(codes)} name {sorted(taxa)}, not one taxon")
    by_list: dict[str, list[SeedEntry]] = {}
    for row in rows:
        by_list.setdefault(row.list_code, []).append(row)
    annex_7 = by_list.pop(RISK_GROUP_LIST, [])
    if len(annex_7) > 1:
        raise SeedEntryError(
            f"{[row.code for row in annex_7]}: one entry of annex 7 gives the group"
        )
    group = annex_7[0] if annex_7 else None
    if group is not None and group.risk_group is None:
        raise SeedEntryError(f"entry {group.code} of annex 7 states no group")
    restrictions = tuple(
        SeedRestriction(
            row.restriction_kind, row.code, _eu_act(row.version) if _is_dual_use(row) else ""
        )
        for other in by_list.values()
        for row in other
        if row.restriction_kind
    )
    return Classified(
        taxon=next(iter(taxa)),
        risk_group=group.risk_group if group else None,
        risk_group_entry=group.code if group else None,
        basis=(
            f"Annex 7 of {group.act}, entry {group.code} ({group.name}), states risk group"
            f" {group.risk_group}."
            if group
            else ""
        ),
        restrictions=restrictions,
    )


@dataclass(frozen=True)
class Standard:
    """A standard laboratory organism the collection records at group 1 (#211)."""

    taxon: str
    strain: str  # the name of the laboratory strain, for the basis


STANDARD: dict[str, Standard] = {
    "escherichia-coli-k12": Standard("Escherichia coli", "K-12"),
    "bacillus-subtilis-168": Standard("Bacillus subtilis", "168"),
    "lactococcus-lactis": Standard("Lactococcus lactis", ""),
    "pseudomonas-putida-kt2440": Standard("Pseudomonas putida", "KT2440"),
}
# Annex 7 names Saccharomyces cerevisiae (entry 5.38, group 2), so the yeast is a listed organism
# and is seeded by its entry: it is no group 1 organism of this table.

_REASON = (
    "The collection recorded risk group 1 as a standard laboratory organism that is not a "
    "pathogen. Annex 7 does not make an unlisted agent group 1 by itself, so this is the "
    "collection's own assessment."
)


def standard(key: str, data_dir: Path = lists.DATA_DIR) -> Classified:
    """A standard organism at group 1, with a basis in words that says what annex 7 says of it.

    No entry of annex 7 names it, and the basis says so. Where an entry names the species with an
    exception for non-pathogenic strains (Escherichia coli, entry 1.73), the basis quotes that
    entry, and the strain is a case of a non-pathogenic strain of a listed species: it
    carries no pointer, because an entry that states group 2 cannot rest group 1.
    """
    if key not in STANDARD:
        raise SeedEntryError(f"{key!r} is not a standard organism: {sorted(STANDARD)}")
    found = STANDARD[key]
    named = [
        row for row in entries_matching(found.taxon, data_dir) if row.list_code == RISK_GROUP_LIST
    ]
    label = f"{found.taxon} {found.strain}".strip()
    if named:
        about = "; ".join(_where(row) + f", risk group {row.risk_group}" for row in named)
        opening = (
            f"Annex 7 of 361/2007 Sb. lists the species: {about}. {label} is a strain the entry"
            " excepts as non-pathogenic."
        )
    else:
        opening = f"Annex 7 of 361/2007 Sb. does not list {label}."
    return Classified(found.taxon, 1, None, f"{opening} {_REASON}", ())


def species_under_genus(taxon: str, data_dir: Path = lists.DATA_DIR) -> Classified:
    """A named species the lists do not name, under an entry that names its genus with "spp.".

    The entry covers other species only where they are known human pathogens (annex 7, notes to
    Table 1). The seed records the group the entry states and says so in the basis. It does not
    decide whether this species is a known pathogen: that is for a person.
    """
    genus_entries = [
        row
        for row in entries_matching(taxon, data_dir)
        if row.list_code == RISK_GROUP_LIST and row.match_scope == MatchScope.GENUS
    ]
    if len(genus_entries) != 1:
        raise SeedEntryError(f"{taxon}: {len(genus_entries)} genus entries of annex 7, not one")
    row = genus_entries[0]
    if row.risk_group is None:
        raise SeedEntryError(f"entry {row.code} states no group")
    if any(
        other.match_scope == MatchScope.EXACT
        for other in entries_matching(taxon, data_dir)
        if other.list_code == RISK_GROUP_LIST
    ):
        raise SeedEntryError(f"{taxon} is named by an entry of its own")
    return Classified(
        taxon,
        row.risk_group,
        row.code,
        f"{_where(row)} names the genus with spp. and states risk group {row.risk_group}. "
        f"{taxon} is not named in annex 7. The entry covers other species only where they are "
        "known human pathogens, and the collection keeps this species under the group the "
        "entry states until a person decides otherwise.",
        (),
    )


def named_taxa(codes: Iterable[str], data_dir: Path = lists.DATA_DIR) -> list[str]:
    """The taxon each code names, for the seeds' list of taxa."""
    return [entry(code, data_dir).taxon for code in codes]


def classify(spec: Mapping[str, Any], taxon: str, data_dir: Path = lists.DATA_DIR) -> Classified:
    """What a seed row's ``classification`` comes to for a strain whose taxon is `taxon`.

    The row says one of ``{"entries": [codes]}``, ``{"standard": key}`` or
    ``{"under_genus": true}``, and nothing else: the taxon the entries name must be the strain's
    own, or the seed is wrong and is refused.
    """
    if "entries" in spec:
        made = listed(spec["entries"], data_dir)
    elif "standard" in spec:
        made = standard(spec["standard"], data_dir)
    elif spec.get("under_genus"):
        made = species_under_genus(taxon, data_dir)
    else:
        raise SeedEntryError(
            f"a classification names entries, a standard organism or a genus: {dict(spec)}"
        )
    if made.taxon != taxon:
        raise SeedEntryError(f"the classification is of {made.taxon}, the strain is {taxon}")
    return made
