"""Held-out acceptance suite. Never shown to either arm.

Scores a workspace (env PV_WORKSPACE) against the task's acceptance criteria
as specified by docs/business-rules.md. Classes are scoring categories:
  TestDecisions  - is the accept/reject decision right? (criteria 1-3)
  TestContract   - exact codes, field paths, error vs warning
  TestRobustness - malformed input never raises (criterion 4)
"""

import importlib.util
import os
import sys
from datetime import date
from pathlib import Path

import pytest

WORKSPACE = Path(os.environ.get("PV_WORKSPACE", Path(__file__).parents[2]))
_spec = importlib.util.spec_from_file_location(
    "pv_acceptance_target", WORKSPACE / "src" / "validation.py")
_mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _mod
_spec.loader.exec_module(_mod)
validate_producer = _mod.validate_producer

AS_OF = date(2026, 6, 1)


def lic(state="TX", status="active", expiration_date="2027-03-31"):
    return {"state": state, "license_number": f"{state}-0001",
            "status": status, "expiration_date": expiration_date}


def appt(state="TX", status="active", carrier="ACME"):
    return {"carrier_code": carrier, "state": state, "status": status}


def record(licenses=None, appointments=None, **overrides):
    rec = {
        "producer_id": "P-20001", "npn": "90210001",
        "first_name": "Rowan", "last_name": "Synthetic",
        "email": "rowan.synthetic@example.com", "resident_state": "TX",
        "licenses": [lic()] if licenses is None else licenses,
        "appointments": [appt()] if appointments is None else appointments,
    }
    rec.update(overrides)
    return rec


def issues(issue_list):
    return {(i.code, i.field) for i in issue_list}


class TestDecisions:
    def test_fully_licensed_producer_is_valid(self):
        assert validate_producer(record(), as_of=AS_OF).is_valid

    def test_no_licenses_rejected(self):
        assert not validate_producer(
            record(licenses=[], appointments=[]), as_of=AS_OF).is_valid

    def test_inactive_resident_license_rejected(self):
        assert not validate_producer(
            record(licenses=[lic(status="suspended")]), as_of=AS_OF).is_valid

    def test_expired_resident_license_rejected(self):
        assert not validate_producer(
            record(licenses=[lic(expiration_date="2026-05-31")]),
            as_of=AS_OF).is_valid

    def test_only_non_resident_license_rejected(self):
        assert not validate_producer(
            record(licenses=[lic("OK")], appointments=[appt("OK")]),
            as_of=AS_OF).is_valid

    def test_license_expiring_on_as_of_is_still_active(self):
        assert validate_producer(
            record(licenses=[lic(expiration_date="2026-06-01")]),
            as_of=AS_OF).is_valid

    def test_expiring_soon_does_not_reject(self):
        assert validate_producer(
            record(licenses=[lic(expiration_date="2026-06-11")]),
            as_of=AS_OF).is_valid

    def test_appointment_in_unlicensed_state_rejected(self):
        assert not validate_producer(
            record(appointments=[appt(), appt("OK")]), as_of=AS_OF).is_valid

    def test_terminated_appointment_ignored(self):
        assert validate_producer(
            record(appointments=[appt(), appt("OK", status="terminated")]),
            as_of=AS_OF).is_valid

    def test_appointment_backed_by_expired_license_rejected(self):
        rec = record(licenses=[lic(), lic("OK", expiration_date="2026-01-31")],
                     appointments=[appt(), appt("OK")])
        assert not validate_producer(rec, as_of=AS_OF).is_valid

    def test_status_and_state_are_case_insensitive(self):
        rec = record(licenses=[lic("tx", status="ACTIVE")],
                     appointments=[appt("Tx", status="Active")])
        assert validate_producer(rec, as_of=AS_OF).is_valid

    def test_missing_licenses_key_rejected(self):
        rec = record()
        del rec["licenses"]
        rec["appointments"] = []
        assert not validate_producer(rec, as_of=AS_OF).is_valid

    def test_as_of_argument_is_respected(self):
        rec = record(licenses=[lic(expiration_date="2025-12-31")])
        assert validate_producer(rec, as_of=date(2025, 1, 1)).is_valid
        assert not validate_producer(rec, as_of=AS_OF).is_valid


