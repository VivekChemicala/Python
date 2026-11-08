from datetime import date

import pytest

from src.validation import validate_producer

AS_OF = date(2026, 6, 1)


def make_record(**overrides):
    record = {
        "producer_id": "P-10001",
        "npn": "17345021",
        "first_name": "Avery",
        "last_name": "Synth",
        "email": "avery.synth@example.com",
        "resident_state": "TX",
        "licenses": [
            {
                "state": "TX",
                "license_number": "TX-88231",
                "status": "active",
                "expiration_date": "2027-03-31",
            }
        ],
        "appointments": [
            {"carrier_code": "ACME", "state": "TX", "status": "active"}
        ],
    }
    record.update(overrides)
    return record


def test_valid_record_has_no_issues():
    result = validate_producer(make_record(), as_of=AS_OF)
    assert result.is_valid
    assert result.errors == []
    assert result.warnings == []


# BR-001
@pytest.mark.parametrize("name", ["producer_id", "npn", "email"])
def test_br001_required_field_missing(name):
    result = validate_producer(make_record(**{name: "  "}), as_of=AS_OF)
    assert not result.is_valid
    assert ("REQUIRED_FIELD_MISSING", name) in [
        (i.code, i.field) for i in result.errors
    ]


# BR-002
@pytest.mark.parametrize("npn", ["12AB", "12345678901", "-1", "123\n"])
def test_br002_npn_invalid(npn):
    result = validate_producer(make_record(npn=npn), as_of=AS_OF)
    assert result.error_codes() == ["NPN_INVALID"]


# BR-003
@pytest.mark.parametrize("email", ["no-at-sign", "a@b@c.com", "x@nodot"])
def test_br003_email_invalid(email):
    result = validate_producer(make_record(email=email), as_of=AS_OF)
    assert result.error_codes() == ["EMAIL_INVALID"]


# BR-004
def test_br004_resident_state_invalid():
    result = validate_producer(make_record(resident_state="ZZ"), as_of=AS_OF)
    assert "STATE_INVALID" in result.error_codes()


def test_br004_resident_state_case_insensitive():
    result = validate_producer(make_record(resident_state="tx"), as_of=AS_OF)
    assert result.is_valid


def test_non_mapping_record_does_not_raise():
    result = validate_producer(None, as_of=AS_OF)
    assert not result.is_valid


def lic(state="TX", status="active", expiration_date="2027-03-31"):
    return {"state": state, "license_number": f"{state}-1",
            "status": status, "expiration_date": expiration_date}


# BR-005
def test_br005_malformed_license_data_reported():
    record = make_record(licenses=[lic(), lic(state="ZZ"),
                                   lic(expiration_date="03/31/2027")])
    result = validate_producer(record, as_of=AS_OF)
    assert ("LICENSE_STATE_INVALID", "licenses[1].state") in [
        (i.code, i.field) for i in result.errors]
    assert ("LICENSE_DATE_INVALID", "licenses[2].expiration_date") in [
        (i.code, i.field) for i in result.errors]


# BR-006 BR-007
@pytest.mark.parametrize("license_", [lic(status="lapsed"),
                                      lic(expiration_date="2026-05-31")])
def test_br007_inactive_or_expired_resident_license(license_):
    result = validate_producer(make_record(licenses=[license_]), as_of=AS_OF)
    assert "RESIDENT_LICENSE_MISSING" in result.error_codes()


# BR-006
def test_br006_expiry_on_as_of_is_active():
    record = make_record(licenses=[lic(expiration_date="2026-06-01")])
    result = validate_producer(record, as_of=AS_OF)
    assert result.is_valid


# BR-008
@pytest.mark.parametrize("expiry,warn", [("2026-07-01", True),
                                         ("2026-07-02", False)])
def test_br008_expiring_soon_window(expiry, warn):
    result = validate_producer(make_record(licenses=[lic(expiration_date=expiry)]),
                               as_of=AS_OF)
    assert result.is_valid
    assert (result.warning_codes() == ["LICENSE_EXPIRING_SOON"]) is warn


# BR-009
def test_br009_appointment_in_unlicensed_state():
    record = make_record(appointments=[
        {"carrier_code": "ACME", "state": "TX", "status": "active"},
        {"carrier_code": "ACME", "state": "OK", "status": "active"},
        {"carrier_code": "ACME", "state": "NM", "status": "terminated"},
    ])
    result = validate_producer(record, as_of=AS_OF)
    assert result.errors[0].code == "APPOINTMENT_STATE_UNLICENSED"
    assert result.errors[0].field == "appointments[1].state"
    assert len(result.errors) == 1
