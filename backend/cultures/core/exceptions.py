"""Domain exceptions raised by services and selectors.

They carry no HTTP or DRF types, so services stay usable from commands and
tasks. The API exception handler (cultures.core.errors) maps each to a status code
and the one problem-details error shape.
"""

from typing import ClassVar


class DomainError(Exception):
    status_code: ClassVar[int] = 400
    default_code: ClassVar[str] = "invalid"
    default_detail: ClassVar[str] = "The request could not be processed."

    def __init__(
        self,
        detail: str | None = None,
        *,
        code: str | None = None,
        attr: str | None = None,
    ) -> None:
        self.detail = detail or self.default_detail
        self.code = code or self.default_code
        self.attr = attr  # the input field the error belongs to, if any
        super().__init__(self.detail)


class NotFound(DomainError):
    """The object does not exist or the caller may not see it (never say which)."""

    status_code = 404
    default_code = "not_found"
    default_detail = "Not found."


class Forbidden(DomainError):
    """The caller sees the object but may not perform this action on it."""

    status_code = 403
    default_code = "permission_denied"
    default_detail = "You do not have permission to perform this action."


class Conflict(DomainError):
    """The request conflicts with the current state (duplicate, already done, locked)."""

    status_code = 409
    default_code = "conflict"
    default_detail = "The request conflicts with the current state."


class PreconditionFailed(DomainError):
    """A stale If-Match or version: the object changed since the caller read it."""

    status_code = 412
    default_code = "precondition_failed"
    default_detail = "The object changed since it was read."


class RuleViolation(DomainError):
    """Well-formed input that breaks a business rule (wrong state, limit exceeded)."""

    status_code = 422
    default_code = "rule_violation"
    default_detail = "The request breaks a business rule."
