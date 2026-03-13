# AGENTS.md - Operational Commands for Ralph Loops

## Environment Setup

```bash
# Activate virtual environment (if applicable)
source .venv/bin/activate

# Required environment variables
export DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis"
export TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test"
export SEC_USER_AGENT="FilingsReviewer contact@example.com"
```

## Extraction Commands

```bash
# Run extraction for a single filing by CIK
python3 scripts/run_v2_extraction.py --cik <CIK>

# Run extraction for a filing by ticker
python3 scripts/run_v2_extraction.py --ticker <TICKER>

# Batch extract all filings (use with caution)
python3 scripts/batch_v2_extraction.py --all
```

## Validation Commands

```bash
# Validate single filing against gold standard
python3 scripts/validate_against_gold_standard.py --cik <CIK> --mode fresh

# Validate all gold standard filings
python3 scripts/validate_against_gold_standard.py --all --mode fresh

# Compare against baseline
python3 scripts/validate_against_gold_standard.py --all --mode fresh --baseline
```

## Test Commands

```bash
# Run all tests
pytest -v

# Run gold standard tests only
pytest -m gold_standard --gold-standard-mode=fresh -v

# Run with coverage
pytest --cov=src --cov-report=term-missing

# Type check
mypy src/review/ --strict
```

## Database Commands

```bash
# Check filing count
psql $DATABASE_URL -c "SELECT COUNT(*) FROM filings;"

# List filings with candidates
psql $DATABASE_URL -c "SELECT f.cik, c.name, COUNT(rc.id) as candidates FROM filings f JOIN companies c ON f.company_id = c.id LEFT JOIN review_candidates rc ON f.id = rc.filing_id GROUP BY f.cik, c.name ORDER BY candidates DESC;"

# Check gold standard coverage
psql $DATABASE_URL -c "SELECT COUNT(DISTINCT filing_id) FROM gold_standard_metrics;"
```

## Backpressure Gates

Before marking a task complete, verify:
1. `pytest -v` - All tests pass
2. `pytest -m gold_standard` - Gold standard tests pass
3. No extraction errors in output
4. Candidate count is reasonable (not 0, not thousands)

## Known Patterns

- Large filings (>2MB HTML) may take 30-60 seconds to extract
- Tables with >10,000 chars are truncated (by design)
- Cohort charts detected via image proximity heuristics
- Financial statement filtering may reduce candidate count significantly
