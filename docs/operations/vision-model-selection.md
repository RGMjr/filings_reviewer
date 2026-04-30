# Vision Model Selection

One-page reference for which model each vision call site uses, what env var controls it, and what the cost trade-off is. Pairs with `vision_spend_usd_by_site` telemetry (added in PR #357) for measurement.

## Call sites

| # | Site | Stage | Method | Env var(s) | Default | Volume |
|---|------|-------|--------|------------|---------|--------|
| 1 | Table OCR | OCRExtraction | `process_table_image` | `VISION_MODEL_OCR` (two_stage) / `VISION_PROVIDER`+`VISION_MODEL_OCR` (legacy) | `gemini-2.5-flash-lite` (two_stage) / `gpt-4o` (legacy) | ≤5 calls/filing |
| 2 | Chart OCR fast | OCRExtraction | `process_chart` (first pass) | `VISION_MODEL_OCR` (two_stage only) | `gemini-2.5-flash-lite` | 5–15 calls/filing |
| 3 | Chart read premium | OCRExtraction | `process_chart` (second pass) | `VISION_MODEL_CHART` (two_stage) / inherits VISION_PROVIDER (legacy) | `claude-sonnet-4-6` (two_stage) / `gpt-4o` (legacy) | 5–15 calls/filing, $0.25 budget cap |
| 4 | Full-page OCR | OCRExtraction | `process_full_page_scan` | `VISION_PROVIDER_FULL_PAGE_OCR`, `VISION_MODEL_FULL_PAGE_OCR` | `gemini` / `gemini-2.0-flash` | ≤30 calls/filing on full-page-scan filings |
| 5 | Prescan | OCRExtraction | `_prescan_ambiguous_images` | `VISION_PROVIDER_PRESCAN`, `VISION_MODEL_PRESCAN` | `gemini` / `gemini-2.0-flash` | ≤10 calls/filing |
| 6 | Metric classify | ImageClassify | `analyze_image_for_metric_classification` | `VISION_CLASSIFY_PROVIDER`, `VISION_CLASSIFY_MODEL` | `gemini` / `gemini-2.5-flash-lite` | 10–40 calls/filing when ENABLE_METRIC_CLASSIFY=true |

## Routing modes

- `VISION_ROUTING_MODE=legacy` (default): single provider for table-OCR + chart-OCR + chart-read, set by `VISION_PROVIDER`.
- `VISION_ROUTING_MODE=two_stage`: cheap OCR provider for sites 1+2, premium provider for site 3.
- Sites 4, 5, 6 are independent of `VISION_ROUTING_MODE` and `VISION_PROVIDER` — their per-site env knobs always win.

## Measuring spend

After a cold-cache run (`LLM_CACHE_DISABLED=1`), inspect `PipelineResult.vision_spend_usd_by_site` (added in PR #357) for per-filing breakdown, or sum across filings via `vision_spend_usd_total`.

## Changing a model

1. Add the env var to Render's `filings-shared-secrets` env group (or set locally).
2. Verify the corresponding API key is present (`GEMINI_API_KEY` for Gemini, `ANTHROPIC_API_KEY` for Claude, `OPENAI_API_KEY` for OpenAI).
3. Restart the affected service. Re-extract a sample filing and check `vision_spend_usd_by_site` for the expected drop / rise.
4. Run `python3 -m src.gold_standard.v2_validator --fail-on-regression` if the swap touches sites 1, 2, or 3 (recall-bearing).
