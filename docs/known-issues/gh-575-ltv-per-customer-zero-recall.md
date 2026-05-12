---
id: 575
source: gh
slug: ltv-per-customer-zero-recall
title: "Phase-1 eval: cm_lifetime_value_per_customer 0 recall on gold corpus"
status: resolved
severity: medium
autonomy: n/a
estimated: —
touches:
  - config/llm_classifier/prompts/cm_lifetime_value_per_customer.yaml
  - config/llm_classifier/thresholds.yaml
discovered: 2026-05-08
updated: 2026-05-08
gh_issue: 575
pr_refs:
  - 588
  - 614
note: prompt v0.2.0 broadens definition + positive_signals to cover chart-caption "lifetime value chart" / "LTV at each year of tenure" variant; adds two hand-authored few-shots; smoke-eval re-run pending
---

### Problem

Phase-1 smoke eval (run_id `20260508T1743`) shows `cm_lifetime_value_per_customer` with precision=0.00, recall=0.00, F1=0.00 across all 5 gold filings. The classifier never predicts `present=true` despite at least one gold positive in the corpus.

This is a Tier-1 metric per `CLAUDE.md`. While the catastrophic-regression smoke gate passed (likely because keyword baseline is also poor and n=5 is too small to count), 0 recall on a Tier-1 metric is unacceptable for the quantitative gate that follows.

The cohort-revenue fix (PR #568) provides a working template — `cm_revenue_by_cohort` was at F1=0.0, then jumped to F1=0.57 after a 2-bucket form definition + hand-authored few-shot. Datadog's section_classification gap (gh-574) may compound this if any LTV-per-customer gold positive sits in Datadog's MD&A.

### Next Steps

- Pull gold-positive segments for `cm_lifetime_value_per_customer` from `data/gold_standard/` and inspect their language.
- Read the current prompt YAML; check whether positive_signal covers the variants observed.
- Add a hand-authored few-shot covering the missed variant (sidecar examples file pattern, deduped by text per PR #568's merge contract in `presence_classifier_client.py::load_metric_prompt`).
- Optional: re-mine few-shots, re-sweep threshold, bump `prompt_version`.
- Re-run smoke eval; target F1 >= 0.5 on gold.

### Resolution

Fixed by PR #588 (merged 2026-05-09). Prompt `cm_lifetime_value_per_customer.yaml` bumped to `prompt_version: 0.2.0` — broadened definition and `positive_signals` to cover chart-caption variants ("lifetime value chart", "LTV at each year of tenure", "cumulative LTV by cohort year"); two hand-authored few-shot examples added. Smoke-eval re-run not yet executed against post-fix prompt; gold-corpus recall verification pending.

Bookkeeping closed by PR #614.
