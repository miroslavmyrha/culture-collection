"""A Markdown summary of JUnit reports for the CI job page ($GITHUB_STEP_SUMMARY, #42).

python tools/junit_summary.py REPORT... prints one table row per report (tests, failed,
skipped, seconds) and the names of the failed tests. A report that is missing or unreadable
says so in its row: a step that never ran its tests is a finding, not a blank. Standard
library only, so CI runs it with the runner's own Python.
"""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET  # the job's own reports, not input from outside
from dataclasses import dataclass, field
from pathlib import Path

MOST_NAMED = 20


@dataclass
class Report:
    name: str
    tests: int = 0
    failed: int = 0
    skipped: int = 0
    seconds: float = 0.0
    failures: list[str] = field(default_factory=list)
    problem: str = ""


def read(path: Path) -> Report:
    """The counts and failed test names of one JUnit file (testsuites or one testsuite)."""
    report = Report(path.name)
    try:
        root = ET.parse(path).getroot()  # noqa: S314  # the job's own report
    except (OSError, ET.ParseError) as error:
        report.problem = f"no report ({type(error).__name__})"
        return report
    for case in root.iter("testcase"):
        report.tests += 1
        report.seconds += float(case.get("time") or 0)
        if case.find("failure") is not None or case.find("error") is not None:
            report.failed += 1
            report.failures.append(f"{case.get('classname', '')} {case.get('name', '')}".strip())
        elif case.find("skipped") is not None:
            report.skipped += 1
    return report


def markdown(reports: list[Report]) -> str:
    lines = ["| Report | Tests | Failed | Skipped | Seconds |", "|---|---:|---:|---:|---:|"]
    for r in reports:
        if r.problem:
            lines.append(f"| {r.name} | {r.problem} | | | |")
        else:
            lines.append(f"| {r.name} | {r.tests} | {r.failed} | {r.skipped} | {r.seconds:.0f} |")
    failed = [name for r in reports for name in r.failures]
    if failed:
        lines += ["", f"Failed ({len(failed)}):", ""]
        lines += [f"- `{name}`" for name in failed[:MOST_NAMED]]
        if len(failed) > MOST_NAMED:
            lines.append(f"- and {len(failed) - MOST_NAMED} more")
    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    sys.stdout.write(markdown([read(Path(arg)) for arg in argv]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
