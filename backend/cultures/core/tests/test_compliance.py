"""docs/compliance.md agrees with the code and the tests (#168).

Every rule about regulated material has an entry there with its kind, its source, the code that
enforces it and the tests that prove it, and each of those tests carries the rule's id as
`@pytest.mark.rule("<id>")`. This test reads the document and the source files (it imports no
test module) and fails for any entry or marker the other side does not confirm. How to read the
document and the checks it is held to: its first two sections.

The checker is a function of the text, the test index, the gate codes and a backend directory,
so the tests at the end run it on small broken documents and prove that each check refuses.
"""

import ast
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from django.conf import settings

from cultures.distribution.policy import gate_codes

BACKEND = Path(settings.BASE_DIR)
# docs/ beside backend/; compose mounts it read-only at /docs next to /app.
DOC = BACKEND.parent / "docs" / "compliance.md"

KINDS = frozenset({"law", "law in part", "own control", "not verified"})
QUOTED = frozenset({"law", "law in part"})
HEADING = re.compile(r"^#{2,6} (?P<id>R-[A-Z]+-\d{2}|[DC]-\d{2}) \S")
NOT_REGULATED_GATES = "### Gates that are not about regulated material"
FIELD = re.compile(r"^- (?P<name>[A-Z][a-z]+(?: [a-z]+)?): ?(?P<value>.*)$")
QUOTE = re.compile(r"„[^“]+“|\"[^\"]+\"")
TICKED = re.compile(r"`([^`]+)`")
REF = re.compile(r"^(?P<path>backend/[\w/.]+\.py)::(?P<symbol>\"[^\"]+\"|[\w.]+)$")
TEST_REF = re.compile(r"^(?P<path>backend/[\w/.]+\.py)::(?P<name>(?:[A-Z]\w*::)?test_\w+)$")


@dataclass
class Entry:
    id: str
    line: int
    fields: dict[str, str] = field(default_factory=dict)

    def refs(self, name: str) -> list[str]:
        return TICKED.findall(self.fields.get(name, ""))


def parse(doc: str) -> tuple[list[Entry], list[str]]:
    """The entries (rules, duties, breaks and the list of gates not about regulated material,
    id "gates") in order, and the problems of the text itself."""
    entries: list[Entry] = []
    problems: list[str] = []
    current: Entry | None = None
    name: str | None = None
    for n, line in enumerate(doc.splitlines(), start=1):
        if line.startswith("#"):
            name = None
            match = HEADING.match(line)
            if match:
                current = Entry(match["id"], n)
                entries.append(current)
            elif line.strip() == NOT_REGULATED_GATES:
                current = Entry("gates", n)
                entries.append(current)
            elif re.match(r"^#{2,6} [RDC]-", line):
                problems.append(f"line {n}: a heading that looks like an id but is not one: {line}")
                current = None
            else:
                current = None
            continue
        if current is None:
            continue
        match = FIELD.match(line)
        if match:
            name = match["name"]
            if name in current.fields:
                problems.append(f"{current.id}: the field {name} twice")
            current.fields[name] = match["value"].strip()
        elif line.startswith("  ") and name is not None:
            current.fields[name] += " " + line.strip()
        else:
            name = None
    return entries, problems


def _strings(tree: ast.AST) -> Iterable[str]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            yield node.value


def _members(body: list[ast.stmt]) -> dict[str, ast.stmt]:
    found: dict[str, ast.stmt] = {}
    for node in body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            found[node.name] = node
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    found[target.id] = node
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            found[node.target.id] = node
    return found


def code_problem(ref: str, backend: Path) -> str | None:
    """Why a code reference names nothing, or None. `path::symbol` is a function, class or
    constant (dotted for a member of a class), `path::"text"` a string the file holds."""
    match = REF.match(ref)
    if not match:
        return f'{ref}: not path::symbol or path::"text"'
    path = backend / match["path"].removeprefix("backend/")
    if not path.is_file():
        return f"{ref}: no such file"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    symbol = match["symbol"]
    if symbol.startswith('"'):
        text = symbol.strip('"')
        if not any(text in s for s in _strings(tree)):
            return f"{ref}: no string in the file holds {text}"
        return None
    body: list[ast.stmt] = tree.body
    for part in symbol.split("."):
        node = _members(body).get(part)
        if node is None:
            return f"{ref}: no {part} in the file"
        body = node.body if isinstance(node, ast.ClassDef) else []
    return None


def _rule_ids(decorator: ast.expr) -> list[str] | None:
    """The ids of a `pytest.mark.rule(...)` decorator, or None for any other decorator."""
    if not isinstance(decorator, ast.Call):
        return None
    func = decorator.func
    if not (
        isinstance(func, ast.Attribute)
        and func.attr == "rule"
        and isinstance(func.value, ast.Attribute)
        and func.value.attr == "mark"
    ):
        return None
    return [
        a.value for a in decorator.args if isinstance(a, ast.Constant) and isinstance(a.value, str)
    ]


