#!/usr/bin/env python3
"""Code risk score (CRAP) per function, for the Python backend and the TypeScript frontend.

    CRAP = complexity^2 * (1 - coverage)^3 + complexity

A function scores badly only when it is both complex and undertested: covering it or splitting
it brings the score down. The script reads reports that other tools wrote and joins them, it
runs nothing itself. See issue #196.

Python (from the backend directory, inside the dev container, which has both tools)::

    coverage run --source=. -m pytest -q
    coverage json -o /tmp/py-coverage.json
    radon cc -j /app > /tmp/py-radon.json

TypeScript (from the frontend directory)::

    npx vitest run --coverage --coverage.reporter=json --coverage.include='src/**' \
        --coverage.reportsDirectory=/tmp/ts-coverage
    npx oxlint -c <config with {"rules": {"complexity": ["warn", {"max": 1}]}}> -f json src \
        > /tmp/ts-complexity.json

Then::

    python tools/crap.py --py-coverage /tmp/py-coverage.json --py-radon /tmp/py-radon.json \
        --ts-coverage /tmp/ts-coverage/coverage-final.json --ts-complexity /tmp/ts-complexity.json

What is measured: every function and method, nested functions on their own. Coverage of a
function is the share of its statements that ran, the ``def`` line itself not counted (it runs
at import, so it would give an untested one-line function 50%). A function without a single
statement is skipped. Left out: migrations, test files and the shared test tools (they produce
the coverage), generated files (``schema.d.ts``), type declaration files. oxlint reports only
functions above its threshold, so a TypeScript function it does not mention has complexity 1.
A callback v8 does not report as a function of its own adds its decisions to the function that
holds it. A file with no coverage data is listed under "no coverage data" and is not scored.

``--gate LIMIT`` makes it a check (``check.sh`` runs it): it fails when a function scores over
the limit, and also when something could not be measured, a file with no coverage data or a
complexity that lands on no function, because a gap there would pass unseen.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

END = 10**9  # an end column v8 left null: the end of the line
DEFAULT_LIMITS = (10, 15, 20, 30, 50)
TOP = 20

PY_EXCLUDED = re.compile(r"(^|/)(migrations|tests|testing)/|(^|/)conftest\.py$")
TS_EXCLUDED = re.compile(r"\.test\.tsx?$|\.d\.ts$|(^|/)test/|(^|/)e2e/")


@dataclass(frozen=True)
class Func:
    side: str
    file: str
    line: int
    name: str
    complexity: int
    coverage: float
    score: float


def crap(complexity: int, coverage: float) -> float:
    """The score of one function. ``coverage`` is a share from 0 to 1."""
    if not 0 <= coverage <= 1:
        raise ValueError(f"coverage must be between 0 and 1, got {coverage}")
    return complexity**2 * (1 - coverage) ** 3 + complexity


def _rel(path: str, root: str) -> str:
    path = path.replace("\\", "/")
    root = root.rstrip("/") + "/"
    return path[len(root) :] if root != "/" and path.startswith(root) else path.lstrip("/")


def _radon_functions(blocks: list[dict[str, Any]], prefix: str = "") -> list[dict[str, Any]]:
    """Flatten radon's blocks into functions: methods and closures become their own entries.

    ``radon cc -j`` lists a method twice, at the top level (with ``classname``) and under its
    class, so the result is deduplicated by the line the function starts on.
    """
    found: dict[int, dict[str, Any]] = {}

    def walk(items: list[dict[str, Any]], prefix: str) -> None:
        for b in items:
            name = prefix + (b["classname"] + "." if b.get("classname") else "") + b["name"]
            if b["type"] in ("function", "method"):
                found.setdefault(b["lineno"], {**b, "name": name})
                walk(b.get("closures", []), name + ".")
            elif b["type"] == "class":
                walk(b.get("methods", []), prefix + b["name"] + ".")

    walk(blocks, prefix)
    return list(found.values())


def python_functions(
    coverage: dict[str, Any], radon: dict[str, Any], root: str = "/app"
) -> tuple[list[Func], list[str], list[str]]:
    """Join coverage.py's JSON report with ``radon cc -j``.

    Returns (scored functions, files with no coverage data, skipped for having no statements).
    """
    cov_files = {_rel(p, root): d for p, d in coverage.get("files", {}).items()}
    scored: list[Func] = []
    missing: list[str] = []
    skipped: list[str] = []
    for path, blocks in radon.items():
        rel = _rel(path, root)
        funcs = _radon_functions(blocks) if isinstance(blocks, list) else []
        if PY_EXCLUDED.search(rel) or not funcs:
            continue
        if rel not in cov_files:
            missing.append(rel)
            continue
        scored += _score_python_file(rel, funcs, cov_files[rel], skipped)
    return scored, sorted(set(missing)), skipped


def _score_python_file(
    rel: str, funcs: list[dict[str, Any]], data: dict[str, Any], skipped: list[str]
) -> list[Func]:
    executed = set(data["executed_lines"])
    statements = executed | set(data["missing_lines"])
    scored = []
    for f in funcs:
        body = [n for n in statements if f["lineno"] < n <= f["endline"]]
        if not body:
            skipped.append(f"{rel}:{f['lineno']} {f['name']}")
            continue
        cov = sum(1 for n in body if n in executed) / len(body)
        scored.append(
            Func("python", rel, f["lineno"], f["name"], f["complexity"], cov,
                 crap(f["complexity"], cov))
        )  # fmt: skip
    return scored


def _pos(p: dict[str, Any], missing_column: int = 0) -> tuple[int, int]:
    """(line, column) of an istanbul position. v8 leaves some end columns null."""
    return (p["line"], missing_column if p["column"] is None else p["column"])


def _holding(
    fns: list[dict[str, Any]], line: int, col: int, *, free: bool
) -> dict[str, Any] | None:
    """The smallest function that holds the position, counted from the start of its
    declaration line; with ``free``, only one that has no complexity of its own yet."""
    holds = [f for f in fns if (f["decl"][0], 0) <= (line, col - 1) <= f["end"]]
    if free:
        holds = [f for f in holds if f["c"] == 1]
    return min(holds, key=lambda f: f["end"][0] - f["decl"][0], default=None)


def _place(
    fns: list[dict[str, Any]], diags: list[tuple[int, int, int]]
) -> list[tuple[int, int, int]]:
    """Put each complexity on its function, and return the ones that land on none.

    oxlint's span starts at the function keyword or the arrow's parameters, v8's decl is the
    name (or the parameters) and its loc the body, and oxlint counts columns from 1. First an
    exact match on the declaration, so a nested function cannot take it, then the smallest
    function that holds the position. v8 leaves out some callbacks it ran (a `.map((x) => ...)`
    inside JSX), so their own complexity has no function to land on. Their statements already
    count towards the function that holds them, and so do their branches: c - 1 decisions each.
    """
    left: list[tuple[int, int, int]] = []
    for line, col, c in diags:
        hit = next((f for f in fns if f["decl"] == (line, col - 1) and f["c"] == 1), None)
        if hit is None:
            left.append((line, col, c))
        else:
            hit["c"] = c
    unplaced = []
    for line, col, c in left:
        if (free := _holding(fns, line, col, free=True)) is not None:
            free["c"] = c
        elif (holder := _holding(fns, line, col, free=False)) is not None:
            holder["inner"] += c - 1
        else:
            unplaced.append((line, col, c))
    return unplaced


def _complexity_by_file(
    diagnostics: list[dict[str, Any]], root: str
) -> dict[str, list[tuple[int, int, int]]]:
    """oxlint's complexity diagnostics as file -> (line, column, complexity)."""
    by_file: dict[str, list[tuple[int, int, int]]] = {}
    for d in diagnostics:
        m = re.search(r"complexity of (\d+)", d["message"])
        if not m or not d.get("labels"):
            continue
        span = d["labels"][0]["span"]
        by_file.setdefault(_rel(d["filename"], root), []).append(
            (span["line"], span["column"], int(m.group(1)))
        )
    return by_file


