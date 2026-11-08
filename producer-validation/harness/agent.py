"""The two workflows under comparison.

basic   : task prompt + source files -> one AI generation ("please test it")
          -> code is delivered as-is (a human would review it manually).
harness : task prompt + AGENTS.md + source + business rules -> AI generation
          -> mandatory verification gates (pytest, flake8, rule checks)
          -> failures fed back to the model (bounded loop)
          -> completion only when every gate passes, with an evidence bundle.
"""

from __future__ import annotations

import difflib
import json
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from harness.llm import LLM
from harness.verify import format_report, verify

EDITABLE = ("src/validation.py", "tests/test_validation.py")
SOURCE_FILES = ("src/validation.py", "tests/test_validation.py")
FILE_BLOCK = re.compile(r'<file path="([^"]+)">\n?(.*?)</file>', re.S)

OUTPUT_FORMAT = """\
## Output format
Return the complete new contents of every file you change, each wrapped
exactly like this (no other wrapping):

<file path="src/validation.py">
...full file contents...
</file>

You may only change: {editable}.
"""

BASIC_SYSTEM = "You are an expert Python developer."
HARNESS_SYSTEM = ("You are an expert Python developer working in a repository "
                  "with the following agent instructions.\n\n{agents_md}")


@dataclass
class ArmResult:
    arm: str
    model: str
    iterations: int = 0
    completed: bool = False
    verified: bool | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    seconds: float = 0.0
    files_changed: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _source_block(root: Path) -> str:
    return "\n\n".join(
        f'<file path="{rel}">\n{(root / rel).read_text()}</file>'
        for rel in SOURCE_FILES
    )


def build_basic_prompt(root: Path, task: str) -> tuple[str, str]:
    user = "\n\n".join([
        task,
        "## Source files",
        _source_block(root),
        "Please implement the change and test it.",
        OUTPUT_FORMAT.format(editable=", ".join(EDITABLE)),
    ])
    return BASIC_SYSTEM, user


def build_harness_prompt(root: Path, task: str) -> tuple[str, str]:
    system = HARNESS_SYSTEM.format(agents_md=(root / "AGENTS.md").read_text())
    user = "\n\n".join([
        task,
        "## Business rules (docs/business-rules.md)",
        (root / "docs" / "business-rules.md").read_text(),
        "## Source files",
        _source_block(root),
        "Your change will be verified automatically with pytest, "
        "flake8 and the business-rule checks (harness/check_rules.py). "
        "If any gate fails you will receive its output and must fix it.",
        OUTPUT_FORMAT.format(editable=", ".join(EDITABLE)),
    ])
    return system, user


def apply_files(root: Path, reply: str) -> tuple[list[str], list[str]]:
    changed, rejected = [], []
    for rel, body in FILE_BLOCK.findall(reply):
        rel = rel.strip()
        if rel not in EDITABLE:
            rejected.append(rel)
            continue
        body = re.sub(r"^```[a-z]*\n|\n?```\s*$", "", body.strip("\n"))
        (root / rel).write_text(body.rstrip("\n") + "\n")
        changed.append(rel)
    return changed, rejected


def write_diff(baseline: Path, root: Path, out: Path) -> None:
    chunks = []
    for rel in EDITABLE:
        a = (baseline / rel).read_text().splitlines(keepends=True)
        b = (root / rel).read_text().splitlines(keepends=True)
        chunks += difflib.unified_diff(a, b, f"a/{rel}", f"b/{rel}")
    out.write_text("".join(chunks))


def _record(evidence: Path, name: str, text: str) -> None:
    (evidence / name).write_text(text)


def run_basic(llm: LLM, root: Path, baseline: Path, task: str,
              evidence: Path) -> ArmResult:
    start = time.time()
    result = ArmResult("basic", llm.model)
    system, user = build_basic_prompt(root, task)
    _record(evidence, "prompt_1.md", f"# system\n{system}\n\n# user\n{user}")
    reply = llm.complete(system, [{"role": "user", "content": user}])
    _record(evidence, "response_1.md", reply.text)
    result.iterations = 1
    result.input_tokens, result.output_tokens = (reply.input_tokens,
                                                 reply.output_tokens)
    result.files_changed, rejected = apply_files(root, reply.text)
    if rejected:
        result.notes.append(f"ignored edits to {rejected}")
    result.completed = bool(result.files_changed)
    result.seconds = round(time.time() - start, 1)
    write_diff(baseline, root, evidence / "diff.patch")
    _record(evidence, "summary.json", json.dumps(asdict(result), indent=2))
    return result


def run_harness(llm: LLM, root: Path, baseline: Path, task: str,
                evidence: Path, max_iterations: int = 3) -> ArmResult:
    start = time.time()
    result = ArmResult("harness", llm.model, verified=False)
    system, user = build_harness_prompt(root, task)
    messages = [{"role": "user", "content": user}]
    changed: set[str] = set()
    for i in range(1, max_iterations + 1):
        _record(evidence, f"prompt_{i}.md",
                f"# system\n{system}\n\n# user\n{messages[-1]['content']}")
        reply = llm.complete(system, messages)
        _record(evidence, f"response_{i}.md", reply.text)
        result.iterations = i
        result.input_tokens += reply.input_tokens
        result.output_tokens += reply.output_tokens
        files, rejected = apply_files(root, reply.text)
        changed.update(files)
        if rejected:
            result.notes.append(f"iter {i}: ignored edits to {rejected}")

        report = verify(root)
        _record(evidence, f"verify_{i}.json", json.dumps(report, indent=2))
        _record(evidence, f"verify_{i}.md", format_report(report))
        if report["passed"]:
            result.verified = result.completed = True
            break
        messages += [
            {"role": "assistant", "content": reply.text},
            {"role": "user", "content":
                "Verification failed. Fix the problems below and return the "
                "complete corrected files in the same format.\n\n"
                + format_report(report)},
        ]
    else:
        result.notes.append("max iterations reached without passing gates")
    result.files_changed = sorted(changed)
    result.seconds = round(time.time() - start, 1)
    write_diff(baseline, root, evidence / "diff.patch")
    _record(evidence, "summary.json", json.dumps(asdict(result), indent=2))
    return result
