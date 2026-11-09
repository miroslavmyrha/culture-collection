"""The data files of the official lists, and the strictness of the parsers that wrote them.

Nothing here fetches anything. The data files are read as they are committed, and the parsers
run against the saved source slices in ``fixtures/``, which ``fetch_regulatory_lists.py
fixtures`` writes from the real texts.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import xml.etree.ElementTree as ET
from collections.abc import Callable
from pathlib import Path
from typing import Any, NamedTuple

import pytest

from tools.fetch_regulatory_lists import (
    BY_ID,
    DATA_DIR,
    EXPECTED,
    FIXTURE_DIR,
    MANIFEST,
    SOURCES,
    XHTML,
    Fetched,
    ShapeError,
    Source,
    cell_text,
    check_records,
    eu_row,
    find_eu_entry,
    fragment_tree,
    load_fixture,
    own_text,
    write_source,
)
from tools.tests.support import fixture_path, read_json, xhtml

IDS = [source.id for source in SOURCES]

# The fragment type codes and depths the e-Sbirka texts of these two acts print, named here so
# a reshape says what it changes in the source rather than which constant the parser reads.
ANNEX_HEADER = "Hlavicka_priloha"
HEADING = "Obecny_text"
ITEM = "Bod_Dd"
NOTE = "Odrazka_Db"
TABLE = "Tabulka"
TABLE_HEADING = "Nadpis"
PART_DEPTH = 4
GROUP_DEPTH = 5
ITEM_DEPTH_UNDER_PART = 5


@pytest.fixture(scope="module")
def manifest() -> dict[str, Any]:
    rows = read_json(DATA_DIR / MANIFEST)["sources"]
    return {row["list"]: row for row in rows}


@pytest.fixture(scope="module")
def expected() -> dict[str, Any]:
    return dict(read_json(FIXTURE_DIR / EXPECTED))


# --------------------------------------------------------------------------------------
# the data files against the manifest


def test_the_manifest_lists_every_data_file(manifest: dict[str, Any]) -> None:
    written = {path.name for path in DATA_DIR.glob("*.json")} - {MANIFEST}
    assert written == {row["file"] for row in manifest.values()}
    assert set(manifest) == set(IDS)


@pytest.mark.parametrize("key", IDS)
def test_a_data_file_carries_what_the_manifest_records(key: str, manifest: dict[str, Any]) -> None:
    row = manifest[key]
    path = DATA_DIR / row["file"]
    raw = path.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == row["file_sha256"]
    payload = json.loads(raw.decode("utf-8"))
    for field in ("source_url", "version", "version_date", "fetched_on", "sha256", "counts"):
        assert payload[field] == row[field], field
    assert payload["entry_count"] == row["entry_count"] == len(payload["entries"])


@pytest.mark.parametrize("key", IDS)
def test_a_data_file_carries_its_provenance(key: str) -> None:
    payload = read_json(DATA_DIR / f"{key}.json")
    assert payload["source_url"].startswith(
        ("https://e-sbirka.gov.cz/", "http://publications.europa.eu/")
    )
    assert payload["version"]
    for field in ("version_date", "fetched_on"):
        assert len(payload[field]) == len("2026-01-01")
        assert payload[field].count("-") == 2
    assert len(payload["sha256"]) == 64
    assert int(payload["sha256"], 16) >= 0


@pytest.mark.parametrize("key", IDS)
def test_every_record_of_a_data_file_is_whole(key: str) -> None:
    payload = read_json(DATA_DIR / f"{key}.json")
    entries = payload["entries"]
    assert entries
    keys: set[tuple[str, ...]] = set()
    for record in entries:
        assert record["code"], record
        assert record["name"], record["code"]
        assert record["kind"] in {"organism", "toxin", "genetic_element"}, record["code"]
        assert any(value not in (None, "", [], {}) for value in record.values())
        identity = tuple(str(record[field]) for field in payload["identity"])
        assert "" not in identity
        assert identity not in keys, identity
        keys.add(identity)
    assert len(keys) == payload["entry_count"]


@pytest.mark.parametrize("key", IDS)
def test_the_counts_add_up_to_the_entry_count(key: str) -> None:
    payload = read_json(DATA_DIR / f"{key}.json")
    assert sum(payload["counts"].values()) == payload["entry_count"]


# --------------------------------------------------------------------------------------
# the parsers against a saved source text


@pytest.mark.parametrize("key", IDS)
def test_a_parser_reads_a_saved_source_text(key: str, expected: dict[str, Any]) -> None:
    source = BY_ID[key]
    records = source.parse(load_fixture(fixture_path(key)))
    counts: dict[str, int] = {}
    for record in records:
        where = str(record[source.count_by]) if source.count_by else ""
        counts[where] = counts.get(where, 0) + 1
    assert len(records) == expected[key]["entry_count"]
    assert counts == expected[key]["counts"]


# --------------------------------------------------------------------------------------
# the parsers refuse a reshaped source text

Reshape = Callable[[Fetched], Fetched]


def reshaped(fetched: Fetched, document: Any) -> Fetched:
    return Fetched(
        url=fetched.url,
        version=fetched.version,
        version_date=fetched.version_date,
        sha256=fetched.sha256,
        document=document,
    )


def fragments_of(fetched: Fetched, kind: str) -> list[dict[str, Any]]:
    return [f for f in fetched.document if f["kodTypuFragmentu"] == kind]


def without_the_annex_heading(fetched: Fetched) -> Fetched:
    kept = [f for f in copy.deepcopy(fetched.document) if f["kodTypuFragmentu"] != ANNEX_HEADER]
    return reshaped(fetched, kept)


def without_the_first_annex_heading(fetched: Fetched) -> Fetched:
    """Only the first annex loses its header, so the other annexes are still found."""
    kept = copy.deepcopy(fetched.document)
    for index, fragment in enumerate(kept):
        if fragment["kodTypuFragmentu"] == ANNEX_HEADER:
            del kept[index]
            break
    return reshaped(fetched, kept)


def with_an_item_renumbered(fetched: Fetched) -> Fetched:
    document = copy.deepcopy(fetched.document)
    first = fragments_of(reshaped(fetched, document), ITEM)[0]
    first["xhtml"] = first["xhtml"].replace("1.", "4.", 1)
    return reshaped(fetched, document)


def with_an_item_moved_deeper(fetched: Fetched) -> Fetched:
    document = copy.deepcopy(fetched.document)
    fragments_of(reshaped(fetched, document), ITEM)[0]["hloubka"] = 9
    return reshaped(fetched, document)


def with_a_part_heading_unnamed(fetched: Fetched) -> Fetched:
    document = copy.deepcopy(fetched.document)
    for fragment in document:
        if fragment["kodTypuFragmentu"] == HEADING and fragment["hloubka"] == PART_DEPTH:
            fragment["xhtml"] = "<p>IX. </p>"
            break
    return reshaped(fetched, document)


def with_a_table_column_dropped(fetched: Fetched) -> Fetched:
    document = copy.deepcopy(fetched.document)
    fragment = fragments_of(reshaped(fetched, document), TABLE)[0]
    tree = fragment_tree(fragment)
    for row in tree.iter(XHTML + "tr"):
        cells = cells_of(row)
        row.remove(cells[-1])
    fragment["xhtml"] = "".join(ET.tostring(child, encoding="unicode") for child in tree)
    return reshaped(fetched, document)


def with_the_group_column_renamed(fetched: Fetched) -> Fetched:
    document = copy.deepcopy(fetched.document)
    table = fragments_of(reshaped(fetched, document), TABLE)[0]
    table["xhtml"] = table["xhtml"].replace("Skupina", "Trida", 1)
    return reshaped(fetched, document)


def with_a_table_dropped(fetched: Fetched) -> Fetched:
    document = copy.deepcopy(fetched.document)
    for index, fragment in enumerate(document):
        if fragment["kodTypuFragmentu"] == TABLE:
            del document[index]
            break
    return reshaped(fetched, document)


def rows_of(table: ET.Element) -> list[ET.Element]:
    return list(table.iter(XHTML + "tr"))


def cells_of(row: ET.Element) -> list[ET.Element]:
    return [cell for cell in row if cell.tag in (XHTML + "td", XHTML + "th")]


def without_an_entry_code(fetched: Fetched) -> Fetched:
    root = copy.deepcopy(fetched.document)
    for cell in root.iter(XHTML + "td"):
        if (cell.text or "").strip() == "1C353":
            cell.text = "1C999"
    for span in root.iter(XHTML + "p"):
        if (span.text or "").strip() == "1C353":
            span.text = "1C999"
    return reshaped(fetched, root)


def with_an_unknown_category(fetched: Fetched) -> Fetched:
    root = copy.deepcopy(fetched.document)
    first = next(iter(root.iter(XHTML + "table")))
    last_cell = cells_of(rows_of(first)[0])[-1]
    for element in last_cell.iter():
        if element.tag != XHTML + "table":
            element.text = "Something the parser does not know, as follows:"
            break
    return reshaped(fetched, root)


def retoken(cell: ET.Element, value: str) -> None:
    """Write a new number or letter into the cell that holds an item's numbering."""
    for element in cell.iter():
        if (element.text or "").strip():
            element.text = value
            return
    raise AssertionError("the numbering cell holds no text")


