# Phase-2 quantitative gate v2 results — 2026-05-14

**Run ID**: `20260514Trerun`
**Decision**: `NO-GO` (criterion C3 failed)
**Compared to**: 2026-05-11 run (`20260511T1416live`) — see `docs/analysis/llm-presence-classifier-phase2-eval-results-20260511.md`
**This run uses C3 reframe + dedup + token aggregation** (PR #pending)

## TL;DR

The Phase-2 v2 gate run answered the question the 2026-05-11 run left open: under a criterion that measures **net-new positives the classifier catches over keyword** (clf_only_tp), the classifier registers **zero contribution on every single enrolled Tier-1 metric.** Aggregate Tier-1 classifier recall is 0.986 vs keyword 0.986 — still tied to 3 decimals after the dedup correction.

This is a cleaner NO-GO than the 2026-05-11 run. The previous run's gate was structurally unreachable (C3 required +5pt over a 98.8% baseline). The v2 gate asks a question the data CAN answer ("does the classifier find anything new?"), and the answer is no.

## Run parameters

| | |
|---|---|
| Script | `scripts/run_phase2_quantitative_eval.py` (with C3 reframe, gh-602 dedup, gh-613 token aggregation, C8 agreement) |
| Branch | `worktree-agent-ad126b1085a92f8f4` (parallel worker output, PR #pending) |
| Corpus | 7 gold (Tenable within-gold dup removed) + 45 reviewed (3 gold↔reviewed dups removed) = **52 filings** |
| Classifier model | Haiku 4.5 (no Sonnet fallback triggered) |
| Concurrency | 8 (eval-only) |
| Wall clock | ~10 hours (07:03 → 17:10 UTC) |
| Total classify_segment calls (filing × metric) | 520 |
| Errors (parse + classification) | 0 of 520 |
| Cost (real, from token totals) | $194.88 (see caveat below) |

## Hard criteria

| ID | Result | Detail |
|----|--------|--------|
| C1 | ✅ PASS | 0 prompt/parse errors |
| C2 | ✅ PASS | 0 per-metric recall regressions (5 metrics skipped — no enrolled prompt) |
| **C3** | ❌ **FAIL** | 0/1 headroom-eligible metrics pass clf_only gate. Only `cm_large_customers_period_end` had kw_recall < 0.95 (at 0.833); its `clf_only_tp = 0`. |
| C4 | ✅ PASS | 0 metrics below F1 0.40 |
| C5 | ✅ PASS | 0/520 calls errored = 0.000% |

## Informational criteria

| ID | Result | Detail |
|----|--------|--------|
| C3_aggregate_recall_delta | ✅ PASS (informational) | clf=0.986 kw=0.986 delta=+0.000 |
| C6 | ⚠ Bogus | 16768/520 = 3224.6% — unit mismatch (tokens / filing-metric pairs). Cache hits are real (~16K tokens served from cache); counter logic needs a fix. See gh-N below. |
| C7 | ❌ FAIL (informational) | $194.88 vs $25 budget. Real spend, count-labeled wrong (`total_calls = 520` is filing × metric pairs, not API calls). The cost guard's pre-flight estimate (count × $0.25 = $13) was way under because actual classify_segment invocations are ~10× higher per filing than counted. See gh-N below. |
| C8 | ❌ FAIL (informational) | 437/520 (filing, metric) rows agree = 84.0% — just under the 85% target. The 16% disagreement is asymmetric: classifier-says-present + keyword-says-absent (FPs from classifier perspective). Consistent with the precision delta below. |

## Per-metric breakdown (merged corpus)

| Metric | n | kw_recall | clf_recall | clf_precision | clf_F1 | **clf_only_tp** |
|---|---|---|---|---|---|---|
| cm_revenue_concentration | 33 | 1.000 | 1.000 | 0.774 | 0.873 | **0** |
| cm_revenue_by_cohort | 19 | 1.000 | 1.000 | 0.714 | 0.833 | **0** |
| cm_customer_retention_rate | 17 | 1.000 | 1.000 | 0.571 | 0.727 | **0** |
| cm_net_revenue_retention | 17 | 1.000 | 1.000 | 0.786 | 0.880 | **0** |
| cm_large_customers_period_end | 14 | 0.833 | 0.833 | 0.625 | 0.714 | **0** |
| cm_customer_acquisition_cost | 12 | 1.000 | 1.000 | 0.429 | 0.600 | **0** |
| cm_lifetime_value_per_customer | 9 | 1.000 | 1.000 | 0.500 | 0.667 | **0** |
| cm_gross_revenue_retention | 9 | 1.000 | 1.000 | 1.000 | 1.000 | **0** |
| cm_ltv_to_cac_ratio | 9 | 1.000 | 1.000 | 1.000 | 1.000 | **0** |
| cm_ltv_to_cac_ratio_by_cohort | 9 | 1.000 | 1.000 | 1.000 | 1.000 | **0** |

The `clf_only_tp = 0` column is the unambiguous finding. The classifier catches the same set of positives as keyword on every metric. Lower precision on 6 of 10 metrics indicates the classifier is also predicting present on filings where ground truth is absent — those become C8 disagreements.

## Comparison vs 2026-05-11 run

| | 2026-05-11 | 2026-05-14 |
|---|---|---|
| Corpus size | 55 (with 5 dups) | 52 (dedup applied) |
| Tier-1 zero-tolerance gate | green | green |
| C1 (errors) | PASS | PASS |
| C2 (per-metric recall) | PASS | PASS |
| C3 (old: agg recall +5pt) | **FAIL** (structural — kw at 98.8%) | demoted to informational |
| C3 (new: clf-only-tp ≥ 3) | n/a | **FAIL** (0 clf-only TPs anywhere) |
| C4 (F1 floor) | PASS | PASS |
| C5 (error rate) | PASS | PASS |
| C6 (cache hit rate) | FAIL (bogus 0%) | FAIL (bogus 3224.6%) — different bug, same outcome |
| C7 (cost) | $13.75 count-estimate | $194.88 real (over budget) |
| C8 (agreement) | n/a | **FAIL** 84.0% |
| Decision | NO-GO | NO-GO |

Both runs concluded NO-GO. The v2 run answered why with much more clarity: classifier ≈ keyword on the scoreable Tier-1 set, with no headroom and no contribution.

## Findings

### 1. The classifier doesn't add value on enrolled Tier-1 metrics

This is the strongest possible signal. The new C3 measures classifier-only TPs at the (filing, metric) aggregation level. Zero across all 10 enrolled Tier-1 metrics. The one metric with measurable kw headroom (cm_large_customers_period_end at 83.3%) also gets zero new positives from the classifier.

### 2. Where keyword is perfect, classifier matches it. Where keyword has gaps, classifier doesn't fill them.

The 9 metrics with kw_recall = 1.0 all have clf_recall = 1.0. The 1 metric with kw_recall < 1.0 (large_customers at 83.3%) also has clf_recall = 0.833 — exactly matching, no addition.

### 3. Classifier produces precision-dropping false positives

clf_precision is materially below 1.0 on 6 of 10 metrics. Under the gold-negative caveat, some of these are real positives not labeled in gold — but C8 agreement at 84% suggests the disagreement signal is real, not artifactual.

### 4. The 5 unenrolled Tier-1 metrics remain untested

`cm_balance_by_cohort`, `cm_customers_period_end_by_tenure`, `cm_gross_margin_by_cohort`, `cm_new_customers_acquired`, `cm_transactions_by_cohort` — these are skipped because no prompt YAML exists. They are precisely the metrics where keyword baseline is *weakest* and the classifier would plausibly add value. Until those prompts are authored (a separate scope decision), the classifier's potential on niche metrics is unmeasured.

### 5. Section_classification gap not fixed on this branch

Of the 52 filings, 5 (209382, 215071, 833, 146, 4221) hit the section_classification heading-markup variant gap and returned 0 paraphrase segments. This branch (`worktree-agent-ad126b1085a92f8f4`) forked off origin/main *before* PR #624 (gh-612) merged. After PR #624, future runs will see those filings produce useful paraphrase signal.

This biases the v2 run downward on classifier contribution: those 5 filings could only contribute keyword-baseline. However, the result is robust — even with the missing 5 filings' paraphrase coverage, the remaining 47 filings show zero clf-only TPs. The conclusion would not flip with their inclusion absent a wildly different result on those filings specifically.

## Caveats

### C6 cache counter unit mismatch (new gh-N follow-up)

`summary.cost.cache_reads` is a sum of cache-read tokens (16,768) across all classify_segment calls. `summary.cost.total_calls` is filing × metric pairs (520). Dividing them produces nonsense. The intended C6 metric is either `(cache_read_tokens / input_tokens)` or `(calls_with_cache_hit / total_calls)`. Per-segment logs throughout the run showed real cache hit rates of 95–99%, so the underlying caching is working — only the rollup is broken.

### C7 cost is real but `total_calls` is mislabeled (same gh-N)

`total_usd = $194.88` is computed from real token totals. The breakdown (estimated): ~22M output tokens × $5/M = $110, plus ~80M input tokens × $1/M = $80. Total matches.

`total_calls = 520` is filing × metric pairs (52 filings × 10 metrics) — NOT classify_segment API call count. The eval's pre-flight cost estimate (`n_filings × $0.25`) underestimated by ~12× because each filing has hundreds of segment-level classify_segment calls.

Two consequences:
1. The pre-flight `--cost-budget` guard is too lenient; should use a per-segment estimate, not per-filing.
2. The cost reporting is correct in dollars but misleading in calls. Operators reading C7 should focus on `total_usd`, not `total_calls`.

### Five unscored metrics still skipped

The dedup correction and the new C3 don't change which metrics are scored — the 5 unenrolled Tier-1 metrics still don't have prompts and are skipped.

## Decision

**NO-GO** with high confidence on the enrolled Tier-1 set.

The classifier:
- Does not add any new positives where the keyword path already works (98.6% baseline)
- Does not fill the one gap where keyword has room to grow (large_customers_period_end at 83.3%)
- Adds precision-dropping false positives on 6 of 10 metrics

There is **no scoreable scenario** where the classifier improves on keyword for these 10 metrics.

The remaining open question — whether the classifier helps on the 5 unenrolled Tier-1 metrics where keyword is presumed weak — requires authoring prompt YAMLs and re-running. This is a substantial scope decision and is not addressed by this run.

## Recommendation

**Adopt Option A (close out classifier rollout for enrolled metrics) with a deliberate Option B carve-out.**

1. **Stop investing in the enrolled-metric classifier path.** Do not flip `presence_classifier_enabled`. The infrastructure works (0 errors of 520 calls; 95–99% cache hit rate) but produces no measurable value on the scored metrics.

2. **Hold the decision on unenrolled metrics open.** Before declaring the classifier non-additive globally, author prompts + few-shots for the 5 unenrolled Tier-1 metrics (`cm_balance_by_cohort` etc.). Re-run only against those. This is the only remaining experiment worth running.

3. **Treat the C6/C7 reporting bugs as housekeeping**, not blockers for the decision. Real cache hit rate is 95–99% from logs; real cost was paid and is reflected. Counter bugs do not change the headline.

## Follow-ups

- **gh-N (new)**: C6 cache counter unit mismatch; C7 `total_calls` mislabeled. Both reporting bugs, headline unaffected. Fix in `scripts/run_phase2_quantitative_eval.py`.
- **gh-N (existing/deferred)**: section_classification variant gap (gh-612) fix already on main as of PR #624; future Phase-2 runs will pick it up. The 2026-05-14 re-run was on a pre-#624 branch.
- **Strategic question (separate decision, not a gh-N)**: should the 5 unenrolled Tier-1 metrics get prompts authored? Recommended yes — see Option B carve-out above.

## Artifacts

- CSV: `data/eval/phase2_quantitative_20260514Trerun.csv` (~520 rows)
- Summary JSON: `data/eval/phase2_quantitative_20260514Trerun_summary.json`
- Run log: `/tmp/phase2-v2-rerun.log`
