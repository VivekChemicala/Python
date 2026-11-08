"""Run the basic vs harness comparison and write a report.

Same model, same task prompt (harness/task.md), same acceptance criteria.
Each arm works in its own copy of the baseline project. Afterwards both are
scored identically: verification gates (measured, even for the basic arm,
which never ran them) and the held-out acceptance suite.

    python -m harness.run_experiment --backend anthropic --model <id> --trials 3
    python -m harness.run_experiment --backend mock    # offline pipeline check
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from dataclasses import asdict
from pathlib import Path

from harness.agent import run_basic, run_harness
from harness.llm import LLM, replay_responder
from harness.verify import verify

PROJECT = Path(__file__).resolve().parents[1]
BASELINE_ITEMS = ("src", "tests", "docs", "data", "AGENTS.md", "pytest.ini",
                  ".flake8")
ACCEPTANCE = PROJECT / "experiment" / "acceptance"
REFERENCE = PROJECT / "experiment" / "reference"
CATEGORIES = ("TestDecisions", "TestContract", "TestRobustness")


def make_workspace(dest: Path) -> Path:
    dest.mkdir(parents=True)
    for item in BASELINE_ITEMS:
        src = PROJECT / item
        if src.is_dir():
            shutil.copytree(src, dest / item, ignore=shutil.ignore_patterns(
                "__pycache__", ".pytest_cache"))
        else:
            shutil.copy2(src, dest / item)
    return dest


def score_acceptance(workspace: Path, out_xml: Path) -> dict:
    env = {**os.environ, "PV_WORKSPACE": str(workspace)}
    subprocess.run(
        [sys.executable, "-m", "pytest", str(ACCEPTANCE), "-q",
         "-p", "no:cacheprovider", f"--junitxml={out_xml}"],
        cwd=PROJECT, env=env, capture_output=True, text=True, timeout=300)
    scores = {c: {"passed": 0, "total": 0, "failed": []} for c in CATEGORIES}
    if not out_xml.exists():
        return {"error": "acceptance run produced no report", **scores}
    for case in ET.parse(out_xml).iter("testcase"):
        cat = case.get("classname", "").rsplit(".", 1)[-1]
        if cat not in scores:  # collection error -> count against all
            for s in scores.values():
                s["failed"].append(case.get("name"))
            continue
        scores[cat]["total"] += 1
        if case.find("failure") is None and case.find("error") is None:
            scores[cat]["passed"] += 1
        else:
            scores[cat]["failed"].append(case.get("name"))
    return scores


def _pct(s: dict) -> str:
    return f"{s['passed']}/{s['total']}" if s["total"] else "0/0"


def write_report(run_dir: Path, rows: list[dict], llm: LLM) -> Path:
    lines = [
        "# Basic vs harness comparison", "",
        f"- Model: `{llm.backend}:{llm.model}` (temperature "
        f"{llm.temperature}) — identical for both arms",
        "- Task: `harness/task.md` — identical for both arms",
        "- Scoring: held-out `experiment/acceptance` suite + verification "
        "gates, applied identically after each arm finished", "",
        "| trial | arm | AI calls | gates run by workflow | pytest | flake8 "
        "| rule checks | decisions | contract | robustness | tokens in/out "
        "| seconds |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        g = r["post_verify"]["gates"]
        a = r["acceptance"]
        lines.append(
            f"| {r['trial']} | {r['arm']} | {r['result']['iterations']} | "
            f"{'yes (mandatory)' if r['arm'] == 'harness' else 'no'} | "
            + " | ".join("pass" if g[k]["passed"] else "FAIL"
                         for k in ("pytest", "flake8", "rules"))
            + " | " + " | ".join(_pct(a[c]) for c in CATEGORIES)
            + f" | {r['result']['input_tokens']}/"
            f"{r['result']['output_tokens']} | {r['result']['seconds']} |")
    lines += ["", "## Failed acceptance tests", ""]
    for r in rows:
        failed = [f"{c}::{n}" for c in CATEGORIES
                  for n in r["acceptance"][c]["failed"]]
        lines.append(f"- trial {r['trial']} {r['arm']}: "
                     + (", ".join(failed) if failed else "none"))
    lines += ["", "Evidence per arm: `trial_N/<arm>/evidence/` (prompts, "
              "responses, verify logs, diff.patch, summary.json)."]
    path = run_dir / "comparison.md"
    path.write_text("\n".join(lines) + "\n")
    return path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--backend", default="anthropic",
                    choices=["anthropic", "openai", "mock"])
    ap.add_argument("--model")
    ap.add_argument("--temperature", type=float, default=0.0,
                    help="use -1 to omit (models that reject temperature)")
    ap.add_argument("--trials", type=int, default=1)
    ap.add_argument("--max-iterations", type=int, default=3)
    ap.add_argument("--arms", default="basic,harness")
    ap.add_argument("--out", type=Path, default=PROJECT / "runs")
    args = ap.parse_args(argv)
    args.out = args.out.resolve()

    responder = None
    if args.backend == "mock":
        responder = replay_responder({
            "src/validation.py": REFERENCE / "validation.py",
            "tests/test_validation.py": REFERENCE / "test_validation.py"})
    llm = LLM(args.backend, args.model,
              None if args.temperature < 0 else args.temperature,
              responder=responder)
    task = (PROJECT / "harness" / "task.md").read_text()
    run_dir = args.out / time.strftime("%Y%m%d-%H%M%S")
    rows = []
    for trial in range(1, args.trials + 1):
        for arm in args.arms.split(","):
            arm_dir = run_dir / f"trial_{trial}" / arm
            baseline = make_workspace(arm_dir / "baseline")
            workspace = make_workspace(arm_dir / "workspace")
            evidence = arm_dir / "evidence"
            evidence.mkdir()
            print(f"trial {trial} / {arm}: running ...", flush=True)
            if arm == "basic":
                result = run_basic(llm, workspace, baseline, task, evidence)
            else:
                result = run_harness(llm, workspace, baseline, task, evidence,
                                     args.max_iterations)
            post = verify(workspace)
            acc = score_acceptance(workspace, evidence / "acceptance.xml")
            (evidence / "post_verify.json").write_text(
                json.dumps(post, indent=2))
            rows.append({"trial": trial, "arm": arm,
                         "result": asdict(result), "post_verify": post,
                         "acceptance": acc})
            print(f"  iterations={result.iterations} verified="
                  f"{post['passed']} acceptance="
                  + ", ".join(f"{c[4:]} {_pct(acc[c])}" for c in CATEGORIES),
                  flush=True)
    (run_dir / "results.json").write_text(json.dumps(rows, indent=2))
    report = write_report(run_dir, rows, llm)
    print(f"report: {report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
