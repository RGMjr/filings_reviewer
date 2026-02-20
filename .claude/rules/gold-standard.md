---
paths:
  - "scripts/validate_against_gold_standard.py"
  - "src/gold_standard/**"
  - "data/gold_standard/**"
---

# Gold Standard Validation Rules

## When to Run

**Required** before committing changes to:
- `config/metric_keywords.yaml`
- `src/extraction/` modules
- `src/review/candidate_generator.py`
- `src/review/keyword_matching.py`

## Validation Workflow

### 1. Quick Check (during development)
```bash
python3 scripts/validate_against_gold_standard.py --all --mode fresh --baseline
```
Review delta: positive = improvement, negative = regression.

### 2. Formal Validation (before commit)
```bash
pytest -m gold_standard --gold-standard-mode=fresh -v
```
All tests must pass. Regressions cause test failures.

### 3. If Regression Detected
- Investigate false negatives (missed metrics)
- Check if trade-off is intentional (precision vs recall)
- If intentional, document rationale in commit message
- If unintentional, fix before committing

### 4. Update Baseline (after intentional changes)
```bash
python3 scripts/validate_against_gold_standard.py --all --mode fresh --update-baseline
```
Commit the updated `data/gold_standard/baseline_metrics.json`.

## Key Metrics

- **Precision**: % of generated candidates that are correct
- **Recall**: % of gold standard metrics that were found
- **F1**: Harmonic mean of precision and recall

## Thresholds

- Regression tolerance: 1% (configurable via `--tolerance`)
- Tests fail if any metric drops below baseline - tolerance

## Transcript Gold Standard

After completing the transcript annotation workflow (Phase 2), use these commands:

### Quick validation (CLI)
```bash
# Validate against tuning split with baseline comparison
python3 scripts/validate_transcript_extraction.py --split tuning --baseline --verbose
```

### Pytest integration
```bash
# Run transcript gold standard (tuning split, default):
pytest -m transcript_gold_standard -v

# Run against test split:
pytest -m transcript_gold_standard --transcript-split test -v

# Update transcript baseline after intentional improvement:
pytest -m transcript_gold_standard --transcript-update-baseline -v
```

### First-run baseline setup
```bash
python3 scripts/validate_transcript_extraction.py --split tuning --save-baseline
python3 scripts/validate_transcript_extraction.py --split test --save-baseline
```
