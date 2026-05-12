---
id: 602
source: gh
slug: phase2-dedup-by-filing-id-gap
title: "Phase-2 eval: dedup-by-URL misses same-filing-id duplicates (Tenable S-1 + S-1/A both processed as gold)"
status: open
severity: low
autonomy: skip
estimated: —
touches:
  - scripts/run_phase2_quantitative_eval.py
  - scripts/run_phase1_eval.py
  - data/gold_standard/split_v1.json
discovered: 2026-05-11
updated: 2026-05-11
gh_issue: 602
note: Phase-2 corpus selection dedups by filing_url; two gold URLs for one filing_id (e.g., Tenable S-1 + amendment) slip through and double-weight that filing in scoring rollups
---

### Problem

Observed during Phase-2 gate run `20260511T1416live`. Two distinct manifestations, both rooted in URL-based dedup:

1. **Within-gold**: filings 4/55 and 5/55 are both `Tenable Holdings, Inc. (gold)` and both resolve to `filing_id=1550`. The gold split file (`data/gold_standard/split_v1.json`) contains two distinct URLs for Tenable (likely S-1 + S-1/A amendment) that both point at the same `filings.filing_id` in the DB.

2. **Cross-corpus (gold → reviewed)**: filing 6/55 is `Chewy, Inc. (gold)` (filing_id=1146); filing 17/55 is `Chewy, Inc. (reviewed)` (filing_id=1146). The reviewed-corpus selector deduplicates against the gold URL set, but Chewy's gold URL format differs from `filings.sec_html_url` format (possibly trailing slash, fragment, query params, or casing) so the string match misses.

Impact: ~$0.25 wasted per duplicate, plus duplicated rows in the CSV that may double-weight the filing in per-metric R/P/F1 and aggregate Tier-1 recall comparison — depending on how `compute_aggregates` and the scoring rollups treat repeated (filing_id, metric) pairs.

### Next Steps

- Add `filing_id` dedup as a second pass after URL dedup in `_select_gold_corpus` / `_select_reviewed_corpus_phase2`. Keep the first occurrence (preserve deterministic order).
- Audit `split_v1.json` for other filing_id collisions across test + calibration splits.
- Verify Phase-2 scoring rollups handle filing-level duplication correctly — each (filing_id, metric) pair should contribute once.
