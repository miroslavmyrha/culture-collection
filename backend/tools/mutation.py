"""The nightly mutation run over the audit and the regulated services (#239, ADR 0005).

python tools/mutation.py run AREA [--max-children N] [--summary FILE]
    writes setup.cfg for the area, runs mutmut, lists the mutants that were not killed and
    compares them with tools/mutation_baseline.toml. Exit 1 when a mutant outside the baseline
    survived: a test that stopped proving its rule is a finding. A baseline entry that is now
    killed is reported, not failed: remove it.
python tools/mutation.py areas
    prints the area names, one a line (the workflow's matrix reads them).

Each area mutates its own files and runs only its own focused tests, without the slow ones
(threads and real transactions do not fit mutmut's forked runs), so one area fits a runner.
Mutant names carry their function and a number: when a function changes, its baseline entries
are rewritten from the next run's list, each with its reason.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
BASELINE = BACKEND / "tools" / "mutation_baseline.toml"
# mutmut through the running interpreter: no PATH lookup.
MUTMUT = (sys.executable, "-m", "mutmut")
NOT_KILLED = frozenset({"survived", "no tests", "suspicious"})


@dataclass(frozen=True)
class Area:
    sources: tuple[str, ...]
    tests: tuple[str, ...]


def _tests(app: str, *names: str) -> tuple[str, ...]:
    return tuple(f"cultures/{app}/tests/{name}" for name in names)


AREAS: dict[str, Area] = {
    "audit": Area(
        ("cultures/audit/events.py", "cultures/audit/context.py"),
        _tests(
            "audit",
            "test_events.py",
            "test_request.py",
            "test_row_changes.py",
            "test_append_only.py",
            "test_claims.py",
        ),
    ),
    "distribution": Area(
        (
            "cultures/distribution/policy.py",
            "cultures/distribution/services/shipment.py",
            "cultures/distribution/services/two_person.py",
            "cultures/distribution/services/decisions.py",
        ),
        _tests(
            "distribution",
            "test_policy.py",
            "test_shipment.py",
            "test_two_person.py",
            "test_approve_again.py",
            "test_request_states.py",
        ),
    ),
    "lineage": Area(
        ("cultures/lineage/services/destructions.py", "cultures/lineage/services/losses.py"),
        _tests(
            "lineage", "test_destructions.py", "test_destruction_guards.py", "test_loss_reports.py"
        ),
    ),
    "strains": Area(
        ("cultures/strains/services/risk_group.py", "cultures/strains/services/restrictions.py"),
        _tests(
            "strains",
            "test_risk_group_basis.py",
            "test_risk_group_proposals.py",
            "test_end_proposals.py",
            "test_services.py",
        ),
    ),
    "users": Area(
        ("cultures/users/factors.py", "cultures/users/login_limits.py", "cultures/users/signin.py"),
        _tests(
            "users",
            "test_second_factor.py",
            "test_enrolment_code.py",
            "test_factor_reset.py",
            "test_login_limits.py",
            "test_auth.py",
        ),
    ),
}


def setup_cfg(area: Area) -> str:
    """mutmut's config for one area. mutmut reads setup.cfg when pyproject has no
    [tool.mutmut], so the areas need no second pyproject."""

    def lines(values: tuple[str, ...]) -> str:
        return "".join(f"\n    {value}" for value in values)

    return (
        "# Written by tools/mutation.py for one area of the nightly run; not kept.\n"
        "[mutmut]\n"
        "source_paths = cultures\n"
        f"only_mutate ={lines(area.sources)}\n"
        f"also_copy ={lines(('config', 'conftest.py', 'cultures', 'tools', 'manage.py'))}\n"
        "pytest_add_cli_args ="
        f"{lines(('-p', 'no:cacheprovider', '--ds=config.settings.test', '-m', 'not slow'))}\n"
        f"pytest_add_cli_args_test_selection ={lines(area.tests)}\n"
        "use_git_change_detection = false\n"
    )


def not_killed(results: str) -> dict[str, str]:
    """The mutants `mutmut results` lists as not killed, with their status."""
    found: dict[str, str] = {}
    for line in results.splitlines():
        name, separator, status = line.strip().rpartition(": ")
        if separator and name and status in NOT_KILLED:
            found[name] = status
    return found


def compare(found: dict[str, str], baseline: dict[str, str]) -> tuple[list[str], list[str]]:
    """New survivors (a finding) and baseline entries now killed (to remove)."""
    return sorted(set(found) - set(baseline)), sorted(set(baseline) - set(found))


def load_baseline(area: str, path: Path | None = None) -> dict[str, str]:
    """The known survivors of an area, each with its reason."""
    path = path or BASELINE
    if not path.exists():
        return {}
    section = tomllib.loads(path.read_text(encoding="utf-8")).get(area, {})
    return {str(name): str(reason) for name, reason in section.items()}


def summary(area: str, found: dict[str, str], new: list[str], gone: list[str]) -> str:
    """A Markdown section for the job page."""
    out = [f"### Mutation: {area}", ""]
    out.append(
        f"Not killed: {len(found)} ({len(new)} new, {len(found) - len(new)} in the baseline)."
    )
    if new:
        out += ["", "New, not in tools/mutation_baseline.toml:", ""]
        out += [f"- `{name}`: {found[name]}" for name in new]
    if gone:
        out += ["", "Killed now, remove from the baseline:", ""]
        out += [f"- `{name}`" for name in gone]
    return "\n".join(out) + "\n"


def run(area_name: str, max_children: int, summary_path: Path | None) -> int:
    area = AREAS[area_name]
    (BACKEND / "setup.cfg").write_text(setup_cfg(area), encoding="utf-8")
    mutmut = [*MUTMUT, "run", "--max-children", str(max_children)]
    subprocess.run(mutmut, cwd=BACKEND, check=False)  # noqa: S603  # fixed arguments
    results = subprocess.run(  # noqa: S603  # fixed arguments
        [*MUTMUT, "results"], cwd=BACKEND, capture_output=True, text=True, check=False
    ).stdout
    found = not_killed(results)
    new, gone = compare(found, load_baseline(area_name))
    for name in new:  # the diff of each new survivor, in the log
        subprocess.run([*MUTMUT, "show", name], cwd=BACKEND, check=False)  # noqa: S603
    text = summary(area_name, found, new, gone)
    sys.stdout.write(text)
    if summary_path is not None:
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        with summary_path.open("a", encoding="utf-8") as handle:
            handle.write(text)
    return 1 if new else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("areas")
    run_parser = commands.add_parser("run")
    run_parser.add_argument("area", choices=sorted(AREAS))
    run_parser.add_argument("--max-children", type=int, default=1)
    run_parser.add_argument("--summary", type=Path)
    args = parser.parse_args(argv)
    if args.command == "areas":
        sys.stdout.write("\n".join(sorted(AREAS)) + "\n")
        return 0
    return run(args.area, args.max_children, args.summary)


if __name__ == "__main__":
    sys.exit(main())
