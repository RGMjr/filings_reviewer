# WORKER PROMPT: Task HRV-2 - Create Validation Scripts

```
═══════════════════════════════════════════════════════════════════════════════
TASK ID:       HRV-2
TASK NAME:     Create scripts to compare system output against gold standard
WORKSTREAM:    Human Review Validation
SOURCE:        docs/HUMAN_REVIEW_VALIDATION_PLAN.md
STATUS:        🟡 PENDING
COMPLETION:    N/A
TIME ESTIMATE: 2-3 hours (validation script 90 min, export script 45 min, testing 30 min)
TIME ACTUAL:   N/A
RISK LEVEL:    None - Read-only analysis scripts
TASK SIZE:     M
DEPENDS ON:    None
UNLOCKS:       HRV-3, HRV-4 (validation workflow depends on these scripts)
BLOCKS:        HRV-3, HRV-4
PARALLEL WITH: HRV-1
═══════════════════════════════════════════════════════════════════════════════
```

## Objective

Create two Python scripts to enable automated validation of review candidates against the gold standard CSV and export review decisions for analysis.

**Business Rationale**: Manual comparison of hundreds of candidates against gold standard is error-prone and time-consuming. Automated scripts provide reproducible precision/recall metrics and systematic FP/FN identification.

**Current Behavior**: No automated way to compare review candidates against gold standard. Validation is entirely manual.

**Desired Behavior**: Run a command to get precision/recall metrics per filing, with detailed FP/FN lists.

## Prerequisites

- None (standalone)
- Database must have review candidates generated
- Gold standard CSV must exist at `data/gold_standard/golden_set_251218.csv`

## Files to Create

1. **`scripts/validate_against_gold_standard.py`** - Compare candidates against gold standard
2. **`scripts/export_review_decisions.py`** - Export web review decisions to CSV

## Files to Read (Context Only)

- `data/gold_standard/golden_set_251218.csv` - Gold standard format
- `src/infra/db.py` - Database connection patterns
- `scripts/generate_review_candidates.py` - Example of database script structure

## Implementation Requirements

### Script 1: validate_against_gold_standard.py

1. **Command Line Interface**
   ```
   Usage: python scripts/validate_against_gold_standard.py [OPTIONS]

   Options:
     --filing-id N      Validate specific filing (by database ID)
     --company NAME     Validate by company name
     --all              Validate all filings with gold standard entries
     --output FILE      Write detailed report to file (JSON or CSV)
     --verbose          Show per-candidate match details
   ```

2. **Core Logic**
   - Load gold standard CSV, filter to selected filing(s)
   - Load review candidates from database for same filing(s)
   - Match candidates to gold standard by:
     - Company name (exact match)
     - Metric ID (normalize to standard IDs like cm_dau, cm_arpu)
     - Value (normalize: "10 million" = "10,000,000")
     - Fuzzy text matching for source quote (optional, for debugging)

3. **Metrics to Calculate**
   - **True Positives (TP)**: Candidates that match gold standard entries
   - **False Positives (FP)**: Candidates with no gold standard match
   - **False Negatives (FN)**: Gold standard entries with no candidate match
   - **Precision**: TP / (TP + FP)
   - **Recall**: TP / (TP + FN)
   - **F1 Score**: 2 * (Precision * Recall) / (Precision + Recall)

4. **Output Format**
   ```
   === Validation Report for Slack S-1 (filing_id=2) ===

   Gold Standard Entries: 38
   Review Candidates: 45

   Metrics:
     True Positives:  32
     False Positives: 13
     False Negatives: 6
     Precision:       71.1%
     Recall:          84.2%
     F1 Score:        77.1%

   False Positives (candidates not in gold standard):
   1. [cm_users] "15 million users" in segment 1234
   2. [cm_revenue] "$500 million" in segment 1256
   ...

   False Negatives (gold standard metrics not detected):
   1. [cm_dau] "10 million daily active users" (line 15 in CSV)
   2. [cm_paid_customers] "paid customers" (line 23 in CSV)
   ...
   ```

### Script 2: export_review_decisions.py

