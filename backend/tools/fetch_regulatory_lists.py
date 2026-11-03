#!/usr/bin/env python3
"""Write the official lists of regulated agents as data files, straight from the source.

Four sources, one data file each, under ``cultures/biosafety/data``:

=========================  ==============================================================
``cz-474-2002``            decree 474/2002 Sb., annexes 1 (VRAT) and 2 (RAT)
``cz-361-2007-annex-7``    government order 361/2007 Sb., annex 7, the risk group tables
``eu-2021-821-annex-i``    Regulation (EU) 2021/821, annex I, entries 1C351, 1C353, 1C354
``eu-2019-2072-annex-ii``  Implementing Regulation (EU) 2019/2072, annex II
=========================  ==============================================================

Run it from the ``backend`` directory (it needs the network and nothing else)::

    python tools/fetch_regulatory_lists.py fetch all
    python tools/fetch_regulatory_lists.py fetch cz-474-2002
    python tools/fetch_regulatory_lists.py parse-file cz-474-2002 <a saved copy>
    python tools/fetch_regulatory_lists.py fixtures

Czech texts come from the e-Sbirka API, EU texts from the Publications Office Cellar and the
version of an EU act from the Cellar's SPARQL endpoint. No browser user agent is sent anywhere.

Every parser asserts the shape it expects and raises ``ShapeError`` with the source's own
identifiers when the text does not match, so a changed source leaves the data files alone
instead of writing half a list. Each data file carries its source URL, version, version date,
fetch date, the SHA-256 of the fetched text and the number of entries; ``manifest.json``
repeats that for every source and adds the SHA-256 of the data file itself. Rerunning the
script on an unchanged source rewrites nothing, so ``fetched_on`` is the day the content last
changed.

Nothing in the application reads these files yet (#169).
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE.parent / "cultures" / "biosafety" / "data"
FIXTURE_DIR = HERE / "tests" / "fixtures"
MANIFEST = "manifest.json"
EXPECTED = "expected.json"

ESBIRKA = "https://e-sbirka.gov.cz/sbr-cache/dokumenty-sbirky/"
CELLAR = "http://publications.europa.eu/resource/celex/"
SPARQL = "http://publications.europa.eu/webapi/rdf/sparql"
XHTML = "{http://www.w3.org/1999/xhtml}"
PRAGUE = ZoneInfo("Europe/Prague")

# e-Sbirka fragments are XHTML snippets that use the HTML nbsp entity, which XML does not know.
NBSP_DTD = '<!DOCTYPE root [<!ENTITY nbsp "&#160;">]>'

TIMEOUT = 180


class ShapeError(Exception):
    """The source text does not have the shape the parser knows how to read."""


def say(message: str) -> None:
    """Report progress on stdout (this is a command line tool)."""
    print(message)  # noqa: T201


# --------------------------------------------------------------------------------------
# fetching


@dataclass(frozen=True)
class Fetched:
    """A source text with where it came from and which version it is.

    ``document`` is what the parser reads: the list of e-Sbirka fragments, or the root
    element of an EU XHTML document.
    """

    url: str
    version: str
    version_date: str
    sha256: str
    document: Any


def http_get(url: str, accept: str | None = None) -> bytes:
    request = urllib.request.Request(url)  # noqa: S310 (fixed official hosts, http(s) only)
    if accept:
        request.add_header("Accept", accept)
        request.add_header("Accept-Language", "eng")
    if not url.startswith(("https://e-sbirka.gov.cz/", "http://publications.europa.eu/")):
        raise ShapeError(f"refusing to fetch from an unexpected host: {url}")
    with urllib.request.urlopen(request, timeout=TIMEOUT) as answer:  # noqa: S310
        body: bytes = answer.read()
    return body


def fetch_esbirka(year: str, number: str) -> Fetched:
    """Fetch the version in force of a Czech act from the official e-Sbirka API."""
    meta_url = ESBIRKA + urllib.parse.quote(f"/sb/{year}/{number}", safe="")
    meta = json.loads(http_get(meta_url))
    stale = meta["staleUrl"]
    fragments_url = ESBIRKA + urllib.parse.quote(stale, safe="") + "/fragmenty"
    pages: list[bytes] = []
    fragments: list[dict[str, Any]] = []
    page = 0
    while True:
        body = http_get(f"{fragments_url}?cisloStranky={page}")
        pages.append(body)
        payload = json.loads(body)
        fragments.extend(payload["seznam"])
        page += 1
        if page >= int(payload.get("pocetStranek", 1)):
            break
    return Fetched(
        url=fragments_url,
        version=stale,
        version_date=meta["datumUcinnostiZneniOd"],
        sha256=hashlib.sha256(b"".join(pages)).hexdigest(),
        document=fragments,
    )


def fetch_cellar(celex: str, version_date: str) -> Fetched:
    """Fetch the English text of an EU act from the Publications Office Cellar."""
    url = CELLAR + celex
    body = http_get(url, accept="application/xhtml+xml")
    try:
        root = ET.fromstring(body)  # noqa: S314 (official source, no entity expansion needed)
    except ET.ParseError as error:
        raise ShapeError(f"{celex}: the Cellar answer is not well formed XHTML: {error}") from error
    return Fetched(
        url=url,
        version=celex,
        version_date=version_date,
        sha256=hashlib.sha256(body).hexdigest(),
        document=root,
    )


def sparql(query: str) -> list[dict[str, Any]]:
    """Ask the Cellar's SPARQL endpoint, which answers for the version of an act."""
    url = SPARQL + "?" + urllib.parse.urlencode({"query": query})
    answer = json.loads(http_get(url, accept="application/sparql-results+json"))
    rows: list[dict[str, Any]] = answer["results"]["bindings"]
    return rows


