---
id: 636
source: gh
slug: vision-client-construction-guard
title: "VisionClient construction-time OPENAI_API_KEY guard blocks non-OpenAI providers"
status: open
severity: medium
autonomy: review
estimated: M
touches:
  - src/llm/vision_client.py
  - src/extraction_v2/stages/ocr_extraction.py
discovered: 2026-05-15
updated: 2026-05-15
gh_issue: 636
note: Split from gh-619; requires confirming Gemini end-to-end for full-page OCR.
---

### Problem

Follow-up split out from gh-619. The pipeline-level guard at
`src/extraction_v2/pipeline.py::_check_vision_api_availability` was made
provider-aware in the gh-619 PR — Stage 4 (image triage) re-enabled
unconditionally and Stage 5 (OCR/chart) now gates on each configured
vision provider's env var.

However, `src/extraction_v2/stages/ocr_extraction.py:258` (the lazy
`vision_client` property) still raises `V2FatalError` on construction if
`OPENAI_API_KEY` is unset, regardless of which provider the pipeline is
configured for. To enable Stage 5 end-to-end on Gemini (or any non-OpenAI
provider), this construction-time guard needs the same provider-aware
treatment.

The per-site clients (`_get_full_page_ocr_client`,
`_get_prescan_client`, `_get_chart_fallback_client`) already route via
the configured provider, so the legacy `vision_client` property is the
remaining OpenAI-only path.

### Next Steps

1. Replace the hard `OPENAI_API_KEY` check in
   `OCRExtractionStage.vision_client` with provider-aware logic — use
   `context.config.vision_full_page_ocr_provider` (or thread the
   relevant provider config through the property) and check the
   matching env var per provider per the same `_VISION_PROVIDER_ENV_VARS`
   map shipped in gh-619.
2. Audit `src/llm/vision_client.py::VisionClient.__init__` for any
   remaining hard OpenAI dependency at construction time.
3. Verify Gemini works end-to-end for full-page OCR — chart-read path
   on Gemini has not been exercised in prod (only metric-classify has).
4. Add an integration test under `tests/integration/extraction_v2/` for
   Stage 5 in a Gemini-only env (no `OPENAI_API_KEY`,
   `vision_full_page_ocr_provider=gemini`,
   `vision_chart_fallback_provider=gemini`, `GOOGLE_API_KEY` set).

### Out of Scope

- The pipeline-level guard (shipped in the gh-619 PR).
- `render.yaml` changes — env already correct for Gemini.
