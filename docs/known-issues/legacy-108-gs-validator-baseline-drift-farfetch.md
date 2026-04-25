---
autonomy: review
discovered: '2026-04-24'
estimated: S
id: 108
severity: medium
slug: gs-validator-baseline-drift-farfetch
source: legacy
status: partially-resolved
title: GS Validator Baseline Drift — Farfetch Reports has_regression=True on Unmodified Main
touches:
  - src/gold_standard/v2_validator.py
  - data/gold_standard/Farfetch_Limited
updated: '2026-04-25'
---

### Problem

Running `python3 -m src.gold_standard.v2_validator --companies "Farfetch Limited" --workers 1 --fail-on-regression` on a clean checkout of `origin/main` (commit `74f0d32`) reports:

```
ComparisonResult(precision_delta=-0.0668, recall_delta=+0.4192, f1_delta=+0.1266,
                 has_regression=True, regressed_metrics=['precision'])
```

Surfaced while running the GS smoke test for the `required_context` retirement PR. Identical numbers on the unmodified main and on the modified branch — confirming the drift is pre-existing, not caused by recent extraction changes. The +0.42 recall delta is too large for any single recent commit; the saved baseline appears materially stale.

Blast radius: any PR that runs the validator with `--fail-on-regression` against Farfetch is blocked at commit time even when the change is metric-neutral. This silently reduces the value of the GS gate.

### Next Steps

- Inspect the Farfetch baseline file to confirm staleness (date, last `--update-baseline` description).
- Compare current TP/FP/FN counts (16/11/0) against the recorded baseline to identify which metrics moved.
- Either (a) update the baseline with `--update-baseline --description "calibration after [...]"` if the new numbers reflect intended improvements, or (b) bisect to find the unintended regression in precision.
- Repeat on at least one other company to determine whether the drift is Farfetch-specific or cross-corpus.

### Investigation 2026-04-25

Full analysis in `docs/analysis/gs-baseline-drift-investigation-2026-04-25.md`.

**Finding:** The `has_regression=True` is a **false positive** caused by a comparator design flaw, not a real regression. When `--companies "Farfetch Limited"` is used, `compare_to_baseline` compares the Farfetch-only run's aggregate metrics (P=59.3%, R=100%, F1=74.4%) against the **full-corpus overall baseline** (P=65.9%, R=58.1%, F1=61.8%), producing `precision_delta=-0.067` unconditionally. The baseline's `by_company["Farfetch Limited"]` entry is numerically identical to the current run — zero delta.

Cross-corpus check on Chewy confirms the pattern is systemic: Chewy's company-specific metrics are also unchanged from baseline; any company with below-average precision would trigger the same false positive with `--companies <name> --fail-on-regression`.

**Recommendation:** Do NOT update the baseline. Fix `src/gold_standard/v2_validator.py` lines 2224–2228 to refuse (exit 2) rather than warn when `--fail-on-regression` is combined with `--companies` or `--limit`. The comparison is structurally invalid for subset runs. See Option A in the analysis doc for the exact change. **The user must approve and run any code change.**

Tier 1 metrics (cm_ltv_to_cac_ratio, cm_ltv_to_cac_ratio_by_cohort) are perfect on Farfetch (P=R=F1=100%). The 11 FPs are pre-existing Tier 2 issues (period/value mismatches on html_table rows for cm_active_customers_total and cm_purchase_transactions_overall) unchanged since at least HRV-4.
