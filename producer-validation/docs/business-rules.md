# Producer Validation Business Rules

These rules govern how **producer records** (licensed insurance agents and
brokers) are validated before onboarding. All records in this repository are
**synthetic**; no real producer data may be committed.

## Conventions

- Validation is performed **as of** a business date (`as_of`). Rule logic must
  use the `as_of` argument and must never read the system clock directly when
  `as_of` is supplied. If `as_of` is omitted, today's date is used.
- A rule violation that blocks onboarding is an **error**. A condition that
  needs attention but does not block onboarding is a **warning**. A record is
  valid if and only if it has zero errors.
- Every issue carries a stable `code` (below), a `field` path, and a
  human-readable `message`. Codes are a public contract: downstream systems
  match on them, so they must be spelled exactly as documented.
- Field paths use dotted notation with zero-based list indexes, e.g.
  `licenses[0].expiration_date`, `appointments[2].state`.
- Validation must **never raise** for malformed input; malformed data is
  reported as issues.
- State codes are two-letter USPS codes. Comparisons are case-insensitive
  (`"tx"` and `"TX"` are the same state).

## Record shape

```json
{
  "producer_id": "P-10001",
  "npn": "17345021",
  "first_name": "Avery",
  "last_name": "Synth",
  "email": "avery.synth@example.com",
  "resident_state": "TX",
  "licenses": [
    {"state": "TX", "license_number": "TX-88231", "status": "active",
     "expiration_date": "2027-03-31"}
  ],
  "appointments": [
    {"carrier_code": "ACME", "state": "TX", "status": "active"}
  ]
}
```

## Identity rules (implemented)

### BR-001 Required fields
`producer_id`, `npn`, `first_name`, `last_name`, `email` and `resident_state`
must be present and non-blank.
- Error code: `REQUIRED_FIELD_MISSING` (field = the missing field name)

### BR-002 NPN format
The National Producer Number is 1 to 10 digits, digits only.
- Error code: `NPN_INVALID`

### BR-003 Email format
Email must contain exactly one `@` with a non-empty local part and a domain
containing a dot.
- Error code: `EMAIL_INVALID`

### BR-004 Resident state
`resident_state` must be a valid two-letter USPS state code (50 states + DC).
- Error code: `STATE_INVALID`

## Licensing rules

### BR-005 License data integrity
`licenses` must be a list (missing is treated as an empty list). Each license
must have a valid `state` and an `expiration_date` in ISO format
`YYYY-MM-DD`. Each malformed field produces one issue and that license is
then ignored by BR-006..BR-008.
- Error code: `LICENSE_STATE_INVALID` (field = `licenses[i].state`)
- Error code: `LICENSE_DATE_INVALID` (field = `licenses[i].expiration_date`)

### BR-006 Active license definition
A license is **active** when its `status` is `"active"` (case-insensitive)
**and** its `expiration_date` is on or after `as_of`. A license expires at the
end of its expiration date, so a license with `expiration_date == as_of` is
still active.

### BR-007 Resident license required
The producer must hold an active license in their `resident_state`.
- Error code: `RESIDENT_LICENSE_MISSING` (field = `licenses`)

### BR-008 License expiring soon
An active license whose `expiration_date` is within 30 days of `as_of`
(i.e. `expiration_date - as_of <= 30 days`) produces a warning. It does not
make the record invalid.
- Warning code: `LICENSE_EXPIRING_SOON` (field = `licenses[i].expiration_date`)

## Appointment rules

### BR-009 Appointment requires active license
Every appointment whose `status` is `"active"` (case-insensitive) must be in a
state where the producer holds an active license (BR-006). Appointments with
any other status (e.g. `"terminated"`, `"pending"`) are ignored.
- Error code: `APPOINTMENT_STATE_UNLICENSED` (field = `appointments[i].state`)
