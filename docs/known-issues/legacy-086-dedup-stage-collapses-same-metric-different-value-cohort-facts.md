---
autonomy: review
discovered: '2026-04-22'
estimated: M
id: 86
note: 'Dissolved by the chart-presence pivot (PRs #147/#150/#151/#154, 2026-04-23).
  Chart pipeline no longer emits per-value facts, so the dedup identity-key collapse
  root cause no longer exists. Residual chart facts drain in PR 4b.'
severity: medium
slug: dedup-stage-collapses-same-metric-different-value-cohort-facts
source: legacy
status: resolved
title: Dedup Stage Collapses Same-Metric Different-Value Cohort Facts
touches:
  - src/extraction_v2/stages/deduplication.py
updated: '2026-04-23'
---

### Problem

On HOOD's S-1, the Annual Revenue by Annual Cohort chart produces candidate per-cohort bar values pre-dedup — gold-standard values $17, $62, $44, $56, $87, $45, $130, $186, $175 all appear in the pre-dedup candidate set — but only one ($87) survives to the persisted fact set. Running `python3 -m src.gold_standard.v2_validator --companies "Robinhood Markets, Inc." --fn-diagnostics` after the 2026-04-22 HOOD backfill (#72, #77) classifies all 9 missing cohort values as `DEDUP_COLLISION` with the diagnostic:

> *"Value-matching fact (17.0) existed pre-dedup but was collapsed into a sibling with different value; 1 match(es) pre-dedup, 2 total post-dedup"*

Same pattern repeats for 62.0, 45.0, 130.0, 186.0, 56.0, 175.0, 326.0 (eight more). The same failure mode also produces HOOD's pre-existing `cm_customer_acquisition_cost` FN (expected $20, collapsed into a sibling).

### Impact

| Metric | Tier | Current P/R/F1 (post-#72 backfill) | Gap vs. perfect |
|---|---|---|---|
| `cm_revenue_by_cohort` | T1 | 50% / 10% / 16.7% | 9 cohort FNs (all `dedup_collision`) |
| `cm_customer_acquisition_cost` | T1 | 100% / 50% / 66.7% | 1 FN (dedup collision on value 20) |

HOOD's overall Tier 1 F1 is 68.6% post-backfill; closing this gap could push it well above 80%. Not a Tier 1 blocker on its own (HOOD T1 recall is already above the pre-scrub 0.3143 baseline thanks to `cm_balance_by_cohort` at 100/100/100), but it's the single biggest remaining per-metric recall gain available without new extractor work.

### Candidate root causes (not yet narrowed)

1. **Post-transfer collision collapse merges too aggressively.** The validator run logged `Post-transfer collision collapse: merged 18 colliding primaries` then `Fuzzy period dedup: removed 4 duplicate-value facts (68 → 28)`. The first step is the suspect — collapsing facts that share `(canonical_metric_id, period, source_type)` but differ in `value` is exactly what's happening here. A cohort chart legitimately has N distinct bars for the same `canonical_metric_id` and effectively no period (period is the cohort dimension, encoded in `cohort_def` / `cohort_type`, not `period_start`/`period_end`).
2. **Identity-key doesn't include `cohort_def`/`cohort_type`.** If the dedup identity key skips those cohort-specific columns for chart-sourced facts, every bar value collapses into one.
3. **`source_locator.img_id` isn't part of the identity either.** Even if two facts came from different bars of the same image, distinctness on img_id + bar position is probably what uniquely identifies a cohort bar.

### Next Steps

1. Read `src/extraction_v2/stages/deduplication.py` and identify which columns form the identity key for the "post-transfer collision collapse" step. Confirm whether chart-sourced cohort facts are being merged on a key that excludes `value`, `cohort_def`, or the bar-position portion of `source_locator`.
2. Add a regression test in `tests/unit/extraction_v2/` that constructs 10 chart-sourced `cm_revenue_by_cohort` facts with identical `canonical_metric_id`/`source_type`/`period_*` and distinct `value`+`cohort_def`; assert all 10 survive the stage.
3. Fix: extend the dedup identity to include `cohort_def` (and/or the bar-position within `source_locator`) for chart-sourced cohort metrics. Should be a narrow change in `_collision_identity_key` or equivalent.
4. Re-run the HOOD validator; expect `cm_revenue_by_cohort` recall to jump from 10% toward 100% and `cm_customer_acquisition_cost` to move from 50% to 100%.
5. Refresh the v2 baseline once the gain is observed (still gated on Issue #78 / Chewy lxml regression per PR #102 body, if unresolved).

### Cross-references

- Issue #72 — HOOD Tier 1 regression (resolved 2026-04-22; this issue was the residual).
- Issue #77 — R2 chart-image bytes (resolved 2026-04-22; unrelated root cause).
- Issue #14 — Farfetch LTV/CAC dedup collision on layout-table misclassification (different failure mode but related stage).
- Validator diagnostic output on HOOD post-backfill: `dedup_collision: 16 (89%)`.

### Resolution (2026-04-23)

Dissolved by the chart-presence pivot — see parent plan `~/.claude/plans/pick-up-issue-86-tranquil-piglet.md`. Under the new model, `ChartFactBridgeStage` no longer emits per-value `v2_metric_facts` rows; it writes `(metric_id, score)` presence records to `v2_image_assets.detected_metrics`. Reviewers confirm per-metric coverage via `v2_image_metric_confirmations` (accept / reject / correct / add). Because the chart pipeline no longer produces same-identity different-value groups, the `post-transfer collision collapse` step in `DeduplicationStage` can no longer collide chart-sourced cohort facts — the root cause is gone.

No code change was made to `src/extraction_v2/stages/deduplication.py`; the bug is structurally impossible post-pivot.

Shipped across four PRs:

- [PR #147](https://github.com/RGMjr/filings_reviewer/pull/147) — `ChartFactBridgeStage` rewrite (emit presence, not facts).
- [PR #150](https://github.com/RGMjr/filings_reviewer/pull/150) — Gold-standard validator: presence P/R/F1; `_derive_chart_native_metrics` drives the chart-vs-text split.
- [PR #151](https://github.com/RGMjr/filings_reviewer/pull/151) — `v2_image_metric_confirmations` schema + `GET /api/v2/metrics/list` + `POST /api/v2/image-metric-confirmations`.
- [PR #154](https://github.com/RGMjr/filings_reviewer/pull/154) — Reviewer UI: Detected metrics card + per-row A/R/C/Add + Playwright coverage.

The HOOD `cm_revenue_by_cohort` 9/10 FN pattern is expected to resolve: the 10 cohort bars now count as **one** presence TP rather than requiring 10 value-level TPs. Any historical `cm_revenue_by_cohort` chart facts persisted pre-pivot are drained in PR 4b.
