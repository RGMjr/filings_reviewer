# GS Baseline Drift Investigation — Farfetch Known-Issue #108

**Date:** 2026-04-25
**Investigator:** Claude Code (automated)
**Related issue:** `docs/known-issues/legacy-108-gs-validator-baseline-drift-farfetch.md`
**Baseline file:** `data/gold_standard/v2_baseline.json`

---

## Executive Summary

The `has_regression=True` reported when running `--companies "Farfetch Limited" --fail-on-regression` is a **false positive caused by a comparator design flaw**, not by any regression in Farfetch's extraction quality. The baseline's `by_company["Farfetch Limited"]` entry is numerically identical to the current run's output. No baseline update is needed.

The root cause: when `--companies` is used to run a single-company subset, `compare_to_baseline` compares the subset's aggregate P/R/F1 against the **full-corpus overall baseline** rather than the company-specific baseline entry. Because Farfetch has below-average precision (59.3% vs corpus 65.9%), every Farfetch-only run produces `precision_delta ≈ -0.067`, unconditionally triggering `has_regression=True`.

Cross-corpus testing on Chewy confirms the pattern is systemic: any company whose individual metrics fall below the corpus average will trigger the same false positive when run with `--companies <name> --fail-on-regression`.

---

## 1. Observed Numbers (Farfetch run 2026-04-25)

```
python3 -m src.gold_standard.v2_validator --companies "Farfetch Limited" --workers 1
```

| Metric    | Value  |
|-----------|--------|
| Precision | 59.3%  |
| Recall    | 100.0% |
| F1        | 74.4%  |
| TP        | 16     |
| FP        | 11     |
| FN        | 0      |

### Tier breakdown

| Tier               | P      | R      | F1     |
|--------------------|--------|--------|--------|
| Tier 1 (must-not-miss) | 100.0% | 100.0% | 100.0% |
| Tier 2 (nice-to-have)  | 47.6%  | 100.0% | 64.5%  |

### Per-metric detail

| Metric                           | Tier | P      | R      | F1     |
|----------------------------------|------|--------|--------|--------|
| cm_ltv_to_cac_ratio              | T1   | 100.0% | 100.0% | 100.0% |
| cm_ltv_to_cac_ratio_by_cohort    | T1   | 100.0% | 100.0% | 100.0% |
| cm_active_customers_total        | T2   | 28.6%  | 100.0% | 44.4%  |
| cm_average_order_value           | T2   | 100.0% | 100.0% | 100.0% |
| cm_cac_payback_period            | T2   | 100.0% | 100.0% | 100.0% |
| cm_purchase_transactions_overall | T2   | 25.0%  | 100.0% | 40.0%  |

### FP diagnostics (11 total)

**BOTH_MISMATCH (4)** — wrong value and wrong period:
- `cm_active_customers_total`: 935,800 [2017 FY] (gold: 796,297) — appears to be thousands-scaled table value (raw: '935.8')
- `cm_active_customers_total`: 415,700 [2015 FY] (gold: 651,674) — raw: '415.7'
- `cm_purchase_transactions_overall`: 800,500 [2015 FY] (gold: 853,195) — raw: '800.5'
- `cm_purchase_transactions_overall`: 1,259,700 [2016 FY] (gold: 1,300,000) — raw: '1,259.7'

**PERIOD_MISMATCH (4)** — correct value, wrong period:
- `cm_active_customers_total`: 796,300 attributed to H1 2017 (gold period: full 2017)
- `cm_active_customers_total`: 651,700 attributed to [2016 FY] (gold: 651,674, same value)
- `cm_purchase_transactions_overall`: 853,200 attributed to H1 2017 (gold: H1 2017)
- `cm_purchase_transactions_overall`: 1,305,300 attributed to H1 2018 (gold: H1 2018)

**VALUE_MISMATCH (3)** — wrong value:
- `cm_active_customers_total`: 1,118,000 for H1 2018 (gold: 796,297)
- `cm_purchase_transactions_overall`: 30 for H1 2018 (gold: 853,195)
- `cm_purchase_transactions_overall`: 1,881,000 for 2017 FY (gold: 1,300,000)

