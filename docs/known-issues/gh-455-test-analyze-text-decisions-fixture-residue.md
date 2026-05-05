---
id: 455
source: gh
slug: test-analyze-text-decisions-fixture-residue
title: "Integration test: v2_review_decisions fixture leaves residue causing UniqueViolation in test_analyze_text_decision_patterns"
status: resolved
severity: medium
autonomy: skip
estimated: —
touches: []
discovered: 2026-05-04
updated: 2026-05-04
gh_issue: 455
pr_refs:
  - 454
note: full-suite run hits UniqueViolation on v2_review_decisions_unique_fact — fixture residue across tests
---

### Problem

`tests/integration/test_analyze_text_decision_patterns.py::test_first_run_anchor_null_processes_all_decisions` fails with `psycopg.errors.UniqueViolation` on constraint `v2_review_decisions_unique_fact` when run as part of the full suite (`pytest -x -q`). The fact_id the fixture inserts already exists from a prior test's residue. Test passes in isolation. Reproduces on `origin/main` without any code changes.

### Next Steps

- Audit `tests/integration/conftest.py` and the test's local fixtures for `v2_review_decisions` cleanup ordering
- Either truncate `v2_review_decisions` in the per-test fixture or generate unique fact_ids per test

### Resolution

Fixed in PR #454 (commit `84e5e7cf`). `_seed_corpus` was updated to create one distinct fact per reporting period (2023 and 2024) instead of reusing a single shared fact. With two separate `fact_id` values, two `v2_review_decisions` rows can attach to two different facts without violating the `v2_review_decisions_unique_fact` unique constraint on `(fact_id, decision_type)`. This eliminates the fixture-residue collision when tests run in full-suite order.