def with_an_item_of_an_entry_renumbered(fetched: Fetched) -> Fetched:
    """The second item under 1C351.a is numbered as if two items before it were missing."""
    root = copy.deepcopy(fetched.document)
    entry = find_eu_entry(root, "1C351")
    letter = eu_row(entry).children[0]
    second = eu_row(letter).children[1]
    retoken(cells_of(rows_of(second)[0])[0], "4.")
    return reshaped(fetched, root)


def with_a_pest_group_renumbered(fetched: Fetched) -> Fetched:
    """The second group of part A is numbered as if groups were missing before it."""
    root = copy.deepcopy(fetched.document)
    table = next(iter(root.iter(XHTML + "table")))
    headings = [
        cells_of(row)[0]
        for row in rows_of(table)
        if len(cells_of(row)) == 1 and re.match(r"^\d+\.\s", cell_text(cells_of(row)[0])[0])
    ]
    assert len(headings) >= 2, "the slice must hold two group headings, or the case proves nothing"
    for element in headings[1].iter():
        if re.match(r"^\s*\d+\.", element.text or ""):
            element.text = re.sub(r"^\s*\d+\.", "5.", element.text or "")
            return reshaped(fetched, root)
    raise AssertionError("the group heading holds no number")


def without_part_b(fetched: Fetched) -> Fetched:
    root = copy.deepcopy(fetched.document)
    for paragraph in root.iter(XHTML + "p"):
        if (paragraph.text or "").strip() == "PART B":
            paragraph.text = "PART C"
    return reshaped(fetched, root)