1. **Command Line Interface**
   ```
   Usage: python scripts/export_review_decisions.py [OPTIONS]

   Options:
     --output FILE      Output CSV path (default: stdout)
     --status STATUS    Filter by decision status (accepted/rejected/all)
     --filing-id N      Filter to specific filing
     --format FORMAT    Output format: csv, json (default: csv)
   ```

2. **Core Logic**
   - Query `review_decisions` table joined with `review_candidates`
   - Join with `filings` and `companies` for context
   - Format output to match gold standard CSV schema

3. **Output Columns** (match gold standard schema)
   ```
   document_url, company, metric_id, is_new_metric, text_variant,
   raw_value, scaled_value, scale_unit, period_start, period_end,
   definition, source_quote, segment_type, is_definition_only,
   value_context, detection_difficulty, notes
   ```

### Error Handling

- **Database Connection**: Exit with clear error if DATABASE_URL not set
- **Empty Results**: Report "No candidates found" rather than divide-by-zero
- **Missing Gold Standard**: Warn if filing not in gold standard, skip metrics
- **Value Normalization Failures**: Log warning, continue with raw comparison

### Performance Requirements

- Complete validation for single filing in <10 seconds
- Handle gold standard CSV up to 1000 rows efficiently

## Test Requirements

### Coverage Target: **≥ 80%** for new scripts

### Test Categories (8+ tests recommended)

1. **CSV Parsing Tests** (2-3 tests)
   - Parse gold standard with multi-line quotes
   - Handle UTF-8-SIG encoding
   - Parse empty optional columns

2. **Matching Logic Tests** (3-4 tests)
   - Exact metric ID match
   - Value normalization (millions, billions, K/M/B)
   - Company name matching (case-insensitive)

3. **Metrics Calculation Tests** (2-3 tests)
   - Precision/recall with known values
   - Edge case: 0 TPs (precision=0)
   - Edge case: 0 FPs (precision=100%)

### Test File Location

- `tests/unit/scripts/test_validate_against_gold_standard.py`

## Acceptance Criteria

- [ ] `validate_against_gold_standard.py` runs without error
- [ ] Outputs precision/recall/F1 metrics for specified filing
- [ ] Lists FP candidates with segment IDs
- [ ] Lists FN gold standard entries with line numbers
- [ ] `export_review_decisions.py` exports valid CSV
- [ ] Exported CSV matches gold standard column schema
- [ ] Both scripts have --help documentation
- [ ] 8+ unit tests covering parsing and matching logic
- [ ] Test coverage ≥ 80%

## Do NOT

- Modify gold standard CSV (read-only)
- Modify database schema
- Add dependencies beyond standard library + existing project deps
- Create integration tests that require database (unit tests with mocks only)

## Verification Commands

```bash
# Test validate script help
python scripts/validate_against_gold_standard.py --help

# Test export script help
python scripts/export_review_decisions.py --help

# Run validation for Slack filing
DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis" \
  python scripts/validate_against_gold_standard.py --filing-id 2

# Run validation for all filings with gold standard
DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis" \
  python scripts/validate_against_gold_standard.py --all

# Export accepted decisions
DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis" \
  python scripts/export_review_decisions.py --status accepted --output accepted.csv

# Run unit tests
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/scripts/test_validate_against_gold_standard.py -v

# Check coverage
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/scripts/ \
  --cov=scripts --cov-report=term-missing
```

## Example Value Normalization

```python
def normalize_value(raw: str) -> float | None:
    """
    Normalize value strings to numeric.

    Examples:
    - "10 million" -> 10_000_000
    - "1.5B" -> 1_500_000_000
    - "500K" -> 500_000
    - "$1.2 billion" -> 1_200_000_000
    - "15%" -> 0.15
    """
    # Implementation left to developer
```

## Reference

- **Issue source**: docs/HUMAN_REVIEW_VALIDATION_PLAN.md
- **Dependencies**: None
- **Related**: HRV-1 (CSV schema), HRV-3/HRV-4 (use these scripts)

---

**Last Updated**: 2025-12-26
**Format Version**: 2.4
