---
autonomy: skip
discovered: '2026-04-20'
estimated: S
id: 63
note: Monkey-patch integration test; mid-complexity
severity: low
slug: cancel-during-populate-not-exercised-by-integration-test
source: legacy
status: resolved
pr_refs:
- 337
title: Cancel-During-Populate Not Exercised by Integration Test
touches: []
updated: '2026-04-29'
---

### Problem

Wave C documents the cancel-during-populate flow (cancel flips `status='cancelled'`; runner respects it on natural completion via the new `WHERE status='running'` predicate on `_BATCH_COMPLETE_SQL`). The conditional SQL is unit-tested via string assertion (`tests/unit/universe/test_onboarding_runner.py::TestBatchCompleteConditional`), but no integration test simulates a runner mid-`build_universe` while cancel fires concurrently.

### Next Steps

1. Add an integration test in `tests/integration/universe/test_onboarding_runner_integration.py::TestPopulateCancellation` that: inserts a populate batch, monkey-patches `UniverseBuilder.build_universe` to flip the batch status to `cancelled` mid-run, calls `_run_populate`, asserts final status stays `cancelled` (not `complete`) and `finished_at IS NOT NULL`.
2. Optionally extend Phase 5's JS to render a "Cancellation pending — batch will stop after current operation completes" banner when `status='cancelled' AND finished_at IS NULL` (today the JS shows the cancelled banner immediately).

---
