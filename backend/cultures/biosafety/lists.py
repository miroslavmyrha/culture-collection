"""Loading the official lists of regulated agents and risk groups into the app (#169).

Four lists, one data file each under ``data/``, written straight from the official sources by
``tools/fetch_regulatory_lists.py`` (#187). Every file carries its source URL, the version, the
version date, the fetch date, the SHA-256 of the fetched text and the number of entries;
``manifest.json`` repeats that for every list and adds the SHA-256 of the data file itself.

Loading is idempotent. The SHA-256 of each file is computed here and compared with the
manifest, so a file changed without its manifest entry is refused rather than loaded. A file
whose SHA-256 the database already holds for its list is skipped. A changed file is a new list
version: its row becomes the current one and the row before it stops being current. Nothing
updates or deletes an entry (the guards of migration 0005), so a list version stays the reading
it was, with the checksum of the text it was read from.

Matching names. An entry's ``name`` is the name its own list prints: Czech prose in decree
474/2002 Sb., a scientific name with its authority in the EU annexes and in annex 7 of
government order 361/2007 Sb. ``match_of`` derives from it the scientific name to match a
taxon against, lower case and NFC, with the scope the entry has:

- ``exact``: the entry names one taxon ("Bacillus subtilis"), so it matches that name and a
  synonym of it;
- ``genus``: the entry names a genus, or the genus with "spp.", so it matches every taxon of
  that genus.

The rule is deliberately narrow. It reads a leading ``Genus [species] [subsp. epithet]``, else
the first such name in brackets, and nothing else; a candidate whose first word is followed by
a letter outside ASCII is Czech prose cut short, and a word of ``NOT_A_GENUS`` is a word of the
list's own language. An entry the rule yields nothing for has no match name and suggests
nothing, which is where the collection stood before #169. Nothing ever matches by substring,
and a suggestion is a read: a person confirms it with a reason.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from django.db import transaction
from django.utils import timezone

from cultures.audit.events import Change, record_event
from cultures.audit.registry import REGULATORY_LIST_LOADED

from .models import (
    LIST_RESTRICTIONS,
    RISK_GROUP_LIST,
    EntryKind,
    ListCode,
    MatchScope,
    RegulatoryList,
    RegulatoryListEntry,
)

DATA_DIR = Path(__file__).resolve().parent / "data"
MANIFEST = "manifest.json"
LIST = "regulatory_list"
# How many entries one INSERT carries. The lists hold a few hundred entries each.
CHUNK = 200

# A scientific name as the lists print it: a capitalised genus, an optional species epithet or
# "spp.", and an optional infraspecific epithet after its marker.
_GENUS = r"[A-Z][a-z]{2,}"
_EPITHET = r"[a-z][a-z-]{2,}"
_WHOLE_GENUS = r"spp?\."
_INFRA = r"(?:subsp|var|f)\."
NAME = re.compile(
    rf"(?P<genus>{_GENUS})"
    rf"(?:\s+(?P<species>{_WHOLE_GENUS}|{_EPITHET}))?"
    rf"(?:\s+{_INFRA}\s+(?P<infra>{_EPITHET}))?"
)
BRACKETED = re.compile(r"\(\s*([A-Z][a-z]{2,}[^)]*)\)")
# A letter the ASCII pattern above stops at: the candidate is a Czech word cut short.
CUT_SHORT = re.compile(r"[^\W\dA-Za-z_]", re.UNICODE)
# What may follow a name and leave it a name: nothing, punctuation, an authority or a note,
# which start with a capital letter, a digit or a bracket. A lower-case word after it means the
# text is prose that happens to begin like a name ("Something horse sickness virus"), so the
# candidate is dropped rather than guessed at.
AFTER_NAME = re.compile(r"[,;:.()\[\]/|&A-Z0-9-]")
# Words of the lists' own language that read as a genus. The virus families and orders of
# annex 7 are left in: they are ranks a taxon can have, so matching them is right.
NOT_A_GENUS = frozenset(
    {
        "all",
        "and",
        "animal",
        "any",
        "bacteria",
        "fungi",
        "genetic",
        "genetically",
        "grapevine",
        "human",
        "koronavirus",
        "not",
        "other",
        "plant",
        "the",
        "toxin",
        "toxins",
        "virus",
        "viruses",
        "viry",
    }
)


class ListDataError(Exception):
    """A data file does not have the shape or the checksum the loader expects."""


@dataclass(frozen=True)
class Match:
    name: str
    scope: MatchScope


@dataclass(frozen=True)
class Loaded:
    """What one call of `load` did to one list."""

    code: str
    version: str
    file_sha256: str
    entries: int
    matched: int
    created: bool  # False: the database held this file's reading already


def normalised(text: str) -> str:
    """One space between words, NFC, lower case: how a name is compared."""
    return " ".join(unicodedata.normalize("NFC", text).split()).lower()


def _candidate(text: str) -> Match | None:
    found = NAME.match(text)
    if found is None:
        return None
    if CUT_SHORT.match(text[found.end("genus") : found.end("genus") + 1] or " "):
        return None
    rest = text[found.end() :].strip()
    if rest and not AFTER_NAME.match(rest[:1]):
        return None
    genus = found["genus"].lower()
    if genus in NOT_A_GENUS:
        return None
    species = found["species"]
    if species is None or re.fullmatch(_WHOLE_GENUS, species):
        return Match(genus, MatchScope.GENUS)
    name = f"{genus} {species}"
    if found["infra"]:
        name = f"{name} {found['infra']}"
    return Match(normalised(name), MatchScope.EXACT)


def match_of(name: str) -> Match | None:
    """The scientific name an entry's name yields, with its scope, or None for no match name."""
    text = " ".join(unicodedata.normalize("NFC", name).split())
    found = _candidate(text)
    if found is not None:
        return found
    bracketed = BRACKETED.search(text)
    if bracketed is not None:
        return _candidate(bracketed.group(1))
    return None


