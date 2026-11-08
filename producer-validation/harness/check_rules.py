"""Business-rule checks: docs <-> code <-> tests traceability.

Checks, derived from docs/business-rules.md:
  R1 every documented error/warning code appears in src/validation.py
  R2 every BR-xxx rule that defines a code is referenced by a test comment
  R3 validation emits only documented codes on the synthetic dataset
  R4 validation never raises on the synthetic dataset
  R5 rule logic does not read the system clock (date.today only as default)
  R6 synthetic records produce the outcomes documented in their `_expect`
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from datetime import date
from pathlib import Path

RULE_HEADER = re.compile(r"^### (BR-\d{3})\b", re.M)
CODE_LINE = re.compile(r"(Error|Warning) code: `([A-Z_]+)`")


def parse_rules(doc: str) -> dict[str, list[tuple[str, str]]]:
    rules: dict[str, list[tuple[str, str]]] = {}
    parts = RULE_HEADER.split(doc)
    for rule_id, body in zip(parts[1::2], parts[2::2]):
        rules[rule_id] = [(k.lower(), c) for k, c in CODE_LINE.findall(body)]
    return rules


def _load_validation(root: Path):
    spec = importlib.util.spec_from_file_location(
        "pv_validation_under_check", root / "src" / "validation.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _outcome_mismatches(rec: dict, res) -> list[str]:
    expect, rid = rec.get("_expect", {}), rec.get("producer_id")
    out = []
    if "valid" in expect and res.is_valid != expect["valid"]:
        out.append(f"{rid}: is_valid={res.is_valid}, expected "
                   f"{expect['valid']}")
    for kind in ("errors", "warnings"):
        if kind not in expect:
            continue
        got = sorted([i.code, i.field] for i in getattr(res, kind))
        if got != sorted(expect[kind]):
            out.append(f"{rid}: {kind} {got}, expected "
                       f"{sorted(expect[kind])}")
    return out


def run_checks(root: Path) -> list[dict]:
    doc = (root / "docs" / "business-rules.md").read_text()
    src = (root / "src" / "validation.py").read_text()
    tests = (root / "tests" / "test_validation.py").read_text()
    rules = parse_rules(doc)
    documented = {c for codes in rules.values() for _, c in codes}
    results = []

    def add(check, ok, detail):
        results.append({"check": check, "passed": ok, "detail": detail})

    missing = sorted(c for c in documented if f'"{c}"' not in src
                     and f"'{c}'" not in src)
    add("R1 documented codes implemented", not missing,
        f"missing: {missing}" if missing else f"{len(documented)} codes")

    untested = sorted(r for r, codes in rules.items()
                      if codes and not re.search(rf"#.*\b{r}\b", tests))
    add("R2 rules traced to tests", not untested,
        f"no '# BR-xxx' test for: {untested}" if untested
        else f"{len(rules)} rules")

    records = json.loads((root / "data" / "synthetic_producers.json")
                         .read_text())
    as_of = date(2026, 6, 1)
    crashes, undocumented, mismatches = [], set(), []
    try:
        module = _load_validation(root)
        for rec in records:
            try:
                res = module.validate_producer(rec, as_of=as_of)
                for issue in [*res.errors, *res.warnings]:
                    if issue.code not in documented:
                        undocumented.add(issue.code)
                mismatches += _outcome_mismatches(rec, res)
            except Exception as exc:  # noqa: BLE001
                crashes.append(f"{rec.get('producer_id')}: {exc!r}")
    except Exception as exc:  # noqa: BLE001
        crashes.append(f"import failed: {exc!r}")
    add("R3 only documented codes emitted", not undocumented,
        f"undocumented: {sorted(undocumented)}" if undocumented
        else f"{len(records)} records")
    add("R4 never raises on synthetic data", not crashes,
        "; ".join(crashes[:5]) if crashes else f"{len(records)} records")

    add("R6 synthetic records match expected outcomes",
        not mismatches and not crashes,
        "; ".join(mismatches[:8]) if mismatches
        else f"{len(records)} records")

    today_calls = re.findall(r"date\.today\(\)|datetime\.now\(", src)
    allowed = len(re.findall(r"as_of\s*=\s*as_of\s+or\s+date\.today\(\)",
                             src))
    add("R5 no system clock in rule logic", len(today_calls) <= allowed,
        f"{len(today_calls)} clock reads, {allowed} allowed default(s)")
    return results


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=".", type=Path)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    results = run_checks(args.root.resolve())
    if args.json:
        print(json.dumps(results, indent=2))
    else:
        for r in results:
            print(f"[{'PASS' if r['passed'] else 'FAIL'}] {r['check']}: "
                  f"{r['detail']}")
    return 0 if all(r["passed"] for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
