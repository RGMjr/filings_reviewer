# Gold Standard Baseline Update Runbook

## Overview

Three validation pipelines maintain independent baselines:

| Pipeline | Status | Baseline file |
|----------|--------|---------------|
| Pre-commit regression guard (`validate_against_gold_standard.py`, SEC + presentation, 15 companies) | Active | `data/gold_standard/baseline_metrics.json` |
| V2 SEC-only diagnostic (`v2_validator.py`, 15 companies) | Active | `data/gold_standard/v2_baseline.json` |
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

## 2. Updating the Pre-commit Regression Baseline

Used by `validate_against_gold_standard.py` as the pre-commit regression guard (covers SEC + presentation data, 15 companies).

### Command

```bash
python3 scripts/validate_against_gold_standard.py --all --mode fresh --update-baseline
```

### Files to commit

```
data/gold_standard/baseline_metrics.json
```

---

## 3. Updating the V2 Baseline

### Command

```bash
python3 -m src.gold_standard.v2_validator --update-baseline --description "Brief rationale"
```

### Verification

```bash
pytest -m gold_standard --gold-standard-mode=fresh -v
```

### Files to commit

```
data/gold_standard/v2_baseline.json
```

---

## 4. Updating Transcript Baselines

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

## 5. Updating the Presentation Baseline

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

## 6. Full Validation Sweep

Run before committing any extraction or keyword config change:

```bash
python3 scripts/validate_against_gold_standard.py --all --mode fresh --baseline && python3 -m src.gold_standard.v2_validator && python3 scripts/validate_transcript_extraction.py --split tuning --baseline --verbose
```