def _read_day(payload: dict[str, Any], field: str, where: str) -> date:
    value = payload.get(field)
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ListDataError(f"{where}: {field} is {value!r}, not a date")
    return date.fromisoformat(value)


def _read_text(payload: dict[str, Any], field: str, where: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ListDataError(f"{where}: {field} is {value!r}, not a text")
    return " ".join(value.split())


def entry_code_of(entry: dict[str, Any], identity: tuple[str, ...], where: str) -> str:
    """An entry's identity inside its list, as the data file's own `identity` field declares it.

    One field for three of the lists ("1C351.a.4"). Decree 474/2002 Sb. numbers its items per
    annex, part and group, so the same item code stands in both annexes and the identity is the
    annex and the code together ("annex-1 I.I 1").
    """
    parts = [_read_text(entry, field, where) for field in identity]
    return " ".join(parts)


def _entry_values(
    code: str, entry: dict[str, Any], identity: tuple[str, ...], where: str
) -> dict[str, Any]:
    """One entry as its row, with what its list says about it."""
    entry_code = entry_code_of(entry, identity, where)
    name = _read_text(entry, "name", where)
    kind = entry.get("kind")
    if kind not in EntryKind.values:
        raise ListDataError(f"{where} {entry_code}: kind {kind!r}")
    restriction = ""
    allowed = LIST_RESTRICTIONS[code]
    if allowed:
        restriction = _restriction_of(code, entry, allowed, f"{where} {entry_code}")
    risk_group = entry.get("risk_group") if code == RISK_GROUP_LIST else None
    if risk_group is not None and risk_group not in (1, 2, 3, 4):
        raise ListDataError(f"{where} {entry_code}: risk group {risk_group!r}")
    found = match_of(name)
    return {
        "code": entry_code,
        "name": name,
        "kind": kind,
        "restriction_kind": restriction,
        "risk_group": risk_group,
        "match_name": found.name if found else "",
        "match_scope": found.scope if found else "",
    }


def _restriction_of(code: str, entry: dict[str, Any], allowed: frozenset[str], where: str) -> str:
    """Which restriction an entry gives. One list carries two: annex 1 of decree 474/2002 Sb.
    is the highly risky agents (VRAT), annex 2 the risky ones (RAT)."""
    if len(allowed) == 1:
        return next(iter(allowed))
    annex = entry.get("list")
    by_annex = {"annex-1": "cz_vrat", "annex-2": "cz_rat"}
    if code != ListCode.CZ_474_2002 or annex not in by_annex:
        raise ListDataError(f"{where}: the annex is {annex!r}")
    return by_annex[annex]


def read_manifest(data_dir: Path = DATA_DIR) -> dict[str, dict[str, Any]]:
    """The manifest by list code, with the SHA-256 of each data file checked against it."""
    path = data_dir / MANIFEST
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ListDataError(f"{path}: {error}") from error
    sources = manifest.get("sources")
    if not isinstance(sources, list) or not sources:
        raise ListDataError(f"{path}: it lists no source")
    by_code: dict[str, dict[str, Any]] = {}
    for source in sources:
        code = source.get("list")
        if code not in ListCode.values:
            raise ListDataError(f"{path}: it names the list {code!r}")
        if code in by_code:
            raise ListDataError(f"{path}: it names the list {code} twice")
        by_code[code] = source
    missing = sorted(set(ListCode.values) - set(by_code))
    if missing:
        raise ListDataError(f"{path}: it names no source for {', '.join(missing)}")
    return by_code


def read_list(code: str, source: dict[str, Any], data_dir: Path = DATA_DIR) -> dict[str, Any]:
    """One data file, with its SHA-256 against the manifest's and its shape checked."""
    name = source.get("file")
    if not isinstance(name, str) or Path(name).name != name:
        raise ListDataError(f"{code}: the manifest names the file {name!r}")
    path = data_dir / name
    try:
        body = path.read_bytes()
    except OSError as error:
        raise ListDataError(f"{path}: {error}") from error
    digest = hashlib.sha256(body).hexdigest()
    if digest != source.get("file_sha256"):
        raise ListDataError(
            f"{path}: its SHA-256 is {digest}, the manifest says {source.get('file_sha256')!r}"
        )
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as error:
        raise ListDataError(f"{path}: {error}") from error
    if payload.get("list") != code:
        raise ListDataError(f"{path}: it is the list {payload.get('list')!r}")
    entries = payload.get("entries")
    if not isinstance(entries, list) or not entries:
        raise ListDataError(f"{path}: it holds no entry")
    if payload.get("entry_count") != len(entries):
        raise ListDataError(
            f"{path}: it says {payload.get('entry_count')!r} entries and holds {len(entries)}"
        )
    return {**payload, "file_sha256": digest}


def _identity(code: str, payload: dict[str, Any]) -> tuple[str, ...]:
    identity = payload.get("identity")
    if (
        not isinstance(identity, list)
        or not identity
        or not all(isinstance(f, str) for f in identity)
    ):
        raise ListDataError(f"{code}: its identity is {identity!r}")
    return tuple(identity)


def _rows(code: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    where = f"{code}"
    identity = _identity(code, payload)
    rows = [_entry_values(code, entry, identity, where) for entry in payload["entries"]]
    seen: set[str] = set()
    for row in rows:
        if row["code"] in seen:
            raise ListDataError(f"{where}: the entry code {row['code']} twice")
        seen.add(row["code"])
    return rows


def _list_values(code: str, payload: dict[str, Any], now: datetime) -> dict[str, Any]:
    where = f"{code}"
    version_date = _read_day(payload, "version_date", where)
    fetched_on = _read_day(payload, "fetched_on", where)
    if fetched_on < version_date:
        raise ListDataError(f"{where}: fetched on {fetched_on} before the version date")
    source_sha256 = _read_text(payload, "sha256", where)
    if not re.fullmatch(r"[0-9a-f]{64}", source_sha256):
        raise ListDataError(f"{where}: the source SHA-256 is {source_sha256!r}")
    return {
        "code": code,
        "title": _read_text(payload, "title", where),
        "act": _read_text(payload, "act", where),
        "source_url": _read_text(payload, "source_url", where),
        "version": _read_text(payload, "version", where),
        "version_date": version_date,
        "fetched_on": fetched_on,
        "source_sha256": source_sha256,
        "file_sha256": payload["file_sha256"],
        "entry_count": len(payload["entries"]),
        "loaded_at": now,
        "is_current": True,
    }


def load_one(
    code: str, source: dict[str, Any], *, data_dir: Path = DATA_DIR, record: bool = True
) -> Loaded:
    """Load one list, or report that the database holds this reading of it already.

    With `record` the caller is inside an audit context and the load becomes one event with the
    version and both checksums. Migration 0006 loads the files a version ships with `record`
    off: the reading's own row carries where it came from, which version it is, when it was
    loaded and the two checksums, and it can never be changed, so a deploy needs no event of
    its own and no test database starts with one.
    """
    payload = read_list(code, source, data_dir)
    values = _list_values(code, payload, timezone.now())
    rows = _rows(code, payload)
    matched = sum(1 for row in rows if row["match_name"])
    held = RegulatoryList.objects.filter(code=code, file_sha256=values["file_sha256"]).first()
    if held is not None:
        return Loaded(code, held.version, held.file_sha256, held.entry_count, matched, False)
    previous = RegulatoryList.objects.filter(code=code, is_current=True).first()
    with transaction.atomic():
        if previous is not None:
            previous.is_current = False
            previous.save(update_fields=["is_current", "updated_at"])
        version = RegulatoryList.objects.create(**values)
        for start in range(0, len(rows), CHUNK):
            RegulatoryListEntry.objects.bulk_create(
                RegulatoryListEntry(list=version, **row) for row in rows[start : start + CHUNK]
            )
    if not record:
        return Loaded(
            code, version.version, version.file_sha256, version.entry_count, matched, True
        )
    record_event(
        REGULATORY_LIST_LOADED,
        Change(
            LIST,
            version.public_id,
            {
                "code": [None, code],
                "version": [previous.version if previous else None, version.version],
                "version_date": [None, version.version_date.isoformat()],
                "fetched_on": [None, version.fetched_on.isoformat()],
                "source_sha256": [None, version.source_sha256],
                "file_sha256": [previous.file_sha256 if previous else None, version.file_sha256],
                "entry_count": [None, version.entry_count],
                "match_names": [None, matched],
            },
        ),
    )
    return Loaded(code, version.version, version.file_sha256, version.entry_count, matched, True)


def load(*, data_dir: Path = DATA_DIR, record: bool = True) -> list[Loaded]:
    """Load every list of the manifest. With `record`, inside an audit context."""
    manifest = read_manifest(data_dir)
    return [
        load_one(code, manifest[code], data_dir=data_dir, record=record) for code in ListCode.values
    ]
