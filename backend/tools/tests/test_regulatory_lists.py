"""The data files of the official lists, and the strictness of the parsers that wrote them.

Nothing here fetches anything. The data files are read as they are committed, and the parsers
run against the saved source slices in ``fixtures/``, which ``fetch_regulatory_lists.py
fixtures`` writes from the real texts.
"""

from __future__ import annotations

import copy
import hashlib
import json
import xml.etree.ElementTree as ET
from collections.abc import Callable
from pathlib import Path
from typing import Any

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
    fragment_tree,
    load_fixture,
    write_source,
)

IDS = [source.id for source in SOURCES]


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


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


def fixture_path(key: str) -> Path:
    return FIXTURE_DIR / f"{key}.slice.json"


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
    kept = [
        f for f in copy.deepcopy(fetched.document) if f["kodTypuFragmentu"] != "Hlavicka_priloha"
    ]
    return reshaped(fetched, kept)


def with_an_item_renumbered(fetched: Fetched) -> Fetched:
    document = copy.deepcopy(fetched.document)
    first = fragments_of(reshaped(fetched, document), "Bod_Dd")[0]
    first["xhtml"] = first["xhtml"].replace("1.", "4.", 1)
    return reshaped(fetched, document)


def with_an_item_moved_deeper(fetched: Fetched) -> Fetched:
    document = copy.deepcopy(fetched.document)
    fragments_of(reshaped(fetched, document), "Bod_Dd")[0]["hloubka"] = 9
    return reshaped(fetched, document)


def with_a_part_heading_unnamed(fetched: Fetched) -> Fetched:
    document = copy.deepcopy(fetched.document)
    for fragment in document:
        if fragment["kodTypuFragmentu"] == "Obecny_text" and fragment["hloubka"] == 4:
            fragment["xhtml"] = "<p>IX. </p>"
            break
    return reshaped(fetched, document)


def with_a_table_column_dropped(fetched: Fetched) -> Fetched:
    document = copy.deepcopy(fetched.document)
    fragment = fragments_of(reshaped(fetched, document), "Tabulka")[0]
    tree = fragment_tree(fragment)
    for row in tree.iter(XHTML + "tr"):
        cells = cells_of(row)
        row.remove(cells[-1])
    fragment["xhtml"] = "".join(ET.tostring(child, encoding="unicode") for child in tree)
    return reshaped(fetched, document)


def with_the_group_column_renamed(fetched: Fetched) -> Fetched:
    document = copy.deepcopy(fetched.document)
    table = fragments_of(reshaped(fetched, document), "Tabulka")[0]
    table["xhtml"] = table["xhtml"].replace("Skupina", "Trida", 1)
    return reshaped(fetched, document)


def with_a_table_dropped(fetched: Fetched) -> Fetched:
    document = copy.deepcopy(fetched.document)
    for index, fragment in enumerate(document):
        if fragment["kodTypuFragmentu"] == "Tabulka":
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


def without_part_b(fetched: Fetched) -> Fetched:
    root = copy.deepcopy(fetched.document)
    for paragraph in root.iter(XHTML + "p"):
        if (paragraph.text or "").strip() == "PART B":
            paragraph.text = "PART C"
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


RESHAPES: tuple[tuple[str, str, Reshape], ...] = (
    ("cz-474-2002", "no annex header", without_the_annex_heading),
    ("cz-474-2002", "an item renumbered", with_an_item_renumbered),
    ("cz-474-2002", "an item at another depth", with_an_item_moved_deeper),
    ("cz-474-2002", "a part heading that names no kind", with_a_part_heading_unnamed),
    ("cz-361-2007-annex-7", "no annex header", without_the_annex_heading),
    ("cz-361-2007-annex-7", "a table with a column less", with_a_table_column_dropped),
    ("cz-361-2007-annex-7", "the group column renamed", with_the_group_column_renamed),
    ("cz-361-2007-annex-7", "a table missing", with_a_table_dropped),
    ("eu-2021-821-annex-i", "an entry code gone", without_an_entry_code),
    ("eu-2021-821-annex-i", "a category the parser does not know", with_an_unknown_category),
    ("eu-2019-2072-annex-ii", "no part B", without_part_b),
    ("eu-2019-2072-annex-ii", "two pests swapped", with_pests_out_of_order),
)


@pytest.mark.parametrize(
    ("key", "what", "reshape"), RESHAPES, ids=[f"{key}: {what}" for key, what, _ in RESHAPES]
)
def test_a_parser_refuses_a_reshaped_source(key: str, what: str, reshape: Reshape) -> None:
    source = BY_ID[key]
    fetched = load_fixture(fixture_path(key))
    assert source.parse(fetched), "the saved text itself must parse, or the case proves nothing"
    with pytest.raises(ShapeError):
        source.parse(reshape(fetched))


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
