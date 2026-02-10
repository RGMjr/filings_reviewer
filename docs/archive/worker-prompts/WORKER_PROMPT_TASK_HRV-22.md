# WORKER PROMPT: Task HRV-22 - Fix HTMLSegmenter raw_html/raw_text Consistency Bug

===============================================================================
TASK ID:       HRV-22
TASK NAME:     Fix HTMLSegmenter bug where raw_text can contain content beyond raw_html
WORKSTREAM:    Human Review Validation / Extraction Bug Fix
SOURCE:        HRV-21 Diagnostic Findings + Critical Evaluation (2026-01-03)
STATUS:        🟡 PENDING
COMPLETION:    N/A
TIME ESTIMATE: 3-4 hours (investigation 45min, implementation 90min, testing 60min, re-extraction 30min)
TIME ACTUAL:   N/A
RISK LEVEL:    Medium - Changes text extraction behavior
               - Risk: Could change extraction results for truncated segments
               - Impact: Review candidates may change; TableRowParser depends on consistency
               - Likelihood: Low (fix ensures consistent limits + adds validation)
               - Mitigation: Re-extraction only for confirmed affected segments
TASK SIZE:     M
DEPENDS ON:    HRV-21
UNLOCKS:       HRV-16
BLOCKS:        None
PARALLEL WITH: None
===============================================================================

## Objective

Fix the HTMLSegmenter to ensure `raw_text` is always consistent with `raw_html`, then re-extract affected segments.

**Business Rationale**: TableRowParser uses `raw_html` to map row boundaries but searches for keywords/numbers in `raw_text`. When `raw_text` contains content that doesn't exist in `raw_html`, these positions can't be mapped to rows, causing valid candidates to be filtered out.

## Root Cause Analysis (REVISED)

### What We Know
- 13 Farfetch table segments have `raw_html` = 10,000 chars but `raw_text` = 716 chars
- Text extractable from the 10,000 char HTML is only 528 chars
- The extra 188 chars in `raw_text` include "Active Consumers" metrics that don't exist in `raw_html`
- **32 total table segments** across 6 filings have `raw_html` = 10,000 chars exactly
- **22 table segments** correctly use 25,000 char limit (TABLE_MAX_LENGTH)
- Some filings (e.g., filing 39) have BOTH limits in segments created at the same timestamp

### What We Don't Fully Understand
- The code at lines 761-762 clearly uses `TABLE_MAX_LENGTH` for tables since Dec 16, 2025
- Yet segments created AFTER that date still have 10,000 char limit
- The exact code path that created the 10,000 limit segments is unclear

### Confirmed Bug in `_split_composite_segment()`
Lines 908-910 unconditionally use `self.max_length` (10,000) for ALL pieces including tables:
```python
if len(text_content) > self.max_length:  # Bug: always 10000
    text_content = text_content[: self.max_length]
    html_content = html_content[: self.max_length]  # Should use TABLE_MAX_LENGTH for tables
```

### Strategy: Defensive Fix + Validation
Rather than trying to fully diagnose historical data issues:
1. Fix the confirmed `_split_composite_segment` bug
2. Add post-extraction validation to catch any future mismatches
3. Re-extract the 32 affected segments

## Prerequisites

- HRV-21 complete (confirmed data corruption exists)
- Docker database running (`docker compose up -d`)
- Read `docs/archive/HRV-21_DIAGNOSTIC_FINDINGS.md` for context

## Files to Modify

1. **`src/extraction/html_segmenter.py`** - Fix `_split_composite_segment()` + add validation
2. **`tests/unit/extraction/test_html_segmenter.py`** - Add focused truncation tests

## Implementation Requirements

### Phase 1: Investigation (30 min)

Verify the scope before coding:

```bash
# 1. Count affected segments by filing
PGPASSWORD=dev psql -h localhost -p 5433 -U dev -d filings_analysis -c "
SELECT s.filing_id, f.accession_number, COUNT(*) as affected_tables
FROM source_segments s
JOIN filings f ON s.filing_id = f.filing_id
WHERE s.segment_type = 'table' AND LENGTH(s.raw_html) = 10000
GROUP BY s.filing_id, f.accession_number
ORDER BY affected_tables DESC;"

# 2. Verify no fractional sequence indices (would indicate _split_composite_segment)
PGPASSWORD=dev psql -h localhost -p 5433 -U dev -d filings_analysis -c "
SELECT COUNT(*) as fractional_count
FROM source_segments
WHERE segment_type = 'table'
  AND LENGTH(raw_html) = 10000
  AND (sequence_index::float - sequence_index::int) != 0;"

# 3. Check if any segments have text longer than extractable from HTML
# (This confirms data corruption - run a Python script if needed)
```