def with_a_paragraph_before_the_part_table(fetched: Fetched) -> Fetched:
    """Something printed between a part heading and its table."""
    root = copy.deepcopy(fetched.document)
    body = root.find(XHTML + "body")
    assert body is not None
    for index, child in enumerate(list(body)):
        if child.tag == XHTML + "p" and (child.text or "").strip() == "PART A":
            spacer = ET.Element(XHTML + "p")
            spacer.text = "Something the parser does not expect here"
            body.insert(index + 1, spacer)
            break
    return reshaped(fetched, root)


def with_pests_out_of_order(fetched: Fetched) -> Fetched:
    root = copy.deepcopy(fetched.document)
    table = next(iter(root.iter(XHTML + "table")))
    for section in table:
        pests = [row for row in section if row.tag == XHTML + "tr" and len(cells_of(row)) == 2]
        if len(pests) >= 2:
            first, second = pests[0], pests[1]
            index = list(section).index(first)
            section.remove(second)
            section.insert(index, second)
            break
    return reshaped(fetched, root)


# --------------------------------------------------------------------------------------
# more reshapes: decree 474/2002


def serialised(tree: ET.Element) -> str:
    """A fragment tree written back as the XHTML snippet an e-Sbirka fragment carries."""
    return "".join(ET.tostring(child, encoding="unicode") for child in tree)


def index_of(document: list[dict[str, Any]], kind: str, depth: int | None = None) -> int:
    for index, fragment in enumerate(document):
        if fragment["kodTypuFragmentu"] == kind and depth in (None, fragment["hloubka"]):
            return index
    raise AssertionError(f"the slice holds no {kind} fragment at depth {depth}")


def annex_end(document: list[dict[str, Any]]) -> int:
    """Where the first annex ends, so a reshape stays inside annex 1."""
    return [i for i, f in enumerate(document) if f["kodTypuFragmentu"] == ANNEX_HEADER][1]


def _as_notes(document: list[dict[str, Any]]) -> int:
    """Print the first note of annex 1 at the depth of a part, and say where it now sits.

    The notes of annex 1 and 2 are printed at the depth of a part and carry no roman number:
    that is how the parser knows the parts have ended.
    """
    at = index_of(document, NOTE, PART_DEPTH)
    document[at]["kodTypuFragmentu"] = HEADING
    return at


def with_the_notes_at_the_depth_of_a_part(fetched: Fetched) -> Fetched:
    document = copy.deepcopy(fetched.document)
    _as_notes(document)
    return reshaped(fetched, document)


def with_a_part_heading_after_the_notes(fetched: Fetched) -> Fetched:
    document = copy.deepcopy(fetched.document)
    at = _as_notes(document)
    document.insert(at + 1, copy.deepcopy(document[index_of(document, HEADING, PART_DEPTH)]))
    return reshaped(fetched, document)