def _ts_function_map(data: dict[str, Any]) -> list[dict[str, Any]]:
    fns = []
    for fn in data["fnMap"].values():
        start, end = _pos(fn["loc"]["start"]), _pos(fn["loc"]["end"], END)
        decl = _pos(fn.get("decl", fn["loc"])["start"])
        fns.append({"fn": fn, "start": start, "end": end, "decl": decl, "c": 1, "inner": 0})
    return fns


def _score_ts_file(
    rel: str, data: dict[str, Any], fns: list[dict[str, Any]], skipped: list[str]
) -> list[Func]:
    stmts = [(_pos(s["start"]), _pos(s["end"], END), data["s"][k]) for k, s in
             data["statementMap"].items()]  # fmt: skip
    scored = []
    for f in fns:
        inner = [hits for s0, s1, hits in stmts if f["start"] <= s0 and s1 <= f["end"]]
        if not inner:
            skipped.append(f"{rel}:{f['decl'][0]} {f['fn']['name']}")
            continue
        complexity = f["c"] + f["inner"]
        cov = sum(1 for h in inner if h > 0) / len(inner)
        scored.append(Func("typescript", rel, f["decl"][0], f["fn"]["name"], complexity, cov,
                           crap(complexity, cov)))  # fmt: skip
    return scored


