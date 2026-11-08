"""The fetching, writing and command line halves of the regulatory list fetcher.

Nothing here reaches the network: every request is answered by ``SavedSources`` from the
source slices in ``fixtures/`` (see ``support.py``). The committed data files are never
written, and a test proves they are untouched after a full run into a temporary directory.
"""

from __future__ import annotations

import copy
import hashlib
import json
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import pytest

from tools.fetch_regulatory_lists import (
    ANNEX_I_CELEX,
    ANNEX_II_BASE,
    BY_ID,
    CELLAR,
    DATA_DIR,
    ESBIRKA,
    EXPECTED,
    FIXTURE_DIR,
    KEEP,
    MANIFEST,
    SOURCES,
    XHTML,
    Fetched,
    ShapeError,
    document_date,
    eu_row,
    fetch_cellar,
    fetch_esbirka,
    http_get,
    keep_first_pests,
    latest_consolidated,
    load_fixture,
    main,
    parse_eu_2019_2072_annex_ii,
    prune_children,
    remove_element,
    run_fetch,
    slice_annex_ii,
    slice_fragments,
    write_fixtures,
    write_manifest,
    write_source,
)
from tools.tests.support import (
    NO_NETWORK,
    SavedSources,
    fixture_path,
    read_json,
    saved,
    saved_sources,
    xhtml,
)

IDS = [source.id for source in SOURCES]
TODAY = "2026-11-08"


@pytest.fixture
def hosts(no_network: None, monkeypatch: pytest.MonkeyPatch) -> SavedSources:
    """The two official hosts, answering from the saved slices for the whole test."""
    double = saved_sources()
    double.install(monkeypatch)
    return double


def test_no_test_of_the_fetcher_can_reach_the_network() -> None:
    """The guard of conftest.py, proven: an official host, and still no connection."""
    with pytest.raises(AssertionError, match=NO_NETWORK):
        http_get(ESBIRKA + "anything")


# --------------------------------------------------------------------------------------
# the transport


def test_a_url_outside_the_two_official_hosts_is_refused(hosts: SavedSources) -> None:
    with pytest.raises(ShapeError, match=r"^refusing to fetch from an unexpected host: "):
        http_get("https://lists.example.com/annex-1.json")
    assert hosts.asked == [], "the refusal must come before the request"


def test_no_request_pretends_to_be_a_browser(hosts: SavedSources) -> None:
    fetch_esbirka("2002", "474")
    fetch_cellar(ANNEX_I_CELEX, "2025-09-08")
    assert hosts.asked
    for request in hosts.asked:
        assert "user-agent" not in {name.lower() for name in request.headers}
        assert "Mozilla" not in str(request.headers)


def test_a_refusal_from_a_source_is_passed_on(hosts: SavedSources) -> None:
    """A source that refuses is not asked a second time and not asked as someone else."""
    url = ESBIRKA + urllib.parse.quote("/sb/2002/474", safe="")
    hosts.refuse(url)
    with pytest.raises(urllib.error.HTTPError) as refusal:
        fetch_esbirka("2002", "474")
    assert refusal.value.code == 403
    assert len(hosts.asked) == 1
    assert "user-agent" not in {name.lower() for name in hosts.asked[0].headers}


def test_an_eu_text_is_asked_for_in_english(hosts: SavedSources) -> None:
    fetch_cellar(ANNEX_I_CELEX, "2025-09-08")
    request = hosts.asked[-1]
    assert request.get_header("Accept") == "application/xhtml+xml"
    assert request.get_header("Accept-language") == "eng"


def test_fetching_a_czech_act_reads_every_page(hosts: SavedSources) -> None:
    payload = saved("cz-474-2002")
    fetched = fetch_esbirka("2002", "474")
    assert fetched.url == payload["url"]
    assert fetched.version == payload["version"]
    assert fetched.version_date == payload["version_date"]
    assert fetched.document == payload["document"]
    pages = [hosts.answers[request.full_url] for request in hosts.asked[1:]]
    assert len(pages) == 2, "the metadata document, then both pages of fragments"
    assert fetched.sha256 == hashlib.sha256(b"".join(pages)).hexdigest()


def test_fetching_an_eu_act_reads_its_xhtml(hosts: SavedSources) -> None:
    payload = saved("eu-2021-821-annex-i")
    fetched = fetch_cellar(ANNEX_I_CELEX, payload["version_date"])
    assert fetched.url == CELLAR + ANNEX_I_CELEX == payload["url"]
    assert fetched.sha256 == payload["sha256"]
    assert fetched.document.find(XHTML + "body") is not None


