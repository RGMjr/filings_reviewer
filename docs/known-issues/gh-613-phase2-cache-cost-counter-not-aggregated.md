---
id: 613
source: gh
slug: phase2-cache-cost-counter-not-aggregated
title: "Phase-2 eval: summary.cost.cache_reads + total_calls always 0; token rollup not aggregated"
status: open
severity: low
autonomy: skip
estimated: —
touches:
  - scripts/run_phase2_quantitative_eval.py
  - tests/unit/scripts/test_run_phase2_quantitative_eval.py
discovered: 2026-05-11
updated: 2026-05-11
gh_issue: 613
note: PR #600 hotfix captured the 4-tuple's token_totals as _fil_tokens and discarded it; summary.cost is from a flat count estimate, C6 cache criterion always FAILs bogusly
---

### Problem

Phase-2 gate run `20260511T1416live` reported `summary.cost.cache_reads: 0, total_calls: 0`, hit rate 0.0%, failing C6 (cache hit rate ≥ 85%). Per-segment logs showed real Anthropic cache hit rates of 95–100% throughout the run. The C6 failure is bogus — Phase-2 is not aggregating the cache stats from `evaluate_filing_pipeline`'s 4th return value.

PR #600 captured the 4th value as `_fil_tokens` (prefixed underscore to silence ruff) and immediately discarded it. `summary.cost.total_usd` is computed as `n_filings × $0.25`, not from real token totals — so operators cannot tell actual spend either.

### Next Steps

- Replace `_fil_tokens` with a real running aggregator over `input_tokens`, `output_tokens`, `cache_read`, `cache_create`.
- Populate `summary.cost` and the C6 cache-hit-rate value from the aggregator.
- Compute `summary.cost.total_usd` from token totals using Haiku 4.5 pricing.
- Add a unit test mocking `evaluate_filing_pipeline` with a fixed token dict and asserting the rollup.
