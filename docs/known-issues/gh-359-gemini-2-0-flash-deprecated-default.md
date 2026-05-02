---
id: 359
source: gh
slug: gemini-2-0-flash-deprecated-default
title: Default gemini-2.0-flash model deprecated for new Gemini API accounts
status: resolved
severity: medium
autonomy: skip
estimated: —
touches:
  - src/extraction_v2/pipeline.py
  - src/llm/vision_client.py
  - src/llm/providers/gemini.py
  - .env.template
discovered: 2026-04-29
updated: 2026-05-02
gh_issue: 359
note: defaults swapped to gemini-2.5-flash-lite (already in use by metric-classify path); gemini-2.0-flash pricing entry retained for historical cost-reporting on legacy runs
---

### Problem

The PR 2 triage-OCR defaults (`vision_full_page_ocr_model`, `vision_prescan_model`) are set to `gemini-2.0-flash`. During unit testing, this model returned `404 NOT_FOUND: "no longer available to new users"` when a newer Gemini API account was used. Production appears unaffected (legacy account key), but any contributor onboarding with a new API key will see silent extraction failures on the full-page-scan and prescan sites.

### Resolution

Swapped the deprecated default to `gemini-2.5-flash-lite` — the same model already in use by the metric-classify path (`PipelineConfig.vision_classify_model`) and the two-stage OCR site (`_TWO_STAGE_DEFAULT_OCR_MODEL` in `vision_client.py`). Updates:

- `src/extraction_v2/pipeline.py` — `vision_full_page_ocr_model`, `vision_prescan_model` defaults
- `src/llm/vision_client.py` — `_PROVIDER_DEFAULT_MODELS["gemini"]["ocr"]`
- `src/llm/providers/gemini.py` — module docstring, `GeminiVisionProvider.__init__` default, pricing-map entry for `gemini-2.5-flash-lite` ($0.10/$0.40 per 1M tokens). `gemini-2.0-flash` pricing entry retained so historical `model_training_runs` rows referencing the deprecated id still resolve a price.
- `.env.template` — commented examples for `VISION_MODEL_FULL_PAGE_OCR`, `VISION_MODEL_PRESCAN`
- `tests/unit/extraction_v2/test_vision_env_overrides.py` — default assertions + env-override test now uses `gemini-2.0-flash-lite` so override semantics remain meaningful
- `.claude/rules/infrastructure.md`, `.claude/rules/v2-pipeline.md`, `docs/operations/vision-model-selection.md` — docs aligned with the new default

A startup-time model-availability probe was scoped out — single-line fall-through is sufficient given Gemini deprecations are infrequent. Track separately if a second deprecation lands.
