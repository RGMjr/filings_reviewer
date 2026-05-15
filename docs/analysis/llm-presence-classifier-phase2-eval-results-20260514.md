# Phase-2 quantitative gate results — 2026-05-14 v2 re-run

**Run ID**: `20260512Trerun`
**Decision**: `NO-GO` (criterion C3 — new framing — failed)
**Companion to**: [`llm-presence-classifier-phase2-eval-results-20260511.md`](./llm-presence-classifier-phase2-eval-results-20260511.md)

## TL;DR

The 2026-05-11 NO-GO was ambiguous: classifier ≈ keyword to 3 decimals, on a gate
(aggregate-recall delta ≥ +5pt) that was mathematically unreachable from a 98.8%
baseline. We rebuilt the gate to ask the actionable question — *does the
classifier catch real positives the keyword baseline misses?* — and re-ran on the
same corpus.

**The classifier is non-additive on the enrolled metric set.** Under the new
C3 (≥3 net-new TPs at ≥50% precision on any Tier-1 metric with `kw_recall <
0.95`), the only Tier-1 metric with headroom (`cm_large_customers_period_end`)
caught 0 net-new TPs and 1 net-new FP. Every other Tier-1 metric was either
at-ceiling on keyword (9 metrics with `kw_recall ≥ 0.95`) or had insufficient
coverage (5 metrics with <5 filings).

The 2026-05-11 run answered "the gate is broken." This run answers "the
classifier doesn't add value on what we've enrolled it for."

## What changed from 2026-05-11

Three code changes, all in `scripts/run_phase2_quantitative_eval.py`:

1. **gh-602** — second-pass dedup by `filing_id` on the enriched merged
   corpus. The 2026-05-11 run double-weighted 5 filings (1 intra-gold
   duplicate + 4 cross-corpus gold↔reviewed duplicates). The v2 corpus is
   52 unique filings (56 selected, 4 dropped: Datadog S-1A, Smartsheet,
   Lemonade, Fastly).

2. **gh-613** — real token + call counters replacing the flat
   `_COST_PER_FILING_USD = $0.25` estimate. Cost now comes from
   `estimate_cost_usd_from_counts(input, output, cache_read, cache_create,
   model=Haiku)` summed across all `classify_segment` calls.

3. **C3 reframe** — replaced the aggregate-recall-delta hard gate with a
   net-new-positives gate. Old C3 demoted to `C3_aggregate_recall_delta`
   (informational). New informational criterion **C8** added (clf-vs-kw
   agreement rate ≥ 85%).

## Run parameters

| | |
|---|---|
| Script | `scripts/run_phase2_quantitative_eval.py` |
| Branch | `worktree-phase2-gate-v2` |
| Corpus (enriched, post-dedup) | 52 filings (8 gold + 44 reviewed) |
| Filings dropped by filing_id dedup | 4 |
| Classifier model | Haiku 4.5 (no Sonnet fallback) |
| Concurrency | 8 (eval-only) |
| Wall clock | ~10h 12min (2026-05-14 17:34 → 2026-05-15 03:46 UTC) |
| Real cost | **$194.79** |
| Total classify_segment calls | **56,905** |
| Token-weighted cache hit rate | **97.0%** (310M cache reads / 320M total inputs) |
| Errors | 0 of 56,905 calls |

## Hard criteria

| ID | Criterion | Result | Detail |
|---|---|---|---|
| C1 | Zero prompt/parse errors | ✅ PASS | 0 errors / 56,905 calls |
| C2 | Per-Tier-1 clf recall ≥ kw − 5pt | ✅ PASS | 0 breaches (5 metrics skipped — insufficient coverage) |
| **C3 (new)** | ≥1 Tier-1 metric with ≥3 net-new TPs at ≥50% precision (kw_recall < 0.95) | ❌ **FAIL** | Only `cm_large_customers_period_end` had headroom; clf_only_tp=0, clf_only_fp=1, clf_only_precision=0.000 |
| C4 | No Tier-1 metric F1 < 0.40 | ✅ PASS | 0 breaches (5 skipped) |
| C5 | Error rate ≤ 0.5% | ✅ PASS | 0/56,905 = 0.000% |

