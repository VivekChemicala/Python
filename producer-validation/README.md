# producer-validation

A small Python project for validating **synthetic** insurance producer
records, and a basic agent harness. The harness runs one coding task two ways
so you can compare them:

| Step | Basic approach | Harness approach |
|---|---|---|
| Instructions | Task prompt | Task prompt + `AGENTS.md` |
| Context | Source files | Source + `docs/business-rules.md` |
| Implementation | AI-generated | AI-generated |
| Testing | Prompt asks the AI to test | Mandatory `pytest` run |
| Validation | Manual review | pytest + flake8 + rule checks (`harness/check_rules.py`) |
| Completion | Generated code | Verified change + evidence bundle |

Both arms use the same model, the same task (`harness/task.md`) and the same
acceptance criteria.

## Layout

```
AGENTS.md                 agent instructions (harness arm only)
docs/business-rules.md    rules BR-001..BR-009 with error/warning codes
src/validation.py         validate_producer(); BR-001..BR-004 already implemented
tests/test_validation.py  existing unit tests
data/synthetic_producers.json   synthetic records used by the rule checks
harness/
  task.md                 the task prompt that both arms get
  llm.py                  stdlib clients for Anthropic and OpenAI, plus a mock
  agent.py                run_basic() / run_harness() workflows
  verify.py               verification gates: pytest, flake8, rule checks
  check_rules.py          checks that docs, code and tests line up (R1-R5)
  run_experiment.py       runs both arms, scores them, writes comparison.md
  test_harness.py         self-tests for the harness
experiment/
  acceptance/             held-out acceptance suite; neither arm sees it
  reference/              reference solution, used by the mock backend
```

## Setup

```bash
pip install -r requirements.txt
python -m pytest            # project unit tests
python -m harness.verify    # all gates (rule checks fail until the task is done)
python -m pytest harness    # harness self-tests
```

## Run the experiment

```bash
export ANTHROPIC_API_KEY=...   # or OPENAI_API_KEY with --backend openai,
                               # or GITHUB_TOKEN (models:read) with --backend github
python -m harness.run_experiment --backend anthropic --model claude-sonnet-4-6 --trials 3
python -m harness.run_experiment --backend mock          # offline pipeline check
```

Results go to `runs/<timestamp>/`:
- `comparison.md` is the side-by-side table.
- `results.json` holds the raw numbers.
- `trial_N/<arm>/evidence/` holds the prompts, model responses, the verify
  log from each iteration, `diff.patch`, `post_verify.json` and
  `acceptance.xml`.

## How scoring works

Once an arm has finished, both arms are scored the same way:

1. **Verification gates.** pytest, flake8 and the rule checks are run on the
   final workspace. The basic workflow never runs them itself; they are only
   used here to measure its result.
2. **Held-out acceptance suite** (`experiment/acceptance`), reported in three
   categories:
   - *Decisions*: is the accept/reject outcome correct?
   - *Contract*: are the codes, field paths and error-vs-warning split exactly
     as documented?
   - *Robustness*: does malformed input avoid raising?

Rule checks (`python -m harness.check_rules`):
- R1: every documented code is implemented.
- R2: every coded rule has a `# BR-xxx` test.
- R3: only documented codes are emitted on the synthetic data.
- R4: validation never raises on the synthetic data.
- R5: rule logic never reads the system clock.
- R6: each synthetic record produces the outcome recorded in its `_expect`
  field (valid or not, plus exact codes and field paths where the docs pin
  them down).

## Fairness notes

- Neither arm ever sees the acceptance suite or the reference solution.
- The task prompt describes behaviour and never names the issue codes. Exact
  codes are only in `docs/business-rules.md`. That gap is what repository
  context adds, so expect the basic arm to lose mostly on *Contract*.
- LLM output varies between runs. Use `--trials N` and compare aggregates.
