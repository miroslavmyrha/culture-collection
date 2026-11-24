"""The CI summary of the JUnit reports (#42): counts, failed names, and a missing report named."""

from __future__ import annotations

from pathlib import Path

from tools.junit_summary import MOST_NAMED, markdown, read

PYTEST = """<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite name="pytest" tests="4">
<testcase classname="cultures.labs.tests.test_models" name="test_ok" time="0.5"/>
<testcase classname="cultures.labs.tests.test_models" name="test_broken" time="1.25">
<failure message="assert">boom</failure></testcase>
<testcase classname="cultures.core.tests.test_x" name="test_error" time="0.25"><error/></testcase>
<testcase classname="cultures.core.tests.test_x" name="test_later" time="0"><skipped/></testcase>
</testsuite></testsuites>
"""


def test_a_report_gives_its_counts_and_failed_names(tmp_path: Path) -> None:
    path = tmp_path / "pytest.xml"
    path.write_text(PYTEST)
    report = read(path)
    assert (report.tests, report.failed, report.skipped, report.seconds) == (4, 2, 1, 2.0)
    assert report.failures == [
        "cultures.labs.tests.test_models test_broken",
        "cultures.core.tests.test_x test_error",
    ]
    text = markdown([report])
    assert "| pytest.xml | 4 | 2 | 1 | 2 |" in text
    assert "- `cultures.labs.tests.test_models test_broken`" in text


def test_a_missing_or_broken_report_is_named_not_blank(tmp_path: Path) -> None:
    broken = tmp_path / "junit.xml"
    broken.write_text("<testsuites><testsuite")
    text = markdown([read(tmp_path / "absent.xml"), read(broken)])
    assert "| absent.xml | no report (FileNotFoundError) |" in text
    assert "| junit.xml | no report (ParseError) |" in text


def test_a_long_list_of_failures_is_cut(tmp_path: Path) -> None:
    cases = "".join(
        f'<testcase classname="c" name="t{i}"><failure/></testcase>' for i in range(MOST_NAMED + 5)
    )
    path = tmp_path / "many.xml"
    path.write_text(f"<testsuite>{cases}</testsuite>")
    text = markdown([read(path)])
    assert text.count("- `c t") == MOST_NAMED
    assert "- and 5 more" in text
