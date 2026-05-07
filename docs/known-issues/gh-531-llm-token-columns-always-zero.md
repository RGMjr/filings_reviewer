---
id: 531
source: gh
slug: llm-token-columns-always-zero
title: LLM classifier token columns always 0 in validator (token threading not implemented)
status: resolved
severity: low
autonomy: n/a
estimated: —
touches: []
discovered: 2026-05-06
updated: 2026-05-07
gh_issue: 531
note: add token fields to StageResult.metadata in LLMPresenceClassifierStage and wire to AggregateMetrics
---

### Problem

`AggregateMetrics` fields `llm_total_input_tokens`, `llm_total_output_tokens`,
`llm_cache_hit_rate`, and `llm_estimated_cost_usd` added in PR3c Part H always
show 0. `PresenceClassifierClient._call_api()` logs token usage via `logger.info()`
only — no structured path threads them to `StageResult.metadata` or
`LLMPresenceSignal`. The validator has no access to per-call token data.

### Resolution

Threaded token counts end-to-end through five changes:

1. `_call_model` now returns `(by_metric, token_counts)` — a tuple where
   `token_counts = {input_tokens, output_tokens, cache_read, cache_create}`.
2. `classify_segment` accumulates token dicts across the Haiku call and any Sonnet
   fallback, and returns `(list[SegmentClassification], total_tokens)`.
3. `LLMPresenceClassifierStage.process` unpacks the tuple in both loops and sums
   tokens into four new `StageResult.metadata` keys: `total_input_tokens`,
   `total_output_tokens`, `total_cache_read`, `total_cache_create`.
4. `ValidationResult` gained a `stage_metadata: dict[str, dict[str, Any]]` field,
   populated alongside `stage_timings` in `validate_filing`.
5. `compute_metrics` sums the token fields from `stage_metadata["llm_presence_classifier"]`
   across all filings and passes them into `AggregateMetrics`, computing
   `llm_cache_hit_rate` and `llm_estimated_cost_usd` via a new public helper
   `estimate_cost_usd_from_counts` in `presence_classifier_client.py`.