def test_an_eu_answer_that_is_not_xhtml_is_refused(hosts: SavedSources) -> None:
    hosts.register(CELLAR + "32025R2003", b"<html><body><p>unclosed")
    with pytest.raises(ShapeError, match=r"^32025R2003: the Cellar answer is not well formed"):
        fetch_cellar("32025R2003", "2025-09-08")


# --------------------------------------------------------------------------------------
# which version of an EU act


def test_the_newest_consolidated_version_in_force_is_chosen(hosts: SavedSources) -> None:
    hosts.consolidations[ANNEX_II_BASE] = [
        f"{ANNEX_II_BASE}-20210101",
        f"{ANNEX_II_BASE}-20261015",
        f"{ANNEX_II_BASE}-20270401",  # adopted, applies after the day asked for
        f"{ANNEX_II_BASE}-R03",  # not a date, so not a consolidated version
    ]
    assert latest_consolidated(ANNEX_II_BASE, TODAY) == f"{ANNEX_II_BASE}-20261015"


def test_a_version_in_force_only_later_is_refused(hosts: SavedSources) -> None:
    hosts.consolidations[ANNEX_II_BASE] = [f"{ANNEX_II_BASE}-20270401"]
    with pytest.raises(ShapeError, match=r"lists no consolidated version in force$"):
        latest_consolidated(ANNEX_II_BASE, TODAY)


def test_the_document_date_comes_from_the_cellar(hosts: SavedSources) -> None:
    assert document_date(ANNEX_I_CELEX) == saved("eu-2021-821-annex-i")["version_date"]


def test_an_act_the_cellar_has_no_date_for_is_refused(hosts: SavedSources) -> None:
    with pytest.raises(ShapeError, match=r"^32099R9999: the Cellar gives no document date$"):
        document_date("32099R9999")


def test_a_document_date_that_is_not_a_date_is_refused(hosts: SavedSources) -> None:
    hosts.dates[ANNEX_I_CELEX] = "in the spring"
    with pytest.raises(ShapeError, match=r"gives the document date as 'in the spr'$"):
        document_date(ANNEX_I_CELEX)


# --------------------------------------------------------------------------------------
# writing the data files


def manifest_rows(out_dir: Path) -> dict[str, dict[str, Any]]:
    rows = read_json(out_dir / MANIFEST)["sources"]
    return {row["list"]: row for row in rows}


def test_a_full_run_writes_every_data_file_and_the_manifest(
    hosts: SavedSources, tmp_path: Path
) -> None:
    run_fetch(["all"], tmp_path)
    expected = read_json(FIXTURE_DIR / EXPECTED)
    rows = manifest_rows(tmp_path)
    assert list(rows) == IDS, "the manifest keeps the order of SOURCES"
    for key in IDS:
        row = rows[key]
        raw = (tmp_path / row["file"]).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == row["file_sha256"]
        payload = json.loads(raw.decode("utf-8"))
        assert payload["entry_count"] == expected[key]["entry_count"]
        assert payload["counts"] == expected[key]["counts"]
        assert payload["version"] == saved(key)["version"]
        assert payload["fetched_on"] == row["fetched_on"]


def test_a_full_run_leaves_the_committed_data_files_alone(
    hosts: SavedSources, tmp_path: Path
) -> None:
    """The writer writes where it is told. The repository's data files are the record."""
    before = {path.name: path.read_bytes() for path in sorted(DATA_DIR.glob("*.json"))}
    assert before, "the data files must be there, or this proves nothing"
    run_fetch(["all"], tmp_path)
    after = {path.name: path.read_bytes() for path in sorted(DATA_DIR.glob("*.json"))}
    assert after == before


def without_the_last_item(fetched: Fetched) -> Fetched:
    """One numbered item less, which the parser accepts: a shorter list, not a changed shape."""
    document = copy.deepcopy(fetched.document)
    for index in reversed(range(len(document))):
        if document[index]["kodTypuFragmentu"] == "Bod_Dd":
            del document[index]
            break
    return Fetched(
        url=fetched.url,
        version=fetched.version,
        version_date=fetched.version_date,
        sha256="0" * 64,
        document=document,
    )


def test_a_changed_source_text_changes_the_manifest_checksum(tmp_path: Path) -> None:
    source = BY_ID["cz-474-2002"]
    fetched = load_fixture(fixture_path(source.id))
    first = write_source(source, fetched, tmp_path, TODAY)
    text = (tmp_path / first["file"]).read_bytes()
    assert write_manifest(tmp_path, [first]) is True

    changed = write_source(source, without_the_last_item(fetched), tmp_path, TODAY)
    assert (tmp_path / changed["file"]).read_bytes() != text
    assert changed["file_sha256"] != first["file_sha256"]
    assert changed["entry_count"] == first["entry_count"] - 1
    assert write_manifest(tmp_path, [changed]) is True
    assert manifest_rows(tmp_path)[source.id]["file_sha256"] == changed["file_sha256"]


