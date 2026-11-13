"""The official lists in the app (#169): loaded from the data files, and editable by nothing.

The counts below are the data files of this version, as `manifest.json` records them. A new
reading of a source moves them, which is the point: the numbers say what the app holds.
"""

import hashlib
import json
import re
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from django.contrib import admin
from django.core.management import CommandError, call_command
from django.db import IntegrityError, connection, transaction
from django.db.backends.utils import CursorWrapper
from django.db.models import ProtectedError

from cultures.audit.context import audit_context
from cultures.audit.models import ActorKind, AuditEvent, Channel
from cultures.audit.tests.conftest import TEST_ROLES, refused
from cultures.biosafety import lists
from cultures.biosafety.api import urls
from cultures.biosafety.models import (
    EntryKind,
    ListCode,
    MatchScope,
    RegulatoryList,
    RegulatoryListEntry,
)

pytestmark = pytest.mark.django_db

# Per list: the entries the data files hold, and how many of them have a name to match a taxon
# against (biosafety.lists: a narrow rule, and an entry it yields nothing for suggests nothing).
ENTRIES = {
    ListCode.CZ_474_2002: 125,
    ListCode.CZ_361_2007_ANNEX_7: 603,
    ListCode.EU_2021_821_ANNEX_I: 147,
    ListCode.EU_2019_2072_ANNEX_II: 186,
}
MATCHED = {
    ListCode.CZ_474_2002: 57,
    ListCode.CZ_361_2007_ANNEX_7: 473,
    ListCode.EU_2021_821_ANNEX_I: 95,
    ListCode.EU_2019_2072_ANNEX_II: 156,
}


def as_command() -> Any:
    return audit_context(
        channel=Channel.COMMAND,
        actor_kind=ActorKind.SYSTEM,
        actor_label="command:test",
        reason="the official lists",
    )


def current(code: str) -> RegulatoryList:
    version: RegulatoryList = RegulatoryList.objects.get(code=code, is_current=True)
    return version


@pytest.mark.rule("R-LIST-01")
def test_the_migration_loaded_every_list_with_its_source_and_its_checksums() -> None:
    manifest = lists.read_manifest()
    assert set(RegulatoryList.objects.values_list("code", flat=True)) == set(ListCode.values)
    for code, count in ENTRIES.items():
        version = current(code)
        source = manifest[code]
        assert version.act == source["act"]
        assert version.source_url == source["source_url"]
        assert version.version == source["version"]
        assert version.version_date == date.fromisoformat(source["version_date"])
        assert version.fetched_on == date.fromisoformat(source["fetched_on"])
        assert version.source_sha256 == source["sha256"]
        assert version.file_sha256 == source["file_sha256"]
        assert version.entry_count == count
        assert version.entries.count() == count


@pytest.mark.django_db(transaction=True)
@pytest.mark.slow
@pytest.mark.rule("R-LIST-01")
def test_the_lists_are_there_for_a_test_that_works_in_a_real_transaction() -> None:
    """Every test database runs the migrations, so every test finds the lists, including one
    that works in a real transaction. The tests after this one in the file find them too."""
    assert RegulatoryListEntry.objects.count() == sum(ENTRIES.values())


@pytest.mark.rule("R-LIST-01")
def test_loading_the_same_files_again_changes_nothing() -> None:
    before = {
        (version.pk, version.file_sha256, version.is_current)
        for version in RegulatoryList.objects.all()
    }
    entries = RegulatoryListEntry.objects.count()
    with as_command():
        loaded = lists.load()
    assert [one.created for one in loaded] == [False] * len(ListCode.values)
    assert {
        (version.pk, version.file_sha256, version.is_current)
        for version in RegulatoryList.objects.all()
    } == before
    assert RegulatoryListEntry.objects.count() == entries


