# WORKER PROMPT: Task EXT-VAL-1 - Fix Validation Script Filing Path Resolution

═══════════════════════════════════════════════════════════════════════════════
TASK ID:       EXT-VAL-1
TASK NAME:     Fix validate_against_gold_standard.py to find filings in gold_standard directory
WORKSTREAM:    Extraction Improvement
SOURCE:        Extraction Quality Analysis (2026-01-13)
STATUS:        🟡 PENDING
COMPLETION:    N/A
TIME ESTIMATE: 1-2 hours (investigation 20 min, implementation 40 min, testing 30 min)
TIME ACTUAL:   N/A
RISK LEVEL:    Low - Path resolution change, no extraction logic affected
TASK SIZE:     S
DEPENDS ON:    None
UNLOCKS:       None (enables better validation workflow)
BLOCKS:        None
PARALLEL WITH: EXT-FP-1, EXT-FN-1
═══════════════════════════════════════════════════════════════════════════════

## Objective

Fix the `fresh_extractor.py` module to find gold standard filing HTML files in their actual location (`data/gold_standard/{company}/filing.html`) instead of only looking in `data/filings/`. Currently, validation fails for 3 of 4 gold standard companies because the script can't find their filings.

**Business Rationale**: Cannot validate extraction changes against the full gold standard set, limiting ability to measure precision/recall improvements accurately.

**Current Behavior**:
- `fresh_extractor.py` looks for filings in `data/filings/{cik}/{accession}/`
- Gold standard filings are stored in `data/gold_standard/{company}/filing.html`
- Validation fails with "Filing not found" for Slack, Farfetch, Samsara Vision

**Desired Behavior**:
- Script first checks `data/gold_standard/{company}/filing.html`
- Falls back to `data/filings/{cik}/{accession}/` if not found in gold_standard
- All 4 gold standard companies validate successfully

## Prerequisites

- Understanding of gold_standard directory structure
- Familiarity with fresh_extractor.py path resolution

## Files to Modify

1. **`src/gold_standard/fresh_extractor.py`** - Add gold_standard path lookup and company_name parameter
2. **`scripts/validate_against_gold_standard.py`** - Pass company_name through `get_fresh_candidates()` to `extract_fresh()`
3. **`tests/unit/gold_standard/test_fresh_extractor.py`** - Add tests for new path resolution

## Files to Read (Context Only)

- `scripts/validate_against_gold_standard.py` - How fresh_extractor is called
- `data/gold_standard/` directory structure - Where filing.html files are located

## Implementation Requirements

### Core Functionality

1. **Add Gold Standard Path Lookup**
   - Modify `find_local_filing()` function signature to accept optional `company_name: str | None = None`
   - Current signature: `find_local_filing(parsed_url: ParsedSecUrl, base_dir: str | Path = "data/filings")`
   - New signature: `find_local_filing(parsed_url: ParsedSecUrl, base_dir: str | Path = "data/filings", company_name: str | None = None)`
   - When `company_name` is provided, check gold_standard path FIRST before existing paths
   - Handle company name variations (spaces → underscores, special chars)

2. **Path Resolution Order** (when company_name provided)
   ```
   1. data/gold_standard/{normalized_company}/filing.html  # NEW - only if company_name provided
   2. data/filings/{cik}/{accession}/{filename}            # existing
   3. data/filings/{cik}/{accession}/primary.htm           # existing
   4. data/filings/{cik_unpadded}/{accession}/{filename}   # existing
   5. data/filings/{cik_unpadded}/{accession}/primary.htm  # existing
   ```

3. **Company Name Normalization** (create helper function `_normalize_company_for_path()`)
   - Replace spaces with underscores: "Slack Technologies" → "Slack_Technologies"
   - Replace periods with underscores: "Inc." → "Inc_"
   - Replace commas with empty string: "Farfetch, Ltd" → "Farfetch_Ltd"
   - Handle trailing punctuation: "Samsara Vision Inc." → "Samsara_Vision_Inc_"
   - Match existing directory naming convention in `data/gold_standard/`

4. **Update Callers**
   - `extract_fresh()` should pass `company_name` to `find_local_filing()` if available
   - Add optional `company_name` parameter to `extract_fresh()` signature
   - `get_fresh_candidates()` in validation script should pass company name from gold standard entry

### Gold Standard Directory Structure