**Document findings before proceeding.**

### Phase 2: Fix `_split_composite_segment()` (Required)

**Location**: Lines 908-910

**Current (buggy)**:
```python
# Truncate if needed
if len(text_content) > self.max_length:
    text_content = text_content[: self.max_length]
    html_content = html_content[: self.max_length]
```

**Fixed**:
```python
# Truncate if needed - use TABLE_MAX_LENGTH for tables
effective_max = self.TABLE_MAX_LENGTH if seg_type == "table" else self.max_length
if len(text_content) > effective_max:
    text_content = text_content[:effective_max]
if html_content and len(html_content) > effective_max:
    html_content = html_content[:effective_max]
```

Also update line 920:
```python
# Current
raw_html=html_content[: self.max_length] if html_content else None,

# Fixed
raw_html=html_content[:effective_max] if html_content else None,
```

### Phase 3: Add Post-Extraction Validation (New)

Add a validation method to detect mismatches:

```python
def _validate_text_html_consistency(
    self,
    raw_text: str,
    raw_html: str,
    segment_type: str
) -> bool:
    """
    Validate that raw_text content exists within raw_html.

    Returns True if consistent, False if mismatch detected.
    Logs warning on mismatch for monitoring.
    """
    if not raw_html:
        return True  # No HTML to validate against

    # Extract text from stored HTML
    try:
        soup = BeautifulSoup(raw_html, 'html.parser')
        html_text = soup.get_text()

        # Check if raw_text content is within what's extractable from HTML
        # Allow some tolerance for whitespace normalization differences
        if len(raw_text) > len(html_text) + 50:  # 50 char tolerance
            logger.warning(
                f"Text/HTML mismatch detected: raw_text={len(raw_text)} chars, "
                f"extractable from raw_html={len(html_text)} chars, "
                f"segment_type={segment_type}"
            )
            return False
    except Exception as e:
        logger.debug(f"Could not validate text/HTML consistency: {e}")

    return True
```

Call this at the end of `_extract_segment()` (after line 787):
```python
# Validate consistency (for monitoring)
self._validate_text_html_consistency(raw_text, raw_html, segment_type)
```

### Phase 4: Re-Extract Affected Segments (Required)

After deploying the fix, re-extract the affected filings:

```python
# Script: scripts/reextract_affected_segments.py
"""Re-extract segments with raw_html/raw_text mismatch."""

import os
from src.infra.db import Database
from src.extraction.html_segmenter import HTMLSegmenter
from src.filing_fetcher.fetcher import FilingFetcher

def get_affected_filing_ids(db: Database) -> list[int]:
    """Get filing IDs with 10000-char truncated tables."""
    query = """
        SELECT DISTINCT filing_id
        FROM source_segments
        WHERE segment_type = 'table' AND LENGTH(raw_html) = 10000
    """
    result = db.execute_query(query)
    return [row['filing_id'] for row in result]

def reextract_filing(filing_id: int, db: Database):
    """Delete and re-extract segments for a filing."""
    # Delete existing segments
    db.execute_query(
        "DELETE FROM source_segments WHERE filing_id = %s",
        (filing_id,)
    )

    # Re-fetch and re-extract
    # ... (use existing extraction pipeline)

if __name__ == "__main__":
    db = Database(os.environ["DATABASE_URL"])
    affected = get_affected_filing_ids(db)
    print(f"Found {len(affected)} affected filings: {affected}")

    for filing_id in affected:
        print(f"Re-extracting filing {filing_id}...")
        reextract_filing(filing_id, db)

    print("Done. Verify with validation query.")
```

**Alternative**: If a re-extraction script exists, use it. The key is to re-run extraction for filings: 28, 29, 30, 31, 39, 40.

## Test Requirements

### Coverage Target: **≥ 85%** for modified code paths

### Test Categories (6-8 tests)

#### 1. `_split_composite_segment` Fix (3 tests)

```python
def test_split_composite_table_uses_table_max_length():
    """Tables from _split_composite_segment use TABLE_MAX_LENGTH (25000)."""
    # Create composite segment with table > 10000 chars
    # Verify split table piece has html up to 25000, not 10000

def test_split_composite_paragraph_uses_max_length():
    """Paragraphs from _split_composite_segment use max_length (10000)."""

def test_split_composite_mixed_content():
    """Mixed text+table composite uses correct limits for each piece."""
```

#### 2. Validation Method (2 tests)

```python
def test_validate_consistency_detects_mismatch():
    """Validation detects when raw_text exceeds extractable HTML text."""

def test_validate_consistency_passes_for_valid():
    """Validation passes for consistent raw_text/raw_html."""
```

#### 3. Regression Test (1 test)