@pytest.mark.rule("R-LIST-01")
def test_the_command_loads_the_lists_and_says_what_it_did(
    capsys: pytest.CaptureFixture[str],
) -> None:
    call_command("load_regulatory_lists")
    said = capsys.readouterr().out
    for code in ListCode.values:
        assert code in said
    assert "held already" in said


@pytest.mark.rule("R-LIST-01")
def test_a_changed_data_file_is_a_new_version_and_the_one_before_it_steps_down(
    tmp_path: Path,
) -> None:
    code = ListCode.EU_2019_2072_ANNEX_II
    was = current(code)
    _copy_with_one_entry_dropped(tmp_path, code)
    with as_command():
        loaded = {one.code: one for one in lists.load(data_dir=tmp_path)}
    assert loaded[code].created is True
    assert loaded[code].file_sha256 != was.file_sha256
    now = current(code)
    assert now.pk != was.pk
    assert now.entry_count == was.entry_count - 1
    was.refresh_from_db()
    assert was.is_current is False
    assert was.entries.count() == ENTRIES[code]


@pytest.mark.rule("R-LIST-01")
def test_a_newer_list_loaded_by_the_command_is_one_event_with_the_version_and_the_checksums(
    tmp_path: Path,
) -> None:
    """The files a version ships come with migration 0006 and record no event: the reading's own
    row is the record, and no database starts its trail with four. A newer list is a choice
    somebody made, so the command records it."""
    assert not AuditEvent.objects.filter(event_type="regulatory_list_loaded").exists()
    code = ListCode.EU_2019_2072_ANNEX_II
    was = current(code)
    _copy_with_one_entry_dropped(tmp_path, code)
    call_command("load_regulatory_lists", data_dir=str(tmp_path))
    events = AuditEvent.objects.filter(event_type="regulatory_list_loaded")
    event = events.get()
    version = current(code)
    assert event.channel == Channel.COMMAND
    assert event.actor_label == "command:load_regulatory_lists"
    assert event.subject_id == version.public_id
    assert event.changes["code"] == [None, code]
    assert event.changes["version"] == [was.version, version.version]
    assert event.changes["source_sha256"] == [None, version.source_sha256]
    assert event.changes["file_sha256"] == [was.file_sha256, version.file_sha256]
    assert event.changes["entry_count"] == [None, version.entry_count]


@pytest.mark.rule("R-LIST-02")
def test_a_data_file_whose_checksum_the_manifest_does_not_confirm_is_not_loaded(
    tmp_path: Path,
) -> None:
    code = ListCode.CZ_474_2002
    source = lists.read_manifest()[code]
    body = json.loads((lists.DATA_DIR / source["file"]).read_text(encoding="utf-8"))
    body["entries"] = body["entries"][:-1]
    body["entry_count"] = len(body["entries"])
    for name in (lists.MANIFEST, source["file"]):
        (tmp_path / name).write_text((lists.DATA_DIR / name).read_text(encoding="utf-8"))
    (tmp_path / source["file"]).write_text(json.dumps(body), encoding="utf-8")
    with as_command(), pytest.raises(lists.ListDataError, match="its SHA-256 is"):
        lists.load(data_dir=tmp_path)
    assert current(code).entry_count == ENTRIES[code]


def _data_file(tmp_path: Path, body: bytes, name: str = "list.json") -> dict[str, Any]:
    (tmp_path / name).write_bytes(body)
    return {"file": name, "file_sha256": hashlib.sha256(body).hexdigest()}


def _payload(**changes: Any) -> bytes:
    payload = {"list": ListCode.CZ_474_2002, "entries": [{"code": "1"}], "entry_count": 1}
    return json.dumps({**payload, **changes}).encode()