def test_writing_the_manifest_again_with_the_same_rows_changes_nothing(tmp_path: Path) -> None:
    source = BY_ID["cz-361-2007-annex-7"]
    row = write_source(source, load_fixture(fixture_path(source.id)), tmp_path, TODAY)
    assert write_manifest(tmp_path, [row]) is True
    before = (tmp_path / MANIFEST).read_bytes()
    assert write_manifest(tmp_path, [row]) is False
    assert (tmp_path / MANIFEST).read_bytes() == before


def test_the_manifest_keeps_the_rows_of_the_sources_a_run_left_out(tmp_path: Path) -> None:
    """Fetching one source keeps what the manifest records about the others."""
    rows = [
        write_source(BY_ID[key], load_fixture(fixture_path(key)), tmp_path, TODAY)
        for key in ("eu-2019-2072-annex-ii", "cz-474-2002")
    ]
    for row in rows:
        assert write_manifest(tmp_path, [row]) is True
    kept = manifest_rows(tmp_path)
    assert list(kept) == ["cz-474-2002", "eu-2019-2072-annex-ii"]
    assert {key: kept[key]["file_sha256"] for key in kept} == {
        row["list"]: row["file_sha256"] for row in rows
    }


# --------------------------------------------------------------------------------------
# the fixtures this script writes


def test_the_fixture_writer_writes_the_saved_slices_again(
    hosts: SavedSources, tmp_path: Path
) -> None:
    """Run over the saved slices, the writer reproduces them byte for byte, and expected.json.

    The slices are the writer's own output, so anything it would change here is a change in
    the writer, not in the source.
    """
    write_fixtures(tmp_path)
    written = sorted(path.name for path in tmp_path.glob("*.json"))
    assert written == sorted(path.name for path in FIXTURE_DIR.glob("*.json"))
    for name in written:
        assert (tmp_path / name).read_bytes() == (FIXTURE_DIR / name).read_bytes(), name


def fragment(kind: str, depth: int, xhtml: str) -> dict[str, Any]:
    return {"id": f"{kind}-{depth}", "kodTypuFragmentu": kind, "hloubka": depth, "xhtml": xhtml}


def table_xhtml(rows: int) -> str:
    """A table of invented agents, one row per number, in the shape annex 7 prints."""
    cells = "".join(
        f"<tr><td>Testella fictiva {number}</td><td>2</td><td>A</td></tr>"
        for number in range(1, rows + 1)
    )
    return (
        '<table xmlns="http://www.w3.org/1999/xhtml"><tbody>'
        "<tr><th>Biologický činitel</th><th>Skupina</th><th>Poznámka</th></tr>"
        f"{cells}</tbody></table>"
    )


def test_a_slice_keeps_the_shape_of_an_annex_and_drops_the_repetition() -> None:
    """Every heading, the first two of each run of items, and only the first rows of a table."""
    fragments = [
        fragment("Hlavicka_priloha", 3, "<p>Příloha č. 7 k nařízení vlády</p>"),
        fragment("Nadpis", 5, "<p>Tabulka č. 1: Bakterie</p>"),
        *[fragment("Bod_Dd", 6, f"<p>{n}. Testella fictiva</p>") for n in range(1, 6)],
        fragment("Tabulka", 5, table_xhtml(6)),
    ]
    out = slice_fragments(fragments, (7,))
    assert [f["kodTypuFragmentu"] for f in out] == [
        "Hlavicka_priloha",
        "Nadpis",
        "Bod_Dd",
        "Bod_Dd",
        "Tabulka",
    ]
    assert list(out[0]) == ["id", "kodTypuFragmentu", "hloubka", "xhtml"]
    kept = xhtml(f'<root xmlns="http://www.w3.org/1999/xhtml">{out[-1]["xhtml"]}</root>')
    assert len(list(kept.iter(XHTML + "tr"))) == KEEP + 1, "the header row and two agents"


def pest_table(groups: int, pests: int) -> ET.Element:
    """A pest table of invented pests: a numbered group heading, then its numbered pests."""
    rows = []
    for group in range(1, groups + 1):
        rows.append(f"<tr><td>{group}. Invented pests</td></tr>")
        rows += [
            f"<tr><td>{number}.</td><td>Mockia fictiva {number} [MOCKIA]</td></tr>"
            for number in range(1, pests + 1)
        ]
    body = "".join(rows)
    return xhtml(f'<table xmlns="http://www.w3.org/1999/xhtml"><tbody>{body}</tbody></table>')


