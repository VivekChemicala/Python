"""Automated verification gates: pytest + flake8 + business-rule checks."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

HARNESS_DIR = Path(__file__).resolve().parent


def _run(cmd: list[str], cwd: Path) -> dict:
    try:
        proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                              timeout=180)
        out, code = proc.stdout + proc.stderr, proc.returncode
    except subprocess.TimeoutExpired as exc:
        out, code = f"TIMEOUT after {exc.timeout}s", 124
    return {"command": " ".join(cmd), "exit_code": code,
            "passed": code == 0, "output": out.strip()}


def verify(root: Path) -> dict:
    root = root.resolve()
    gates = {
        "pytest": _run([sys.executable, "-m", "pytest", "-q",
                        "-p", "no:cacheprovider"], root),
        "flake8": _run([sys.executable, "-m", "flake8", "src", "tests"],
                       root),
        "rules": _run([sys.executable, str(HARNESS_DIR / "check_rules.py"),
                       "--root", str(root)], root),
    }
    return {"passed": all(g["passed"] for g in gates.values()),
            "gates": gates}


def format_report(report: dict) -> str:
    lines = []
    for name, gate in report["gates"].items():
        status = "PASS" if gate["passed"] else "FAIL"
        lines += [f"## {name}: {status}", f"$ {gate['command']}",
                  "```", gate["output"][-4000:] or "(no output)", "```", ""]
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=".", type=Path)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    report = verify(args.root)
    print(json.dumps(report, indent=2) if args.json
          else format_report(report))
    print("VERIFIED" if report["passed"] else "NOT VERIFIED")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
