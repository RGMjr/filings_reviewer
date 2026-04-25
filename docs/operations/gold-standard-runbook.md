# Gold Standard Baseline Update Runbook

> **Pivot status (2026-04-25):** Under the chart-presence pivot (#86, 2026-04-23), chart-native metrics are scored on **presence-P/R/F1**, not value-level P/R/F1. Text-pipeline scoring will flip to **presence-recall** as the Tier-1 gate when PR2 of the text-presence pivot lands (gold-standard derivation + validator wiring; pending). Until then, the V2 validator still gates on fact-recall for text/table metrics. See [`text-pipeline-presence-pivot-plan.md`](text-pipeline-presence-pivot-plan.md). Known gap: legacy-098 — `presence_f1` is not yet populated in the validator output; chart-native improvements are unmeasurable until that fixes.

## Overview

Three validation pipelines maintain independent baselines:

| Pipeline | Status | Baseline file |
|----------|--------|---------------|
| V2 SEC extraction (`v2_validator.py`, 15 companies) — pre-commit regression guard | Active | `data/gold_standard/v2_baseline.json` |
| Transcript | Active | `data/transcript_gold_standard/transcript_baseline_{split}.json` |
| Presentation | Active | `data/presentation_results/presentation_baseline.json` |

The **gold standard CSV** (`data/gold_standard/golden_set_260408.csv`) is the human-verified dataset all pipelines validate against. Baselines record the P/R/F1 at the last accepted state.

---

## 1. Updating the Gold Standard CSV

### When

- Adding a new company to the validation set
- Correcting annotation errors
- Updating metric IDs after taxonomy changes

### Steps

1. Edit `data/gold_standard/golden_set_260408.csv` following the rules in `docs/GOLD_STANDARD_SPECIFICATION.md`
2. Cache the filing HTML locally (if a new company): `data/gold_standard/{Company_Name}/filing.html` + `metadata.json`
3. Run all pipelines to see impact before updating baselines (see §6)
4. Update baselines for any pipeline where metrics changed intentionally (see §2–§5)

### Files to commit

- `data/gold_standard/golden_set_260408.csv`
- Any new `data/gold_standard/{Company_Name}/` directories

---

## 2. Updating the V2 Baseline

The V2 validator is the pre-commit regression guard (covers SEC data, 15 companies).

### Command

```bash
python3 -m src.gold_standard.v2_validator --update-baseline --description "Brief rationale"
```

### Verification

```bash
python3 -m src.gold_standard.v2_validator --fail-on-regression
```

### Files to commit

```
data/gold_standard/v2_baseline.json
```

---

## 3. Updating Transcript Baselines

### Commands

```bash
# Update tuning split baseline
python3 scripts/validate_transcript_extraction.py --split tuning --save-baseline

# Update test split baseline
python3 scripts/validate_transcript_extraction.py --split test --save-baseline
```

### Verification

```bash
pytest -m transcript_gold_standard -v
```

---

## 4. Updating the Presentation Baseline

### Command

```bash
python3 scripts/validate_presentation_extraction.py --save-baseline
```

### Verification

```bash
pytest -m presentation_gold_standard -v
```

> Note: no test currently uses the `presentation_gold_standard` marker — the above invocation is stale. Use the CLI validator directly:
>
> ```bash
> python3 scripts/validate_presentation_extraction.py --form-type 8-K --baseline --verbose
> python3 scripts/validate_presentation_extraction.py --form-type S-1 --baseline --verbose
> ```

---

## 5. Full Validation Sweep

Run before committing any extraction or keyword config change:

```bash
python3 -m src.gold_standard.v2_validator && python3 scripts/validate_transcript_extraction.py --split tuning --baseline --verbose
```

---

## 6. Updating the Chart-Pipeline Baseline

After Phase 1 or later chart-bridge work delivers new recall for chart-embedded metrics:

```bash
python3 -m src.gold_standard.v2_validator --update-baseline \
  --description "Phase N: chart fact bridge for <metric_list>"
```

Then commit `data/gold_standard/v2_baseline.json` separately with message `chore(gold-standard): update v2 baseline for Phase N chart bridge delivery`.

---

## 7. Reading V2 Validator Output

After each validator run (`v2_validator.py`), output includes a Tier breakdown followed by a chart confirmation line:

```
Tier 1 recall: ...
Tier 2 recall: ...

CHART cross-source confirmation: m/n (pct%)
```

The `m/n` counts chart facts that were independently confirmed by a second source type (e.g., a TEXT or TABLE fact agreeing on the same metric+period+value slot). `pct%` is `m/n * 100`. (Under the chart-presence pivot the chart pipeline no longer auto-emits per-value chart facts; this line currently reflects only residual pre-pivot rows. The metric will be deprecated in PR2 of the text-presence pivot in favor of a presence-derived check.)

A soft `WARNING` is printed if `pct < 30%`. This warning is not a hard failure and will not block a baseline update, but it indicates that the chart bridge is producing few cross-confirmed facts — which may signal chart OCR quality issues or a gap in the text/table extraction path for those metrics. Discuss with the team before updating the baseline when this warning appears.

### 7a. Presence-derived metrics (PR2-pending)

PR2 of the text-presence pivot will add the following to the validator output:

```
Tier 1 presence-recall: ...
Tier 1 presence-F1: ...     ← NEW Tier-1 gate (replaces fact-recall)
Tier 2 presence-recall: ...
```

Mechanics under PR2 (interface contract, not yet shipped — see `text-pipeline-presence-pivot-plan.md` §3):

- The validator queries `v_doc_metric_presence` (UNION view of `v2_text_metric_presence` + `v2_image_metric_presence`, the per-image grain table that lands with image-review Wave 2).
- Tier-1 gate flips from "fact-recall on text/table" to "presence-recall on the doc grain". A regression on a Tier-1 metric blocks PR merge regardless of whether per-value facts exist.
- Chart-native metrics (`cm_revenue_by_cohort`, `cm_balance_by_cohort`, `cm_gross_margin_by_cohort`, etc.) become measurable for the first time post-pivot — pre-PR2 their recall has been silently zero in the gate because the chart pipeline emits no facts.

Until PR2 lands, do not expect chart-native presence improvements to show up in the V2 baseline; they are still tracked manually via gold-standard inspection and the `vision-bakeoff-metric-classify-2026-04-23.md` report. Known gap: legacy-098 (`presence_f1` not yet populated in the validator output).

---

## 8. Phase 2 Chart Fixture Recording Procedure

Phase 2 fixtures are hand-authored JSON files in `tests/fixtures/charts/`. To add a new fixture: create `<NAME>.chart_data.json` matching the `ChartData` schema (`chart_type`, `title`, `x_axis_label`, `y_axis_label`, `series[]`, `annotations[]`). Series point values should represent what Vision OCR would return. No API calls required.
