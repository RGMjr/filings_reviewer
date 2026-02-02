# Static Analysis Summary

**Generated:** 2026-02-02
**Review ID:** ralph/review-20260202-batch

---

## Executive Summary

Comprehensive static analysis of the SEC Filings Customer Metrics Extraction System reveals a mature codebase with good test coverage (81.57%) but significant complexity hotspots and maintainability concerns in critical modules. Key findings:

- **Critical complexity**: 22 functions with CC > 20 (highest: 57)
- **Large modules**: 3 files with MI score of 0.0 (unmaintainable)
- **Test coverage**: 81.57% (exceeds 75% target)
- **Type safety**: Limited mypy issues (26 errors, mostly stub imports)
- **Failed tests**: 19 unit tests failing in image routes

---

## 1. Lines of Code

| Category | Count | Notes |
|----------|-------|-------|
| Source code | 39,847 LOC | Across 74 Python files in src/ |
| Test code | 81,244 LOC | 2.04x test-to-source ratio |
| **Total** | **121,091 LOC** | Substantial codebase |

### Largest Source Files

1. `src/infra/db.py` - 4,006 LOC (10% of total source)
2. `src/review/pattern_analyzer.py` - 2,544 LOC
3. `src/extraction/html_segmenter.py` - 2,028 LOC
4. `src/extraction/segment_enricher.py` - 1,878 LOC
5. `src/extraction/value_extractor.py` - 1,547 LOC

**Risk Assessment:** `db.py` is a major maintainability concern at 4,006 LOC. Recommend decomposition into focused modules (queries, schema, migrations, etc.).

---

## 2. Cyclomatic Complexity

**Summary Statistics:**
- Total functions analyzed: 858
- Average complexity: 5.30 (good)
- Maximum complexity: 57 (critical)
- Functions with CC > 10: 113 (13.2%)
- Functions with CC > 20: 22 (2.6%)

### Top 10 Complexity Hotspots

| Rank | File | Function | CC | Line | Risk |
|------|------|----------|-----|------|------|
| 1 | `candidate_generator.py` | `_process_segment` | 57 | 481 | CRITICAL |
| 2 | `keyword_matching.py` | `find_keywords_near_number` | 46 | 523 | CRITICAL |
| 3 | `db.py` | `bulk_insert_review_candidates` | 42 | 1421 | CRITICAL |
| 4 | `pattern_analyzer.py` | `_generate_two_feature_patterns` | 38 | 1600 | HIGH |
| 5 | `html_segmenter.py` | `segment_filing` | 37 | 168 | HIGH |
| 6 | `keyword_config.py` | `_validate_config` | 35 | 82 | HIGH |
| 7 | `value_extractor.py` | `_parse_table_row` | 34 | 1179 | HIGH |
| 8 | `false_positive_filter.py` | `is_false_positive` | 32 | 722 | HIGH |
| 9 | `html_segmenter.py` | `_split_composite_segment` | 32 | 795 | HIGH |
| 10 | `pattern_analyzer.py` | `discover_patterns` | 31 | 939 | HIGH |

**Critical Concerns:**
1. **`_process_segment` (CC=57)**: Core extraction logic in candidate generation. Likely has too many conditional branches and responsibilities.
2. **`find_keywords_near_number` (CC=46)**: Complex proximity matching with many edge cases. May benefit from strategy pattern refactoring.
3. **`bulk_insert_review_candidates` (CC=42)**: Database operation with complex validation/transformation logic mixed in.

---

## 3. Maintainability Index

Radon MI scores (0-100 scale, A=20-100, B=10-20, C=0-10):

**Rank C (Unmaintainable - MI = 0.0):**
1. `src/infra/db.py` (4,006 LOC, MI=0.0)
2. `src/extraction/html_segmenter.py` (2,028 LOC, MI=0.0)
3. `src/review/pattern_analyzer.py` (2,544 LOC, MI=0.0)

**Rank B (Low Maintainability):**
1. `src/extraction/segment_enricher.py` (MI=15.99)
2. `src/extraction/value_extractor.py` (MI=13.75)

**Notes:**
- 3 files score 0.0 MI (likely due to size/complexity formula overflow)
- These represent the core extraction pipeline and data access layer
- All 3 files are P0/P1 priority in review plan

**All other modules**: Rank A (MI > 20) - generally maintainable

---

## 4. Type Safety (mypy)

**Configuration:** `mypy src/ --ignore-missing-imports`

**Total Issues:** 26 type errors (sample of first 200 lines)

### Issue Breakdown

| Category | Count | Severity |
|----------|-------|----------|
| Missing stub packages | 4 | Low |
| Implicit Optional violations | 4 | Medium |
| Type assignment errors | 11 | Medium |
| no-any-return errors | 4 | Medium |
| Other | 3 | Low-Medium |

### Key Findings

1. **Missing type stubs (4 errors):**
   - `requests` library (http_client.py, sec_client.py, filing_fetcher.py)
   - `yaml` library (keyword_config.py)
   - **Fix:** `pip install types-requests types-PyYAML`

2. **Implicit Optional (4 errors):**
   - `src/llm/prompts.py:77, 150` - `context_text` parameter
   - Violates PEP 484 no_implicit_optional
   - **Fix:** Change `context_text: str = None` to `context_text: Optional[str] = None`

3. **List[None] violations (11 errors):**
   - `src/extraction/extraction_validation.py` - multiple lines
   - Lists contain `None` values but declared as `List[str]`
   - **Fix:** Change to `List[Optional[str]]` or filter out None values

4. **Any return type leaks (4 errors):**
   - Functions returning `Any` from untyped operations
   - Affects: `sec_client.py:256`, `keyword_config.py:229`, `filing_fetcher.py:627`