def with_an_item_after_the_notes(fetched: Fetched) -> Fetched:
    document = copy.deepcopy(fetched.document)
    at = _as_notes(document)
    document.insert(at + 1, copy.deepcopy(document[index_of(document, ITEM)]))
    return reshaped(fetched, document)


def with_an_item_before_the_first_part(fetched: Fetched) -> Fetched:
    document = copy.deepcopy(fetched.document)
    document.insert(1, copy.deepcopy(document[index_of(document, ITEM)]))
    return reshaped(fetched, document)


def with_a_group_heading_before_the_first_part(fetched: Fetched) -> Fetched:
    """A heading at the depth of a group, printed before any part, groups nothing."""
    document = copy.deepcopy(fetched.document)
    document.insert(1, copy.deepcopy(document[index_of(document, HEADING, GROUP_DEPTH)]))
    return reshaped(fetched, document)


def with_an_item_not_numbered(fetched: Fetched) -> Fetched:
    document = copy.deepcopy(fetched.document)
    item = document[index_of(document, ITEM)]
    item["xhtml"] = re.sub(r"<var>.*?</var>", "<var>x</var>", item["xhtml"], count=1)
    return reshaped(fetched, document)


def with_a_second_marked_name(fetched: Fetched) -> Fetched:
    document = copy.deepcopy(fetched.document)
    item = document[index_of(document, ITEM)]
    item["xhtml"] = item["xhtml"] + "<var>and another marked name</var>"
    return reshaped(fetched, document)


def without_any_numbered_item(fetched: Fetched) -> Fetched:
    kept = [f for f in copy.deepcopy(fetched.document) if f["kodTypuFragmentu"] != ITEM]
    return reshaped(fetched, kept)


def with_a_part_heading_twice(fetched: Fetched) -> Fetched:
    document = copy.deepcopy(fetched.document)
    at = index_of(document, HEADING, PART_DEPTH)
    document.insert(at + 1, copy.deepcopy(document[at]))
    return reshaped(fetched, document)


def without_the_last_part(fetched: Fetched) -> Fetched:
    document = copy.deepcopy(fetched.document)
    parts = [
        i
        for i, f in enumerate(document[: annex_end(document)])
        if f["kodTypuFragmentu"] == HEADING and f["hloubka"] == PART_DEPTH
    ]
    del document[parts[-1]]
    return reshaped(fetched, document)


def with_an_item_under_the_last_part(fetched: Fetched) -> Fetched:
    """A numbered item under part IV, which lists genetic elements and never numbered them."""
    document = copy.deepcopy(fetched.document)
    end = annex_end(document)
    parts = [
        i
        for i, f in enumerate(document[:end])
        if f["kodTypuFragmentu"] == HEADING and f["hloubka"] == PART_DEPTH
    ]
    item = copy.deepcopy(document[index_of(document[:end], ITEM, ITEM_DEPTH_UNDER_PART)])
    document.insert(parts[-1] + 1, item)
    return reshaped(fetched, document)


# --------------------------------------------------------------------------------------
# more reshapes: government order 361/2007, annex 7


def without_the_first_table_heading(fetched: Fetched) -> Fetched:
    document = copy.deepcopy(fetched.document)
    del document[index_of(document, TABLE_HEADING)]
    return reshaped(fetched, document)


def with_a_table_heading_that_names_nothing(fetched: Fetched) -> Fetched:
    document = copy.deepcopy(fetched.document)
    document[index_of(document, TABLE_HEADING)]["xhtml"] = "<p>Tabulka č. 1</p>"
    return reshaped(fetched, document)


def with_two_tables_in_one_fragment(fetched: Fetched) -> Fetched:
    document = copy.deepcopy(fetched.document)
    fragment = document[index_of(document, TABLE)]
    fragment["xhtml"] = fragment["xhtml"] + fragment["xhtml"]
    return reshaped(fetched, document)


def with_a_table_of_one_row(fetched: Fetched) -> Fetched:
    document = copy.deepcopy(fetched.document)
    fragment = document[index_of(document, TABLE)]
    tree = fragment_tree(fragment)
    for section in tree.iter(XHTML + "tbody"):
        for row in rows_of(section)[1:]:
            section.remove(row)
    fragment["xhtml"] = serialised(tree)
    return reshaped(fetched, document)