```python
def test_farfetch_table_pattern_fixed():
    """Reproduce Farfetch bug: 13666 char table should use 25000 limit."""
    # Create table HTML of 13666 chars
    # Extract via HTMLSegmenter
    # Verify raw_html is NOT truncated to 10000
    # Verify raw_text is extractable from raw_html
```

## Acceptance Criteria

- [ ] `_split_composite_segment()` uses `TABLE_MAX_LENGTH` for table pieces (lines 908-920 fixed)
- [ ] Post-extraction validation method added and called
- [ ] **6-8 unit tests** covering the fixes
- [ ] **Test coverage ≥ 85%** for modified code paths
- [ ] All new tests pass
- [ ] All existing tests still pass
- [ ] Affected segments re-extracted (32 segments across 6 filings)
- [ ] Post-re-extraction: No segments with raw_html=10000 AND segment_type='table' AND html > 10000 in source

## Do NOT

- Modify `src/review/table_structure.py` - that code is correct
- Change TABLE_MAX_LENGTH or max_length constants
- Over-engineer with full HTML re-parsing (validation check is sufficient)
- Skip the re-extraction step (fix alone won't help existing data)

## Verification Commands

```bash
# Run new tests
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/extraction/test_html_segmenter.py -v -k "split_composite or validate_consist" --tb=short

# Check coverage
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/extraction/test_html_segmenter.py \
  --cov=src/extraction/html_segmenter --cov-report=term-missing -q

# Full regression
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/extraction/ --no-cov -q

# Verify no affected segments remain after re-extraction
PGPASSWORD=dev psql -h localhost -p 5433 -U dev -d filings_analysis -c "
SELECT COUNT(*) as remaining
FROM source_segments
WHERE segment_type = 'table' AND LENGTH(raw_html) = 10000;"
```

## Auto-Generated Verification Script

```bash
#!/bin/bash
# Verification for Task HRV-22
set -e
echo "═══════════════════════════════════════════════════════════════"
echo "Verifying Task HRV-22: HTMLSegmenter Consistency Fix"
echo "═══════════════════════════════════════════════════════════════"

# 1. Run targeted tests
echo "✓ Running targeted tests..."
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/extraction/test_html_segmenter.py \
  -v -k "split_composite or validate_consist or farfetch" --tb=short

# 2. Full extraction test suite
echo "✓ Running full extraction test suite..."
TEST_DATABASE_URL="postgresql://dev:dev@localhost:5433/filings_analysis_test" \
  python3 -m pytest tests/unit/extraction/ --no-cov -q

# 3. Check for remaining affected segments
echo "✓ Checking for remaining affected segments..."
REMAINING=$(PGPASSWORD=dev psql -h localhost -p 5433 -U dev -d filings_analysis -t -c "
SELECT COUNT(*) FROM source_segments
WHERE segment_type = 'table' AND LENGTH(raw_html) = 10000;")

if [ "$REMAINING" -gt 0 ]; then
    echo "⚠️  Warning: $REMAINING segments still have 10000 char limit"
    echo "   Run re-extraction script to fix existing data"
else
    echo "✅ No affected segments remaining"
fi

echo "═══════════════════════════════════════════════════════════════"
echo "✅ Task HRV-22 verification complete!"
echo "═══════════════════════════════════════════════════════════════"
```

## Critical Evaluation Phase

After verification passes but BEFORE committing:

### 1. Code Quality Review
- [ ] `_split_composite_segment` fix is minimal and focused
- [ ] Validation method is lightweight (doesn't re-parse for every segment)
- [ ] No linting issues or type errors

### 2. Test Coverage Assessment
- [ ] `_split_composite_segment` table path tested
- [ ] Validation detection tested
- [ ] Farfetch regression pattern covered

### 3. Data Verification
- [ ] Re-extraction completed for affected filings
- [ ] No segments remain with 10000-char truncated tables

### 4. User Approval (REQUIRED)
**STOP and ask the user before committing.**

## Reference

- **Issue source**: HRV-21 Diagnostic Investigation + Critical Evaluation
- **Root cause**: `_split_composite_segment` uses wrong limit; possible historical data issues
- **Affected filings**: 28, 29, 30, 31 (Farfetch), 39, 40
- **Affected segment count**: 32 table segments
- **Related**: HRV-17 (table row parsing), HRV-16 (validation re-run)

---

**Last Updated**: 2026-01-03
**Format Version**: 2.7
**Revision Note**: Major revision after critical evaluation:
- Simplified solution (validation check instead of re-parsing)
- Added confirmed `_split_composite_segment` bug fix
- Included re-extraction in scope (was previously follow-up)
- Reduced test count from 12+ to 6-8
- Updated root cause analysis to note incomplete understanding
- Removed HRV-20 dependency (now superseded)
