"""Self-tests for the harness itself (run: python -m pytest harness)."""

import json

from harness import check_rules, run_experiment
from harness.agent import apply_files

PROJECT = run_experiment.PROJECT


def test_baseline_fails_rule_checks_for_unimplemented_rules():
    results = {r["check"][:2]: r for r in check_rules.run_checks(PROJECT)}
    assert not results["R1"]["passed"]
    assert not results["R2"]["passed"]
    assert results["R4"]["passed"]


def test_apply_files_only_allows_editable_paths(tmp_path):
    (tmp_path / "src").mkdir()
    reply = ('<file path="src/validation.py">\nX = 1\n</file>\n'
             '<file path="docs/business-rules.md">\nhack\n</file>')
    changed, rejected = apply_files(tmp_path, reply)
    assert changed == ["src/validation.py"]
    assert rejected == ["docs/business-rules.md"]
    assert (tmp_path / "src/validation.py").read_text() == "X = 1\n"


def test_mock_experiment_end_to_end(tmp_path):
    run_experiment.main(["--backend", "mock", "--out", str(tmp_path)])
    rows = json.loads(next(tmp_path.glob("*/results.json")).read_text())
    harness = next(r for r in rows if r["arm"] == "harness")
    assert harness["result"]["verified"] is True
    assert harness["result"]["iterations"] == 1
    for cat in run_experiment.CATEGORIES:
        score = harness["acceptance"][cat]
        assert score["total"] > 0 and score["passed"] == score["total"]


def test_harness_feeds_gate_failures_back_until_verified(tmp_path):
    from harness.agent import run_harness
    from harness.llm import LLM

    ref = run_experiment.REFERENCE
    seen = []

    def responder(system, messages):
        seen.append(messages[-1]["content"])
        if len(messages) == 1:  # first attempt: code without tests
            return ('<file path="src/validation.py">\n'
                    + (ref / "validation.py").read_text() + "</file>")
        return ('<file path="tests/test_validation.py">\n'
                + (ref / "test_validation.py").read_text() + "</file>")

    workspace = run_experiment.make_workspace(tmp_path / "ws")
    baseline = run_experiment.make_workspace(tmp_path / "base")
    evidence = tmp_path / "ev"
    evidence.mkdir()
    result = run_harness(LLM("mock", responder=responder), workspace,
                         baseline, "task", evidence)
    assert result.verified and result.iterations == 2
    assert "R2 rules traced to tests" in seen[1]
    assert (evidence / "verify_1.md").exists()


def test_sandbox_env_strips_credentials(monkeypatch):
    from harness.verify import sandbox_env

    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.setenv("GH_TOKEN", "x")
    env = sandbox_env(PV_WORKSPACE="/w")
    assert "ANTHROPIC_API_KEY" not in env and "GH_TOKEN" not in env
    assert env["PV_WORKSPACE"] == "/w" and "PATH" in env
