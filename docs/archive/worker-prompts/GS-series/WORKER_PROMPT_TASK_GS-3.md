# WORKER PROMPT: Task GS-3 - Fresh Extraction Mode

═══════════════════════════════════════════════════════════════════════════════
TASK ID:       GS-3
TASK NAME:     Add fresh extraction mode to validation script
WORKSTREAM:    Testing Infrastructure
SOURCE:        Gold Standard Regression Testing Framework Plan
STATUS:        PENDING
COMPLETION:    N/A
TIME ESTIMATE: 2-3 hours (implementation 1.5 hr, testing 1 hr)
TIME ACTUAL:   N/A
RISK LEVEL:    Low (adding new mode, not changing existing logic)
TASK SIZE:     M
DEPENDS ON:    GS-2
UNLOCKS:       GS-5
BLOCKS:        None
PARALLEL WITH: GS-4
═══════════════════════════════════════════════════════════════════════════════

## Objective

Add a `--mode fresh` option to the validation script that re-segments filing HTML and generates candidates from scratch, enabling testing of keyword changes without relying on database candidates.

**Business Rationale**: When modifying keyword patterns, developers need to test against actual filing content, not potentially stale database candidates. Fresh extraction ensures changes are tested end-to-end.

**Current Behavior**: Validation only compares against candidates already in the database, which may not reflect recent code changes.

**Desired Behavior**: With `--mode fresh`, the script downloads/reads filing HTML, segments it, generates candidates, and compares to gold standard.

## Prerequisites

- GS-2 complete (enhanced validation script exists)

## Files to Modify

1. **`scripts/validate_against_gold_standard.py`** - Add `--mode fresh|db` and fresh extraction logic

## Files to Create

1. **`src/gold_standard/fresh_extractor.py`** - Module to run fresh extraction on filings
2. **`tests/unit/gold_standard/test_fresh_extractor.py`** - Unit tests for fresh extraction

## Files to Read (Context Only)

- `src/extraction/html_segmenter.py` - HTMLSegmenter for parsing filings
- `src/review/candidate_generator.py` - CandidateGenerator for generating candidates
- `data/gold_standard/golden_set_251218.csv` - Contains filing URLs to process
- `tests/integration/test_gold_standard_coverage.py` - Existing fresh extraction tests for reference

## Implementation Requirements

### Core Functionality

1. **New CLI Argument**
   - `--mode fresh|db` - Choose extraction source (default: `db`)
   - `fresh`: Re-segment filing and generate candidates
   - `db`: Use existing candidates from database (current behavior)

2. **Fresh Extraction Pipeline**
   - Parse accession number from gold standard Document URL
   - Locate filing HTML in `data/filings/` cache
   - If not cached, fetch from SEC EDGAR
   - Run `HTMLSegmenter.segment_filing()` on HTML
   - Run `CandidateGenerator.generate_for_filing()` on segments
   - Return candidates for comparison

3. **Filing URL to Path Resolution**
   - Parse SEC URL: `https://www.sec.gov/Archives/edgar/data/{CIK}/{accession}/{filename}`
   - Map to local path: `data/filings/{CIK}/{accession}/{filename}`
   - Handle alternative paths if primary not found

4. **Caching Strategy**
   - Check local cache first (`data/filings/`)
   - Only fetch from SEC if not cached
   - Respect SEC rate limiting (100ms between requests)

5. **Progress Reporting**
   - Show which filing is being processed
   - Show segmentation/generation progress
   - Report any filings that couldn't be processed

### Error Handling

- **Filing not found locally**: Attempt SEC fetch, warn if both fail
- **Segmentation failure**: Log error, skip filing, continue with others
- **No segments generated**: Warn, treat as zero candidates

### Performance Requirements

- Cache filing HTML to avoid repeated downloads
- Process filings sequentially (SEC rate limiting)
- Expect ~30-60 seconds per filing for segmentation

## Test Requirements

### Coverage Target: **>= 85%** for `src/gold_standard/fresh_extractor.py`

### Test Categories (10+ tests recommended)

1. **URL Parsing** (3-4 tests)
   - Parse SEC URL to CIK/accession
   - Handle different URL formats
   - Invalid URL returns None