Pattern: most FPs originate from `src=html_table`. The Farfetch filing contains a table with thousands-scaled rolling values that the table reconstruction stage reads, producing both scale mismatches and ambiguous period attributions. This is a known pre-existing extraction limitation; it is not a regression.

---

## 2. Baseline File Analysis

**File:** `data/gold_standard/v2_baseline.json`

| Field             | Value                                     |
|-------------------|-------------------------------------------|
| `baseline_date`   | `2026-04-24T02:46:34.842851+00:00`        |
| `description`     | "Post-#158 cohort-pivot cleanup drift: recall +12%, F1 +7%, Slack precision -0.87%. Accepted as new truth before Leg B lands." |
| Overall precision | 0.6594 (65.9%)                            |
| Overall recall    | 0.5808 (58.1%)                            |
| Overall F1        | 0.6176 (61.8%)                            |

**Farfetch-specific baseline entry (`by_company["Farfetch Limited"]`):**

| Metric    | Baseline value         | Current run value      | Delta |
|-----------|------------------------|------------------------|-------|
| Precision | 0.5925925925925926     | 0.5925925925925926     | **0.000** |
| Recall    | 1.0                    | 1.0                    | **0.000** |
| F1        | 0.7441860465116279     | 0.7441860465116279     | **0.000** |

**Conclusion:** The Farfetch company-specific baseline entry is current and accurate. There is no Farfetch regression. The baseline is not stale for Farfetch.

---

## 3. Root Cause: Comparator Logic Flaw

The `compare_to_baseline` function (`src/gold_standard/baseline.py:210`) always computes deltas against `baseline.overall` — the aggregated metrics across all 15 corpus companies. When `--companies` filters to a single company, the current run's "overall" is that company's metrics, not the corpus aggregate.

```
Comparison (Farfetch-only run vs full-corpus baseline):
  current.overall.precision (Farfetch-only)  = 0.5926
  baseline.overall.precision (all companies) = 0.6594
  delta = -0.0668  →  has_regression=True, regressed_metrics=['precision']
```

The validator already emits a `logger.warning` at line 2224 when `--companies` is combined with `--fail-on-regression` ("comparison is partial; regressions outside the subset will not be caught"), but this warning is about missed regressions — not about false positive regressions. The comparison still proceeds against the wrong denominator.

---

## 4. Cross-Corpus Reproduction (Chewy, Inc.)

```
python3 -m src.gold_standard.v2_validator --companies "Chewy, Inc." --workers 1
```

| Metric    | Current | Baseline (`by_company`) | Delta |
|-----------|---------|-------------------------|-------|
| Precision | 58.3%   | 58.3%                   | **0.000** |
| Recall    | 50.0%   | 50.0%                   | **0.000** |
| F1        | 53.8%   | 53.8%                   | **0.000** |

Chewy's company-specific metrics are also unchanged. However, if run with `--fail-on-regression`, the same flaw would apply:

```
Hypothetical Chewy-only comparison vs full-corpus baseline:
  current.precision (Chewy-only)  = 0.5833
  baseline.precision (all cos.)   = 0.6594
  delta = -0.0761  →  has_regression=True  [FALSE POSITIVE]
```

**Finding: The issue is cross-corpus, not Farfetch-specific.** Any company whose individual P/R/F1 metrics fall below the corpus average will trigger a false regression when run with `--companies <name> --fail-on-regression`. The comparator assumes a full-corpus run.

---

## 5. Metric Delta Summary (Tier classification per CLAUDE.md)

### Tier 1 (must-not-miss) — Farfetch

| Metric                         | Baseline P/R/F1 | Current P/R/F1  | Status          |
|--------------------------------|-----------------|-----------------|-----------------|
| cm_ltv_to_cac_ratio            | n/a (not in company baseline) | 100/100/100 | **No regression** |
| cm_ltv_to_cac_ratio_by_cohort  | n/a (not in company baseline) | 100/100/100 | **No regression** |

