---
id: 626
source: gh
slug: phase2-c6-c7-reporting-bugs
title: "Phase-2 eval: C6 cache hit rate counter unit mismatch + C7 total_calls mislabeled"
status: open
severity: low
autonomy: skip
estimated: —
touches:
  - scripts/run_phase2_quantitative_eval.py
  - tests/unit/scripts/test_run_phase2_quantitative_eval.py
  - docs/operations/llm-presence-classifier-phase2-quantitative-eval-runbook.md
discovered: 2026-05-14
updated: 2026-05-14
gh_issue: 626
note: C6 displays "3224.6%" (tokens ÷ filing-metric-pairs); C7 cost in dollars is correct but total_calls is filing-metric-pairs not API-call count. Headline unaffected; reporting clarity affected.
---

### Problem

Phase-2 v2 gate run `20260514Trerun` surfaced two reporting bugs in `summary.cost`:

**C6 unit mismatch**: `cache_reads` (16,768 cache-read tokens) ÷ `total_calls` (520 filing-metric pairs) = "3224.6%" — nonsense. Per-segment logs show real Anthropic cache hit rates of 95–99% throughout the run, so caching works; only the rollup is broken.

**C7 mislabeled**: `total_usd = $194.88` is correctly computed from real token totals. But `total_calls = 520` is filing × metric pairs, NOT the actual classify_segment API call count (hundreds per filing). Two consequences: (1) the pre-flight cost guard underestimated by ~12× because `n_filings × $0.25` doesn't account for per-segment classify_segment invocations; (2) operators read "520 calls cost $194" and over-estimate per-call cost.

Neither bug changes the go/no-go decision. Headline result (NO-GO due to C3) is unaffected.

### Next Steps

- Fix C6 to use token-ratio (`cache_read_tokens / (cache_read_tokens + input_tokens_non_cached)`) matching Anthropic's convention.
- Rename `total_calls` → `total_segment_calls` and add a separate `total_filing_metric_pairs` field for scoring.
- Update runbook cost guidance to use per-segment estimate (roughly `paraphrase_segs × n_metric_sets` per filing).
- Add a unit test asserting cost rollup matches mocked token totals.