@dataclass
class MarkerIndex:
    # "backend/<path>::<name>" (or "::Class::name") of every test function, with its rule ids.
    tests: dict[str, set[str]] = field(default_factory=dict)
    # Markers placed anywhere but on a test function.
    stray: list[str] = field(default_factory=list)


def _index_body(
    body: list[ast.stmt], prefix: str, relative: str, index: MarkerIndex, placed: set[int]
) -> None:
    for node in body:
        if isinstance(node, ast.ClassDef):
            _index_body(node.body, f"{prefix}{node.name}::", relative, index, placed)
        elif isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
            ids: set[str] = set()
            for decorator in node.decorator_list:
                found = _rule_ids(decorator)
                if found is not None:
                    ids.update(found)
                    placed.add(id(decorator))
            index.tests[f"{relative}::{prefix}{node.name}"] = ids


def index_tests(backend: Path) -> MarkerIndex:
    index = MarkerIndex()
    for path in sorted((backend / "cultures").rglob("test_*.py")):
        relative = f"backend/{path.relative_to(backend).as_posix()}"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        placed: set[int] = set()
        _index_body(tree.body, "", relative, index, placed)
        index.stray += [
            f"{relative}:{node.lineno}"
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and _rule_ids(node) is not None and id(node) not in placed
        ]
    return index


def rule_problems(entry: Entry, index: MarkerIndex, backend: Path) -> list[str]:
    """What is wrong with one rule: its fields, its code and its tests."""
    found: list[str] = []
    kind = entry.fields.get("Kind", "")
    if kind not in KINDS:
        found.append(f"{entry.id}: kind {kind!r} is none of {sorted(KINDS)}")
    if kind in QUOTED and not QUOTE.search(entry.fields.get("Quote", "")):
        found.append(f"{entry.id}: a rule of kind {kind} quotes no sentence of its source")
    if not entry.fields.get("Source"):
        found.append(f"{entry.id}: names no source")
    if not entry.refs("Code"):
        found.append(f"{entry.id}: names no code")
    found += [f"{entry.id}: {p}" for ref in entry.refs("Code") if (p := code_problem(ref, backend))]
    if not entry.refs("Tests"):
        found.append(f"{entry.id}: names no test")
    for ref in entry.refs("Tests"):
        if not TEST_REF.match(ref):
            found.append(f"{entry.id}: {ref}: not path::test_name")
        elif ref not in index.tests:
            found.append(f"{entry.id}: {ref}: no such test")
        elif entry.id not in index.tests[ref]:
            found.append(f'{entry.id}: {ref} does not carry @pytest.mark.rule("{entry.id}")')
    return found


def problems(doc: str, index: MarkerIndex, gates: set[str], backend: Path) -> list[str]:
    entries, found = parse(doc)
    seen: set[str] = set()
    named: dict[str, set[str]] = {}  # rule id -> the tests it names
    documented_gates: set[str] = set()
    for entry in entries:
        if entry.id in seen:
            found.append(f"{entry.id}: the id is used twice")
        seen.add(entry.id)
        documented_gates.update(entry.refs("Gate codes"))
        if entry.id.startswith("R-"):
            found += rule_problems(entry, index, backend)
            named[entry.id] = set(entry.refs("Tests"))
        elif entry.id != "gates" and not entry.fields.get("Issue"):
            found.append(f"{entry.id}: names no issue (write the issue, or none)")
    for ref, ids in sorted(index.tests.items()):
        for rule in sorted(ids):
            if rule not in named:
                found.append(f"{ref} carries {rule}, which is no rule of the document")
            elif ref not in named[rule]:
                found.append(f"{ref} carries {rule}, and {rule} does not name it")
    found += [f"{place}: a rule marker that is not on a test function" for place in index.stray]
    found += [f"gate code {code}: in no rule" for code in sorted(gates - documented_gates)]
    found += [f"gate code {code}: no such code" for code in sorted(documented_gates - gates)]
    return found


def test_the_document_agrees_with_the_code_and_the_tests() -> None:
    assert DOC.is_file(), f"{DOC} not found: compose mounts ./docs at /docs"
    doc = DOC.read_text(encoding="utf-8")
    markers = index_tests(BACKEND)
    entries, _ = parse(doc)
    # The walk is not empty: the document has its rules and the tests carry their markers.
    assert sum(e.id.startswith("R-") for e in entries) >= 50
    assert sum(bool(ids) for ids in markers.tests.values()) >= 100
    assert problems(doc, markers, set(gate_codes()), BACKEND) == []


# The checks refuse what they claim to refuse: each case breaks one thing of a small document.

