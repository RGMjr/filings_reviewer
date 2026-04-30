# Vision Model Selection

One-page reference for which model each vision call site uses, what env var controls it, and what the cost trade-off is. Pairs with `vision_spend_usd_by_site` telemetry (added in PR #357) for measurement.

## Call sites

| # | Site | Stage | Method | Env var(s) | Default | Volume |
|---|------|-------|--------|------------|---------|--------|
| 1 | Table OCR | OCRExtraction | `process_table_image` | `VISION_MODEL_OCR` (two_stage) / `VISION_PROVIDER`+`VISION_MODEL_OCR` (legacy) | `gemini-2.5-flash-lite` (two_stage) / `gpt-4o` (legacy) | ≤5 calls/filing |
| 2 | Chart OCR fast | OCRExtraction | `process_chart` (first pass) | `VISION_MODEL_OCR` (two_stage only) | `gemini-2.5-flash-lite` | 5–15 calls/filing |
| 3 | Chart read premium | OCRExtraction | `process_chart` (second pass) | `VISION_MODEL_CHART` (two_stage) / inherits VISION_PROVIDER (legacy) | `claude-haiku-4-5-20251001` (two_stage), Sonnet fallback on conf<0.7 / `gpt-4o` (legacy) | 5–15 calls/filing, $0.25 budget cap |
| 4 | Full-page OCR | OCRExtraction | `process_full_page_scan` | `VISION_PROVIDER_FULL_PAGE_OCR`, `VISION_MODEL_FULL_PAGE_OCR` | `gemini` / `gemini-2.0-flash` | ≤30 calls/filing on full-page-scan filings |
| 5 | Prescan | OCRExtraction | `_prescan_ambiguous_images` | `VISION_PROVIDER_PRESCAN`, `VISION_MODEL_PRESCAN` | `gemini` / `gemini-2.0-flash` | ≤10 calls/filing |
| 6 | Metric classify | ImageClassify | `analyze_image_for_metric_classification` | `VISION_CLASSIFY_PROVIDER`, `VISION_CLASSIFY_MODEL` | `gemini` / `gemini-2.5-flash-lite` | 10–40 calls/filing when ENABLE_METRIC_CLASSIFY=true |

## Routing modes

- `VISION_ROUTING_MODE=legacy` (default): single provider for table-OCR + chart-OCR + chart-read, set by `VISION_PROVIDER`.
- `VISION_ROUTING_MODE=two_stage`: cheap OCR provider for sites 1+2, premium provider for site 3.
- Sites 4, 5, 6 are independent of `VISION_ROUTING_MODE` and `VISION_PROVIDER` — their per-site env knobs always win.

## Chart-read fallback escalation (PR 3)

The two-stage chart-read pass uses Haiku-4.5 by default for cost. If the
parsed chart response's confidence falls below `VISION_CHART_CONFIDENCE_THRESHOLD`
(default 0.7), the stage re-calls a fallback model (default `claude-sonnet-4-6`)
and uses whichever response has higher confidence. Both calls' costs are
attributed to `chart_read_premium`. The escalation count is exposed in
`StageResult.metadata['chart_fallback_escalations']`.

**Production monitoring:** if escalation rate exceeds ~15-20% on a filing
or in aggregate, consider lowering the threshold (Haiku is rescuing too
often → its accuracy is bad enough to warrant just defaulting to Sonnet
again) or raising the threshold (Haiku is rescuing rarely → drop the
fallback entirely to save the cost of monitoring).

**Disabling the fallback:** set `VISION_CHART_FALLBACK_MODEL=` (empty string).
This pins chart-read to Haiku regardless of confidence.

## Measuring spend

After a cold-cache run (`LLM_CACHE_ENABLED=false`), inspect `PipelineResult.vision_spend_usd_by_site` (added in PR #357) for per-filing breakdown, or sum across filings via `vision_spend_usd_total`.

### Production observability

Every successful pipeline run emits a single structured log line at INFO level via `V2Pipeline.process()`:

```
vision_spend filing_id=<id> total_usd=<f> by_site=<json> chart_fallback_escalations=<n> duration_ms=<n>
```

The `by_site` field is JSON-encoded with all six call-site keys present (zero-spend keys included). To recover the production distribution from Render logs:

```bash
# Stream recent vision_spend lines
gh run view ...                              # or use Render's log search UI
grep "vision_spend filing_id=" <log>         # all rows
grep "chart_fallback_escalations=" <log> | awk -F'chart_fallback_escalations=' '{print $2}' | awk '{print $1}' | sort | uniq -c
                                              # escalation-rate distribution
```

Healthy ranges (post-PR #367):
- `chart_read_premium` averaging ~$0.07–0.10 on chart-heavy filings (was ~$0.23 with Sonnet primary).
- `chart_fallback_escalations` per chart-heavy filing in the 0–3 range; aggregate escalation rate 5–20% across filings. >25% suggests Haiku is rescuing too often (consider rolling back); <5% suggests the fallback is dead weight (drop it).

## Changing a model

1. Add the env var to Render's `filings-shared-secrets` env group (or set locally).
2. Verify the corresponding API key is present (`GEMINI_API_KEY` for Gemini, `ANTHROPIC_API_KEY` for Claude, `OPENAI_API_KEY` for OpenAI).
3. Restart the affected service. Re-extract a sample filing and check `vision_spend_usd_by_site` for the expected drop / rise.
4. Run `python3 -m src.gold_standard.v2_validator --fail-on-regression` if the swap touches sites 1, 2, or 3 (recall-bearing).