def typescript_functions(
    coverage: dict[str, Any], diagnostics: list[dict[str, Any]], root: str
) -> tuple[list[Func], list[str], list[str], list[str]]:
    """Join the istanbul-shaped ``coverage-final.json`` with oxlint's complexity diagnostics.

    Returns (scored, files with no coverage data, skipped for having no statements, complexity
    diagnostics that matched no function).
    """
    by_file = _complexity_by_file(diagnostics, root)
    scored: list[Func] = []
    skipped: list[str] = []
    unmatched: list[str] = []
    cov_files = {_rel(p, root): d for p, d in coverage.items()}
    missing = sorted(f for f in by_file if f not in cov_files and not TS_EXCLUDED.search(f))
    for rel, data in cov_files.items():
        if TS_EXCLUDED.search(rel):
            continue
        fns = _ts_function_map(data)
        unmatched += [f"{rel}:{r[0]} complexity {r[2]}" for r in _place(fns, by_file.get(rel, []))]
        scored += _score_ts_file(rel, data, fns, skipped)
    return scored, missing, skipped, unmatched


def quartiles(values: list[float]) -> tuple[float, float, float, float, float]:
    """Minimum, 25th, 50th, 75th percentile and maximum."""
    if not values:
        return (0.0,) * 5
    if len(values) == 1:
        return (values[0],) * 5
    q = statistics.quantiles(values, n=4, method="inclusive")
    return (min(values), q[0], q[1], q[2], max(values))


def count_over(funcs: list[Func], limit: float) -> int:
    return sum(1 for f in funcs if f.score > limit)


def _table(rows: list[Func]) -> str:
    out = [
        "| file | line | name | complexity | coverage | score |",
        "|---|---:|---|---:|---:|---:|",
    ]
    out += [
        f"| {f.file} | {f.line} | {f.name} | {f.complexity} | {f.coverage:.0%} | {f.score:.1f} |"
        for f in rows
    ]
    return "\n".join(out)


