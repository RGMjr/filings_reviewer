---
id: 366
source: gh
slug: vision-routing-mode-test-contamination
title: Fix VISION_ROUTING_MODE test contamination causing 16 ordering-dependent failures
status: resolved
severity: medium
autonomy: skip
estimated: —
touches: []
discovered: 2026-04-30
updated: 2026-04-30
gh_issue: 366
note: Root cause identified and fixed — test_batch_runner.py's module-level exec_module runs load_dotenv() which sets VISION_ROUTING_MODE=two_stage from local .env; fixed via autouse conftest fixture + save/restore guard in test_batch_runner.py
---

### Problem

When `tests/unit/` runs as a full suite, `test_image_pipeline_integration.py::TestChartAnnotationExtraction::test_annotations_parsed_from_response` fails because `VISION_ROUTING_MODE=two_stage` leaks from `test_batch_runner.py` into subsequent tests that expect legacy mode. The test passes in isolation. The failure was pre-existing on `main`.

**Root cause:** `test_batch_runner.py` loads `batch_v2_extraction.py` via `importlib.exec_module` at module collection time. That script calls `load_dotenv()` at module level, which reads `VISION_ROUTING_MODE=two_stage` from the local `.env` file and sets it in `os.environ` for the rest of the test session.

### Fix Applied

1. Added `tests/unit/extraction_v2/conftest.py` with an `autouse=True` fixture that calls `monkeypatch.delenv("VISION_ROUTING_MODE", raising=False)` before each test — runtime guarantee.
2. Added save/restore guard around `exec_module` in `test_batch_runner.py` — documents the root cause and provides module-load-time protection.
