# Phase-2 quantitative gate results — 2026-05-11

**Run ID**: `20260511T1416live`
**Decision**: `NO-GO` (criterion C3 failed)
**Caveat-adjusted reading**: classifier ≈ keyword; structural gate infeasibility, not classifier failure

## TL;DR

The Phase-2 gate ran cleanly to completion across 55 filings (8 gold + 47 reviewed) at $13.75 of API spend over ~11.5 hours wall clock. The classifier hit `NO-GO` not because it underperformed but because **classifier recall and keyword recall are tied to 3 decimal places (0.988 / 0.988) on the scoreable Tier-1 metrics, and C3 required a 5pt improvement that is mathematically unreachable from a 98.8% baseline.**

The interesting question — whether the classifier helps on the 5 Tier-1 metrics with weak keyword baseline — was **unanswered**. Those metrics had insufficient coverage in this corpus and were skipped by the gate.

## Run parameters

| | |
|---|---|
| Script | `scripts/run_phase2_quantitative_eval.py` |
| Branch | `claude/fix-reviewed-corpus-column-name` (PR #600, two follow-up fixes applied: `companies.company_name` SQL + 4-tuple unpack) |
| Corpus | 8 gold (test + calibration splits) + 47 reviewed (top-density text-source decisions, capped at 50 raw) |
| Total filings processed | 55 (5 duplicates included — see Caveats) |
| Classifier model | Haiku 4.5 (no Sonnet fallback triggered) |
| Concurrency | 8 (eval-only) |
| Wall clock | ~11.5 hours (10:18 → 21:49 UTC) |
| Cost (count estimate) | $13.75 ($0.25 × 55) — not real spend; see C6 bug below |
| Total classify_segment calls | 550 |
| Errors (parse + classification) | 0 of 550 calls |

## Hard criteria

| ID | Criterion | Result | Detail |
|---|---|---|---|
| C1 | Zero prompt/parse errors | ✅ PASS | 0 errors |
| C2 | Per-Tier-1 clf recall ≥ kw − 5pt | ✅ PASS | 0 breaches (5 metrics skipped) |
| C3 | Aggregate Tier-1 clf recall ≥ kw + 5pt | ❌ FAIL | clf=0.988 kw=0.988 delta=+0.000 |
| C4 | No Tier-1 metric F1 < 0.40 | ✅ PASS | 0 breaches (5 skipped) |
| C5 | Error rate ≤ 0.5% | ✅ PASS | 0/550 = 0.000% |

## Informational criteria

| ID | Criterion | Result | Detail |
|---|---|---|---|
| C6 | Cache hit rate ≥ 85% | ❌ FAIL | 0/550 = 0.0% — **counter aggregation bug** (see Caveats) |
| C7 | Total cost ≤ $25 | ✅ PASS | $13.75 vs $25 budget |

## Per-metric breakdown (merged corpus)

| Metric | n | kw_recall | clf_recall | clf_precision | clf_F1 |
|---|---|---|---|---|---|
| cm_revenue_concentration | 37 | 1.000 | **1.000** | 0.794 | 0.885 |
| cm_net_revenue_retention | 20 | 1.000 | **1.000** | 0.722 | 0.839 |
| cm_revenue_by_cohort | 18 | 1.000 | **1.000** | 0.667 | 0.800 |
| cm_customer_retention_rate | 18 | 1.000 | **1.000** | 0.571 | 0.727 |
| cm_large_customers_period_end | 16 | 0.857 | **0.857** | 0.500 | 0.632 |
| cm_customer_acquisition_cost | 14 | 1.000 | **1.000** | 0.375 | 0.546 |
| cm_lifetime_value_per_customer | 11 | 1.000 | **1.000** | 0.500 | 0.667 |
| cm_gross_revenue_retention | 11 | 1.000 | **1.000** | 1.000 | 1.000 |
| cm_ltv_to_cac_ratio | 11 | 1.000 | **1.000** | 1.000 | 1.000 |
| cm_ltv_to_cac_ratio_by_cohort | 10 | 1.000 | **1.000** | 1.000 | 1.000 |

### Tier-1 metrics skipped (insufficient coverage)

These 5 Tier-1 metrics had < `MIN_FILINGS_FOR_METRIC_GATE` (5) of coverage in the corpus and were not scored:

- `cm_balance_by_cohort`
- `cm_customers_period_end_by_tenure`
- `cm_gross_margin_by_cohort`
- `cm_new_customers_acquired`
- `cm_transactions_by_cohort`

These are the metrics where the keyword baseline is *weakest* (niche disclosure language with low keyword catchment). They are also the metrics where a paraphrase-recall classifier could plausibly add the most value. **The gate run did not measure classifier performance on this subset.**

## Findings

### 1. Classifier recall == keyword recall on every scored metric

Tied to 3 decimals on 9 of 10 metrics; tied at 0.857 on `cm_large_customers_period_end`. The classifier neither catches a positive the keyword missed nor misses a positive the keyword caught, across the entire scoreable Tier-1 set.

This is the core finding. The paraphrase-recall path is finding the same set of positive (filing, metric) pairs as the keyword shortlist — at the (filing, metric) level of aggregation that the gate scores. At the segment level the classifier returns many additional positives, but those segments live on filings where the keyword path already triggered.

### 2. Classifier precision is materially lower than keyword on 6 of 10 metrics

Because classifier recall is at ceiling (1.000 on 9 of 10) and gold negatives are biased high, the classifier's *additional* "present" predictions are interpreted as false positives. This produces an F1 differential favoring keyword on metrics where keyword is already at recall=1.0:

- `cm_customer_acquisition_cost`: clf precision 0.375 vs implied kw precision near 1.0
- `cm_customer_retention_rate`: clf precision 0.571
- `cm_large_customers_period_end`: clf precision 0.500
- `cm_lifetime_value_per_customer`: clf precision 0.500
- `cm_net_revenue_retention`: clf precision 0.722
- `cm_revenue_by_cohort`: clf precision 0.667

The gold-negative caveat (positives not in gold are weakly-true negatives) inflates the apparent FP count. With a fully-labeled corpus, true classifier precision would be higher. But even after that correction, classifier appears to be over-predicting compared to keyword shortlist.

### 3. C3 was structurally unreachable

The gate's C3 criterion required `clf_recall ≥ kw_recall + 0.050`. The merged-corpus aggregate keyword recall was 0.988, leaving a maximum possible classifier delta of +0.012. The 5pt threshold is unachievable from this baseline irrespective of classifier quality.

This is a gate-design issue, not a classifier issue. C3's intent — "classifier must improve aggregate recall by a meaningful margin" — only works when the keyword baseline has measurable headroom. On the Tier-1 metrics with enrolled prompts, keyword baseline has effectively no headroom.

### 4. The interesting question wasn't asked

If the value proposition of the classifier is "catch metrics that keyword regex misses entirely," that hypothesis can only be tested on metrics where keyword catchment is < 100%. Those are precisely the 5 Tier-1 metrics this corpus could not score.

## Caveats

### Cache hit rate counter bug (C6)

The summary reports `total_calls: 0, cache_reads: 0`, hit rate 0.0%. Per-segment logs throughout the run consistently showed hit rates of 95–100% on the Anthropic prompt cache. The Phase-2 aggregator is not reading the cache stats from Phase-1's `evaluate_filing_pipeline` 4th return value (`_fil_tokens`) — the inline fix in PR #600 captured the tuple but discarded it. C6's "FAIL" is bogus; do not interpret as a real cache issue. **Cost was also count-estimated, not summed from real token usage** — actual spend is likely materially below $13.75 given the cache hit rate.

To fix: roll `_fil_tokens` (containing `input_tokens`, `output_tokens`, `cache_read`, `cache_create`) into a running total in `run_eval`, and populate `summary.cost` from the totals. Same pattern as Phase-1 gh-554 (PR #586).

### Dup-by-URL gap (gh-602)

5 filings were processed twice within the corpus because dedup is URL-based, not filing-id-based:

| Filing | Type | Slots |
|---|---|---|
| Tenable Holdings (1550) | within-gold | 4 + 5 |
| Datadog (1539) | gold↔reviewed | 1 + 18 |
| Chewy (1146) | gold↔reviewed | 6 + 17 |
| Kingsoft Cloud (1543) | gold↔reviewed | 8 + 33 |
| Maplebear (1544) | gold↔reviewed | 2 + 49 |

Effect on results: the duplicated filings contribute 2 rows per (filing, metric) to the rollup instead of 1, double-weighting them in `compute_aggregates`. With classifier ≈ keyword across all 5 duplicates, this does NOT change the headline conclusion — the duplication amplifies the tie rather than skewing it in either direction. Fix tracked in gh-602.

### Section_classification gap (new known-issue — gh-N)

6 of 55 filings (≈11%) returned 0 paraphrase segments because section_classification detected no whitelisted sections (MDA, Business, Risk Factors). The gh-574 ingestion fix caught the Datadog-style heading shape but missed at least one other variant.

Affected filings: **209382, 215071, 833, 10273, 192171, 207445**.

Impact on this run: limited. These filings contributed only keyword-baseline signal (paraphrase path inert), so they push classifier and keyword toward the same scores. Without a paraphrase pass, however, they cannot show classifier-only positives — they're effectively excluded from the "does the classifier add value" question, in the same direction as the 5 skipped metrics.

### Gold-negative bias

`golden_set_260408.csv` is incomplete by construction. Per-metric precision against gold is biased high (gold-set absence does not mean labeled absent). The classifier's apparent false positives include a substantial fraction of true positives not labeled in gold. Real classifier precision is higher than the table suggests — but this does not change the recall comparison, which is the gate-relevant metric.

## Decision options

Three paths forward, ordered from cheapest to most informative.

### Option A — Declare classifier non-additive on the scoreable Tier-1 set; do not ship

Document the run results, retire the classifier code path or keep it shadowed behind the flag indefinitely. Pros: cheap, defensible from the data. Cons: leaves the "5 skipped metrics" question unanswered, abandons the rollout pipeline that's been built across PRs #524–#598.

### Option B — Expand corpus to cover the 5 skipped Tier-1 metrics, re-run

Build a targeted reviewed slice that *selects* for filings known to discuss `cm_balance_by_cohort`, `cm_customers_period_end_by_tenure`, `cm_gross_margin_by_cohort`, `cm_new_customers_acquired`, `cm_transactions_by_cohort`. Re-run the gate. Pros: actually answers the question of whether the classifier adds value on its strongest theoretical case. Cons: requires either manual curation (operator effort) or a smarter selector that knows which filings mention which metrics (more code). Estimated cost: another ~$5–25 of API spend.

### Option C — Ship as non-cost-bearing shadow; learn from production

Flip `presence_classifier_enabled` so the classifier runs and writes its outputs to DB, but extraction continues to consume the keyword baseline. Compare classifier-only vs reviewer decisions over several weeks of real traffic. Pros: tests on the long tail of real filings the gate cannot cover; classifier output is preserved for later threshold-tuning or rollout. Cons: real Anthropic spend on every extraction; classifier output stored but unused (operational complexity).

### Recommendation

**Option B is the highest-information move.** Until the 5-skipped-metrics question is answered, "the classifier doesn't help" is an incomplete conclusion — we know it doesn't help where it isn't needed, and we don't know whether it helps where it would matter. If Option B comes back with the same tied-recall result on those metrics, then Option A is the clean answer with full justification.

Option C is reasonable if the team prefers learning from real production data over investing more in corpus curation, but it has ongoing cost and the comparison-vs-reviewers loop needs separate tooling.

## Follow-ups

- **gh-600** (PR open): fix `companies.company_name` SQL + Phase-2 4-tuple unpack (the two latent reuse bugs surfaced by this run). Already in flight.
- **gh-602** (filed): dedup-by-filing-id in `_select_reviewed_corpus_phase2` to eliminate the 5 dups observed.
- **gh-612** (filed): section_classification variant gap. gh-574 fix didn't catch the heading-markup variant present in filings 209382, 215071, 833, 10273, 192171, 207445. ~11% of corpus affected.
- **gh-613** (filed): Phase-2 cache/cost counter not aggregating. `summary.cost.cache_reads` and `total_calls` always 0; need to roll `_fil_tokens` from `evaluate_filing_pipeline` into the running total. Same shape as gh-554 / PR #586 for Phase-1.

## Artifacts

- CSV: `data/eval/phase2_quantitative_20260511T1416live.csv` (~550 rows)
- Summary JSON: `data/eval/phase2_quantitative_20260511T1416live_summary.json`
- Run log: `/tmp/phase2-gate.log`

CSV and summary are operator-scratch (`data/eval/` is not git-tracked). Copy specific rows into this analysis or a follow-up before they're cleaned up.