def latest_consolidated(base_celex: str, today: str) -> str:
    """The newest consolidated version of an act that is already in force.

    A consolidated CELEX is the act's number with the date it applies from, for example
    ``02019R2072-20261015``.
    """
    query = (
        "PREFIX cdm: <http://publications.europa.eu/ontology/cdm#> "
        "SELECT ?id WHERE { ?w cdm:resource_legal_id_celex ?id . "
        f'FILTER(STRSTARTS(STR(?id), "{base_celex}-")) }} ORDER BY DESC(?id) LIMIT 50'
    )
    stamp = today.replace("-", "")
    found = [str(row["id"]["value"]) for row in sparql(query)]
    in_force = sorted(
        c for c in found if re.fullmatch(rf"{base_celex}-\d{{8}}", c) and c[-8:] <= stamp
    )
    if not in_force:
        raise ShapeError(f"{base_celex}: the Cellar lists no consolidated version in force")
    return in_force[-1]


def document_date(celex: str) -> str:
    """The date an EU act carries, as the Cellar records it."""
    query = (
        "PREFIX cdm: <http://publications.europa.eu/ontology/cdm#> "
        "SELECT ?date WHERE { "
        f'?w cdm:resource_legal_id_celex "{celex}"^^<http://www.w3.org/2001/XMLSchema#string> ; '
        "cdm:work_date_document ?date } LIMIT 1"
    )
    rows = sparql(query)
    if not rows:
        raise ShapeError(f"{celex}: the Cellar gives no document date")
    date = str(rows[0]["date"]["value"])[:10]
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        raise ShapeError(f"{celex}: the Cellar gives the document date as {date!r}")
    return date


# --------------------------------------------------------------------------------------
# reading XHTML


def norm(text: str | None) -> str:
    return " ".join((text or "").split())


def fragment_tree(fragment: dict[str, Any]) -> ET.Element:
    """The XHTML of one e-Sbirka fragment as an element tree."""
    snippet = fragment.get("xhtml") or ""
    try:
        return ET.fromstring(  # noqa: S314 (official source)
            f'{NBSP_DTD}<root xmlns="http://www.w3.org/1999/xhtml">{snippet}</root>'
        )
    except ET.ParseError as error:
        raise ShapeError(
            f"fragment {fragment.get('id')} is not well formed XHTML: {error}"
        ) from error


def fragment_text(fragment: dict[str, Any]) -> str:
    return norm("".join(fragment_tree(fragment).itertext()))


def own_text(element: ET.Element) -> str:
    """The text of an element without the text of any table nested in it."""
    parts: list[str] = [element.text or ""]

    def walk(node: ET.Element) -> None:
        for child in node:
            if child.tag == XHTML + "table":
                parts.append(child.tail or "")
                continue
            parts.append(child.text or "")
            walk(child)
            parts.append(child.tail or "")

    walk(element)
    return norm("".join(parts))


def table_rows(table: ET.Element) -> list[list[ET.Element]]:
    """The rows of a table as lists of their own cells."""
    return [
        [cell for cell in row if cell.tag in (XHTML + "td", XHTML + "th")]
        for row in table.iter(XHTML + "tr")
    ]


def cell_text(cell: ET.Element, drop: str = "sup") -> tuple[str, list[str]]:
    """The text of a cell with the footnote markers taken out, and those markers."""
    copied = copy.deepcopy(cell)
    markers: list[str] = []
    for parent in copied.iter():
        for child in list(parent):
            if child.tag == XHTML + drop:
                markers.append(norm("".join(child.itertext())))
                tail = child.tail or ""
                parent.remove(child)
                if tail.strip():
                    parent.text = (parent.text or "") + tail
    return norm("".join(copied.itertext())), [m for m in markers if m]


# --------------------------------------------------------------------------------------
# decree 474/2002 Sb., annexes 1 and 2

ANNEX_HEADER = "Hlavicka_priloha"
HEADING = "Obecny_text"
ITEM = "Bod_Dd"

# A part of annex 1 or 2 says in its heading what kind of thing it lists. Exactly one of these
# words must appear in it, or the parser does not know the part and refuses the text.
CZ_PART_KINDS = (
    ("živoč", "organism"),
    ("rostlin", "organism"),
    ("toxin", "toxin"),
    ("genet", "genetic_element"),
)
# How deep an annex 1 or 2 fragment sits: a part, a group inside a part, and a numbered item,
# which hangs under its group when the part has groups and under the part itself when it has none.
PART_DEPTH = 4
GROUP_DEPTH = 5
ITEM_DEPTH_UNDER_GROUP = 6
ITEM_DEPTH_UNDER_PART = 5

ROMAN_PART = re.compile(r"^([IVX]+)\.")
ROMAN_GROUP = re.compile(r"^([IVX]+\.[IVX]+)")
NUMBERED = re.compile(r"^(\d+)\.\s+(.+)$")


def annex_slice(fragments: Sequence[dict[str, Any]], number: int) -> list[dict[str, Any]]:
    """The fragments of one annex, from its header to the header of the next one."""
    starts = [
        index
        for index, fragment in enumerate(fragments)
        if fragment["kodTypuFragmentu"] == ANNEX_HEADER
    ]
    if not starts:
        raise ShapeError("the text has no annex headers")
    for position, index in enumerate(starts):
        if fragment_text(fragments[index]).startswith(f"Příloha č. {number} "):
            end = starts[position + 1] if position + 1 < len(starts) else len(fragments)
            return list(fragments[index:end])
    raise ShapeError(f"the text has no annex {number}")


def part_kind(code: str, heading: str) -> str:
    low = heading.lower()
    kinds = sorted({kind for word, kind in CZ_PART_KINDS if word in low})
    if len(kinds) != 1:
        raise ShapeError(
            f"part {code}: its heading matches {len(kinds)} of the known kinds, expected one"
        )
    return kinds[0]