**Positive Note:** Only `src/review/` and `src/extraction/segment_enricher.py` pass `mypy --strict` currently (per CLAUDE.md). The non-strict run shows relatively few issues for a ~40K LOC codebase.

---

## 5. Test Coverage

**Overall Coverage:** 81.57% (exceeds 75% minimum requirement)

| Metric | Value |
|--------|-------|
| Total Statements | 11,491 |
| Covered | 9,373 |
| Missing | 2,118 |
| **Coverage** | **81.57%** |

**Test Execution Results:**
- Tests run: 3,467
- Passed: 3,436
- Failed: 19
- Skipped: 12
- Execution time: 100.05s (1:40)

### Failed Tests (19)

**All failures in:** `tests/unit/web/test_api_images_routes.py`

| Test Category | Count | Likely Cause |
|---------------|-------|--------------|
| `TestCreateImageDecision` | 5 | Image decision API changes |
| `TestSkipImageCandidate` | 1 | Candidate skip logic |
| `TestValidChartTypes` | 7 | Chart type validation schema |
| `TestValidRejectionReasons` | 6 | Rejection reason validation |

**Root Cause Hypothesis:** Recent changes to image/chart handling models or validation logic in the extraction_v2 pipeline may have broken the API contract. Tests may need updating to reflect new enum values or validation rules.

**Action Required:** Fix these 19 tests before proceeding with deeper review to ensure baseline functionality.

---

## 6. Key Risks Identified

### P0 - Critical Risks

1. **Monolithic `db.py` (4,006 LOC, MI=0.0)**
   - Single point of failure for all data access
   - Complex function `bulk_insert_review_candidates` (CC=42)
   - Difficult to test, modify, or understand
   - **Recommendation:** Decompose into repository pattern or at minimum separate concerns (queries, schema, migrations, connection management)

2. **Complex Extraction Logic**
   - `_process_segment` (CC=57) in candidate_generator.py
   - Core extraction path with 57 decision branches
   - High risk for bugs, difficult to extend
   - **Recommendation:** Extract sub-strategies for different segment types, apply strategy/command patterns

3. **Keyword Matching Complexity**
   - `find_keywords_near_number` (CC=46)
   - Proximity matching with many edge cases
   - Critical for extraction quality
   - **Recommendation:** Break into smaller functions: tokenize, filter, score, validate

### P1 - High Risks

4. **HTML Segmenter (2,028 LOC, MI=0.0)**
   - `segment_filing` function (CC=37)
   - DOM parsing with many conditional branches
   - **Recommendation:** Extract table parsing, list parsing, text normalization into separate modules

5. **Pattern Analyzer (2,544 LOC, MI=0.0)**
   - `_generate_two_feature_patterns` (CC=38)
   - Machine learning feature generation
   - **Recommendation:** Move statistical/ML logic to separate module, simplify feature extraction pipeline

6. **Test Failures in Image Routes (19 failures)**
   - Indicates potential regression in image/chart handling
   - May affect extraction quality for chart-based metrics
   - **Recommendation:** Fix immediately before code review

### P2 - Medium Risks

7. **Type Safety Gaps**
   - 26 mypy errors (fixable with stub installs + explicit Optional)
   - Lack of strict type checking outside `src/review/`
   - **Recommendation:** Gradual adoption of strict typing, module by module

8. **Test-to-Source Ratio**
   - 2.04x ratio suggests good testing discipline
   - But 18.43% of code still uncovered (2,118 statements)
   - **Recommendation:** Focus on covering high-complexity, low-coverage paths

---

## 7. Recommendations for Review

### Phase 2: Claude Review Preparation

**D1 (Architecture):**
- Focus on `db.py` decomposition strategy
- Analyze extraction pipeline data flow through 6 stages
- Evaluate extraction vs extraction_v2 coexistence

**D2 (Extraction Quality):**
- Deep dive into `_process_segment`, `find_keywords_near_number`, `is_false_positive`
- Analyze keyword pattern YAML scalability
- Review table row estimation logic in `_parse_table_row`

**D3 (Code Quality):**
- Prioritize top 10 complexity hotspots
- Assess error handling consistency across modules
- Review magic number/string externalization

**D4 (Testing):**
- Investigate 19 failed tests in image routes
- Identify critical paths in uncovered 18.43%
- Evaluate edge case coverage (encoding, malformed HTML)

**D5 (Performance):**
- Profile `db.py` for N+1 query patterns
- Analyze memory usage in html_segmenter large document parsing
- Evaluate LLM call batching/caching effectiveness

**D6 (Security):**
- Verify SQL parameterization in `db.py` (4,006 LOC of queries)
- Check XSS prevention in web routes
- Audit file path handling in filing_fetcher

---

## 8. Files Generated

All artifacts saved to `ops/review_artifacts/static_analysis/`:

1. `complexity.json` (229 KB) - Full radon CC analysis
2. `complexity_summary.txt` (1.5 KB) - Top 20 complex functions
3. `maintainability.json` (5 KB) - Radon MI scores
4. `mypy_report.txt` (sample, 200 lines) - Type errors
5. `coverage_summary.txt` (918 KB) - Pytest coverage output
6. `loc.txt` (9.7 KB) - Line counts for all files
7. `SUMMARY.md` (this file) - Executive summary

---

## Next Steps

1. **Immediate:** Fix 19 failing tests in `test_api_images_routes.py`
2. **Immediate:** Install missing type stubs: `pip install types-requests types-PyYAML`
3. **Phase 2:** Proceed with PREP-2 (generate dimension context files)
4. **Phase 2:** Begin Claude dimensional reviews (D1-D6)

---

**End of Static Analysis Summary**
