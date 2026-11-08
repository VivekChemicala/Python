# Task: enforce producer licensing rules

Extend `validate_producer` in `src/validation.py` so that producer licensing
is validated, and add tests for the new behaviour.

## Acceptance criteria
1. A producer without an active license in their resident state is rejected.
2. A producer with an active carrier appointment in a state where they are not
   actively licensed is rejected.
3. Expired or inactive licenses are not treated as active. Licenses that
   expire soon are flagged without rejecting the producer.
4. Malformed license data (bad dates, bad state codes) is reported as
   validation issues; `validate_producer` never raises.
5. Existing behaviour and existing tests keep passing; new behaviour is
   covered by new tests.
