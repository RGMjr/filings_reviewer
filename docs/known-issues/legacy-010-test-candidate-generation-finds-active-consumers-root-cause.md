---
autonomy: n/a
discovered: '2026-04-22'
estimated: —
id: 10
severity: n/a
slug: test-candidate-generation-finds-active-consumers-root-cause
source: legacy
status: archived
title: '`test_candidate_generation_finds_active_consumers` — Root Cause Unclear'
touches: []
updated: '2026-04-22'
---

`tests/integration/test_gold_standard_coverage.py` was deleted in commit `03a8a20` ("refactor(v1): retire review_candidates + source_segments + suppressed_candidates"). The failing test no longer exists; pipeline-level recall for `cm_active_customers_total` remains 100% on Farfetch. See commit `03a8a20`.
