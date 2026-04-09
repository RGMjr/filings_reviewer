---
paths:
  - "scripts/validate_against_gold_standard.py"
  - "src/gold_standard/**"
  - "data/gold_standard/**"
  - "data/presentation_gold_standard/**"
---

# Gold Standard Validation Rules

## When to Run

**Required** before committing changes to:
- `config/metric_keywords.yaml`
- `src/extraction_v2/` modules (active V2 pipeline)
- `src/extraction/` modules (V1, deprecated)
- `src/shared/keyword_config.py` or `src/shared/models.py`
- `src/review/candidate_generator.py`
- `src/review/keyword_matching.py`

## Validation Workflow

### 1. Quick Check (during development)
```bash
python scripts/validate_against_gold_standard.py --all --mode fresh --baseline
```
Review delta: positive = improvement, negative = regression.

### 2. Formal Validation (before commit)
```bash
pytest -m gold_standard --gold-standard-mode=fresh -v
```
All tests must pass. Regressions cause test failures.

### 3. If Regression Detected

Check the **tier breakdown** in validation output to determine severity:

**Tier 1 regression (must-not-miss metrics):** Blocker. Fix before committing.
- Investigate root cause (missed keywords, FP rule too aggressive, value binding gap)
- Do not trade Tier 1 recall for Tier 2 improvements

**Tier 2 regression (nice-to-have metrics):** Acceptable if Tier 1 improves or holds.
- Document the trade-off rationale in commit message
- No need to fix unless Tier 2 drop is severe (>5pp F1)

**Mixed regression:** If Tier 1 improves but Tier 2 regresses, this is generally acceptable. Note the trade-off in the commit message.

For any regression:
- Check if trade-off is intentional (precision vs recall)
- If unintentional on Tier 1, fix before committing

### 4. Update Baseline (after intentional changes)
```bash
python scripts/validate_against_gold_standard.py --all --mode fresh --update-baseline
```
Commit the updated `data/gold_standard/baseline_metrics.json`.

### 5. Update V2 Baseline (after intentional V2 changes)
```bash
python3 -m src.gold_standard.v2_validator --update-baseline --description "Rationale"
```
Commit the updated `data/gold_standard/v2_baseline.json`.

## Key Metrics

- **Precision**: % of generated candidates that are correct
- **Recall**: % of gold standard metrics that were found
- **F1**: Harmonic mean of precision and recall

## Thresholds

- Regression tolerance: 1% (configurable via `--tolerance`)
- Tests fail if any metric drops below baseline - tolerance
- **Tier-aware policy:** Tier 1 regressions are blockers; Tier 2 regressions are acceptable trade-offs (see "If Regression Detected" above)
- Tier definitions: `config/metric_keywords.yaml` (`tier:` field per metric)

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

## Full Procedures

See `docs/operations/gold-standard-runbook.md` for the complete baseline update runbook covering V1, V2, transcript, and presentation pipelines.
