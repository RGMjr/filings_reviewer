# Gold Standard Baseline Update Runbook

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

After each validator run (`v2_validator.py`), output includes two tier breakdowns plus a chart confirmation line:

```
==== METRIC TIER BREAKDOWN ====
  Tier 1 (must-not-miss):  P=...  R=...  F1=...   (informational under PR2)
  Tier 2 (nice-to-have):   P=...  R=...  F1=...   (informational)

==== TEXT-PRESENCE TIER BREAKDOWN (PR2 Tier-1 gate surface) ====
  Tier 1 (must-not-miss) [GATE]:           P=...  R=...  F1=...
  Tier 2 (nice-to-have) [informational]:   P=...  R=...  F1=...

CHART cross-source confirmation: m/n (pct%)   (informational)
```

**The PR2 gate** keys on `Tier 1 [GATE] R=...` (presence-recall). `--fail-on-regression` exits 1 only when that number drops below `tier1_presence_recall` in `data/gold_standard/v2_baseline.json` minus tolerance. All other lines (fact-level Tier 1/2, chart cross-source confirmation, per-company drops) are informational and will be reported in the comparison summary with an `[informational]` prefix but will not block the commit. See `docs/operations/text-pipeline-presence-pivot-plan.md` for the rationale.

The `m/n` chart cross-source counts chart facts independently confirmed by a second source type (TEXT or TABLE fact agreeing on the same metric+period+value slot). `pct%` is `m/n * 100`.

A soft `WARNING` is printed if `pct < 30%`. This warning is not a hard failure and will not block a baseline update, but it indicates that the chart bridge is producing few cross-confirmed facts — which may signal chart OCR quality issues or a gap in the text/table extraction path for those metrics. Discuss with the team before updating the baseline when this warning appears.

---

## 8. Phase 2 Chart Fixture Recording Procedure

Phase 2 fixtures are hand-authored JSON files in `tests/fixtures/charts/`. To add a new fixture: create `<NAME>.chart_data.json` matching the `ChartData` schema (`chart_type`, `title`, `x_axis_label`, `y_axis_label`, `series[]`, `annotations[]`). Series point values should represent what Vision OCR would return. No API calls required.