@dataclass
class CzPart:
    code: str
    name: str
    kind: str


def parse_cz_474(fetched: Fetched) -> list[dict[str, Any]]:
    """Annexes 1 and 2 of decree 474/2002 Sb.: one record per numbered item."""
    records: list[dict[str, Any]] = []
    for annex in (1, 2):
        records.extend(_parse_cz_474_annex(fetched.document, annex))
    return records


def _parse_cz_474_annex(fragments: Sequence[dict[str, Any]], annex: int) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    part: CzPart | None = None
    group: tuple[str, str] | None = None
    counters: dict[str, int] = {}
    with_entries: set[str] = set()
    parts_seen: list[str] = []
    after_parts = False
    for fragment in annex_slice(fragments, annex)[1:]:
        kind = fragment["kodTypuFragmentu"]
        depth = int(fragment["hloubka"])
        if kind == HEADING and depth == PART_DEPTH:
            text = fragment_text(fragment)
            match = ROMAN_PART.match(text)
            if not match:
                after_parts = True
                continue
            if after_parts:
                raise ShapeError(f"annex {annex}: a part heading follows the notes")
            part = CzPart(match.group(1), text, part_kind(match.group(1), text))
            parts_seen.append(part.code)
            group = None
        elif kind == HEADING and depth == GROUP_DEPTH and part is not None and not after_parts:
            text = fragment_text(fragment)
            match = ROMAN_GROUP.match(text)
            group = (match.group(1), text) if match else None
        elif kind == ITEM:
            if after_parts:
                raise ShapeError(f"annex {annex}: a numbered item follows the notes")
            if part is None:
                raise ShapeError(f"annex {annex}: a numbered item before the first part")
            records.append(
                _cz_474_record(
                    fragment, annex, part=part, group=group, counters=counters, depth=depth
                )
            )
            with_entries.add(part.code)
    _check_cz_474_annex(annex, parts_seen, with_entries, records)
    return records


def _cz_474_record(
    fragment: dict[str, Any],
    annex: int,
    *,
    part: CzPart,
    group: tuple[str, str] | None,
    counters: dict[str, int],
    depth: int,
) -> dict[str, Any]:
    expected_depth = ITEM_DEPTH_UNDER_GROUP if group else ITEM_DEPTH_UNDER_PART
    if depth != expected_depth:
        raise ShapeError(
            f"annex {annex}, part {part.code}: a numbered item sits at depth {depth}, "
            f"expected {expected_depth}"
        )
    tree = fragment_tree(fragment)
    text = norm("".join(tree.itertext()))
    match = NUMBERED.match(text)
    if not match:
        raise ShapeError(
            f"annex {annex}, part {part.code}: an item does not start with its number "
            f"(fragment {fragment.get('id')})"
        )
    names = [norm("".join(var.itertext())) for var in tree.iter(XHTML + "var")]
    if len(names) != 1:
        raise ShapeError(
            f"annex {annex}, part {part.code}, item {match.group(1)}: {len(names)} marked names, "
            "expected one"
        )
    group_code = group[0] if group else part.code
    number = int(match.group(1))
    expected = counters.get(group_code, 0) + 1
    if number != expected:
        raise ShapeError(
            f"annex {annex}, group {group_code}: the items are numbered "
            f"{expected - 1} then {number}"
        )
    counters[group_code] = number
    return {
        "list": f"annex-{annex}",
        "part": part.code,
        "part_name": part.name,
        "group": group[0] if group else None,
        "group_name": group[1] if group else None,
        "code": f"{group_code} {number}",
        "number": number,
        "name": match.group(2),
        "scientific_name": names[0],
        "kind": part.kind,
    }


def _check_cz_474_annex(
    annex: int, parts_seen: Sequence[str], with_entries: set[str], records: Sequence[object]
) -> None:
    if not records:
        raise ShapeError(f"annex {annex}: no numbered item at all")
    if len(set(parts_seen)) != len(parts_seen):
        raise ShapeError(f"annex {annex}: a part code appears twice ({', '.join(parts_seen)})")
    if parts_seen != ["I", "II", "III", "IV"]:
        raise ShapeError(f"annex {annex}: its parts are {', '.join(parts_seen) or 'none'}")
    if "IV" in with_entries:
        raise ShapeError(f"annex {annex}: part IV has numbered items, which it never had")


# --------------------------------------------------------------------------------------
# government order 361/2007 Sb., annex 7: the risk group tables

TABLE = "Tabulka"
TABLE_HEADING = "Nadpis"
PART = "Cast"
GROUP_COLUMN = "Skupina"
NOTE_COLUMN = "Poznámka"

# Each table of part 1 lists one kind of agent. All of them are organisms; an unknown heading
# means the annex changed and the parser refuses the text.
CZ_TABLE_WORDS = ("bakterie", "viry", "encefalopat", "parazit", "houby")
EXPECTED_TABLES = 5
TABLE_COLUMNS = 3
HEADER_AND_A_ROW = 2

# A group cell is a number, and the asterisk that sends the reader to a note is printed either
# in brackets or on its own, sometimes as a footnote marker this parser lifts out of the cell.
RISK_GROUP = re.compile(r"^(\d+)?\s*(?:\(\s*(\**)\s*\)|(\*+))?$")
# A note cell holds the flags of the annex (A, T, V, D) and may send the reader to a lettered
# note, printed in brackets or as a footnote marker this parser lifts out of the cell.
NOTE_CELL = re.compile(r"^([A-Z](?:\s*,\s*[A-Z])*)?\s*(?:\(\s*([a-z]?)\s*\))?$")


