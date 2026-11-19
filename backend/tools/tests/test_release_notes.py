"""The release notes: the version's changelog section, and a release without one stops."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.release_notes import NotesError, main, notes, section

CHANGELOG = """# Changelog

## Unreleased
- Something not released yet (#300).

## [0.2.0] - 2026-12-01
- A second line (#250).
- A first line (#240).

## [0.1.0] - 2026-11-20
- The first release (#179).
"""


def test_the_section_of_the_version_and_nothing_around_it() -> None:
    assert section(CHANGELOG, "0.2.0") == "- A second line (#250).\n- A first line (#240)."
    assert section(CHANGELOG, "0.1.0") == "- The first release (#179)."


def test_a_version_without_a_section_stops_the_release() -> None:
    with pytest.raises(NotesError, match=r"no \"## \[0\.3\.0\] - YYYY-MM-DD\" section"):
        section(CHANGELOG, "0.3.0")


def test_unreleased_lines_are_not_a_release() -> None:
    # The Unreleased heading names no version: tagging before moving the lines stops.
    with pytest.raises(NotesError):
        section("## Unreleased\n- Something (#1).\n", "0.1.0")


def test_a_heading_without_its_date_is_not_the_section() -> None:
    with pytest.raises(NotesError):
        section("## [0.1.0]\n- Something (#1).\n", "0.1.0")


def test_an_empty_section_stops_the_release() -> None:
    with pytest.raises(NotesError, match="empty"):
        section("## [0.1.0] - 2026-11-20\n\n## [0.0.9] - 2026-11-01\n- Old.\n", "0.1.0")


def test_a_tag_that_is_not_a_version_is_refused() -> None:
    with pytest.raises(NotesError, match="not a version"):
        section(CHANGELOG, "v0.1.0")


def test_dependabot_updates_follow_the_section_in_number_order() -> None:
    pulls: list[dict[str, object]] = [
        {"number": 275, "title": "chore(deps): bump nginx"},
        {"number": 272, "title": "chore(deps): bump uv"},
    ]
    assert notes(CHANGELOG, "0.1.0", pulls) == (
        "- The first release (#179).\n\n### Dependency updates\n"
        "- chore(deps): bump uv (#272)\n- chore(deps): bump nginx (#275)\n"
    )


def test_no_dependency_heading_without_updates() -> None:
    assert "Dependency" not in notes(CHANGELOG, "0.1.0", [])


def test_main_prints_the_notes_and_fails_loudly(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(CHANGELOG, encoding="utf-8")
    pulls = tmp_path / "pulls.json"
    pulls.write_text(json.dumps([{"number": 1, "title": "bump"}]), encoding="utf-8")
    assert main(["0.1.0", str(changelog), str(pulls)]) == 0
    assert capsys.readouterr().out.endswith("- bump (#1)\n")
    assert main(["9.9.9", str(changelog)]) == 1
    assert "FAILED: CHANGELOG.md has no" in capsys.readouterr().err
    assert main([]) == 2