def with_a_cell_rewritten(fetched: Fetched, column: int, text: str) -> Fetched:
    """The first agent row of the first table, with one of its three cells rewritten."""
    document = copy.deepcopy(fetched.document)
    fragment = document[index_of(document, TABLE)]
    tree = fragment_tree(fragment)
    cell = cells_of(rows_of(tree)[1])[column]
    for child in list(cell):
        cell.remove(child)
    cell.text = text
    fragment["xhtml"] = serialised(tree)
    return reshaped(fetched, document)


def with_the_agent_column_emptied(fetched: Fetched) -> Fetched:
    return with_a_cell_rewritten(fetched, 0, "")


def with_the_group_column_unreadable(fetched: Fetched) -> Fetched:
    return with_a_cell_rewritten(fetched, 1, "two")


def with_the_note_column_unreadable(fetched: Fetched) -> Fetched:
    return with_a_cell_rewritten(fetched, 2, "see below")


# --------------------------------------------------------------------------------------
# more reshapes: Regulation (EU) 2021/821, annex I


def blank_own_text(cell: ET.Element) -> None:
    """Take a cell's own text away, keeping the item tables printed inside it."""

    def walk(node: ET.Element) -> None:
        node.text = None
        for child in list(node):
            child.tail = None
            if child.tag != XHTML + "table":
                walk(child)

    walk(cell)


def retoken_item(item: ET.Element, value: str) -> None:
    """Write a new numbering into the cell of an item table that prints its number."""
    token = eu_row(item).token
    for cell in cells_of(rows_of(item)[0])[:-1]:
        if token and own_text(cell) == token:
            retoken(cell, value)
            return
    raise AssertionError("the item prints no numbering")


def with_the_entry_row_numbered(fetched: Fetched) -> Fetched:
    """The row of entry 1C351 numbered as if the entry were an item of a list."""
    root = copy.deepcopy(fetched.document)
    cells_of(rows_of(find_eu_entry(root, "1C351"))[0])[0].text = "x"
    return reshaped(fetched, root)


def with_an_item_of_an_entry_emptied(fetched: Fetched) -> Fetched:
    root = copy.deepcopy(fetched.document)
    letter = eu_row(find_eu_entry(root, "1C351")).children[0]
    blank_own_text(cells_of(rows_of(letter)[0])[-1])
    return reshaped(fetched, root)


def with_an_item_of_an_entry_unreadable(fetched: Fetched) -> Fetched:
    root = copy.deepcopy(fetched.document)
    retoken_item(eu_row(find_eu_entry(root, "1C351")).children[0], "x)")
    return reshaped(fetched, root)


# --------------------------------------------------------------------------------------
# more reshapes: Implementing Regulation (EU) 2019/2072, annex II


def part_a_table(root: ET.Element) -> ET.Element:
    return next(iter(root.iter(XHTML + "table")))


def pest_rows(table: ET.Element) -> list[ET.Element]:
    return [row for row in rows_of(table) if len(cells_of(row)) == 2]


def group_headings(table: ET.Element) -> list[ET.Element]:
    return [
        row
        for row in rows_of(table)
        if len(cells_of(row)) == 1 and re.match(r"^\d+\.\s", cell_text(cells_of(row)[0])[0])
    ]


def remove_row(table: ET.Element, row: ET.Element) -> None:
    for section in table:
        if row in list(section):
            section.remove(row)
            return
    raise AssertionError("the row is not in the table")


def without_the_annex_mark(fetched: Fetched) -> Fetched:
    root = copy.deepcopy(fetched.document)
    for paragraph in root.iter(XHTML + "p"):
        if (paragraph.text or "").strip() == "ANNEX II":
            paragraph.text = "ANNEX IIa"
    return reshaped(fetched, root)


def with_a_third_cell_in_a_pest_row(fetched: Fetched) -> Fetched:
    root = copy.deepcopy(fetched.document)
    row = pest_rows(part_a_table(root))[0]
    ET.SubElement(row, XHTML + "td").text = "a column the annex does not print"
    return reshaped(fetched, root)


def without_the_first_group_heading(fetched: Fetched) -> Fetched:
    root = copy.deepcopy(fetched.document)
    table = part_a_table(root)
    remove_row(table, group_headings(table)[0])
    return reshaped(fetched, root)


def without_any_pest(fetched: Fetched) -> Fetched:
    root = copy.deepcopy(fetched.document)
    table = part_a_table(root)
    for row in pest_rows(table):
        remove_row(table, row)
    return reshaped(fetched, root)


def with_an_unnumbered_heading_after_the_pests(fetched: Fetched) -> Fetched:
    root = copy.deepcopy(fetched.document)
    headings = group_headings(part_a_table(root))
    assert len(headings) >= 2, "the slice must hold two group headings, or the case proves nothing"
    cell = cells_of(headings[1])[0]
    blank_own_text(cell)
    cell.text = "A heading that numbers no group"
    return reshaped(fetched, root)