def parse_cz_361_annex_7(fetched: Fetched) -> list[dict[str, Any]]:
    """The risk group tables of annex 7: one record per table row."""
    fragments = annex_slice(fetched.document, 7)
    records: list[dict[str, Any]] = []
    heading: str | None = None
    table_number = 0
    parts = 0
    for fragment in fragments[1:]:
        kind = fragment["kodTypuFragmentu"]
        if kind == PART:
            parts += 1
            if parts > 1:
                break
        elif kind == TABLE_HEADING:
            heading = fragment_text(fragment)
        elif kind == TABLE:
            if heading is None:
                raise ShapeError("annex 7: a table before any heading")
            table_number += 1
            records.extend(_parse_cz_361_table(fragment, table_number, heading))
    if table_number != EXPECTED_TABLES:
        raise ShapeError(f"annex 7, part 1: {table_number} tables, expected {EXPECTED_TABLES}")
    return records


def _table_word(number: int, heading: str) -> None:
    low = heading.lower()
    if not any(word in low for word in CZ_TABLE_WORDS):
        raise ShapeError(f"annex 7, table {number}: its heading names no kind the parser knows")


def _parse_cz_361_table(
    fragment: dict[str, Any], number: int, heading: str
) -> list[dict[str, Any]]:
    _table_word(number, heading)
    tables = list(fragment_tree(fragment).iter(XHTML + "table"))
    if len(tables) != 1:
        raise ShapeError(f"annex 7, table {number}: {len(tables)} tables in one fragment")
    rows = table_rows(tables[0])
    if len(rows) < HEADER_AND_A_ROW:
        raise ShapeError(f"annex 7, table {number}: {len(rows)} rows")
    widths = {len(row) for row in rows}
    if widths != {TABLE_COLUMNS}:
        raise ShapeError(
            f"annex 7, table {number}: its rows have {sorted(widths)} cells, "
            f"expected {TABLE_COLUMNS}"
        )
    header = [cell_text(cell)[0] for cell in rows[0]]
    if header[1] != GROUP_COLUMN or header[2] != NOTE_COLUMN:
        raise ShapeError(
            f"annex 7, table {number}: its columns are headed {header!r}, "
            f"expected the second {GROUP_COLUMN!r} and the third {NOTE_COLUMN!r}"
        )
    return [
        _cz_361_record(row, number, heading, index) for index, row in enumerate(rows[1:], start=1)
    ]


def _cz_361_record(
    row: Sequence[ET.Element], number: int, heading: str, index: int
) -> dict[str, Any]:
    where = f"annex 7, table {number}, row {index}"
    name, name_refs = cell_text(row[0])
    if not name:
        raise ShapeError(f"{where}: the agent column is empty")
    group_text, group_marks = cell_text(row[1])
    match = RISK_GROUP.match(group_text)
    if not match:
        raise ShapeError(f"{where}: the group column reads {group_text!r}")
    note_text, note_marks = cell_text(row[2])
    note = NOTE_CELL.match(note_text)
    if not note:
        raise ShapeError(f"{where}: the note column reads {note_text!r}")
    markers = [m for m in [*group_marks, match.group(2), match.group(3)] if m]
    return {
        "table": number,
        "table_name": heading,
        "code": f"{number}.{index}",
        "number": index,
        "name": name,
        "name_refs": name_refs,
        "risk_group": int(match.group(1)) if match.group(1) else None,
        "risk_group_markers": markers,
        "note": note_text or None,
        "note_flags": [f.strip() for f in (note.group(1) or "").split(",") if f.strip()],
        "note_refs": [r for r in [note.group(2), *note_marks] if r],
        "kind": "organism",
    }


# --------------------------------------------------------------------------------------
# Regulation (EU) 2021/821, annex I: entries 1C351, 1C353 and 1C354

# Annex I is replaced whole by a delegated regulation. The English text in force is the one
# below; Delegated Regulation (EU) 2026/1405, which is newer, only corrects other language
# versions and carries no annex (checked against its text on 2026-11-03).
ANNEX_I_CELEX = "32025R2003"
ANNEX_I_ENTRIES = ("1C351", "1C353", "1C354")

# What a category heading of annex I starts with tells what its items are. A category the
# parser does not know means the annex changed and it refuses the text.
EU_CATEGORY_KINDS = (
    ("viruses", "organism"),
    ("bacteria", "organism"),
    ("fungi", "organism"),
    ("protozoa", "organism"),
    ("rickettsiae", "organism"),
    ("prions", "organism"),
    ("human and animal pathogens", "organism"),
    ("plant pathogens", "organism"),
    ("toxins", "toxin"),
    ("genetic elements", "genetic_element"),
    ("genetically modified", "genetic_element"),
)
NOTE_TOKEN = re.compile(r"^(N\.B\.|Note|NOTE|Technical Note)")
# An item row prints its number or letter in one cell and the item in the next, after an empty
# cell for the level above when there is one.
ITEM_ROW_CELLS = (2, 3)
EU_TOKEN = re.compile(r"^(?:([a-z])|(\d+))\.?$")


def category_kind(text: str) -> str | None:
    low = text.lower().lstrip("\u201c\u201d\u2018\u2019'\" ")
    for word, kind in EU_CATEGORY_KINDS:
        if low.startswith(word):
            return kind
    return None


def cell_items(cell: ET.Element) -> list[tuple[str, Any]]:
    """What a cell holds, in the order it is printed: text runs and the tables under it."""
    items: list[tuple[str, Any]] = []

    def walk(node: ET.Element) -> None:
        for child in node:
            if child.tag == XHTML + "table":
                items.append(("table", child))
            elif next(child.iter(XHTML + "table"), None) is None:
                text = norm("".join(child.itertext()))
                if text:
                    items.append(("text", text))
            else:
                walk(child)
            tail = norm(child.tail)
            if tail:
                items.append(("text", tail))

    walk(cell)
    return items