GOOD = """\
## Rules enforced

#### R-TEST-01 A rule of the law

- Kind: law
- Source: act 1/2000 Sb., § 1
- Quote: „Věta zákona.“
- English: A sentence of the act.
- Code: `backend/cultures/x/rules.py::check`, `backend/cultures/x/rules.py::Box.limit`,
  `backend/cultures/x/rules.py::"x_box_guard"`
- Tests: `backend/cultures/x/tests/test_x.py::test_it`
- Gate codes: `gate_a`

### Gates that are not about regulated material

- Gate codes: `gate_b`

## Legal duties the app does not enforce yet

### D-01 A duty

- Source: act 1/2000 Sb., § 2
- Issue: #1
"""


@pytest.fixture
def backend(tmp_path: Path) -> Path:
    (tmp_path / "cultures/x/tests").mkdir(parents=True)
    (tmp_path / "cultures/x/rules.py").write_text(
        "def check() -> None: ...\n\n"
        "class Box:\n    limit = 3\n\n"
        'SQL = "CREATE TRIGGER x_box_guard"\n'
    )
    return tmp_path


def index(**tests: set[str]) -> MarkerIndex:
    return MarkerIndex(
        tests={f"backend/cultures/x/tests/test_x.py::{k}": v for k, v in tests.items()}
    )


GATES = {"gate_a", "gate_b"}


def test_a_document_that_agrees_has_no_problem(backend: Path) -> None:
    assert problems(GOOD, index(test_it={"R-TEST-01"}), GATES, backend) == []


@pytest.mark.parametrize(
    ("old", "new", "expected"),
    [
        ("::test_it`", "::test_gone`", "test_gone: no such test"),
        ("- Quote: „Věta zákona.“", "- Quote: Věta zákona.", "quotes no sentence"),
        ("- Quote: „Věta zákona.“\n", "", "quotes no sentence"),
        ("- Kind: law", "- Kind: probably law", "kind 'probably law'"),
        ("rules.py::check`", "rules.py::checks`", "no checks in the file"),
        ("::Box.limit`", "::Box.size`", "no size in the file"),
        ('::"x_box_guard"`', '::"x_box_gard"`', "no string in the file holds x_box_gard"),
        ("x/rules.py::check", "x/rule.py::check", "no such file"),
        ("- Tests: `backend/cultures/x/tests/test_x.py::test_it`", "- Tests:", "names no test"),
        ("- Issue: #1", "- Issue:", "D-01: names no issue"),
        ("`gate_a`", "`gate_c`", "gate code gate_c: no such code"),
        ("- Gate codes: `gate_b`", "- Gate codes:", "gate code gate_b: in no rule"),
        ("### D-01 A duty", "#### R-TEST-01 Again", "R-TEST-01: the id is used twice"),
        ("#### R-TEST-01 A rule", "#### R-TEST-1 A rule", "looks like an id but is not one"),
    ],
)
def test_a_broken_document_is_refused(backend: Path, old: str, new: str, expected: str) -> None:
    doc = GOOD.replace(old, new, 1)
    assert doc != GOOD
    found = problems(doc, index(test_it={"R-TEST-01"}), GATES, backend)
    assert any(expected in p for p in found), found


@pytest.mark.parametrize(
    ("tests", "expected"),
    [
        ({"test_it": set()}, 'does not carry @pytest.mark.rule("R-TEST-01")'),
        ({"test_it": {"R-TEST-01", "R-TEST-02"}}, "carries R-TEST-02, which is no rule"),
        ({"test_it": {"R-TEST-01"}, "test_other": {"R-TEST-01"}}, "R-TEST-01 does not name it"),
    ],
)
def test_a_marker_the_document_does_not_confirm_is_refused(
    backend: Path, tests: dict[str, set[str]], expected: str
) -> None:
    found = problems(GOOD, index(**tests), GATES, backend)
    assert any(expected in p for p in found), found


def test_the_index_reads_markers_from_decorators_only(backend: Path) -> None:
    (backend / "cultures/x/tests/test_x.py").write_text(
        "import pytest\n\n"
        '@pytest.mark.rule("R-TEST-01", "R-TEST-02")\ndef test_it() -> None: ...\n\n'
        "class TestBox:\n"
        '    @pytest.mark.rule("R-TEST-03")\n    def test_in_class(self) -> None: ...\n\n'
        'pytestmark = [pytest.mark.rule("R-TEST-04")]\n\n'
        "def test_plain() -> None: ...\n"
    )
    found = index_tests(backend)
    assert found.tests == {
        "backend/cultures/x/tests/test_x.py::test_it": {"R-TEST-01", "R-TEST-02"},
        "backend/cultures/x/tests/test_x.py::TestBox::test_in_class": {"R-TEST-03"},
        "backend/cultures/x/tests/test_x.py::test_plain": set(),
    }
    assert found.stray == ["backend/cultures/x/tests/test_x.py:10"]