def test_a_slice_of_a_pest_table_keeps_the_first_pests_of_every_group() -> None:
    table = pest_table(groups=2, pests=4)
    keep_first_pests(table)
    rows = [
        [cell for cell in row if cell.tag in (XHTML + "td", XHTML + "th")]
        for row in table.iter(XHTML + "tr")
    ]
    assert [len(cells) for cells in rows] == [1, 2, 2, 1, 2, 2]


def entry_table(items: int) -> ET.Element:
    """An entry of annex I with ``items`` lettered items and a note printed after them."""
    letters = "".join(
        f"<table><tr><td>{chr(ord('a') + number)}.</td>"
        f"<td>Testella fictiva {number + 1}</td></tr></table>"
        for number in range(items)
    )
    return xhtml(
        '<table xmlns="http://www.w3.org/1999/xhtml"><tr><td/><td>1C351</td>'
        f"<td>Invented pathogens, as follows: {letters}"
        "<table><tr><td>N.B.</td><td>A note about the entry</td></tr></table>"
        "</td></tr></table>"
    )


def test_a_slice_of_an_entry_keeps_its_first_items_and_every_note() -> None:
    table = entry_table(items=4)
    prune_children(table)
    tokens = [eu_row(child).token for child in eu_row(table).children]
    assert tokens == ["a.", "b.", "N.B."], "two items of the entry and the note after them"


def test_an_element_is_removed_wherever_it_sits() -> None:
    root = xhtml("<a><b><c/><d/></b></a>")
    target = root.find("./b/d")
    assert target is not None
    remove_element(root, target)
    assert [element.tag for element in root.iter()] == ["a", "b", "c"]


def test_removing_an_element_that_is_not_there_changes_nothing() -> None:
    root = xhtml("<a><b/></a>")
    remove_element(root, ET.Element("b"))
    assert [element.tag for element in root.iter()] == ["a", "b"]


def no_body() -> Fetched:
    return Fetched(
        url="http://publications.europa.eu/resource/celex/02019R2072-20261015",
        version="02019R2072-20261015",
        version_date="2026-10-15",
        sha256="0" * 64,
        document=xhtml('<html xmlns="http://www.w3.org/1999/xhtml"><head/></html>'),
    )


def test_an_eu_document_without_a_body_is_refused_by_the_parser() -> None:
    with pytest.raises(ShapeError, match=r"^annex II: the document has no body$"):
        parse_eu_2019_2072_annex_ii(no_body())


def test_an_eu_document_without_a_body_is_refused_by_the_slicer() -> None:
    with pytest.raises(ShapeError, match=r"^annex II: the document has no body$"):
        slice_annex_ii(no_body().document)


# --------------------------------------------------------------------------------------
# the command line


def test_a_source_key_names_one_source(hosts: SavedSources, tmp_path: Path) -> None:
    assert main(["fetch", "cz-474-2002", "--out", str(tmp_path)]) == 0
    assert sorted(path.name for path in tmp_path.glob("*.json")) == [
        "cz-474-2002.json",
        MANIFEST,
    ]


def test_all_fetches_every_source(hosts: SavedSources, tmp_path: Path) -> None:
    assert main(["fetch", "all", "--out", str(tmp_path)]) == 0
    assert sorted(path.name for path in tmp_path.glob("*.json")) == sorted(
        [*[f"{key}.json" for key in IDS], MANIFEST]
    )


def test_an_unknown_source_key_stops_the_run(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match=r"^unknown source: cz-474-2003$"):
        main(["fetch", "cz-474-2003", "--out", str(tmp_path)])
    assert list(tmp_path.glob("*.json")) == []


def test_parsing_a_saved_file_reports_its_counts(capsys: pytest.CaptureFixture[str]) -> None:
    # Named list, not key: the secret scan reads that word followed by a dashed value as a
    # credential (the same reason the Source field is named id).
    listed = "cz-361-2007-annex-7"
    assert main(["parse-file", listed, str(fixture_path(listed))]) == 0
    assert f"{listed}: 10 entries" in capsys.readouterr().out


def test_a_source_the_parser_cannot_read_fails_the_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A changed shape ends the command with a failure, and names what it did not recognise."""
    payload = saved("cz-474-2002")
    payload["document"] = [
        f for f in payload["document"] if f["kodTypuFragmentu"] != "Hlavicka_priloha"
    ]
    path = tmp_path / "broken.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    assert main(["parse-file", "cz-474-2002", str(path)]) == 1
    assert "FAILED: the text has no annex headers" in capsys.readouterr().out


def test_the_fixtures_command_writes_the_slices(hosts: SavedSources, tmp_path: Path) -> None:
    assert main(["fixtures", "--out", str(tmp_path)]) == 0
    assert read_json(tmp_path / EXPECTED) == read_json(FIXTURE_DIR / EXPECTED)