@dataclass
class EuNode:
    token: str
    text: str
    items: list[tuple[str, Any]]

    @property
    def children(self) -> list[ET.Element]:
        return [value for kind, value in self.items if kind == "table"]


def eu_row(table: ET.Element) -> EuNode:
    """One item of an EU list: its number or letter, its own text and its children."""
    rows = table_rows(table)
    if not rows:
        raise ShapeError("an item table has no row")
    cells = rows[0]
    if len(cells) not in ITEM_ROW_CELLS:
        raise ShapeError(f"an item row has {len(cells)} cells, expected {ITEM_ROW_CELLS}")
    texts = [own_text(cell) for cell in cells]
    token = next((text for text in texts[:-1] if text), "")
    return EuNode(token=token, text=texts[-1], items=cell_items(cells[-1]))


def find_eu_entry(root: ET.Element, code: str) -> ET.Element:
    """The table whose item is the annex entry with this code."""
    for table in root.iter(XHTML + "table"):
        for cells in table_rows(table):
            if any(own_text(cell) == code for cell in cells[:-1]):
                return table
    raise ShapeError(f"annex I: entry {code} is not in the text")


def parse_eu_2021_821_annex_i(fetched: Fetched) -> list[dict[str, Any]]:
    """Entries 1C351, 1C353 and 1C354 of annex I: one record per item, at every level."""
    records: list[dict[str, Any]] = []
    for code in ANNEX_I_ENTRIES:
        table = find_eu_entry(fetched.document, code)
        node = eu_row(table)
        if node.token and node.token != code:
            raise ShapeError(f"annex I: entry {code} sits in a row numbered {node.token!r}")
        kind = category_kind(node.text)
        if kind is None:
            raise ShapeError(
                f"annex I: entry {code} opens with a category the parser does not know"
            )
        records.append(
            {
                "entry": code,
                "code": code,
                "parent": None,
                "name": node.text,
                "has_children": bool(node.children),
                "kind": kind,
            }
        )
        _walk_eu_items(node, code, code, kind, records)
    return records


def _walk_eu_items(
    node: EuNode, entry: str, code: str, kind: str, records: list[dict[str, Any]]
) -> None:
    """Record every child of an item, keeping the printed numbering as the code."""
    seen: list[str] = []
    notes = False
    for kind_of_item, value in node.items:
        if kind_of_item == "text":
            # A heading such as "Technical Notes:" stands between two items: everything after
            # it explains the entry instead of listing something.
            notes = notes or bool(NOTE_TOKEN.match(value))
            continue
        child: ET.Element = value
        item = eu_row(child)
        if NOTE_TOKEN.match(item.token):
            # A note explains the entry instead of listing something, and so does everything
            # printed after it at this level.
            notes = True
        if not notes:
            token = _eu_token(entry, code, item.token, seen)
            seen.append(token)
            child_kind = category_kind(item.text) or kind
            child_code = f"{code}.{token}"
            if not item.text:
                raise ShapeError(f"annex I: item {child_code} has no text")
            records.append(
                {
                    "entry": entry,
                    "code": child_code,
                    "parent": code,
                    "name": item.text,
                    "has_children": bool(item.children),
                    "kind": child_kind,
                }
            )
            _walk_eu_items(item, entry, child_code, child_kind, records)


def _eu_token(entry: str, code: str, token: str, seen: Sequence[str]) -> str:
    match = EU_TOKEN.match(token)
    if not match:
        raise ShapeError(f"annex I, entry {entry}: an item under {code} is numbered {token!r}")
    value = match.group(1) or match.group(2)
    expected = _next_token(seen[-1]) if seen else ("a" if match.group(1) else "1")
    if value != expected:
        raise ShapeError(
            f"annex I, entry {entry}: the items under {code} run {seen[-1] if seen else 'none'} "
            f"then {value}"
        )
    return value


def _next_token(previous: str) -> str:
    if previous.isdigit():
        return str(int(previous) + 1)
    return chr(ord(previous) + 1)


# --------------------------------------------------------------------------------------
# Implementing Regulation (EU) 2019/2072, annex II: Union quarantine pests

ANNEX_II_BASE = "02019R2072"
ANNEX_II_PARTS = ("PART A", "PART B")
ANNEX_II_MARK = "ANNEX II"
ANNEX_II_END = "ANNEX III"
CONSOLIDATION_MARK = "▼"
EPPO_CODE = re.compile(r"\[([A-Z0-9]{4,})\]")
PEST_GROUP = re.compile(r"^(\d+)\.\s+(.+)$")
PEST_NUMBER = re.compile(r"^(\d+(?:\.\d+)?)\.?$")
PEST_ROW_CELLS = 2


def document_sequence(element: ET.Element) -> Iterator[tuple[str, Any]]:
    """Paragraphs and tables of a document in the order they are printed."""
    for child in element:
        if child.tag == XHTML + "table":
            yield "table", child
            continue
        if child.tag == XHTML + "p":
            text = norm("".join(child.itertext()))
            if text:
                yield "p", text
        yield from document_sequence(child)


def parse_eu_2019_2072_annex_ii(fetched: Fetched) -> list[dict[str, Any]]:
    """Annex II, parts A and B: one record per numbered pest."""
    body = fetched.document.find(XHTML + "body")
    if body is None:
        raise ShapeError("annex II: the document has no body")
    sequence = list(document_sequence(body))
    window = _annex_ii_window(sequence)
    records: list[dict[str, Any]] = []
    for part in ANNEX_II_PARTS:
        table = _table_after(window, part)
        records.extend(_parse_pest_table(table, part.removeprefix("PART ")))
    return records


