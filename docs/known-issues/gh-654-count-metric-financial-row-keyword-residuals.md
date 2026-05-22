---
id: 654
source: gh
slug: count-metric-financial-row-keyword-residuals
title: Count-metric keyword over-matches financial line-item rows ('Total accounts receivable')
status: open
severity: medium
autonomy: skip
estimated: M
touches:
  - config/metric_keywords.yaml
  - src/extraction_v2/stages/value_binding.py
discovered: '2026-05-22'
updated: '2026-05-22'
gh_issue: 654
note: keyword '\btotal\s+accounts?\b' over-matches 'Total accounts receivable'; PR #655 guard suppresses stub-matching rows only — residual FPs and over-suppression of human-vetted values both observed in 2026-05-22 retroactive cleanup
---

### Problem

The count-metric keyword `\btotal\s+accounts?\b` (for `cm_customers_period_end` / `cm_active_customers_total`) spuriously matches the substring "Total accounts" inside the financial-statement stub "Total accounts receivable". The value-binding row-scan then binds the row's dollar figures as customer counts.

**Forward fix shipped (PR #655):** `_is_financial_line_item_count_row` in `src/extraction_v2/stages/value_binding.py` (with `_FINANCIAL_LINE_ITEM_STUB_RE` / `_FINANCIAL_LINE_ITEM_STUB_ALLOW`), wired into the row-scan path and Strategy 5, scoped to `_COUNT_ONLY_METRICS`. The **retroactive data cleanup** of pre-fix FP facts was completed 2026-05-22 (deleted 4 `auto_accepted` FP facts on filing 1414 Oportun; rejected/accepted/corrected left intact — see `~/.claude/plans/retroactive-financial-row-fp-cleanup.md`).

That cleanup surfaced two residual failure modes the shipped guard does **not** resolve — both are this issue's remaining scope:

**(a) Residual FPs the guard misses (under-suppression).** Filing 1414 (Oportun) still has `cm_active_customers_total` = 695,697 and 699,650 (`auto_accepted`, present in `v_analytics_fact_wide`). A re-extraction diff confirmed the current code still produces them — their table-row stub does not match `_FINANCIAL_LINE_ITEM_STUB_RE`, so the guard leaves them. The financial-figure-as-count failure class is broader than the single "Total accounts receivable" stub.

**(b) Over-suppression of human-vetted values.** The same diff found the guard now suppresses two values a reviewer had already actioned: an `accepted` `cm_active_customers_total` = "179 Million" (filing 3036, PayPal) and a `corrected` `cm_customers_period_end` = 243 (filing 1543, Kingsoft Cloud). Evidence the stub regex / row-classifier may be slightly too broad in some layouts.

### Next Steps

- Tighten the candidate-generation keyword and/or the `_is_financial_line_item_count_row` classifier to (i) catch the broader financial-figure-as-count class behind residual (a) without (ii) regressing the human-vetted values in (b). Verify against gold standard before shipping (Tier-1 metrics — regression-gated).
- Consider a magnitude/plausibility signal for count metrics (exact-to-the-unit values in the 10^5–10^6 band sourced from financial-statement sections) as a secondary guard.

### Related (separate root cause — may warrant its own issue)

15 filings (Chewy / DoorDash / PayPal, 25 count facts total) could not be assessed in the 2026-05-22 cleanup because their `filings.html_storage_path` is neither an R2 `filings/` key nor resolvable on disk, so they cannot be re-extracted/diffed. Disposition of any FPs among them is blocked on an HTML re-fetch — a storage-resolution gap, not a keyword issue.