def with_a_pest_unnumbered(fetched: Fetched) -> Fetched:
    root = copy.deepcopy(fetched.document)
    retoken(cells_of(pest_rows(part_a_table(root))[0])[0], "x")
    return reshaped(fetched, root)


def with_the_pest_column_emptied(fetched: Fetched) -> Fetched:
    root = copy.deepcopy(fetched.document)
    blank_own_text(cells_of(pest_rows(part_a_table(root))[0])[1])
    return reshaped(fetched, root)


class Case(NamedTuple):
    """One reshaped source text and the refusal it must draw.

    ``refusal`` is matched against the message, so the case proves which guard refused. Asserting
    ShapeError alone proves nothing: a reshape that slips past its own check usually trips a
    later one, and then deleting the check leaves every test green (found in review).
    """

    source: str
    what: str
    reshape: Reshape
    refusal: str


CASES: tuple[Case, ...] = (
    Case(
        "cz-474-2002",
        "no annex header at all",
        without_the_annex_heading,
        r"^the text has no annex headers$",
    ),
    Case(
        "cz-474-2002",
        "the header of annex 1 gone",
        without_the_first_annex_heading,
        r"^the text has no annex 1$",
    ),
    Case(
        "cz-474-2002",
        "an item renumbered",
        with_an_item_renumbered,
        r"^annex 1, group I\.I: the items are numbered 0 then 4$",
    ),
    Case(
        "cz-474-2002",
        "an item at another depth",
        with_an_item_moved_deeper,
        r"^annex 1, part I: a numbered item sits at depth 9, expected 6$",
    ),
    Case(
        "cz-474-2002",
        "a part heading that names no kind",
        with_a_part_heading_unnamed,
        r"^part IX: its heading matches 0 of the known kinds, expected one$",
    ),
    Case(
        "cz-474-2002",
        "a part heading after the notes",
        with_a_part_heading_after_the_notes,
        r"^annex 1: a part heading follows the notes$",
    ),
    Case(
        "cz-474-2002",
        "a numbered item after the notes",
        with_an_item_after_the_notes,
        r"^annex 1: a numbered item follows the notes$",
    ),
    Case(
        "cz-474-2002",
        "a numbered item before the first part",
        with_an_item_before_the_first_part,
        r"^annex 1: a numbered item before the first part$",
    ),
    Case(
        "cz-474-2002",
        "an item that does not start with its number",
        with_an_item_not_numbered,
        r"^annex 1, part I: an item does not start with its number \(fragment .+\)$",
    ),
    Case(
        "cz-474-2002",
        "a second marked name in an item",
        with_a_second_marked_name,
        r"^annex 1, part I, item 1: 2 marked names, expected one$",
    ),
    Case(
        "cz-474-2002",
        "no numbered item at all",
        without_any_numbered_item,
        r"^annex 1: no numbered item at all$",
    ),
    Case(
        "cz-474-2002",
        "the same part twice",
        with_a_part_heading_twice,
        r"^annex 1: a part code appears twice \(I, I, II, III, IV\)$",
    ),
    Case(
        "cz-474-2002",
        "a part missing",
        without_the_last_part,
        r"^annex 1: its parts are I, II, III$",
    ),
    Case(
        "cz-474-2002",
        "a numbered item under part IV",
        with_an_item_under_the_last_part,
        r"^annex 1: part IV has numbered items, which it never had$",
    ),
    Case(
        "cz-361-2007-annex-7",
        "no annex header at all",
        without_the_annex_heading,
        r"^the text has no annex headers$",
    ),
    Case(
        "cz-361-2007-annex-7",
        "a table before any heading",
        without_the_first_table_heading,
        r"^annex 7: a table before any heading$",
    ),
    Case(
        "cz-361-2007-annex-7",
        "a table heading that names no kind",
        with_a_table_heading_that_names_nothing,
        r"^annex 7, table 1: its heading names no kind the parser knows$",
    ),
    Case(
        "cz-361-2007-annex-7",
        "two tables in one fragment",
        with_two_tables_in_one_fragment,
        r"^annex 7, table 1: 2 tables in one fragment$",
    ),
    Case(
        "cz-361-2007-annex-7",
        "a table with its agent rows gone",
        with_a_table_of_one_row,
        r"^annex 7, table 1: 1 rows$",
    ),
    Case(
        "cz-361-2007-annex-7",
        "the agent column empty",
        with_the_agent_column_emptied,
        r"^annex 7, table 1, row 1: the agent column is empty$",
    ),
    Case(
        "cz-361-2007-annex-7",
        "the group column unreadable",
        with_the_group_column_unreadable,
        r"^annex 7, table 1, row 1: the group column reads 'two'$",
    ),
    Case(
        "cz-361-2007-annex-7",
        "the note column unreadable",
        with_the_note_column_unreadable,
        r"^annex 7, table 1, row 1: the note column reads 'see below'$",
    ),
    Case(
        "cz-361-2007-annex-7",
        "a table with a column less",
        with_a_table_column_dropped,
        r"^annex 7, table 1: its rows have \[2\] cells, expected 3$",
    ),
    Case(
        "cz-361-2007-annex-7",
        "the group column renamed",
        with_the_group_column_renamed,
        r"^annex 7, table 1: its columns are headed .*expected the second 'Skupina'",
    ),
    Case(
        "cz-361-2007-annex-7",
        "a table missing",
        with_a_table_dropped,
        r"^annex 7, part 1: 4 tables, expected 5$",
    ),
    Case(
        "eu-2021-821-annex-i",
        "an entry code gone",
        without_an_entry_code,
        r"^annex I: entry 1C353 is not in the text$",
    ),
    Case(
        "eu-2021-821-annex-i",
        "a category the parser does not know",
        with_an_unknown_category,
        r"^annex I: entry 1C351 opens with a category the parser does not know$",
    ),
    Case(
        "eu-2021-821-annex-i",
        "an item of an entry renumbered",
        with_an_item_of_an_entry_renumbered,
        r"^annex I, entry 1C351: the items under 1C351\.a run 1 then 4$",
    ),
    Case(
        "eu-2021-821-annex-i",
        "the entry row numbered",
        with_the_entry_row_numbered,
        r"^annex I: entry 1C351 sits in a row numbered 'x'$",
    ),
    Case(
        "eu-2021-821-annex-i",
        "an item of an entry without text",
        with_an_item_of_an_entry_emptied,
        r"^annex I: item 1C351\.a has no text$",
    ),
    Case(
        "eu-2021-821-annex-i",
        "an item of an entry numbered in a way the parser cannot read",
        with_an_item_of_an_entry_unreadable,
        r"^annex I, entry 1C351: an item under 1C351 is numbered 'x\)'$",
    ),
    Case(
        "eu-2019-2072-annex-ii",
        "no ANNEX II mark",
        without_the_annex_mark,
        r"^the text has no ANNEX II followed by ANNEX III$",
    ),
    Case(
        "eu-2019-2072-annex-ii",
        "a third cell in a pest row",
        with_a_third_cell_in_a_pest_row,
        r"^annex II, part A, row \d+: 3 cells, expected one or 2$",
    ),
    Case(
        "eu-2019-2072-annex-ii",
        "a pest before the first group heading",
        without_the_first_group_heading,
        r"^annex II, part A, row \d+: a numbered pest before the first group heading$",
    ),
    Case(
        "eu-2019-2072-annex-ii",
        "no pest at all",
        without_any_pest,
        r"^annex II, part A: no numbered pest at all$",
    ),
    Case(
        "eu-2019-2072-annex-ii",
        "a heading that numbers no group after the pests",
        with_an_unnumbered_heading_after_the_pests,
        r"^annex II, part A, row \d+: a heading that is not a numbered group follows the pests$",
    ),
    Case(
        "eu-2019-2072-annex-ii",
        "a pest numbered in a way the parser cannot read",
        with_a_pest_unnumbered,
        r"^annex II, part A, row \d+: a pest is numbered 'x'$",
    ),
    Case(
        "eu-2019-2072-annex-ii",
        "the pest column empty",
        with_the_pest_column_emptied,
        r"^annex II, part A, row \d+: the pest column is empty$",
    ),
    Case(
        "eu-2019-2072-annex-ii",
        "a pest group renumbered",
        with_a_pest_group_renumbered,
        r"^annex II, part A, row \d+: group 5 follows group 1$",
    ),
    Case(
        "eu-2019-2072-annex-ii",
        "no part B",
        without_part_b,
        r"^annex II: it has no PART B$",
    ),
    Case(
        "eu-2019-2072-annex-ii",
        "something between part A and its table",
        with_a_paragraph_before_the_part_table,
        r"^annex II: PART A is not followed by a table$",
    ),
    Case(
        "eu-2019-2072-annex-ii",
        "two pests swapped",
        with_pests_out_of_order,
        r"^annex II, part A, row 5: 2 is followed by 1$",
    ),
)