2. **Local Cache Lookup** (2-3 tests)
   - Find cached filing
   - Return None for missing file
   - Handle alternative paths

3. **Fresh Extraction** (3-4 tests)
   - Segment filing and generate candidates
   - Handle empty segments
   - Integration with existing test filings

4. **Error Handling** (2-3 tests)
   - Missing filing handled gracefully
   - Segmentation error logged and skipped

## Acceptance Criteria

- [ ] `--mode fresh|db` argument added to script
- [ ] `--mode fresh` segments filing HTML and generates candidates
- [ ] Filing URL parsed to locate local cache
- [ ] SEC fetch attempted if not cached (with rate limiting)
- [ ] Progress reported during extraction
- [ ] Failed filings logged but don't crash script
- [ ] **10+ unit tests** covering extraction logic
- [ ] **Test coverage >= 85%** for fresh_extractor module
- [ ] `mypy src/gold_standard/fresh_extractor.py --strict` passes
- [ ] `--mode db` behavior unchanged (backward compatible)
- [ ] All existing tests still pass

## Do NOT

- Modify `HTMLSegmenter` or `CandidateGenerator` internals
- Change database candidate retrieval logic
- Remove or alter existing CLI arguments
- Ignore SEC rate limiting requirements

## Verification Commands

```bash
# Test fresh mode works
python scripts/validate_against_gold_standard.py \
  --company "Slack Technologies" --mode fresh

# Test db mode still works (backward compatible)
python scripts/validate_against_gold_standard.py \
  --company "Slack Technologies" --mode db

# Run unit tests
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/gold_standard/test_fresh_extractor.py -v

# Check coverage
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/gold_standard/test_fresh_extractor.py \
  --cov=src/gold_standard/fresh_extractor --cov-report=term-missing --cov-fail-under=85

# Type safety check
mypy src/gold_standard/fresh_extractor.py --strict
```

## Auto-Generated Verification Script

```bash
#!/bin/bash
# Verification for Task GS-3: Fresh Extraction Mode
set -e

echo "═══════════════════════════════════════════════════════════════════════════════"
echo "Verifying Task GS-3: Fresh Extraction Mode"
echo "═══════════════════════════════════════════════════════════════════════════════"

cd "/Users/rgmarkey/Library/CloudStorage/OneDrive-CMASB/Analytics/Filings Analysis/Filings review tool/filings_reviewer"

# Check --mode argument exists
echo "Checking: --mode argument exists..."
python scripts/validate_against_gold_standard.py --help | grep -q "mode"

# Check fresh_extractor module exists
echo "Checking: fresh_extractor.py exists..."
test -f src/gold_standard/fresh_extractor.py

# Type safety
echo "Checking: mypy passes..."
mypy src/gold_standard/fresh_extractor.py --strict

# Run unit tests
echo "Running unit tests..."
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/gold_standard/test_fresh_extractor.py -v \
  --cov=src/gold_standard/fresh_extractor --cov-report=term-missing --cov-fail-under=85

echo "═══════════════════════════════════════════════════════════════════════════════"
echo "All acceptance criteria verified for Task GS-3!"
echo "═══════════════════════════════════════════════════════════════════════════════"
```

## Critical Evaluation Phase

**Required for all tasks. Depth scales with task size (M = thorough review).**

After verification passes but BEFORE committing:
1. Code Quality Review (linting, DRY, naming, error handling)
2. Test Coverage Assessment (edge cases, negative tests)
3. Architecture Alignment (CLAUDE.md patterns, minimal changes)
4. Identify Improvements (optimizations, edge cases, simplifications)
5. **User Approval (REQUIRED)** - STOP and ask user before proceeding
6. Implement Approved Changes
7. Generate Follow-Up Tasks for deferred improvements
8. Update Documentation
9. Commit and Push

## Reference

- **Issue source**: Gold Standard Regression Testing Framework Plan
- **Dependencies**: GS-2 (enhanced validation script)
- **Related**: tests/integration/test_gold_standard_coverage.py (existing fresh extraction tests)

---

**Last Updated**: 2025-12-31
**Format Version**: 2.4
