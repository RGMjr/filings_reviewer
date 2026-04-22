---
autonomy: skip
discovered: '2026-04-21'
estimated: S
id: 55
note: Data cleanup; needs inspection of stuck filings
severity: low
slug: 28-stuck-8-k-filings-in-class-e-from-form-filter-bypass
source: legacy
status: open
title: 28 Stuck 8-K Filings in Class (E) from Form-Filter Bypass
touches: []
updated: '2026-04-21'
---

### Problem

Of the 38 filings in `scripts/diagnostic_chart_evidence_coverage.py` Class (E) on Neon prod, **28 are 8-K filings** in `processing_status='processing'` with `html_storage_path IS NULL` and `html_content IS NULL`. The extraction system is designed for S-1/F-1 (see `DEFAULT_FORM_TYPES_S1F1` in `src/universe/universe_builder.py`), yet these 8-Ks reached ingestion far enough to have `v2_image_assets` chart-classified rows written, then stalled. This suggests a form-filter bypass somewhere in the ingestion path — possibly an early-path onboarding script, possibly a reviewer action, possibly a daily-cron edge case.

Seven of the 28 additionally have 2–3 reviewer decisions each on text/table facts, which is even more puzzling for an allegedly out-of-scope form type.

Filing ids captured in `data/audit/issue_35_prod_class_e_raw.txt` and the original target/exclusion lists.

### Next Steps

- Trace how these 8-K filings entered the pipeline: `git log` the ingestion path around the 2026-04-xx window, `grep` for any codepath that calls `FilingFetcher` or `V2Pipeline.process` without a form-type gate.
- Decide cleanup strategy: (a) retroactively delete the `filings` + `v2_image_assets` + `v2_metric_facts` rows for these 28 ids; or (b) reclassify to `processing_status='out_of_scope'` and update the Class (E) diagnostic to filter on `form_type IN ('S-1','S-1/A','F-1','F-1/A')`.
- If reviewer decisions on 8-Ks are intentional (user-directed review for some reason), skip the deletion option and go with (b).
