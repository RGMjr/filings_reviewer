---
id: 654
source: gh
slug: customers-period-end-total-accounts-overmatch
title: cm_customers_period_end keyword '\btotal\s+accounts?\b' over-matches 'Total accounts receivable'
status: open
severity: low
autonomy: skip
estimated: —
touches:
  - config/metric_keywords.yaml
  - src/extraction_v2/stages/candidate_generation.py
discovered: '2026-05-21'
updated: '2026-05-21'
gh_issue: 654
note: over-broad count keyword still emits AR-stub candidates; value-binding guard suppresses them but a candidate-gen exclusion would be cleaner
---

### Problem

The candidate-generation pattern `\btotal\s+accounts?\b` for `cm_customers_period_end` matches the substring "Total accounts" inside financial-statement stub labels like "Total accounts receivable", generating spurious customer-count candidates. As of the value-binding financial-line-item count-row guard (`_is_financial_line_item_count_row` in `src/extraction_v2/stages/value_binding.py`), these are suppressed at bind time, so no FP facts are emitted — but the over-broad keyword still produces wasted candidates and relies entirely on downstream filtering.

### Next Steps

- Add a defense-in-depth candidate-generation exclusion (e.g. `\baccounts?\s+receivables?\b` / financial-line-item terms) under `cm_customers_period_end`, OR tighten `\btotal\s+accounts?\b` to require a customer/subscriber context.
- Verify against the gold standard before shipping (the value-binding guard already covers the observed FPs, so this is precision/efficiency, not recall).
