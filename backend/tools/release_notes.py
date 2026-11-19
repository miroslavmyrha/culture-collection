"""The notes of a release (#179): its CHANGELOG.md section and the dependency updates.

    python3 backend/tools/release_notes.py 0.1.0 CHANGELOG.md [dependabot.json]

The section is "## [X.Y.Z] - YYYY-MM-DD", up to the next "## " heading; without it the release
stops, so no version ships without saying what changed. dependabot.json is the output of
`gh pr list --json number,title` over the Dependabot pull requests merged since the previous
release: they write no changelog line (#277), so the notes list them here.

Standard library only: the release workflow runs it on the runner, outside the image.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

VERSION = re.compile(r"^\d+\.\d+\.\d+$")
DATE = r"\d{4}-\d{2}-\d{2}"


class NotesError(Exception):
    """What is missing for the notes, said for the person cutting the release."""


def section(changelog: str, version: str) -> str:
    """The body of the version's section, without its heading."""
    if not VERSION.fullmatch(version):
        raise NotesError(f"{version!r} is not a version X.Y.Z")
    heading = re.compile(rf"^## \[{re.escape(version)}\] - {DATE}$", re.MULTILINE)
    found = heading.search(changelog)
    if found is None:
        raise NotesError(
            f'CHANGELOG.md has no "## [{version}] - YYYY-MM-DD" section: move the Unreleased'
            " lines under one before tagging"
        )
    rest = changelog[found.end() :]
    following = re.search(r"^## ", rest, re.MULTILINE)
    body = (rest[: following.start()] if following else rest).strip()
    if not body:
        raise NotesError(f"the section of {version} in CHANGELOG.md is empty")
    return body


def dependency_lines(pulls: list[dict[str, object]]) -> list[str]:
    """One line per merged Dependabot pull request, oldest number first."""
    ordered = sorted(pulls, key=lambda pull: int(str(pull["number"])))
    return [f"- {pull['title']} (#{pull['number']})" for pull in ordered]


def notes(changelog: str, version: str, pulls: list[dict[str, object]]) -> str:
    text = section(changelog, version)
    lines = dependency_lines(pulls)
    if lines:
        text += "\n\n### Dependency updates\n" + "\n".join(lines)
    return text + "\n"


def main(argv: list[str]) -> int:
    if not 2 <= len(argv) <= 3:  # noqa: PLR2004 (version, changelog, optional pulls)
        sys.stderr.write(__doc__ or "")
        return 2
    version, changelog_path, *rest = argv
    pulls = json.loads(Path(rest[0]).read_text(encoding="utf-8")) if rest else []
    try:
        sys.stdout.write(notes(Path(changelog_path).read_text(encoding="utf-8"), version, pulls))
    except NotesError as error:
        sys.stderr.write(f"FAILED: {error}\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
