---
id: 576
source: gh
slug: ltv-to-cac-by-cohort-zero-recall
title: "Phase-1 eval: cm_ltv_to_cac_ratio_by_cohort 0 recall on gold corpus"
status: open
severity: medium
autonomy: skip
estimated: —
touches:
  - config/llm_classifier/prompts/cm_ltv_to_cac_ratio_by_cohort.yaml
  - config/llm_classifier/thresholds.yaml
discovered: 2026-05-08
updated: 2026-05-08
gh_issue: 576
note: classifier never predicts present; base cm_ltv_to_cac_ratio scores F1=1.00, so issue is the cohort-disaggregation distinction
---

### Problem

Phase-1 smoke eval (run_id `20260508T1743`) shows `cm_ltv_to_cac_ratio_by_cohort` with precision=1.00, recall=0.00, F1=0.00 across all 5 gold filings. Precision is 1.0 only because the classifier never predicts present (zero false positives, zero true positives). At least one gold positive exists.

This is a Tier-1 metric per `CLAUDE.md`. The base `cm_ltv_to_cac_ratio` metric scored F1=1.00 in the same run, so the issue is specifically the cohort-disaggregation distinction. The "by-cohort" suffix likely makes this prompt narrow — the classifier may require explicit cohort-vintage language in the same segment as the LTV/CAC discussion, but real disclosures often split context across paragraphs.

### Next Steps

- Pull gold-positive segments for `cm_ltv_to_cac_ratio_by_cohort` and inspect language; confirm whether positives sit in a single segment or span paragraphs.
- Read `config/llm_classifier/prompts/cm_ltv_to_cac_ratio_by_cohort.yaml`; check whether positive_signal admits cross-paragraph cohort context.
- If cross-segment context is required, this metric may genuinely need multi-segment classification (out of scope for prompt-only fix); if not, add hand-authored few-shots covering the observed positives.
- Re-run smoke eval; target recall > 0.