Both Tier 1 metrics extracted by the pipeline on Farfetch are correct (TP only, no FPs, no FNs). The precision regression flag has no Tier 1 impact.

### Tier 2 (nice-to-have) — Farfetch

| Metric                           | P      | R      | F1    | FP count | FP type             |
|----------------------------------|--------|--------|-------|----------|---------------------|
| cm_active_customers_total        | 28.6%  | 100.0% | 44.4% | 7        | period + value mismatch (table scale) |
| cm_purchase_transactions_overall | 25.0%  | 100.0% | 40.0% | 4        | period + value mismatch (table scale) |
| cm_average_order_value           | 100.0% | 100.0% | 100%  | 0        | clean               |
| cm_cac_payback_period            | 100.0% | 100.0% | 100%  | 0        | clean               |

The 11 FPs are pre-existing and unchanged from the baseline. They reflect a structural difficulty in the Farfetch S-1: the filing contains an html_table with rolling-average or scaled values that look syntactically like customer counts and order counts, but don't map cleanly to gold-standard point-in-time values.

---

## 6. Commits Since Baseline (2026-04-24) Touching Extraction

Three commits touch `src/extraction_v2/` or `config/metric_keywords.yaml` since the baseline was saved:

| Commit | Description | Impact on Farfetch |
|--------|-------------|-------------------|
| `6baf882` | Retire `required_context` gating (dead code removal) | None — `cm_gmv` was only user |
| `a350007` | Review-UI skip/undo, chart-fact promotion | None — no text-extraction logic |
| `e3d827a` | Remove stale comment in image_classify | None — comment only |

None of these commits could have changed Farfetch's extraction output. The Farfetch numbers being identical between `origin/main` (commit `74f0d32`) and the current HEAD is consistent with this.

---

## 7. Recommendation

**Do NOT update the baseline.** The baseline accurately reflects current extraction quality for Farfetch and all other companies. The drift signal is an artifact of the comparison logic.

**Recommended fix: make `--fail-on-regression` and `--companies` mutually incompatible** (or implement subset-aware comparison).

### Option A (recommended — minimal, safe): Hard-refuse the combination

Change the `logger.warning` at `src/gold_standard/v2_validator.py:2224–2228` to an error + early return:

```python
if fail_on_regression and (companies or limit is not None):
    print(
        "ERROR: --fail-on-regression cannot be used with --companies or --limit.\n"
        "Subset-run aggregate metrics are structurally incomparable to the "
        "full-corpus baseline. Run without --companies for regression gating."
    )
    sys.exit(2)
```

This prevents the false positive regression while preserving the ability to use `--companies` for development inspection. The pre-commit hook and CI should always run full-corpus validation anyway.

### Option B (more complete): Subset-aware comparison

When `--companies` specifies companies that are all present in `baseline.by_company`, recompute a virtual overall from only those entries for comparison:

```python
if companies and all(c in baseline.by_company for c in companies):
    # Build a synthetic "baseline overall" from the subset's by_company entries
    # so the comparison is against the right denominator
    ...
```

This is more complex but allows meaningful regression detection within a subset. It requires aggregating TP/FP/FN from company baseline entries — currently not stored in `v2_baseline.json` (only P/R/F1 per company are stored, not raw counts).

**For now, Option A is the correct fix.** The pre-commit hook must run the full corpus; `--companies` is a development/debugging tool and should not gate commits.

---

## 8. Prior Art

The Farfetch FP pattern (period + value mismatches on `cm_active_customers_total` and `cm_purchase_transactions_overall`) was previously analyzed in `docs/analysis/INV-1_FARFETCH_EXTRACTION_REPORT.md` and `docs/analysis/HRV-4_FARFETCH_VALIDATION.md`. Those reports document the same html_table false positives. The current 11 FPs are consistent with those prior findings.