@pytest.mark.rule("R-LIST-02")
@pytest.mark.parametrize(
    ("source", "refusal"),
    [
        (lambda d: {"file": "../list.json"}, "the manifest names the file '../list.json'"),
        (lambda d: {"file": "absent.json"}, "absent.json: .*No such file"),
        (lambda d: _data_file(d, b"\xff not text"), "list.json: .*utf-8"),
        (lambda d: _data_file(d, b"{"), "list.json: Expecting"),
        (lambda d: _data_file(d, _payload(list="eu_other")), "it is the list 'eu_other'"),
        (lambda d: _data_file(d, _payload(entries=[], entry_count=0)), "it holds no entry"),
        (lambda d: _data_file(d, _payload(entry_count=3)), "it says 3 entries and holds 1"),
    ],
    ids=["path", "missing", "not text", "not json", "other list", "empty", "count"],
)
def test_a_data_file_that_is_not_the_list_the_manifest_names_is_refused(
    tmp_path: Path, source: Any, refusal: str
) -> None:
    with pytest.raises(lists.ListDataError, match=refusal):
        lists.read_list(ListCode.CZ_474_2002, source(tmp_path), data_dir=tmp_path)


@pytest.mark.rule("R-LIST-02")
def test_the_command_reports_a_data_file_it_cannot_read(tmp_path: Path) -> None:
    with pytest.raises(CommandError, match=r"manifest\.json"):
        call_command("load_regulatory_lists", data_dir=str(tmp_path))


@pytest.mark.rule("R-LIST-03")
def test_each_entry_carries_what_its_own_list_says_and_nothing_else() -> None:
    by_list = {
        ListCode.CZ_474_2002: {"cz_vrat", "cz_rat"},
        ListCode.CZ_361_2007_ANNEX_7: {""},
        ListCode.EU_2021_821_ANNEX_I: {"dual_use"},
        ListCode.EU_2019_2072_ANNEX_II: {"quarantine_pest"},
    }
    for code, kinds in by_list.items():
        entries = current(code).entries.all()
        assert {entry.restriction_kind for entry in entries} == kinds
        assert {entry.kind for entry in entries} <= set(EntryKind.values)
        groups = {entry.risk_group for entry in entries}
        if code == ListCode.CZ_361_2007_ANNEX_7:
            # Annex 7 states groups 2 to 4, and leaves the column empty where its table
            # states none: no group follows from a row that does not give one.
            assert groups == {None, 2, 3, 4}
        else:
            assert groups == {None}


@pytest.mark.rule("R-LIST-03")
def test_every_match_name_is_a_lower_case_scientific_name_with_its_scope() -> None:
    for code, count in MATCHED.items():
        assert current(code).entries.exclude(match_name="").count() == count, code
    matched = RegulatoryListEntry.objects.exclude(match_name="")
    for entry in matched.iterator():
        assert re.fullmatch(r"[a-z][a-z-]+( [a-z.-]+)*", entry.match_name), entry.code
        assert entry.match_scope in set(MatchScope.values)
        assert (" " in entry.match_name) == (entry.match_scope == MatchScope.EXACT)
    assert not RegulatoryListEntry.objects.filter(match_name="").exclude(match_scope="").exists()


@pytest.mark.rule("R-LIST-03")
@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Mockia fictiva", ("mockia fictiva", MatchScope.EXACT)),
        ("Mockia fictiva subsp. minor", ("mockia fictiva minor", MatchScope.EXACT)),
        ("Mockia fictiva (Novak) Horak, 1952", ("mockia fictiva", MatchScope.EXACT)),
        ("Mockia", ("mockia", MatchScope.GENUS)),
        ("Mockia spp.", ("mockia", MatchScope.GENUS)),
        ("Mockia fictiva, serovar 2", ("mockia fictiva", MatchScope.EXACT)),
        ("brambory (Mockia fictiva)", ("mockia fictiva", MatchScope.EXACT)),
        ("Lidský nákazlivý činitel", None),
        ("toxiny bakterie Mockia fictiva", None),
        ("virus koní (African horse sickness virus)", None),
        ("Mockia fictiva neurotoxins", None),
        ("Virus horečky", None),
        ("Not used", None),
        ("", None),
    ],
)
def test_a_name_yields_its_scientific_name_or_none_at_all(
    name: str, expected: tuple[str, MatchScope] | None
) -> None:
    found = lists.match_of(name)
    assert (None if found is None else (found.name, found.scope)) == expected


