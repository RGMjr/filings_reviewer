---
id: 619
source: gh
slug: extraction-image-pipeline-silently-dark
title: "filings-extraction image pipeline silently dark: OPENAI_API_KEY guard ignores Gemini provider"
status: resolved
severity: medium
autonomy: n/a
estimated: —
touches:
  - src/extraction_v2/pipeline.py
  - render.yaml
discovered: 2026-05-13
updated: 2026-05-15
gh_issue: 619
note: Discovered while debugging the 2026-05-12 filings-extraction OOM. The OOM and this guard issue are independent — both surfaced in the same log.
---

### Problem

`src/extraction_v2/pipeline.py:629` (`_check_vision_api_availability`) disables image triage (Stage 4) and chart OCR (Stage 5) whenever `OPENAI_API_KEY` is missing — even when the cron is explicitly configured to use Gemini for vision via gh-441 / gh-469.

The 2026-05-12 `filings-extraction` cron log emitted:

```
WARNING:src.extraction_v2.pipeline:OPENAI_API_KEY is not set. Disabling image and chart extraction (Stages 4 and 5). Text extraction will proceed normally.
```

despite `render.yaml:62-71` configuring `ENABLE_METRIC_CLASSIFY=true`, `VISION_CLASSIFY_PROVIDER=gemini`, `VISION_CLASSIFY_MODEL=gemini-2.5-flash-lite`, and `GOOGLE_API_KEY` (set via dashboard).

Net effect: the cron has likely been running text-only for image stages since the gh-441 flip (2026-05-04), even though Gemini classify is provisioned.

### Next Steps

Two possibilities to resolve first:

1. **Stale guard.** Replace `OPENAI_API_KEY`-only check with a provider-aware check that maps `VISION_CLASSIFY_PROVIDER` → required env var. Add a unit test asserting image stages remain enabled when only `GOOGLE_API_KEY` is set under Gemini config.
2. **Intentional scoping.** Full-page OCR / chart OCR genuinely still requires OpenAI, only metric-classify is on Gemini. Fix the warning copy to clarify and add a positive log line for the Gemini classify substage.

Then: query prod to confirm what fraction of `filings-extraction` runs since 2026-05-04 produced `v2_image_classifications` / `v2_image_assets.detected_metrics` rows, to quantify how much image work has been missed.

### Resolution

`_check_vision_api_availability` is now provider-aware. It builds a map from
each configured vision provider (`vision_full_page_ocr_provider`,
`vision_prescan_provider`, `vision_chart_fallback_provider`) to its required
env var via `_VISION_PROVIDER_ENV_VARS` (`openai`→`OPENAI_API_KEY`,
`gemini`/`google`→`GOOGLE_API_KEY`, `anthropic`→`ANTHROPIC_API_KEY`).

- **Stage 4 (image triage)** — re-enabled unconditionally. Has no vision-API
  dependency (uses learned-model + keyword-proximity heuristics only).
- **Stage 5 (OCR/chart)** — disabled only when one of its configured
  providers' env vars is missing. Under current `filings-extraction` env
  (only `GOOGLE_API_KEY` set; default `chart_fallback=anthropic`), Stage 5
  remains disabled because `ANTHROPIC_API_KEY` is unset — preventing the
  construction-time crash described in the deferred follow-up.
- Warning copy now names the offending config field, provider, and missing
  env var explicitly; INFO log emitted when Stage 4 runs without Stage 5
  so operators can see the partial-enable state.

The construction-time `OPENAI_API_KEY` requirement inside
`OCRExtractionStage.vision_client` (and any residual OpenAI hard-coding in
`src/llm/vision_client.py`) is intentionally **deferred to a follow-up**:
see gh-636. That fix needs to thread the configured provider through the
lazy `vision_client` property and verify Gemini end-to-end for full-page
OCR (not just metric-classify).
