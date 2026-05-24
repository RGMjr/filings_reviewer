---
id: 546
source: gh
slug: script-test-mocks-classify-segment-signature-drift
title: "Script test mocks drift from PresenceClassifierClient.classify_segment signature"
status: archived
severity: medium
autonomy: skip
estimated: —
touches: []
discovered: 2026-05-07
updated: 2026-05-07
gh_issue: 546
pr_refs:
  - 556
note: tighten or share script-side fake-client mocks so they cannot drift from inspect.signature(real_classify_segment)
---

### Problem

PR #535 (gh-531 token threading) changed
`PresenceClassifierClient.classify_segment` to return
`tuple[list[SegmentClassification], dict[str, int]]`. Two scripts
(`scripts/run_phase1_eval.py:666` and
`scripts/calibrate_llm_thresholds.py:542`) kept the old
list-iteration shape and crashed on first live run with
`AttributeError: 'list' object has no attribute 'metric_id'`. The
eval-runner test file did not exercise `evaluate_filing_direct` at all
against the real classifier signature; the sweep-mode test mocked
`classify_segment` with the old list-only return.

### Next Steps

- Tighten existing fake-client mocks across `tests/unit/scripts/` to assert their return shape matches `inspect.signature(real_callable).return_annotation` at construction time.
- Or introduce a shared `FakePresenceClient` under a `tests/_fixtures/` (or similar) module that mirrors the real signature, used by every script test's `run_sweep` / `evaluate_filing_direct` path.
- Backfill an integration test for `run_sweep` (sweep_corpus → assertions about `thresholds.yaml` contents, end-to-end through `classify_segment`).
