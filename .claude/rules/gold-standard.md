---
paths:
  - "src/gold_standard/**"
  - "data/gold_standard/**"
  - "data/presentation_gold_standard/**"
  - "data/filing_gold_standard/**"
---

# Gold Standard Validation Rules

## When to Run

**Required** before committing changes to:
- `config/metric_keywords.yaml`
- `src/extraction_v2/` modules (active V2 pipeline)
- `src/shared/models.py` (SourceSegment and related shared types)
- `src/extraction_v2/stages/ingestion.py` (V2 segmentation entry point)
- `src/shared/keyword_config.py` or `src/shared/models.py`
- `src/review/keyword_matching.py`

## Validation Workflow

### 1. Quick Check (during development)
```bash
python3 -m src.gold_standard.v2_validator --limit 3 --workers 1
```
Review delta: positive = improvement, negative = regression.

### 2. Formal Validation (before commit)
```bash
python3 -m src.gold_standard.v2_validator --fail-on-regression
```
Non-zero exit indicates a regression.

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

### 4. Update V2 Baseline (after intentional changes)
```bash
python3 -m src.gold_standard.v2_validator --update-baseline --description "Rationale"
```
Commit the updated `data/gold_standard/v2_baseline.json`.

### 5. Subsetting during iteration

When tuning a single metric or debugging one filing, run only a subset:
```bash
python3 -m src.gold_standard.v2_validator --companies "Slack Technologies" --companies "Datadog, Inc."
python3 -m src.gold_standard.v2_validator --limit 3 --workers 1
```
- `--companies`: repeat the flag for each company. Exact-match against the CSV "Company" column (unknown names error out with the valid-names list). Repeatable form handles names containing commas (e.g. "Chewy, Inc.") cleanly.
- `--limit N`: cap at the first N companies (applied after `--companies` filter).
- `--workers N`: parallel worker count (default 4; use `--workers 1` for sequential debugging).
- `--update-baseline` is **incompatible** with `--companies` or `--limit` — the CLI errors out to prevent writing a partial baseline. Always run the full set before updating the baseline.

## Key Metrics

- **Precision**: % of extracted facts that are correct
- **Recall**: % of gold standard metrics that were found
- **F1**: Harmonic mean of precision and recall

## Thresholds

- Regression tolerance: 1% (configurable via `--tolerance`)
- Validator fails if any metric drops below baseline - tolerance
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

## Known Quirks

**Known flaky transcript files:** TMUS_2025-04-24 and META_2025-04-30 vary by 1 TP between runs due to non-deterministic dedup ordering. Allow ±1pp per metric before flagging as a regression.

**SNAP presentations:** SNAP Q3/Q4 2025 filings have poor precision (~29%) due to an image-based investor letter generating spurious text candidates. This is a known limitation, not a regression signal.

## Full Procedures

See `docs/operations/gold-standard-runbook.md` for the complete baseline update runbook covering V2, transcript, and presentation pipelines.
