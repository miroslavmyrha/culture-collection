"""Test tools every app shares. Imported by tests only, never by application code.

- logged_in(user): a Django test client with that user's real session
- assert_problem(response, status, code): the API's one error shape
- ViewsetContract and Write: the role matrix every scoped viewset passes
- run_before(target, name, competitor): a competing write at an exact point
- QueryBaseline: the type of the root conftest's query_baseline fixture
"""

from .clients import logged_in
from .contract import COVERED, ViewsetContract, Write
from .problems import PROBLEM_KEYS, assert_problem
from .queries import QueryBaseline
from .races import run_before

__all__ = [
    "COVERED",
    "PROBLEM_KEYS",
    "QueryBaseline",
    "ViewsetContract",
    "Write",
    "assert_problem",
    "logged_in",
    "run_before",
]
