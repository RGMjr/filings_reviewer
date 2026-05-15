---
id: 631
source: gh
slug: option-b-unenrolled-tier1-classifier
title: "Option B carve-out: enroll 5 unenrolled Tier-1 metrics in LLM presence classifier (tracking only)"
status: open
severity: low
autonomy: skip
estimated: —
touches:
  - config/llm_classifier/prompts/
  - config/llm_classifier/thresholds.yaml
  - config/llm_classifier/recall_augmentation.yaml
discovered: 2026-05-15
updated: 2026-05-15
gh_issue: 631
note: "Tracking only — not active scope. 5 Tier-1 metrics (balance_by_cohort, customers_period_end_by_tenure, gross_margin_by_cohort, new_customers_acquired, transactions_by_cohort) skipped by Phase-2 runs because no prompt YAML; only legitimate future activation path for the dormant classifier infrastructure."
---

### Problem

The Phase-2 quantitative gate (2026-05-11 and 2026-05-14 runs) determined that the LLM presence classifier provides zero net-new positives over keyword on the 10 currently-enrolled Tier-1 metrics. Rollout closed per Option A on 2026-05-15 (see `docs/analysis/llm-presence-classifier-rollout-closeout-20260515.md`).

5 additional Tier-1 metrics were skipped by both Phase-2 runs because no prompt YAML exists for them:

- `cm_balance_by_cohort`
- `cm_customers_period_end_by_tenure`
- `cm_gross_margin_by_cohort`
- `cm_new_customers_acquired`
- `cm_transactions_by_cohort`

These are presumed-weak keyword catchment metrics — the only remaining scenario where the classifier might add measurable value. This issue tracks the carve-out for activating the classifier on them specifically, if pursued.

### Next Steps (activation path, not active scope)

- Audit current keyword catchment on the 5 metrics against gold + reviewed corpora. If > 90%, close this scope.
- Otherwise: author prompt YAMLs, mine few-shots, sweep thresholds, build a targeted reviewed-corpus selector that picks filings known to discuss these metrics, re-run Phase-2 v2 against the targeted slice.
- A separate decision is needed about whether to enable the classifier for only these 5 metrics (would require metric-gated classifier flag — separate infra).
