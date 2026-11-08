# AGENTS.md — producer-validation

Instructions for AI coding agents working in this repository.

## Project
Validation of **synthetic** insurance producer records. Public API:
`src.validation.validate_producer(record, as_of=None) -> ValidationResult`.

## Source of truth
- `docs/business-rules.md` defines every rule (BR-xxx), its error/warning
  code, and field path. Implement rules **exactly** as written there.
- Issue codes are a public contract: spell them exactly as documented. Do not
  invent new codes; if a rule seems to need one, stop and say so.
- Distinguish errors (block onboarding) from warnings (do not block).

## Coding rules
- Python 3.10+, standard library only. Do not add dependencies.
- Rule logic must use the `as_of` argument; never call `date.today()` inside
  rule checks.
- `validate_producer` must never raise for malformed input — report issues.
- Keep each rule in its own small `_check_*` helper, mirroring existing code.
- Only modify `src/validation.py` and `tests/test_validation.py` unless the
  task says otherwise.
- Use synthetic data only (`example.com` emails, fake NPNs). Never add real
  personal data.

## Tests
- Every rule BR-xxx you implement needs at least one test in
  `tests/test_validation.py`, preceded by a `# BR-xxx` comment for
  traceability.
- Cover boundaries: expiry on `as_of`, the 30-day warning window, case
  differences, malformed values.
- Tests must pass a fixed `as_of` date; never depend on the real clock.

## Definition of done
A change is done only when **all** of these pass from the project root:

```bash
python -m pytest            # unit tests
flake8 src tests            # lint
python -m harness.check_rules   # business-rule traceability checks
```

or all at once: `python -m harness.verify`. Report the command output as
evidence. Do not claim completion with failing checks.