@pytest.mark.rule("R-LIST-03")
def test_a_match_name_never_comes_from_a_part_of_a_word() -> None:
    """Nothing matches by substring: the rule reads whole words only."""
    assert lists.match_of("Mockiana fictiva") == lists.Match("mockiana fictiva", MatchScope.EXACT)
    assert lists.match_of("Mo fictiva") is None


@pytest.mark.rule("R-LIST-04")
def test_no_api_and_no_admin_page_writes_a_list() -> None:
    registered = {model.__name__ for model in admin.site._registry}
    assert "RegulatoryList" not in registered
    assert "RegulatoryListEntry" not in registered
    patterns = [str(pattern.pattern) for pattern in urls.urlpatterns]
    assert not any("list" in pattern for pattern in patterns)


@pytest.mark.rule("R-LIST-04")
def test_the_database_refuses_to_edit_an_entry_of_a_list() -> None:
    entry = current(ListCode.CZ_474_2002).entries.first()
    assert entry is not None
    entry.name = "Mockia fictiva"
    with pytest.raises(IntegrityError, match="never edited"), transaction.atomic():
        entry.save(update_fields=["name"])


@pytest.mark.rule("R-LIST-04")
def test_the_database_refuses_to_delete_an_entry_or_a_list() -> None:
    version = current(ListCode.CZ_474_2002)
    entry = version.entries.first()
    assert entry is not None
    with pytest.raises(IntegrityError, match="never deleted"), transaction.atomic():
        RegulatoryListEntry.objects.filter(pk=entry.pk).delete()
    # The entries point at the list with PROTECT, so Django refuses first. The trigger is the
    # line behind it: a delete that reaches the database is refused there too.
    with pytest.raises(ProtectedError), transaction.atomic():
        RegulatoryList.objects.filter(pk=version.pk).delete()
    with (
        pytest.raises(IntegrityError, match="never deleted"),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute("DELETE FROM biosafety_regulatorylist WHERE id = %s", [version.pk])


@pytest.mark.rule("R-LIST-04")
def test_the_database_refuses_every_change_of_a_list_but_stepping_down() -> None:
    version = current(ListCode.CZ_474_2002)
    with pytest.raises(IntegrityError, match="never edited"), transaction.atomic():
        RegulatoryList.objects.filter(pk=version.pk).update(version="made up")
    with transaction.atomic():
        RegulatoryList.objects.filter(pk=version.pk).update(is_current=False)
    with pytest.raises(IntegrityError, match="current again"), transaction.atomic():
        RegulatoryList.objects.filter(pk=version.pk).update(is_current=True)


@pytest.mark.rule("R-LIST-03")
def test_the_database_refuses_an_entry_that_does_not_fit_its_own_list() -> None:
    annex_7 = current(ListCode.CZ_361_2007_ANNEX_7)
    dual_use = current(ListCode.EU_2021_821_ANNEX_I)
    with pytest.raises(IntegrityError, match="its own list gives"), transaction.atomic():
        RegulatoryListEntry.objects.create(
            list=annex_7,
            code="made-up-1",
            name="Mockia fictiva",
            kind=EntryKind.ORGANISM,
            restriction_kind="dual_use",
            risk_group=2,
        )
    with pytest.raises(IntegrityError, match="states a risk group"), transaction.atomic():
        RegulatoryListEntry.objects.create(
            list=dual_use,
            code="made-up-2",
            name="Mockia fictiva",
            kind=EntryKind.ORGANISM,
            restriction_kind="dual_use",
            risk_group=2,
        )


@pytest.mark.rule("R-LIST-04")
def test_the_database_refuses_an_entry_of_a_list_that_was_replaced(tmp_path: Path) -> None:
    code = ListCode.EU_2019_2072_ANNEX_II
    was = current(code)
    _copy_with_one_entry_dropped(tmp_path, code)
    with as_command():
        lists.load(data_dir=tmp_path)
    with pytest.raises(IntegrityError, match="current reading"), transaction.atomic():
        RegulatoryListEntry.objects.create(
            list=was,
            code="made-up-3",
            name="Mockia fictiva",
            kind=EntryKind.ORGANISM,
            restriction_kind="quarantine_pest",
        )


@pytest.mark.rule("R-LIST-01")
def test_one_reading_of_a_list_is_current_and_one_row_per_file() -> None:
    version = current(ListCode.CZ_474_2002)
    with pytest.raises(IntegrityError, match="one_current"), transaction.atomic():
        RegulatoryList.objects.create(
            **{
                field: getattr(version, field)
                for field in (
                    "code",
                    "title",
                    "act",
                    "source_url",
                    "version",
                    "version_date",
                    "fetched_on",
                    "source_sha256",
                    "entry_count",
                    "loaded_at",
                )
            },
            file_sha256="f" * 64,
            is_current=True,
        )
    with transaction.atomic():
        RegulatoryList.objects.filter(pk=version.pk).update(is_current=False)
    with pytest.raises(IntegrityError, match="file_sha256_uniq"), transaction.atomic():
        RegulatoryList.objects.create(
            **{
                field: getattr(version, field)
                for field in (
                    "code",
                    "title",
                    "act",
                    "source_url",
                    "version",
                    "version_date",
                    "fetched_on",
                    "source_sha256",
                    "file_sha256",
                    "entry_count",
                    "loaded_at",
                )
            },
            is_current=True,
        )


@pytest.mark.rule("R-LIST-04")
def test_the_runtime_role_cannot_edit_or_delete_a_list(runtime_role: CursorWrapper) -> None:
    """The grants of audit.roles, not only the triggers: the app's own role may read the lists
    and insert a new reading, and nothing else."""
    runtime_role.execute("SELECT current_user")
    assert runtime_role.fetchone() == (TEST_ROLES.runtime,)
    runtime_role.execute("SELECT count(*) FROM biosafety_regulatorylistentry")
    assert runtime_role.fetchone() == (sum(ENTRIES.values()),)
    refused(
        runtime_role,
        "UPDATE biosafety_regulatorylistentry SET name = 'Mockia fictiva'",
        "permission denied",
    )
    refused(runtime_role, "DELETE FROM biosafety_regulatorylistentry", "permission denied")
    refused(runtime_role, "DELETE FROM biosafety_regulatorylist", "permission denied")


def _copy_with_one_entry_dropped(tmp_path: Path, code: str) -> None:
    """The data files in `tmp_path`, with one entry taken out of `code` and the manifest's
    checksum for it brought along: one changed source, as a new reading of it would be. Every
    other file is copied byte for byte, so its SHA-256 and its reading stay what they were.
    """
    manifest = json.loads((lists.DATA_DIR / lists.MANIFEST).read_text(encoding="utf-8"))
    for source in manifest["sources"]:
        name = source["file"]
        if source["list"] != code:
            (tmp_path / name).write_bytes((lists.DATA_DIR / name).read_bytes())
            continue
        body = json.loads((lists.DATA_DIR / name).read_text(encoding="utf-8"))
        body["entries"] = body["entries"][:-1]
        body["entry_count"] = len(body["entries"])
        body["version"] = f"{body['version']}-test"
        text = json.dumps(body, ensure_ascii=False, indent=1)
        (tmp_path / name).write_text(text, encoding="utf-8")
        source["file_sha256"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
        source["entry_count"] = body["entry_count"]
        source["version"] = body["version"]
    (tmp_path / lists.MANIFEST).write_text(json.dumps(manifest, ensure_ascii=False))
