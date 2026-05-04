---
id: 461
source: gh
slug: flaky-text-decision-patterns-unique-violation
title: Flaky test_first_run_anchor_null_processes_all_decisions — v2_review_decisions_unique_fact UniqueViolation under xdist
status: open
severity: medium
autonomy: skip
estimated: —
touches: []
discovered: 2026-05-04
updated: 2026-05-04
gh_issue: 461
note: integration test added by #450 intermittently fails on parallel xdist runs; fixture insert collides with a sibling test on (filing_id, metric_id)
---

### Problem

`tests/integration/test_analyze_text_decision_patterns.py::test_first_run_anchor_null_processes_all_decisions` (added 2026-05-04 by #450, gh-398) intermittently fails with `psycopg.errors.UniqueViolation: duplicate key value violates unique constraint "v2_review_decisions_unique_fact"` when run under `pytest -n auto`. The fixture is not isolating its `v2_review_decisions` inserts from sibling tests sharing the same `(filing_id, metric_id)` keyspace.

Observed failures on `origin/main` runs `f25f209a` and `4250a4a8` (2026-05-04, 16:08 / 16:19 UTC), and on PR #451 — which cleared on a single `gh run rerun --failed`. Will keep blocking PRs at the required Integration Tests check until fixed.

### Next Steps

- Repro under `pytest -n auto tests/integration/test_analyze_text_decision_patterns.py tests/integration/test_*.py -x -q` to find the colliding sibling test.
- Tighten fixture isolation: either use a unique `filing_id` / `metric_id` per worker (xdist `worker_id`), or wrap inserts in `ON CONFLICT DO NOTHING` if the test doesn't require the unique-constraint write to succeed.
- Add the fixture-isolation pattern to `.claude/rules/tests.md` so future integration tests don't repeat the bug.
