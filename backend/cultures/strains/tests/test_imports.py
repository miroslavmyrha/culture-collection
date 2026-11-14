"""The strain selectors do not import the lineage selectors (#229): those import these, and a
cycle forced an import inside a function. Which batches may go out lives in its own module."""

import ast
from pathlib import Path

import cultures.strains.selectors as strain_selectors


def test_the_strain_selectors_do_not_import_the_lineage_selectors() -> None:
    tree = ast.parse(Path(strain_selectors.__file__).read_text())
    imported = {
        node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module
    }
    assert "cultures.lineage.selectors" not in imported
    assert "cultures.lineage.distributable" in imported
