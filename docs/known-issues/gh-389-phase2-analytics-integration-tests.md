---
id: 389
source: gh
slug: phase2-analytics-integration-tests
title: Add integration tests for Phase-2 Metric Analytics helpers
status: open
severity: low
autonomy: skip
estimated: —
touches: []
discovered: 2026-05-01
updated: 2026-05-01
gh_issue: 389
note: 7 new db.py helpers landed with unit tests only; add integration tests against TEST_DATABASE_URL
---

### Problem

Phase 2 of the Metric Analytics rollout added 7 new helpers on `DatabaseAdapter` (`get_last_training_run`, `count_image_decisions_since`, `count_text_decisions_since`, `get_recent_text_corrections` / `_additions`, `get_recent_image_additions` / `_corrections`). Only unit tests landed (mocked `DatabaseAdapter.query`). The plan called for integration tests against `TEST_DATABASE_URL` to catch SQL syntax errors, JOIN issues, and NULL handling that mocks miss.

### Next Steps

- Add `tests/integration/test_db_analytics.py`.
- Insert a `model_training_runs` row + a few `v2_image_metric_confirmations` / `v2_review_decisions` / `v2_metric_facts` rows via fixtures.
- Assert `count_image_decisions_since` splits accept/correct/add vs reject correctly with `since=ts` and `since=None`.
- Assert recent-* helpers respect `ORDER BY DESC` and `LIMIT`.