@pytest.mark.parametrize("case", CASES, ids=[f"{c.source}: {c.what}" for c in CASES])
def test_a_parser_refuses_a_reshaped_source(case: Case) -> None:
    source = BY_ID[case.source]
    fetched = load_fixture(fixture_path(case.source))
    assert source.parse(fetched), "the saved text itself must parse, or the case proves nothing"
    with pytest.raises(ShapeError, match=case.refusal):
        source.parse(case.reshape(fetched))


# --------------------------------------------------------------------------------------
# what the parsers read past without refusing

Unchanged = Callable[[Fetched], Fetched]

UNCHANGED: tuple[tuple[str, Unchanged], ...] = (
    # The notes at the end of an annex are printed at the depth of a part and number none.
    ("the notes at the depth of a part", with_the_notes_at_the_depth_of_a_part),
    # A heading at the depth of a group before any part groups nothing.
    ("a group heading before the first part", with_a_group_heading_before_the_first_part),
)


@pytest.mark.parametrize(("what", "reshape"), UNCHANGED, ids=[u[0] for u in UNCHANGED])
def test_a_heading_that_lists_nothing_changes_no_record(what: str, reshape: Unchanged) -> None:
    source = BY_ID["cz-474-2002"]
    fetched = load_fixture(fixture_path(source.id))
    assert source.parse(reshape(fetched)) == source.parse(fetched)