## Informational criteria

| ID | Criterion | Result | Detail |
|---|---|---|---|
| `C3_aggregate_recall_delta` | clf − kw ≥ +5pt | ❌ | clf=0.986 kw=0.986 delta=+0.000 (informational target +0.050) |
| C6 | Token-weighted cache hit rate ≥ 85% | ✅ | 310,533,111 / 320,163,713 cached tokens = **97.0%** |
| C7 | Total cost ≤ $25 | ❌ | **$194.79** spent — see Cost surprise below |
| **C8 (new)** | Clf-vs-kw agreement rate ≥ 85% | ❌ | 432/520 pairs agree = **83.1%** |

## The decisive number

The new C3 considers a Tier-1 metric only if it has ≥5-filing coverage AND
`kw_recall < 0.95` (the headroom gate). Of 15 Tier-1 metrics, only one
survived both gates:

```
cm_large_customers_period_end: clf_only_tp=0 clf_only_fp=1 clf_only_precision=0.000
```

Zero net-new TPs on the one metric where the classifier had any room to
contribute. That's the answer the gate was redesigned to extract.

The remaining 14 metrics:

| Bucket | Metrics |
|---|---|
| `kw_recall ≥ 0.95` (no headroom — 9 metrics) | `cm_customer_acquisition_cost`, `cm_customer_retention_rate`, `cm_gross_revenue_retention`, `cm_lifetime_value_per_customer`, `cm_ltv_to_cac_ratio`, `cm_ltv_to_cac_ratio_by_cohort`, `cm_net_revenue_retention`, `cm_revenue_by_cohort`, `cm_revenue_concentration` (all at `kw_recall = 1.000`) |
| Insufficient coverage (<5 filings — 5 metrics) | `cm_balance_by_cohort`, `cm_customers_period_end_by_tenure`, `cm_gross_margin_by_cohort`, `cm_new_customers_acquired`, `cm_transactions_by_cohort` (all 0 filings in this corpus) |

## Per-metric (merged corpus)

| Metric | n | precision | recall | F1 | kw_recall |
|---|---:|---:|---:|---:|---:|
| `cm_customer_acquisition_cost` | 12 | 0.333 | 1.000 | 0.500 | 1.000 |
| `cm_customer_retention_rate` | 17 | 0.571 | 1.000 | 0.727 | 1.000 |
| `cm_gross_revenue_retention` | 9 | 1.000 | 1.000 | 1.000 | 1.000 |
| `cm_large_customers_period_end` | 14 | 0.556 | 0.833 | 0.667 | **0.833** |
| `cm_lifetime_value_per_customer` | 9 | 0.500 | 1.000 | 0.667 | 1.000 |
| `cm_ltv_to_cac_ratio` | 9 | 1.000 | 1.000 | 1.000 | 1.000 |
| `cm_ltv_to_cac_ratio_by_cohort` | 9 | 1.000 | 1.000 | 1.000 | 1.000 |
| `cm_net_revenue_retention` | 17 | 0.786 | 1.000 | 0.880 | 1.000 |
| `cm_revenue_by_cohort` | 19 | 0.714 | 1.000 | 0.833 | 1.000 |
| `cm_revenue_concentration` | 33 | 0.727 | 1.000 | 0.842 | 1.000 |

Recall is 1.000 on every metric the classifier was measured against, except
`cm_large_customers_period_end` (0.833). Precision is mixed — the classifier
is over-triggering relative to gold on several metrics (CAC, retention rate,
LTV), which is consistent with the "weakly-true negatives" caveat (gold
absence ≠ labeled absence) but is also the surface that C3 (new) used to
ask whether those FPs are masking real net-new TPs. The answer: they aren't.

## Aggregate-recall delta (informational)

The old C3:

```
clf=0.986 kw=0.986 delta=+0.000 (informational target +0.050)
```

