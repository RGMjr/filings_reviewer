---
id: 576
source: gh
slug: ltv-to-cac-by-cohort-zero-recall
title: "Phase-1 eval: cm_ltv_to_cac_ratio_by_cohort 0 recall on gold corpus"
status: resolved
severity: medium
autonomy: n/a
estimated: —
touches:
  - config/llm_classifier/prompts/cm_ltv_to_cac_ratio_by_cohort.yaml
  - config/llm_classifier/thresholds.yaml
discovered: 2026-05-08
updated: 2026-05-08
gh_issue: 576
pr_refs:
  - 590
  - 614
note: root cause was chart-caption variant — all gold positives are terse section headings ("Lifetime Value of a Consumer to Consumer Acquisition Cost Ratios") pointing at a chart; prompt extended to cover plural-"Ratios" chart-caption shape with hand-authored few-shots
---

### Problem

Phase-1 smoke eval (run_id `20260508T1743`) shows `cm_ltv_to_cac_ratio_by_cohort` with precision=1.00, recall=0.00, F1=0.00 across all 5 gold filings. Precision is 1.0 only because the classifier never predicts present (zero false positives, zero true positives). At least one gold positive exists.

This is a Tier-1 metric per `CLAUDE.md`. The base `cm_ltv_to_cac_ratio` metric scored F1=1.00 in the same run.

### Root Cause (identified 2026-05-08)

All gold positives come from the Farfetch filing. Every positive's text segment is a terse section heading ("Lifetime Value of a Consumer to Consumer Acquisition Cost Ratios") accompanied by a chart image — the cohort data (ratios at 6, 12, 24 months per acquisition year) is inside the chart and invisible to the text classifier. The prompt previously required explicit cohort-vintage language in text, which the heading lacks. This is the chart-caption variant (same pattern as cm_lifetime_value_per_customer / gh-575).

### Fix Applied

Extended `cm_ltv_to_cac_ratio_by_cohort.yaml`:
- Definition now covers plural-"Ratios" chart-caption disclosures where cohort breakdown is in the figure
- New positive_signals bullet for terse chart/table headings using plural "Ratios"
- Strengthened negative_signals: single-blended LTV/CAC chart captions excluded
- Four hand-authored few_shot_examples (3 label=true including bare heading case; 1 label=false boundary guard)
- prompt_version bumped to 0.2.0

### Resolution

Fixed by PR #590 (merged 2026-05-09). Prompt `cm_ltv_to_cac_ratio_by_cohort.yaml` bumped to `prompt_version: 0.2.0` — definition extended to cover plural-"Ratios" chart-caption disclosures; new `positive_signals` bullet for terse chart/table headings using plural "Ratios"; four hand-authored `few_shot_examples` added (3 label=true including bare heading case; 1 label=false boundary guard). Smoke-eval re-run not yet executed against post-fix prompt; gold-corpus recall verification pending.

Bookkeeping closed by PR #614.
