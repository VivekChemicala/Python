# Live run results

Model `anthropic:claude-sonnet-4-6`, temperature 0, same `harness/task.md` for both
arms. 3 trials total: run 1 (`--trials 1`), then run 2 (`--trials 2`). Each arm was
scored afterwards with the same gates and the held-out `experiment/acceptance` suite.

| run/trial | arm | AI calls | pytest | flake8 | rule checks | decisions | contract | robustness | tokens in/out |
|---|---|---|---|---|---|---|---|---|---|
| 1/1 | basic | 1 | pass | FAIL | FAIL | 13/13 | 4/10 | 13/13 | 2001/7277 |
| 1/1 | harness | 1 | pass | pass | pass | 13/13 | 10/10 | 13/13 | 3726/7020 |
| 2/1 | basic | 1 | pass | pass | FAIL | 13/13 | 7/10 | 13/13 | 2001/6424 |
| 2/1 | harness | 1 | pass | pass | pass | 13/13 | 10/10 | 13/13 | 3726/7093 |
| 2/2 | basic | 1 | pass | FAIL | FAIL | 13/13 | 7/10 | 13/13 | 2001/6941 |
| 2/2 | harness | 2 | pass | pass | pass | 13/13 | 10/10 | 13/13 | 15291/14844 |

## Observations

- Both arms made the right accept/reject decision every time and never crashed.
  The model handles the licensing logic fine without the rules doc.
- The basic arm lost every time on **contract**: it made up its own issue codes
  (e.g. `NO_RESIDENT_STATE_LICENSE`, `APPOINTMENT_WITHOUT_LICENSE`) instead of the
  documented ones, and in every trial it put the expiry-warning boundary in a
  different place than BR-008 does (30 days). Its own tests passed every time, so
  "ask the AI to test" did not catch any of it.
- The harness arm met the full contract in all 3 trials. In run 2 trial 2 its first
  attempt failed flake8 (long lines); the fix loop sent the report back and the
  second attempt passed. That trial cost about 3x the tokens of the others.
- Temperature 0 was not fully deterministic: identical prompts gave different
  basic-arm contract scores (4/10 vs 7/10) and different harness iteration counts.
- Small sample (3 trials). It is enough to show where the difference comes from,
  not to measure effect size.

Reproduce: `ANTHROPIC_API_KEY=... python -m harness.run_experiment --backend anthropic --trials 3`
