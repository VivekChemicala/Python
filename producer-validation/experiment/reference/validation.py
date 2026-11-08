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

NPN_PATTERN = re.compile(r"[0-9]{1,10}")
ISO_DATE_PATTERN = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


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
    if not NPN_PATTERN.fullmatch(str(npn)):
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


EXPIRY_WARNING_DAYS = 30


def _parse_date(value: Any) -> date | None:
    if not isinstance(value, str) or not ISO_DATE_PATTERN.fullmatch(value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _valid_state(value: Any) -> str | None:
    if isinstance(value, str) and value.strip().upper() in US_STATES:
        return value.strip().upper()
    return None


def _is_status(item: dict, status: str) -> bool:
    value = item.get("status")
    return isinstance(value, str) and value.strip().lower() == status


def _active_licenses(
    record: dict, as_of: date, result: ValidationResult
) -> dict[str, list[tuple[int, date]]]:
    """BR-005/BR-006: return active licenses by state as (index, expiry)."""
    licenses = record.get("licenses")
    if licenses is None:
        licenses = []
    if not isinstance(licenses, list):
        result.errors.append(
            Issue("LICENSE_STATE_INVALID", "licenses", "licenses must be a list")
        )
        return {}
    active: dict[str, list[tuple[int, date]]] = {}
    for i, lic in enumerate(licenses):
        if not isinstance(lic, dict):
            lic = {}
        state = _valid_state(lic.get("state"))
        expiry = _parse_date(lic.get("expiration_date"))
        if state is None:
            result.errors.append(
                Issue("LICENSE_STATE_INVALID", f"licenses[{i}].state",
                      "license state is not a valid USPS state code")
            )
        if expiry is None:
            result.errors.append(
                Issue("LICENSE_DATE_INVALID", f"licenses[{i}].expiration_date",
                      "expiration_date must be YYYY-MM-DD")
            )
        if state is None or expiry is None:
            continue
        if _is_status(lic, "active") and expiry >= as_of:
            active.setdefault(state, []).append((i, expiry))
    return active


def _check_licenses(record: dict, as_of: date, result: ValidationResult) -> None:
    active = _active_licenses(record, as_of, result)

    resident = _valid_state(record.get("resident_state"))
    if resident is not None and resident not in active:
        result.errors.append(
            Issue("RESIDENT_LICENSE_MISSING", "licenses",
                  f"no active resident license in {resident}")
        )

    for entries in active.values():
        for i, expiry in entries:
            if (expiry - as_of).days <= EXPIRY_WARNING_DAYS:
                result.warnings.append(
                    Issue("LICENSE_EXPIRING_SOON",
                          f"licenses[{i}].expiration_date",
                          f"license expires on {expiry.isoformat()}")
                )

    appointments = record.get("appointments")
    if not isinstance(appointments, list):
        return
    for i, appt in enumerate(appointments):
        if not isinstance(appt, dict) or not _is_status(appt, "active"):
            continue
        state = _valid_state(appt.get("state"))
        if state is None or state not in active:
            result.errors.append(
                Issue("APPOINTMENT_STATE_UNLICENSED", f"appointments[{i}].state",
                      f"no active license for appointment state "
                      f"{appt.get('state')!r}")
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
    _check_licenses(record, as_of, result)
    return result
