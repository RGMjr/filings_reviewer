---
id: 654
source: gh
slug: customers-period-end-total-accounts-overmatch
title: cm_customers_period_end keyword '\btotal\s+accounts?\b' over-matches 'Total accounts receivable'
status: open
severity: medium
autonomy: skip
estimated: M
touches:
  - config/metric_keywords.yaml
  - src/extraction_v2/stages/candidate_generation.py
  - src/extraction_v2/stages/value_binding.py
discovered: '2026-05-21'
updated: '2026-05-22'
gh_issue: 654
note: over-broad count keyword emits AR-stub candidates; value-binding guard suppresses stub-matching rows ONLY — 2026-05-22 cleanup found residual FPs the guard misses AND over-suppression of human-vetted values
---

### Problem

The candidate-generation pattern `\btotal\s+accounts?\b` for `cm_customers_period_end` matches the substring "Total accounts" inside financial-statement stub labels like "Total accounts receivable", generating spurious customer-count candidates. The value-binding financial-line-item count-row guard (`_is_financial_line_item_count_row` in `src/extraction_v2/stages/value_binding.py`) suppresses these **only when the row stub matches `_FINANCIAL_LINE_ITEM_STUB_RE`** — the over-broad keyword still produces wasted candidates and relies entirely on downstream filtering.

### Next Steps

- Add a defense-in-depth candidate-generation exclusion (e.g. `\baccounts?\s+receivables?\b` / financial-line-item terms) under `cm_customers_period_end`, OR tighten `\btotal\s+accounts?\b` to require a customer/subscriber context.
- Verify against the gold standard before shipping (Tier-1 metrics — regression-gated).

### Update — 2026-05-22 retroactive cleanup

The retroactive cleanup of pre-fix FP facts ran 2026-05-22 (deleted 4 `auto_accepted` FP facts on filing 1414 Oportun; rejected/accepted/corrected left intact — see `~/.claude/plans/retroactive-financial-row-fp-cleanup.md`). An in-memory re-extraction diff over all affected filings surfaced two failure modes the shipped guard does **not** resolve — correcting the earlier claim that "no FP facts are emitted":

- **(a) Residual FPs the guard misses (under-suppression).** Filing 1414 still has `cm_active_customers_total` = 695,697 and 699,650 (`auto_accepted`, present in `v_analytics_fact_wide`). The current code still produces them — their row stub does not match `_FINANCIAL_LINE_ITEM_STUB_RE`, so the guard leaves them. The financial-figure-as-count failure class is broader than the single "Total accounts receivable" stub, and affects `cm_active_customers_total` as well as `cm_customers_period_end`.
- **(b) Over-suppression of human-vetted values.** The diff found the guard now suppresses two values a reviewer had already actioned: an `accepted` `cm_active_customers_total` = "179 Million" (filing 3036, PayPal) and a `corrected` `cm_customers_period_end` = 243 (filing 1543, Kingsoft Cloud) — evidence the stub regex / row-classifier is slightly too broad in some layouts.

So the fix must catch the broader class in (a) **without** regressing the human-vetted values in (b). Consider a magnitude/plausibility signal (exact-to-the-unit counts in the 10^5–10^6 band sourced from financial-statement sections) as a secondary guard.

**Related (separate root cause):** 15 filings (Chewy / DoorDash / PayPal, 25 count facts) could not be assessed because their `filings.html_storage_path` is neither an R2 `filings/` key nor resolvable on disk, so they cannot be re-extracted/diffed — a storage-resolution gap, not a keyword issue. May warrant its own issue.
