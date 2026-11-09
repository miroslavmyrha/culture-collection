"""Shared readers and the offline stand-in for the two official hosts.

Nothing here reaches the network. ``SavedSources`` answers every request the fetcher makes
from the source slices in ``fixtures/``, which ``fetch_regulatory_lists.py fixtures`` wrote
from the real texts, wrapped in the envelope the real APIs use:

* e-Sbirka: the metadata document with ``staleUrl`` and ``datumUcinnostiZneniOd``, then pages
  of ``{"seznam": [...], "pocetStranek": n}``. Field names and paging as the official API uses
  them (the same shape an independent download script of these acts reads).
* Cellar: the XHTML document of a CELEX, and SPARQL answers in the standard
  ``{"results": {"bindings": [...]}}`` shape, with the versions and dates the saved slices and
  the committed data files record.

A URL nothing is registered for answers 404, and ``refuse()`` registers a refusal: a double
answers what the real source answers, including a refusal, and no test works around one. No
request carries a browser user agent, which ``test_regulatory_fetch.py`` proves.
"""

from __future__ import annotations

import email.message
import json
import re
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from types import TracebackType
from typing import Any, NoReturn

import pytest

from tools.fetch_regulatory_lists import (
    ANNEX_I_CELEX,
    ANNEX_II_BASE,
    CELLAR,
    ESBIRKA,
    FIXTURE_DIR,
    SPARQL,
)

# What a saved slice is named, and how the consolidated CELEX of an EU act is written in the
# SPARQL queries this double answers.
SLICE_SUFFIX = ".slice.json"
STRSTARTS = re.compile(r'STRSTARTS\(STR\(\?id\), "([^"]+)-"\)')
QUOTED_CELEX = re.compile(r'resource_legal_id_celex "([^"]+)"')


NO_NETWORK = "a test of the fetcher must not open a connection"


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """No test here opens a connection. ``SavedSources`` answers instead of the hosts.

    Proven by test_no_test_of_the_fetcher_can_reach_the_network.
    """

    def refuse(*args: object, **kwargs: object) -> NoReturn:
        raise AssertionError(NO_NETWORK)

    monkeypatch.setattr(urllib.request, "urlopen", refuse)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def xhtml(text: str) -> ET.Element:
    """Parse a snippet a test wrote itself. Source texts are read by the parsers instead."""
    return ET.fromstring(text)  # noqa: S314 (a literal written in the test that calls this)


def fixture_path(key: str) -> Path:
    return FIXTURE_DIR / f"{key}{SLICE_SUFFIX}"


def saved(key: str) -> dict[str, Any]:
    """The saved slice of one source: its URL, version, version date and document."""
    payload: dict[str, Any] = read_json(fixture_path(key))
    return payload


class Answered:
    """What ``urlopen`` returns: a context manager over the bytes the host answered."""

    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> Answered:
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None


class SavedSources:
    """The two official hosts, answering from the saved slices instead of the network."""

    def __init__(self) -> None:
        self.answers: dict[str, bytes] = {}
        self.refusals: dict[str, int] = {}
        self.consolidations: dict[str, list[str]] = {}
        self.dates: dict[str, str] = {}
        self.asked: list[urllib.request.Request] = []

    # registering what the hosts hold -------------------------------------------------

    def register(self, url: str, body: bytes) -> None:
        self.answers[url] = body

    def refuse(self, url: str, status: int = 403) -> None:
        """This URL answers a refusal, as a source that does not want to be read does."""
        self.refusals[url] = status

    def esbirka(self, key: str, year: str, number: str, pages: int = 2) -> None:
        """Serve a saved Czech act: its metadata, then its fragments over ``pages`` pages."""
        payload = saved(key)
        fragments: list[dict[str, Any]] = payload["document"]
        self.register(
            ESBIRKA + urllib.parse.quote(f"/sb/{year}/{number}", safe=""),
            json.dumps(
                {
                    "staleUrl": payload["version"],
                    "datumUcinnostiZneniOd": payload["version_date"],
                }
            ).encode("utf-8"),
        )
        per_page = -(-len(fragments) // pages)
        for page in range(pages):
            self.register(
                f"{payload['url']}?cisloStranky={page}",
                json.dumps(
                    {
                        "seznam": fragments[page * per_page : (page + 1) * per_page],
                        "pocetStranek": pages,
                    }
                ).encode("utf-8"),
            )

    def cellar(self, key: str) -> None:
        """Serve a saved EU document under its CELEX."""
        payload = saved(key)
        self.register(CELLAR + payload["version"], payload["document"].encode("utf-8"))

    # answering -----------------------------------------------------------------------

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Answer the fetcher's requests from here for the rest of the test."""
        monkeypatch.setattr(urllib.request, "urlopen", self._urlopen)

    def _urlopen(self, request: urllib.request.Request, timeout: float | None = None) -> Answered:
        self.asked.append(request)
        url = request.full_url
        if url in self.refusals:
            raise self._http_error(url, self.refusals[url], "Forbidden")
        if url.startswith(SPARQL):
            return Answered(self._sparql(url))
        body = self.answers.get(url)
        if body is None:
            raise self._http_error(url, 404, "Not Found")
        return Answered(body)

    def _sparql(self, url: str) -> bytes:
        """The endpoint's answer: the rows it has, and none for something it does not know."""
        query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["query"][0]
        rows: list[dict[str, dict[str, str]]] = []
        base = STRSTARTS.search(query)
        celex = QUOTED_CELEX.search(query)
        if base:
            rows = [{"id": {"value": v}} for v in self.consolidations.get(base.group(1), [])]
        elif celex and celex.group(1) in self.dates:
            rows = [{"date": {"value": self.dates[celex.group(1)]}}]
        return json.dumps({"results": {"bindings": rows}}).encode("utf-8")

    @staticmethod
    def _http_error(url: str, status: int, reason: str) -> urllib.error.HTTPError:
        return urllib.error.HTTPError(url, status, reason, email.message.Message(), None)


def saved_sources() -> SavedSources:
    """A double holding all four sources, each at the version its saved slice records."""
    hosts = SavedSources()
    hosts.esbirka("cz-474-2002", "2002", "474")
    hosts.esbirka("cz-361-2007-annex-7", "2007", "361")
    hosts.cellar("eu-2021-821-annex-i")
    hosts.cellar("eu-2019-2072-annex-ii")
    hosts.dates[ANNEX_I_CELEX] = saved("eu-2021-821-annex-i")["version_date"]
    hosts.consolidations[ANNEX_II_BASE] = [saved("eu-2019-2072-annex-ii")["version"]]
    return hosts