def test_a_row_an_amendment_marked_is_not_a_pest() -> None:
    """The consolidated text marks an amended passage with a triangle and the amendment's number."""
    source = BY_ID["eu-2019-2072-annex-ii"]
    fetched = load_fixture(fixture_path(source.id))
    before = source.parse(fetched)
    root = copy.deepcopy(fetched.document)
    retoken(cells_of(pest_rows(part_a_table(root))[0])[0], "▼M9")
    assert len(source.parse(reshaped(fetched, root))) == len(before) - 1


# --------------------------------------------------------------------------------------
# the readers of one fragment, one row and one record


def test_a_fragment_that_is_not_well_formed_is_refused() -> None:
    with pytest.raises(ShapeError, match=r"^fragment 7 is not well formed XHTML: "):
        fragment_tree({"id": 7, "xhtml": "<p>an element nobody closed"})


def table_of(body: str) -> ET.Element:
    return xhtml(f'<table xmlns="http://www.w3.org/1999/xhtml">{body}</table>')


def test_an_item_table_without_a_row_is_refused() -> None:
    with pytest.raises(ShapeError, match=r"^an item table has no row$"):
        eu_row(table_of(""))


def test_an_item_row_with_one_cell_is_refused() -> None:
    with pytest.raises(ShapeError, match=r"^an item row has 1 cells, expected \(2, 3\)$"):
        eu_row(table_of("<tr><td>a.</td></tr>"))


def record(**fields: Any) -> dict[str, Any]:
    """A record of annex 1 of decree 474/2002, of an invented agent (a public repository)."""
    return {
        "list": "annex-1",
        "code": "I.I 1",
        "name": "Testella fictiva",
        "kind": "organism",
        **fields,
    }


@pytest.mark.parametrize("field", ["code", "name", "kind"])
def test_a_record_without_what_every_record_has_is_refused(field: str) -> None:
    source = BY_ID["cz-474-2002"]
    with pytest.raises(ShapeError, match=rf"^cz-474-2002: a record has no {field}$"):
        check_records(source, [record(**{field: ""})])


def test_two_records_with_the_same_key_are_refused() -> None:
    source = BY_ID["cz-474-2002"]
    with pytest.raises(ShapeError, match=r"two records share the key \('annex-1', 'I\.I 1'\)$"):
        check_records(source, [record(), record(name="Mockia fictiva")])


# --------------------------------------------------------------------------------------
# writing the same text twice


def written(source: Source, tmp_path: Path, day: str) -> bytes:
    write_source(source, load_fixture(fixture_path(source.id)), tmp_path, day)
    return (tmp_path / f"{source.id}.json").read_bytes()


@pytest.mark.parametrize("key", IDS)
def test_writing_an_unchanged_text_again_changes_no_file(key: str, tmp_path: Path) -> None:
    source = BY_ID[key]
    first = written(source, tmp_path, "2026-01-01")
    again = written(source, tmp_path, "2026-01-01")
    assert again == first
    later = written(source, tmp_path, "2026-06-30")
    assert later == first
    assert json.loads(first.decode("utf-8"))["fetched_on"] == "2026-01-01"
