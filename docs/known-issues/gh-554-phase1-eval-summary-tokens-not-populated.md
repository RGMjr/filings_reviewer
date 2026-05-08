---
id: 554
source: gh
slug: phase1-eval-summary-tokens-not-populated
title: "Phase-1 eval: surface token counts in summary.tokens rollup"
status: resolved
severity: low
autonomy: n/a
estimated: —
touches:
  - scripts/run_phase1_eval.py
  - docs/operations/llm-presence-classifier-phase1-eval-runbook.md
discovered: 2026-05-07
updated: 2026-05-08
gh_issue: 554
---

### Problem

Both Path A (`--path pipeline`) and Path B (`--path direct`) of `run_phase1_eval.py` discard token counts. Path B discards the `_tokens` dict returned by `classify_segment` (line with `results, _tokens = client.classify_segment(...)`). Path A token counts come from `LLMPresenceClassifierStage` inside the V2 pipeline and are equally unreachable post-run. The `summary.tokens` key referenced in the runbook ("total in/out, cache hit rate, $") is never written, so operators have no cost visibility when running the eval.

### Resolution

- Path B: `evaluate_filing_direct` now unpacks `(results, seg_tokens)` from each `classify_segment` call and accumulates into `filing_tokens`; returns `(aggregates, errors, filing_tokens)` (3-tuple). `run_eval` sums `filing_tokens` across all filings into `total_tokens`.
- Path A: `evaluate_filing_pipeline` reads `total_input_tokens` / `total_output_tokens` / `total_cache_read` / `total_cache_create` from `StageResult.metadata` for `PipelineStage.LLM_PRESENCE_CLASSIFIER`; returns `(aggregates, kw_present, errors, filing_tokens)` (4-tuple).
- Both paths write `summary.tokens: {input_tokens, output_tokens, cache_read_tokens, cache_create_tokens, estimated_cost_usd}` via `estimate_cost_usd_from_counts`.
- Unit tests in `tests/unit/scripts/test_phase1_eval_tokens.py` assert token accumulation and summary key population with mocked classifier.
- Callers of `evaluate_filing_pipeline` in `tests/unit/scripts/test_run_phase1_eval_pipeline.py` updated to unpack the new 4-tuple.