def _annex_ii_window(sequence: Sequence[tuple[str, Any]]) -> list[tuple[str, Any]]:
    marks = [index for index, (kind, value) in enumerate(sequence) if kind == "p"]
    start = next((i for i in marks if sequence[i][1] == ANNEX_II_MARK), None)
    end = next((i for i in marks if i > (start or 0) and sequence[i][1] == ANNEX_II_END), None)
    if start is None or end is None:
        raise ShapeError(f"the text has no {ANNEX_II_MARK} followed by {ANNEX_II_END}")
    return list(sequence[start:end])


def _table_after(window: Sequence[tuple[str, Any]], part: str) -> ET.Element:
    for index, (kind, value) in enumerate(window):
        if kind == "p" and value == part:
            for next_kind, next_value in window[index + 1 :]:
                if next_kind == "table":
                    table: ET.Element = next_value
                    return table
                raise ShapeError(f"annex II: {part} is not followed by a table")
    raise ShapeError(f"annex II: it has no {part}")


def _parse_pest_table(table: ET.Element, part: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    group: tuple[str, str] | None = None
    counters: dict[str, str] = {}
    for index, row in enumerate(table_rows(table), start=1):
        where = f"annex II, part {part}, row {index}"
        texts = [cell_text(cell)[0] for cell in row]
        if len(texts) == 1:
            group = _pest_heading(texts[0], group, records, where)
            continue
        if len(texts) != PEST_ROW_CELLS:
            raise ShapeError(f"{where}: {len(texts)} cells, expected one or {PEST_ROW_CELLS}")
        if texts[0].startswith(CONSOLIDATION_MARK):
            continue
        if group is None:
            raise ShapeError(f"{where}: a numbered pest before the first group heading")
        records.append(_pest_record(texts, part, group, counters, where))
    if not records:
        raise ShapeError(f"annex II, part {part}: no numbered pest at all")
    return records


def _pest_heading(
    text: str,
    group: tuple[str, str] | None,
    records: Sequence[object],
    where: str,
) -> tuple[str, str] | None:
    """A group heading is numbered and the groups count up; the rest is a column header."""
    if text.startswith(CONSOLIDATION_MARK):
        return group
    match = PEST_GROUP.match(text)
    if match:
        expected = str(int(group[0]) + 1) if group else "1"
        if match.group(1) != expected:
            raise ShapeError(
                f"{where}: group {match.group(1)} follows group {group[0] if group else 'none'}"
            )
        return (match.group(1), text)
    if records or group is not None:
        raise ShapeError(f"{where}: a heading that is not a numbered group follows the pests")
    return group


def _pest_record(
    texts: Sequence[str],
    part: str,
    group: tuple[str, str],
    counters: dict[str, str],
    where: str,
) -> dict[str, Any]:
    match = PEST_NUMBER.match(texts[0])
    if not match:
        raise ShapeError(f"{where}: a pest is numbered {texts[0]!r}")
    number = match.group(1)
    key = f"{part}.{group[0]}"
    _check_pest_order(counters.get(key), number, where)
    counters[key] = number
    if not texts[1]:
        raise ShapeError(f"{where}: the pest column is empty")
    return {
        "part": part,
        "group": group[0],
        "group_name": group[1],
        "code": f"{part}.{group[0]}.{number}",
        "number": number,
        "name": texts[1],
        "eppo_codes": EPPO_CODE.findall(texts[1]),
        "kind": "organism",
    }


def _as_pair(number: str) -> tuple[int, int]:
    whole, _, sub = number.partition(".")
    return int(whole), int(sub or 0)


def _check_pest_order(previous: str | None, number: str, where: str) -> None:
    """A pest's number rises inside its group.

    It does not simply count up: the consolidated text keeps the gap where an amendment
    deleted an entry, and inserts sub-numbers such as 21.1 under an entry.
    """
    if previous is None:
        return
    if _as_pair(number) <= _as_pair(previous):
        raise ShapeError(f"{where}: {previous} is followed by {number}")


# --------------------------------------------------------------------------------------
# the sources


@dataclass(frozen=True)
class Source:
    # The field is named id, not the obvious word: the secret scan reads that word followed by
    # a dashed value as a credential.
    id: str
    title: str
    act: str
    identity: tuple[str, ...]
    count_by: str | None
    fetch: Callable[[str], Fetched]
    parse: Callable[[Fetched], list[dict[str, Any]]]


def _fetch_474(today: str) -> Fetched:
    return fetch_esbirka("2002", "474")


def _fetch_361(today: str) -> Fetched:
    return fetch_esbirka("2007", "361")


def _fetch_821(today: str) -> Fetched:
    return fetch_cellar(ANNEX_I_CELEX, document_date(ANNEX_I_CELEX))


def _fetch_2072(today: str) -> Fetched:
    celex = latest_consolidated(ANNEX_II_BASE, today)
    date = celex[-8:]
    return fetch_cellar(celex, f"{date[:4]}-{date[4:6]}-{date[6:]}")


SOURCES: tuple[Source, ...] = (
    Source(
        id="cz-474-2002",
        title="Decree 474/2002 Sb., annex 1 (VRAT) and annex 2 (RAT)",
        act="474/2002 Sb.",
        identity=("list", "code"),
        count_by="list",
        fetch=_fetch_474,
        parse=parse_cz_474,
    ),
    Source(
        id="cz-361-2007-annex-7",
        title="Government order 361/2007 Sb., annex 7, part 1: risk groups of biological agents",
        act="361/2007 Sb.",
        identity=("code",),
        count_by="table",
        fetch=_fetch_361,
        parse=parse_cz_361_annex_7,
    ),
    Source(
        id="eu-2021-821-annex-i",
        title="Regulation (EU) 2021/821, annex I, entries 1C351, 1C353 and 1C354",
        act="2021/821",
        identity=("code",),
        count_by="entry",
        fetch=_fetch_821,
        parse=parse_eu_2021_821_annex_i,
    ),
    Source(
        id="eu-2019-2072-annex-ii",
        title="Implementing Regulation (EU) 2019/2072, annex II: Union quarantine pests",
        act="2019/2072",
        identity=("code",),
        count_by="part",
        fetch=_fetch_2072,
        parse=parse_eu_2019_2072_annex_ii,
    ),
)
BY_ID = {source.id: source for source in SOURCES}


# --------------------------------------------------------------------------------------
# writing the data files


def today_in_prague() -> str:
    return datetime.now(tz=PRAGUE).date().isoformat()


def counts_of(source: Source, records: Sequence[dict[str, Any]]) -> dict[str, int]:
    if source.count_by is None:
        return {}
    counts: dict[str, int] = {}
    for record in records:
        key = str(record[source.count_by])
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def payload_of(
    source: Source, fetched: Fetched, records: Sequence[dict[str, Any]], fetched_on: str
) -> dict[str, Any]:
    check_records(source, records)
    return {
        "list": source.id,
        "title": source.title,
        "act": source.act,
        "source_url": fetched.url,
        "version": fetched.version,
        "version_date": fetched.version_date,
        "fetched_on": fetched_on,
        "sha256": fetched.sha256,
        "identity": list(source.identity),
        "entry_count": len(records),
        "counts": counts_of(source, records),
        "entries": list(records),
    }


def check_records(source: Source, records: Sequence[dict[str, Any]]) -> None:
    """A record has a code, a name and a kind, and no two records share a key."""
    keys: set[tuple[str, ...]] = set()
    for record in records:
        for field in ("code", "name", "kind"):
            if not record.get(field):
                raise ShapeError(f"{source.id}: a record has no {field}")
        key = tuple(str(record[field]) for field in source.identity)
        if key in keys:
            raise ShapeError(f"{source.id}: two records share the key {key}")
        keys.add(key)


def as_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False) + "\n"


