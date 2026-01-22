# Validation Plan

**Created**: 2026-01-21
**Purpose**: Track bulk validation against gold standard
**Mode**: Ralph autonomous loop

---

## Instructions

1. Ensure gold standard files exist in `data/gold_standard/`
2. Run `./ops/loop.sh validate` to start the loop
3. Ralph will validate one filing per iteration
4. Results accumulate in `ops/VALIDATION_RESULTS.md`

---

## Filings to Validate

### Gold Standard Filings
<!-- Only filings with gold standard data can be validated -->

- [x] 0001764925 | Slack Technologies | GS: slack_gold_standard.csv - P=28.6% R=63.6% F1=39.4% [REGRESSION]
- [ ] 0001740260 | Farfetch | GS: farfetch_gold_standard.csv
- [ ] 0001640147 | Snowflake | GS: snowflake_gold_standard.csv

### Filings Without Gold Standard
<!-- These will be skipped with [SKIP] -->

- [ ] 0001467623 | DocuSign | No gold standard
- [ ] 0001744676 | Samsara | No gold standard

---

## Completed

<!-- Results format: [x] CIK | Company | P=XX% R=XX% F1=XX% -->

- [x] 0001764925 | Slack Technologies | P=28.6% R=63.6% F1=39.4%

---

## Skipped

<!-- Format: [SKIP] CIK | Company | Reason -->

---

## Regressions

<!-- Format: [REGRESSION] CIK | Company | Metric dropped: XX% -> YY% -->

- [REGRESSION] 0001764925 | Slack Technologies | Precision: 76% -> 28.6% (-47.4%), Recall: 84% -> 63.6% (-20.4%), F1: 80% -> 39.4% (-40.6%)

---

## Errors

<!-- Format: [ERROR] CIK | Company | Error description -->

---

## Statistics

| Metric | Count |
|--------|-------|
| Total Filings | 5 |
| Validated | 1 |
| Skipped | 0 |
| Regressions | 1 |
| Errors | 0 |

---

## Baseline Comparison

**Baseline Date**: (not yet established)
**Baseline File**: `data/gold_standard/baseline_metrics.json`

| Filing | Baseline P | Baseline R | Baseline F1 |
|--------|-----------|-----------|-------------|
| Slack | 76% | 84% | 80% |
| Farfetch | 67% | 47% | 55% |
| Snowflake | TBD | TBD | TBD |