```
data/gold_standard/
├── Slack_Technologies/
│   ├── filing.html          # ← This is what we need to find
│   ├── extracted_values.csv
│   └── metadata.json
├── Samsara_Vision_Inc_/
│   └── filing.html
├── Farfetch_Ltd/
│   └── (no filing.html - only extracted CSVs)
└── Snowflake_Inc/
    └── (uses data/filings/ path)
```

### Error Handling

- **Filing not in gold_standard**: Fall back to data/filings/ lookup (existing behavior)
- **Company name mismatch**: Log warning, try alternative normalizations
- **SEC wrapper handling**: filing.html may have `<DOCUMENT>` wrapper (already handled)

## Test Requirements

### Coverage Target: **Maintain existing coverage** for `fresh_extractor.py`

### Test Categories (8+ tests recommended)

1. **Gold Standard Path Resolution** (4-5 tests)
   - Find filing in gold_standard directory
   - Fall back to data/filings when not in gold_standard
   - Handle company name normalization (spaces, punctuation)
   - Handle trailing underscore in directory names

2. **Integration Tests** (2-3 tests)
   - Validate Slack filing is found via gold_standard path
   - Validate Snowflake filing still found via data/filings path
   - Validate fallback works when gold_standard path doesn't exist

### Known Edge Cases to Test

- Company names with "Inc.", "Ltd.", trailing periods
- Directory names with trailing underscores (Samsara_Vision_Inc_)
- Companies with only extracted CSVs (no filing.html) should fall back gracefully

## Acceptance Criteria

- [ ] Gold standard path lookup added to fresh_extractor.py
- [ ] Slack filing found at `data/gold_standard/Slack_Technologies/filing.html`
- [ ] Samsara Vision filing found at `data/gold_standard/Samsara_Vision_Inc_/filing.html`
- [ ] Snowflake still found via existing `data/filings/` path
- [ ] Farfetch gracefully reports "filing not found" (no filing.html exists)
- [ ] **8+ unit tests** covering path resolution scenarios
- [ ] All existing tests still pass

## Do NOT

- Modify gold_standard directory structure or file naming
- Change the validation script itself (`scripts/validate_against_gold_standard.py`) **except** to pass `company_name` to `get_fresh_candidates()`
- Add automatic SEC fetching (use existing `--allow-sec-fetch` flag if needed)
- Change how filings are processed after being found

## Verification Commands

```bash
# Run fresh_extractor tests
python3 -m pytest tests/unit/gold_standard/test_fresh_extractor.py -v

# Verify Slack is found via gold_standard path
cd /Users/rgmarkey/Library/CloudStorage/OneDrive-CMASB/Analytics/Filings\ Analysis/Filings\ review\ tool/filings_reviewer && python3 << 'EOF'
from src.gold_standard.fresh_extractor import find_local_filing, parse_sec_url

# Parse the SEC URL first
parsed = parse_sec_url("https://www.sec.gov/Archives/edgar/data/1764925/000162828019007428/slacks-1a3.htm")

# Test Slack (should find in gold_standard)
slack_path = find_local_filing(
    parsed_url=parsed,
    company_name="Slack Technologies"
)
print(f"Slack path: {slack_path}")
print(f"Found: {slack_path is not None}")
print(f"Expected: data/gold_standard/Slack_Technologies/filing.html")
EOF

# Run full validation on all companies
python scripts/validate_against_gold_standard.py --all --mode fresh
```

## Critical Evaluation Phase

**Required for all tasks. Depth: S (Standard)**

After verification passes but BEFORE committing:
1. Code Quality Review - Is path resolution logic clean and maintainable?
2. Test Coverage Assessment - Are all company name variations covered?
3. Architecture Alignment - Does this follow existing path resolution patterns?
4. **User Approval (REQUIRED)** - STOP and ask user before committing

## Expected Impact

**Before EXT-VAL-1**:
- Validation coverage: 1/4 companies (Snowflake only)
- Gold standard entries validated: 105/219 (48%)

**After EXT-VAL-1**:
- Validation coverage: 3/4 companies (Snowflake, Slack, Samsara Vision)
- Gold standard entries validated: ~152/219 (69%)
- Farfetch still missing (no filing.html in gold_standard)

## Reference

- **Issue source**: Extraction Quality Analysis (2026-01-13)
- **Dependencies**: None
- **Related**: HRV-2 (original validation script creation)

---

**Last Updated**: 2026-01-13
**Format Version**: 2.6
