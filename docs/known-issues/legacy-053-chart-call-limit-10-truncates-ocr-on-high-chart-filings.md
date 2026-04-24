---
autonomy: skip
discovered: '2026-04-21'
estimated: M
id: 53
note: 'Chart call limit; needs data-driven tuning. Post-#86 chart-presence pivot
  (2026-04-23), truncation affects presence coverage only (missed detected_metrics
  signals) — no per-value correctness impact because the pipeline no longer emits
  per-value chart facts.'
severity: low
slug: chart-call-limit-10-truncates-ocr-on-high-chart-filings
source: legacy
status: open
title: Chart Call Limit (10) Truncates OCR on High-Chart Filings
touches: []
updated: '2026-04-23'
---

### Problem

`OCRExtractionStage` enforces a hard cap on per-filing chart OCR calls. During the Chewy smoke (`logs/issue_35_prod_smoke3.log`), only 10 of 20 queued chart/table images were OCR'd before:

```
WARNING:src.extraction_v2.stages.ocr_extraction:Chart call limit (10) reached
```

Filings with lots of charts (Chewy has 16 chart-classified images; Snowflake has 8; on-average-larger S-1s exceed 10 easily) silently lose extraction coverage on the trailing images. The skipped images never get queried, so any Tier 1 cohort/NRR chart in positions 11+ is invisible to the bridge regardless of whether the OCR would have succeeded.

### Next Steps

- Locate the limit in `src/extraction_v2/stages/ocr_extraction.py` (likely a module-level constant or `PipelineConfig` field) and either raise the default, convert to a per-filing override, or expose via CLI flag on `batch_v2_extraction.py`.
- Re-run the Chewy smoke with the cap raised to quantify the missed-recall impact.
- Consider prioritization: OCR charts in likely-Tier-1 sections first (MDA, financials) rather than HTML order.
