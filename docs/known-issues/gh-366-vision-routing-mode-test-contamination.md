---
id: 366
source: gh
slug: vision-routing-mode-test-contamination
title: Fix VISION_ROUTING_MODE test contamination causing 16 ordering-dependent failures
status: open
severity: medium
autonomy: skip
estimated: —
touches: []
discovered: 2026-04-30
updated: 2026-04-30
gh_issue: 366
note: 16 chart-related tests fail in full suite due to VISION_ROUTING_MODE=two_stage leaking from an earlier test; all pass in isolation; root cause not yet traced
---

### Problem

When `tests/unit/extraction_v2/` runs as a full suite, 16 chart-extraction tests fail because `VISION_ROUTING_MODE=two_stage` leaks from an earlier test into subsequent tests that expect legacy mode. All 16 pass when run in isolation. The failure set is identical between the current `main` and the PR 3 worktree — pre-existing, not introduced by recent changes. Root cause: a test somewhere before `test_image_pipeline_integration.py`, `test_ocr_extraction.py`, and `test_vision_cost_telemetry.py` sets the env var without monkeypatch cleanup.

### Next Steps

- Bisect to find which test file introduces the contamination (binary search via `pytest --collect-only` ordering)
- Fix the leaking test to use `monkeypatch.setenv` instead of direct `os.environ` mutation
- Consider adding a session-scoped fixture that asserts `VISION_ROUTING_MODE` is unset at the start of each test file