Identical reading to 2026-05-11 (`clf=0.988 kw=0.988`). The new corpus
shape (52 vs 55 filings) didn't move this number. The classifier and the
keyword baseline really do converge at the (filing, metric) level on this
enrolled set.

## Agreement rate (C8)

83.1% of (filing, metric) pairs had `classifier_present == keyword_present`.
The 16.9% disagreement is distributed across:

- Classifier flagging present where keyword doesn't (potential net-new TPs
  or net-new FPs — answered by C3 above: net-new FPs dominate).
- Classifier flagging absent where keyword does (the C2 measurement —
  passed, no Tier-1 regression).

83.1% is below the 85% target but the gap is small and not in itself
diagnostic of a problem.

## Cost surprise

The worker prompt expected ≤$2 if cache hit rate ≥ 85%. The real run cost
**$194.79**. The expectation was wrong by ~100×. Math:

- 56,905 classify_segment calls
- ~5,571 cache-read tokens per call (the cached prompt prefix) × $1.00/M × 0.10
  (Anthropic cache-read multiplier) = $0.000557/call from cache reads alone
- ~500 output tokens per call × $5.00/M = $0.0025/call
- ~170 fresh input tokens per call × $1.00/M = $0.0002/call
- **~$0.003/call × 56,905 calls ≈ $170** — close to the $194.79 observed

The cache *is* working (97.0% hit rate). The per-call floor just isn't $0.
The 2026-05-11 estimate of $13.75 was the bogus `n_filings × $0.25` proxy
that gh-613 replaced; we now have the real number for the first time.

**Operator takeaway**: a 52-filing run on the current prompt set is a
~$200 spend, not a ~$20 one. Future gate runs should budget accordingly
or use `--limit N` for cheaper rehearsals.

## Recommendations

Three real paths forward (separate scope from this PR):

1. **Close out the classifier rollout for the enrolled metric set.** The
   data says the classifier is redundant with keyword on the 10 measured
   metrics. Don't flip `presence_classifier_enabled`. Document
   "non-additive on enrolled set" in the rollout plan and move on.

2. **Re-target the classifier at the 5 zero-coverage Tier-1 metrics**
   (`cm_balance_by_cohort`, `cm_customers_period_end_by_tenure`,
   `cm_gross_margin_by_cohort`, `cm_new_customers_acquired`,
   `cm_transactions_by_cohort`). Their keyword baseline is unknown but
   likely lower — that's where the classifier has the most potential
   headroom. Requires authoring prompt YAMLs for the 5 metrics + expanding
   gold coverage on them.

3. **Expand gold coverage on the 5 zero-coverage metrics first**, then
   re-gate. If the keyword baseline turns out to be 100% on those too,
   the classifier has no headroom anywhere and option 1 is the only
   path. If the baseline is lower, option 2 becomes viable.

The decision between 1, 2, and 3 is a CMASB-priority + budget call, not a
code call. This PR ships the gate v2 + the answer it produced; the next
decision belongs to the operator.

## Bugs surfaced (now fixed in this PR)

| | Description | Status |
|---|---|---|
| gh-602 | URL dedup missed cross-corpus filing_id duplicates | Fixed — filing_id dedup added; 4 dups dropped |
| gh-613 | `total_calls`, `cache_reads`, `total_usd` all zero | Fixed — real token aggregation + canonical cost helper |
| (new, caught mid-PR) | C6 divided cache_read tokens by call count, producing 545,704% hit rate | Fixed — C6 now computes `cache_reads / (cache_reads + input_tokens)` |
| (new, caught post-run) | `summary.selected_gold_filings` + `selected_reviewed_filings` lists were populated pre-dedup; the same file showed 56 selected but `per_metric.n` reflected 52 | Fixed — selected lists are now derived from the post-dedup enriched corpus; a new `summary.dedup_dropped` field captures the dropped filings for audit |

## Run history

This entry corresponds to the second row in the
[runbook's run history table](../operations/llm-presence-classifier-phase2-quantitative-eval-runbook.md#run-history).
