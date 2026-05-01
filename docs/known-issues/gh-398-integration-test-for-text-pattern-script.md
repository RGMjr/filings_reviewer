---
id: 398
source: gh
slug: integration-test-for-text-pattern-script
title: "Add integration test for scripts/analyze_text_decision_patterns.py"
status: open
severity: low
autonomy: skip
estimated: —
touches: []
discovered: 2026-05-01
updated: 2026-05-01
gh_issue: 398
note: DB-touching script needs tests/integration/test_<script>.py per scripts.md
---

### Problem

The text-decision pattern-analysis script ships with unit tests for its pure-Python helpers (`_tokenize`, `_ngrams`, `_segment_window`, `_mine_phrases_for_metric`, `_build_metric_summary`). The DB-touching orchestration path — anchor resolution against `text_decision_analysis_runs`, the `v2_review_decisions ⨝ v2_metric_facts ⨝ v2_segments` pull, the per-(run, metric, phrase) INSERTs, run-row UPDATE on success, and the failure path that flips the row to `status='failed'` — is not exercised end-to-end. Per `.claude/rules/scripts.md`, DB-touching scripts get integration tests at `tests/integration/test_<script>.py`.

### Next Steps

- Seed a small fixture corpus (companies, filings, `v2_metric_facts`, `v2_segments`, `v2_review_decisions`) under the integration `conftest` `test_db_adapter` fixture.
- Add `tests/integration/test_analyze_text_decision_patterns.py` covering: first-run anchor=NULL path, second-run anchor pickup, success path writes summary + finding rows + UPDATE, exception flips `status='failed'`.
- Load the script via `importlib` (sibling pattern, see `tests/integration/test_onboard_tickers_cli.py`).
