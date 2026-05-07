---
id: 554
source: gh
slug: phase1-eval-summary-tokens-not-populated
title: "Phase-1 eval: surface token counts in summary.tokens rollup"
status: open
severity: low
autonomy: skip
estimated: —
touches:
  - scripts/run_phase1_eval.py
  - docs/operations/llm-presence-classifier-phase1-eval-runbook.md
discovered: 2026-05-07
updated: 2026-05-07
gh_issue: 554
note: summary.tokens key in eval output is never populated; token counts from classify_segment and pipeline are discarded
---

### Problem

Both Path A (`--path pipeline`) and Path B (`--path direct`) of `run_phase1_eval.py` discard token counts. Path B discards the `_tokens` dict returned by `classify_segment` (line with `results, _tokens = client.classify_segment(...)`). Path A token counts come from `LLMPresenceClassifierStage` inside the V2 pipeline and are equally unreachable post-run. The `summary.tokens` key referenced in the runbook ("total in/out, cache hit rate, $") is never written, so operators have no cost visibility when running the eval.

### Next Steps

- Accumulate token dicts from `classify_segment` (Path B) and `LLMPresenceClassifierStage` stage metadata (Path A) across all filings/segments.
- Write a `summary.tokens` rollup: `{input_tokens, output_tokens, cache_read_tokens, cache_create_tokens, estimated_cost_usd}`.
- Update the runbook Path A cost range once real observed numbers are available.