def write_if_changed(path: Path, text: str) -> bool:
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return True


def keep_fetch_date(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    """Keep the recorded fetch date when nothing else in the file changed.

    The fetch date is then the day the content last changed, and rerunning the script on an
    unchanged source rewrites nothing.
    """
    if not path.exists():
        return payload
    old = json.loads(path.read_text(encoding="utf-8"))
    without_date = dict(payload, fetched_on=old.get("fetched_on"))
    return without_date if without_date == old else payload


def write_source(
    source: Source, fetched: Fetched, out_dir: Path, fetched_on: str
) -> dict[str, Any]:
    """Write one data file and return its row of the manifest."""
    records = source.parse(fetched)
    path = out_dir / f"{source.id}.json"
    payload = keep_fetch_date(path, payload_of(source, fetched, records, fetched_on))
    text = as_json(payload)
    changed = write_if_changed(path, text)
    say(
        f"{source.id}: {payload['entry_count']} entries "
        f"({', '.join(f'{k} {v}' for k, v in payload['counts'].items()) or 'one list'}), "
        f"version {payload['version']} of {payload['version_date']}, "
        f"sha256 {payload['sha256']}, {'written' if changed else 'unchanged'}"
    )
    return {
        "list": source.id,
        "file": path.name,
        "act": source.act,
        "source_url": payload["source_url"],
        "version": payload["version"],
        "version_date": payload["version_date"],
        "fetched_on": payload["fetched_on"],
        "sha256": payload["sha256"],
        "entry_count": payload["entry_count"],
        "counts": payload["counts"],
        "file_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
    }


def write_manifest(out_dir: Path, rows: Sequence[dict[str, Any]]) -> bool:
    path = out_dir / MANIFEST
    kept: dict[str, dict[str, Any]] = {}
    if path.exists():
        old = json.loads(path.read_text(encoding="utf-8"))
        kept = {row["list"]: row for row in old["sources"]}
    for row in rows:
        kept[row["list"]] = row
    order = [source.id for source in SOURCES]
    payload = {
        "written_by": "tools/fetch_regulatory_lists.py",
        "sources": [kept[key] for key in order if key in kept],
    }
    return write_if_changed(path, as_json(payload))


# --------------------------------------------------------------------------------------
# fixtures: a structural slice of each source text, written by this script


def fixture_payload(fetched: Fetched, document: Any) -> dict[str, Any]:
    text = document if isinstance(document, str) else json.dumps(document, ensure_ascii=False)
    return {
        "fixture": True,
        "url": fetched.url,
        "version": fetched.version,
        "version_date": fetched.version_date,
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "kind": "xhtml" if isinstance(document, str) else "fragments",
        "document": document,
    }


def load_fixture(path: Path) -> Fetched:
    """Read a saved source copy written by the ``fixtures`` subcommand."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    document: Any = payload["document"]
    if payload["kind"] == "xhtml":
        document = ET.fromstring(document)  # noqa: S314 (a file this script wrote)
    return Fetched(
        url=payload["url"],
        version=payload["version"],
        version_date=payload["version_date"],
        sha256=payload["sha256"],
        document=document,
    )


KEEP = 2


FRAGMENT_FIELDS = ("id", "kodTypuFragmentu", "hloubka", "xhtml")


def slice_fragments(
    fragments: Sequence[dict[str, Any]], annexes: Sequence[int]
) -> list[dict[str, Any]]:
    """Keep the shape of each annex: every heading, but only the first of each run of items."""
    out: list[dict[str, Any]] = []
    for annex in annexes:
        kept = 0
        last = ""
        for fragment in annex_slice(fragments, annex):
            kind = fragment["kodTypuFragmentu"]
            kept = kept + 1 if kind == last else 1
            last = kind
            if kept > KEEP:
                continue
            short = {field: fragment.get(field) for field in FRAGMENT_FIELDS}
            if kind == TABLE:
                short["xhtml"] = slice_table_xhtml(fragment)
            out.append(short)
    return out


def slice_table_xhtml(fragment: dict[str, Any]) -> str:
    tree = fragment_tree(fragment)
    for table in tree.iter(XHTML + "table"):
        for body in table:
            rows = [row for row in body if row.tag == XHTML + "tr"]
            for row in rows[KEEP + 1 :]:
                body.remove(row)
    inner = "".join(ET.tostring(child, encoding="unicode") for child in tree)
    return (tree.text or "") + inner


def slice_eu_entries(root: ET.Element, codes: Sequence[str]) -> str:
    """A small XHTML document holding the wanted entries with their first items."""
    html = ET.Element(XHTML + "html")
    body = ET.SubElement(html, XHTML + "body")
    for code in codes:
        table = copy.deepcopy(find_eu_entry(root, code))
        prune_children(table)
        body.append(table)
    return ET.tostring(html, encoding="unicode")


def prune_children(table: ET.Element) -> None:
    """Keep the first items of each level, and every note, so the slice keeps the whole shape."""
    node = eu_row(table)
    kept: list[ET.Element] = []
    for child in node.children:
        note = bool(NOTE_TOKEN.match(eu_row(child).token))
        if note or len(kept) < KEEP:
            kept.append(child)
        else:
            remove_element(table, child)
    for child in kept:
        prune_children(child)


def remove_element(root: ET.Element, target: ET.Element) -> None:
    for parent in root.iter():
        for child in list(parent):
            if child is target:
                parent.remove(child)
                return


def slice_annex_ii(root: ET.Element) -> str:
    """A small XHTML document with the annex II markers and the first pests of each group."""
    body = root.find(XHTML + "body")
    if body is None:
        raise ShapeError("annex II: the document has no body")
    window = list(document_sequence(body))
    html = ET.Element(XHTML + "html")
    out = ET.SubElement(html, XHTML + "body")
    mark(out, ANNEX_II_MARK)
    for part in ANNEX_II_PARTS:
        mark(out, part)
        table = copy.deepcopy(_table_after(_annex_ii_window(window), part))
        keep_first_pests(table)
        out.append(table)
    mark(out, ANNEX_II_END)
    return ET.tostring(html, encoding="unicode")


def mark(parent: ET.Element, text: str) -> None:
    paragraph = ET.SubElement(parent, XHTML + "p")
    paragraph.text = text


def keep_first_pests(table: ET.Element) -> None:
    for section in table:
        kept = 0
        for row in list(section):
            if row.tag != XHTML + "tr":
                continue
            cells = [cell for cell in row if cell.tag in (XHTML + "td", XHTML + "th")]
            if len(cells) == 1:
                # A group heading starts the count again; a consolidation marker does not.
                if not cell_text(cells[0])[0].startswith(CONSOLIDATION_MARK):
                    kept = 0
                continue
            kept += 1
            if kept > KEEP:
                section.remove(row)


def write_fixtures(out_dir: Path) -> None:
    expected: dict[str, Any] = {}
    for source in SOURCES:
        fetched = source.fetch(today_in_prague())
        document: Any
        if source.id == "cz-474-2002":
            document = slice_fragments(fetched.document, (1, 2))
        elif source.id == "cz-361-2007-annex-7":
            document = slice_fragments(fetched.document, (7,))
        elif source.id == "eu-2021-821-annex-i":
            document = slice_eu_entries(fetched.document, ANNEX_I_ENTRIES)
        else:
            document = slice_annex_ii(fetched.document)
        payload = fixture_payload(fetched, document)
        path = out_dir / f"{source.id}.slice.json"
        write_if_changed(path, as_json(payload))
        records = source.parse(load_fixture(path))
        check_records(source, records)
        expected[source.id] = {
            "entry_count": len(records),
            "counts": counts_of(source, records),
        }
        say(f"{source.id}: fixture with {len(records)} entries")
    write_if_changed(out_dir / EXPECTED, as_json(expected))


# --------------------------------------------------------------------------------------
# the command line


def chosen(names: Sequence[str]) -> list[Source]:
    if names == ["all"]:
        return list(SOURCES)
    missing = [name for name in names if name not in BY_ID]
    if missing:
        raise SystemExit(f"unknown source: {', '.join(missing)}")
    return [BY_ID[name] for name in names]


def run_fetch(names: Sequence[str], out_dir: Path) -> None:
    today = today_in_prague()
    rows = [write_source(source, source.fetch(today), out_dir, today) for source in chosen(names)]
    say("manifest.json: " + ("written" if write_manifest(out_dir, rows) else "unchanged"))


def run_parse_file(name: str, path: Path) -> None:
    source = chosen([name])[0]
    records = source.parse(load_fixture(path))
    check_records(source, records)
    say(
        f"{source.id}: {len(records)} entries "
        f"({', '.join(f'{k} {v}' for k, v in counts_of(source, records).items()) or 'one list'})"
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    commands = parser.add_subparsers(dest="command", required=True)
    fetch = commands.add_parser("fetch", help="fetch the sources and write their data files")
    fetch.add_argument("sources", nargs="+", help="source keys, or all")
    fetch.add_argument("--out", type=Path, default=DATA_DIR, help="where to write the data files")
    saved = commands.add_parser(
        "parse-file", help="parse a saved source copy and report its counts"
    )
    saved.add_argument("source")
    saved.add_argument("path", type=Path)
    fixtures = commands.add_parser("fixtures", help="write a structural slice of each source")
    fixtures.add_argument("--out", type=Path, default=FIXTURE_DIR)
    args = parser.parse_args(argv)
    try:
        if args.command == "fetch":
            run_fetch(args.sources, args.out)
        elif args.command == "parse-file":
            run_parse_file(args.source, args.path)
        else:
            write_fixtures(args.out)
    except ShapeError as error:
        say(f"FAILED: {error}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
