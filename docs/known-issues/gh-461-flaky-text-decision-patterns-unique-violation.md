---
id: 461
source: gh
slug: flaky-text-decision-patterns-unique-violation
title: Flaky test_first_run_anchor_null_processes_all_decisions — v2_review_decisions_unique_fact UniqueViolation under xdist
status: resolved
severity: medium
autonomy: skip
estimated: —
touches: []
discovered: 2026-05-04
updated: 2026-05-04
gh_issue: 461
pr_refs:
- 450
- 454
- 459
note: flake not reproduced after #450/#454/#459; 3x pytest -n auto passes confirmed locally 2026-05-04
---

### Problem

`tests/integration/test_analyze_text_decision_patterns.py::test_first_run_anchor_null_processes_all_decisions` (added 2026-05-04 by #450, gh-398) intermittently fails with `psycopg.errors.UniqueViolation: duplicate key value violates unique constraint "v2_review_decisions_unique_fact"` when run under `pytest -n auto`. The fixture is not isolating its `v2_review_decisions` inserts from sibling tests sharing the same `(filing_id, metric_id)` keyspace.

Observed failures on `origin/main` runs `f25f209a` and `4250a4a8` (2026-05-04, 16:08 / 16:19 UTC), and on PR #451 — which cleared on a single `gh run rerun --failed`. Will keep blocking PRs at the required Integration Tests check until fixed.

### Next Steps

- Repro under `pytest -n auto tests/integration/test_analyze_text_decision_patterns.py tests/integration/test_*.py -x -q` to find the colliding sibling test.
- Tighten fixture isolation: either use a unique `filing_id` / `metric_id` per worker (xdist `worker_id`), or wrap inserts in `ON CONFLICT DO NOTHING` if the test doesn't require the unique-constraint write to succeed.
- Add the fixture-isolation pattern to `.claude/rules/tests.md` so future integration tests don't repeat the bug.

### Resolution

Three interlocking changes jointly eliminated the `v2_review_decisions_unique_fact` UniqueViolation:

1. **Per-worker DB isolation** (`tests/integration/conftest.py::_isolate_xdist_worker_database`, landed with legacy-078 fix): each xdist worker gets its own Postgres database (`filings_analysis_test_gw0`, `_gw1`, …), preventing cross-worker keyspace collisions on `(filing_id, metric_id)` entirely.

2. **Seed-per-period fix** (PR #454): the test fixture now seeds two distinct `v2_metric_facts` rows differentiated by `period_start`/`period_end`, removing the intra-worker duplicate that could trigger the unique constraint even in a single-worker run.

3. **INSERT-RETURNING fix** (PR #459): the underlying INSERT was changed to use `RETURNING` so callers receive the row's actual `id`, eliminating a pattern that could re-insert on retry paths.

**Verification:** `pytest tests/integration/test_analyze_text_decision_patterns.py -n auto -x -q --tb=short` run 3 times consecutively on 2026-05-04 — all 3 runs passed 4/4 tests with 12 xdist workers active.