def report(funcs: list[Func], limits: tuple[int, ...], top: int, full: bool) -> str:
    out: list[str] = []
    for side in ("python", "typescript"):
        mine = sorted((f for f in funcs if f.side == side), key=lambda f: -f.score)
        if not mine:
            continue
        mn, q1, med, q3, mx = quartiles([f.score for f in mine])
        out.append(f"## {side}: {len(mine)} functions measured")
        out.append(f"score min {mn:.1f}, quartiles {q1:.1f} / {med:.1f} / {q3:.1f}, max {mx:.1f}\n")
        out.append("functions over a limit: " + ", ".join(
            f"> {lim}: {count_over(mine, lim)}" for lim in limits) + "\n")  # fmt: skip
        out.append(f"### top {top}" if not full else "### all, by score")
        out.append(_table(mine if full else mine[:top]) + "\n")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--py-coverage", type=Path)
    ap.add_argument("--py-radon", type=Path)
    ap.add_argument("--py-root", default="/app", help="directory the Python paths are under")
    ap.add_argument("--ts-coverage", type=Path)
    ap.add_argument("--ts-complexity", type=Path)
    ap.add_argument("--ts-root", default="", help="directory the TypeScript paths are under")
    ap.add_argument("--limits", default=",".join(map(str, DEFAULT_LIMITS)))
    ap.add_argument("--top", type=int, default=TOP)
    ap.add_argument("--full", action="store_true", help="print every function, not the top")
    ap.add_argument("--gate", type=float, help="fail over this score, or on anything unmeasured")
    args = ap.parse_args(argv)
    limits = tuple(int(x) for x in args.limits.split(","))
    funcs: list[Func] = []
    notes: list[str] = []
    gaps: list[str] = []
    if args.py_coverage and args.py_radon:
        _measure_python(args, funcs, notes, gaps)
    if args.ts_coverage and args.ts_complexity:
        _measure_typescript(args, funcs, notes, gaps)
    if not funcs:
        sys.stderr.write(
            "nothing to measure: give --py-coverage with --py-radon and/or "
            "--ts-coverage with --ts-complexity\n"
        )
        return 2
    out = report(funcs, limits, args.top, args.full)
    sys.stdout.write(out + "\n" + "\n".join(f"- {n}" for n in notes + gaps) + "\n")
    if args.gate is None:
        return 0
    return gate(funcs, gaps, args.gate)


def _measure_python(
    args: argparse.Namespace, funcs: list[Func], notes: list[str], gaps: list[str]
) -> None:
    py, missing, skipped = python_functions(
        json.loads(args.py_coverage.read_text()),
        json.loads(args.py_radon.read_text()),
        args.py_root,
    )
    funcs += py
    notes.append(f"python: {len(skipped)} functions without statements skipped")
    gaps += [f"python: no coverage data, not scored: {m}" for m in missing]


def _measure_typescript(
    args: argparse.Namespace, funcs: list[Func], notes: list[str], gaps: list[str]
) -> None:
    # A relative root never matches the absolute paths v8 writes, and then every function
    # would read as complexity 1.
    root = str(Path(args.ts_root).resolve()) if args.ts_root else ""
    diag = json.loads(args.ts_complexity.read_text())["diagnostics"]
    ts, missing, skipped, unmatched = typescript_functions(
        json.loads(args.ts_coverage.read_text()), diag, root
    )
    funcs += ts
    notes.append(f"typescript: {len(skipped)} functions without statements skipped")
    gaps += [f"typescript: no coverage data, not scored: {m}" for m in missing]
    gaps += [f"typescript: complexity matched no function: {u}" for u in unmatched]


def gate(funcs: list[Func], gaps: list[str], limit: float) -> int:
    """1, with every function over the limit and every gap named, else 0."""
    over = sorted((f for f in funcs if f.score > limit), key=lambda f: -f.score)
    for f in over:
        sys.stderr.write(
            f"over {limit:g}: {f.file}:{f.line} {f.name} (complexity {f.complexity}, "
            f"coverage {f.coverage:.0%}, score {f.score:.1f})\n"
        )
    for g in gaps:
        sys.stderr.write(f"not measured: {g}\n")
    return 1 if over or gaps else 0


if __name__ == "__main__":
    sys.exit(main())
