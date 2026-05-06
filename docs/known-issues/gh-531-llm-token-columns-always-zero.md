---
id: 531
source: gh
slug: llm-token-columns-always-zero
title: LLM classifier token columns always 0 in validator (token threading not implemented)
status: open
severity: low
autonomy: skip
estimated: —
touches: []
discovered: 2026-05-06
updated: 2026-05-06
gh_issue: 531
note: add token fields to StageResult.metadata in LLMPresenceClassifierStage and wire to AggregateMetrics
---

### Problem

`AggregateMetrics` fields `llm_total_input_tokens`, `llm_total_output_tokens`,
`llm_cache_hit_rate`, and `llm_estimated_cost_usd` added in PR3c Part H always
show 0. `PresenceClassifierClient._call_api()` logs token usage via `logger.info()`
only — no structured path threads them to `StageResult.metadata` or
`LLMPresenceSignal`. The validator has no access to per-call token data.

### Next Steps

- Add token fields to `StageResult.metadata` in `LLMPresenceClassifierStage` (sum across all `_call_api` calls)
- Or add token fields to `LLMPresenceSignal` and aggregate in `MetricPresenceStage`
- Wire the chosen source into `AggregateMetrics` in `compute_metrics`
