"""Validation of synthetic insurance producer records."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

US_STATES = frozenset(
    "AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN "
    "MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA "
    "WV WI WY".split()
)

REQUIRED_FIELDS = (
    "producer_id",
    "npn",
    "first_name",
    "last_name",
    "email",
    "resident_state",
)

NPN_PATTERN = re.compile(r"^\d{1,10}$")


@dataclass(frozen=True)
class Issue:
    code: str
    field: str
    message: str


@dataclass
class ValidationResult:
    errors: list[Issue] = field(default_factory=list)
    warnings: list[Issue] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return not self.errors

    def error_codes(self) -> list[str]:
        return [issue.code for issue in self.errors]

    def warning_codes(self) -> list[str]:
        return [issue.code for issue in self.warnings]


def _is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _check_required(record: dict, result: ValidationResult) -> None:
    for name in REQUIRED_FIELDS:
        if _is_blank(record.get(name)):
            result.errors.append(
                Issue("REQUIRED_FIELD_MISSING", name, f"{name} is required")
            )


def _check_npn(record: dict, result: ValidationResult) -> None:
    npn = record.get("npn")
    if _is_blank(npn):
        return
    if not NPN_PATTERN.match(str(npn)):
        result.errors.append(
            Issue("NPN_INVALID", "npn", "NPN must be 1-10 digits")
        )


def _check_email(record: dict, result: ValidationResult) -> None:
    email = record.get("email")
    if _is_blank(email):
        return
    local, sep, domain = str(email).partition("@")
    if not sep or not local or "@" in domain or "." not in domain:
        result.errors.append(
            Issue("EMAIL_INVALID", "email", "email address is malformed")
        )


def _check_resident_state(record: dict, result: ValidationResult) -> None:
    state = record.get("resident_state")
    if _is_blank(state):
        return
    if str(state).upper() not in US_STATES:
        result.errors.append(
            Issue(
                "STATE_INVALID",
                "resident_state",
                f"{state!r} is not a valid USPS state code",
            )
        )


def validate_producer(
    record: dict, as_of: date | None = None
) -> ValidationResult:
    """Validate a producer record as of a business date (default: today)."""
    as_of = as_of or date.today()
    result = ValidationResult()
    if not isinstance(record, dict):
        result.errors.append(
            Issue("REQUIRED_FIELD_MISSING", "", "record must be a mapping")
        )
        return result

    _check_required(record, result)
    _check_npn(record, result)
    _check_email(record, result)
    _check_resident_state(record, result)
    return result