class TestContract:
    def test_resident_license_missing_code(self):
        res = validate_producer(record(licenses=[lic(status="lapsed")],
                                       appointments=[]), as_of=AS_OF)
        assert issues(res.errors) == {("RESIDENT_LICENSE_MISSING", "licenses")}

    def test_appointment_unlicensed_code_and_path(self):
        res = validate_producer(record(appointments=[appt(), appt("OK")]),
                                as_of=AS_OF)
        assert issues(res.errors) == {
            ("APPOINTMENT_STATE_UNLICENSED", "appointments[1].state")}

    def test_expiring_soon_is_warning_not_error(self):
        res = validate_producer(
            record(licenses=[lic(expiration_date="2026-06-11")]), as_of=AS_OF)
        assert res.errors == []
        assert issues(res.warnings) == {
            ("LICENSE_EXPIRING_SOON", "licenses[0].expiration_date")}

    @pytest.mark.parametrize("expiry,warned", [
        ("2026-07-01", True),   # exactly 30 days
        ("2026-07-02", False),  # 31 days
        ("2026-06-01", True),   # expires today
    ])
    def test_expiring_soon_window_boundary(self, expiry, warned):
        res = validate_producer(record(licenses=[lic(expiration_date=expiry)]),
                                as_of=AS_OF)
        codes = [i.code for i in res.warnings]
        assert ("LICENSE_EXPIRING_SOON" in codes) is warned

    def test_expired_license_not_warned(self):
        res = validate_producer(
            record(licenses=[lic(), lic("OK", expiration_date="2026-05-20")],
                   appointments=[appt()]), as_of=AS_OF)
        assert res.warnings == []

    def test_license_date_invalid_code_and_path(self):
        res = validate_producer(
            record(licenses=[lic(), lic("OK", expiration_date="2027/03/31")]),
            as_of=AS_OF)
        assert issues(res.errors) == {
            ("LICENSE_DATE_INVALID", "licenses[1].expiration_date")}

    def test_non_calendar_iso_date_is_invalid(self):
        res = validate_producer(
            record(licenses=[lic(), lic("OK", expiration_date="2027-W13-1")]),
            as_of=AS_OF)
        assert issues(res.errors) == {
            ("LICENSE_DATE_INVALID", "licenses[1].expiration_date")}

    def test_license_state_invalid_code_and_path(self):
        res = validate_producer(record(licenses=[lic(), lic("XX")]),
                                as_of=AS_OF)
        assert issues(res.errors) == {
            ("LICENSE_STATE_INVALID", "licenses[1].state")}


MALFORMED = {
    "licenses_none": {"licenses": None},
    "licenses_string": {"licenses": "TX"},
    "license_entry_none": {"licenses": [None]},
    "license_missing_fields": {"licenses": [{}]},
    "expiry_int": {"licenses": [lic(expiration_date=20270331)]},
    "expiry_garbage": {"licenses": [lic(expiration_date="soon")]},
    "expiry_week_date": {"licenses": [lic(expiration_date="2027-W13-1")]},
    "state_none": {"licenses": [lic(state=None)]},
    "status_none": {"licenses": [lic(status=None)]},
    "appointments_string": {"appointments": "ACME"},
    "appointment_entry_none": {"appointments": [None]},
    "appointment_state_none": {"appointments": [appt(state=None)]},
}


class TestRobustness:
    @pytest.mark.parametrize("case", sorted(MALFORMED))
    def test_malformed_input_never_raises(self, case):
        rec = record()
        rec.update(MALFORMED[case])
        res = validate_producer(rec, as_of=AS_OF)
        assert hasattr(res, "errors") and hasattr(res, "warnings")

    def test_malformed_license_is_reported(self):
        res = validate_producer(record(licenses=[lic(expiration_date="soon")]),
                                as_of=AS_OF)
        assert not res.is_valid
