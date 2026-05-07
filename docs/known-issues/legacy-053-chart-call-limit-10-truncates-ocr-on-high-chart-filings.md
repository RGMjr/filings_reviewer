---
autonomy: skip
discovered: '2026-04-21'
estimated: M
id: 53
note: Original count cap superseded by dollar budget in PR #131 (2026-04-22). Residual presence-truncation concern declared obsolete (2026-05-07) — non-Tier-1 chart presence signals are not load-bearing post-#86 pivot, and Tier-1 charts bypass the budget entirely. Closing without measurement.
pr_refs:
  - 131
severity: low
slug: chart-call-limit-10-truncates-ocr-on-high-chart-filings
source: legacy
status: resolved
title: Chart OCR dollar budget may truncate non-Tier-1 presence signals on high-chart filings
touches: []
updated: '2026-05-07'
---

### Original problem (2026-04-21)

`OCRExtractionStage` enforced a hard count cap (`MAX_CHART_CALLS_PER_DOCUMENT=10`) on per-filing chart OCR calls. During the Chewy smoke (`logs/issue_35_prod_smoke3.log`), only 10 of 20 queued chart/table images were OCR'd before logging `Chart call limit (10) reached`. Filings with >10 charts silently lost trailing-image coverage.

### Superseded by Wave A3 (PR #131, commit `7b02584`, 2026-04-22)

The count cap was replaced by a per-filing dollar budget (`DEFAULT_CHART_BUDGET_PER_FILING_USD=0.25`) in `src/extraction_v2/stages/ocr_extraction.py:113`. Tier-1 charts bypass the budget entirely; non-Tier-1 charts share the dollar pool. The `Chart call limit (10) reached` warning is no longer emitted.

### Residual concern (post-#86 chart-presence pivot)

Post-pivot (2026-04-23, #86), the pipeline no longer emits per-value chart facts — chart processing is purely a presence signal. The dollar budget can still truncate trailing non-Tier-1 charts on filings with many charts, which translates to **missed `detected_metrics` presence signals** rather than missed values. Whether this matters depends on how many high-chart filings have Tier-1-relevant non-Tier-1 metric coverage in positions past the budget.

### Next steps

- Quantify on a high-chart filing (Chewy / Snowflake / Robinhood S-1) how many non-Tier-1 charts the dollar budget skips.
- If the missed presence signal is non-trivial, raise `DEFAULT_CHART_BUDGET_PER_FILING_USD` or prioritize charts in likely-Tier-2-relevant sections (MDA, financials) first within the non-Tier-1 pool.
- See also legacy-097 (residual chart facts after presence pivot) — same code area, same pivot context.
