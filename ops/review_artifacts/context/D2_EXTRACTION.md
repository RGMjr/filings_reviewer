# D2: Extraction Quality Review Context

## Dimension Focus
False positives, false negatives, keyword patterns, table parsing, chart detection, value extraction accuracy.

## Primary Files to Review

### src/extraction/html_segmenter.py (2,029 LOC, MI=0.0, CC=37)
**Role**: Parses filing HTML into segments (paragraphs, tables, footnotes)
**Complexity**: Average CC=9.8, Max CC=37 (`segment_filing`)
**Coverage**: 84%
**Key concerns**:
- 6 sub-phases of complex processing
- Character encoding detection with fallback cascade (80% confidence threshold)
- Heading cache that's never invalidated
- Fractional sequence indices for composite segments (float precision risk)

**Code Sample** (lines 77-100):
```python
class HTMLSegmenter:
    """
    Segment SEC filing HTML into source_segments for metric extraction.

    Segments types:
        - paragraph: Text paragraphs
        - table: HTML tables
        - footnote: Footnotes and endnotes
        - definition_block: Detected definition sections
        - methodology_block: Detected calculation methodology sections
        - other: Fallback for other content
    """

    # Minimum text length for a segment to be included
    MIN_SEGMENT_LENGTH = 50

    # Maximum text length for a single text segment
    MAX_SEGMENT_LENGTH = 10000

    # Maximum text length for tables (higher limit to preserve data integrity)
    TABLE_MAX_LENGTH = 25000

    # Parallel processing configuration (SEG11)
    PARALLEL_SENTENCE_DETECTION_WORKERS = 4
```

**Known Issues**:
1. **Fractional sequence indices** (line 940): Float precision could cause collisions
2. **Heading cache**: Never invalidated if DOM changes during processing
3. **Charset encoding**: 80% confidence threshold may reject valid encodings
4. **Encoding fallback**: UTF-8 → Latin-1 cascade may miss other encodings

---

### src/extraction/value_extractor.py (582 LOC, CC=34)
**Role**: Extracts numeric values from segments
**Coverage**: 66% (**lowest of core modules**)
**Complexity**: Average CC=7.2, Max CC=34 (`_parse_table_row`)
**Key concerns**:
- Only 66% test coverage (critical gap for extraction quality)
- LLM metric name mapping with 170+ manual entries
- LLM-first extraction with rule-based fallback
- Complex table row parsing logic

**Code Sample** - `_parse_table_row` function (lines 1179-1329, CC=34):
```python
def _parse_table_row(
    self,
    cells: list,
    headers: list[str],
    column_info: dict,
    segment: SourceSegment,
    company_id: int,
    row_parser: TableRowParser | None = None,
) -> list[MetricValue]:
    """
    Parse a single table row to extract metric values.

    Args:
        cells: List of table cells
        headers: List of header labels
        column_info: Column type information
        segment: Source segment
        company_id: Company ID
        row_parser: Optional TableRowParser for row boundary validation (EI-4)

    Returns:
        List of MetricValue objects from this row
    """
    values = []

    # Extract cohort label from first column if it's a cohort column
    cohort_label = None
    cohort_type = None
    cohort_normalized = None
    cohort_position = None  # EI-4: Track cohort position for row validation

    for i, info in column_info.items():
        if info["type"] == "cohort" and i < len(cells):
            cohort_label = self._clean_text(cells[i].get_text())
            cohort_type, cohort_normalized = self.parse_cohort_label(cohort_label)
            # EI-4: Find position of cohort label for row validation
            if cohort_label and segment.raw_text:
                cohort_position = segment.raw_text.find(cohort_label)
            break

    # ... (continues with cross-row validation, false positive filtering, etc.)
```

**LLM Mapping Concern**: 170+ entry manual mapping in `openai_client.py`:
```python
METRIC_NAME_MAPPING = {
    "total_customers": "cm_customers_period_end",
    "paid_customers": "cm_customers_period_end",
    "active_customers": "cm_active_customers_total",
    # ... 167 more entries
}
```

---

### src/review/table_structure.py (250 LOC)
**Role**: Row-aware table parsing for same-row validation
**Coverage**: 98%
**Key concerns**:
- Text position estimation can be brittle
- Whitespace normalization differences
- Approximate matching fallback when exact match fails

**Algorithm**:
1. Parse HTML table structure
2. Extract text from each cell
3. Find cell text positions in rendered text
4. Build position → row mapping
5. Validate keyword/number pairs are in same row

**Failure Modes**:
- Whitespace differences between HTML and rendered text
- Cell text appears multiple times in document
- Colspan/rowspan complicates position mapping
- Fallback approximate matching may introduce errors

---

### src/review/false_positive_filter.py (750 LOC, CC=32)
**Role**: Filter false positives (dates, references, page numbers)
**Complexity**: Max CC=32 (`is_false_positive`)
**Coverage**: 99%
**Key concerns**:
- Multiple overlapping rules (hard to understand precedence)
- Hard to debug which rule triggered
- Format validation (count vs dollar vs percentage)

**Filter Categories**:
1. **Date patterns**: "12 months", "fiscal year 2023"
2. **Page/footnote references**: "page 12", "note 3"
3. **Address/phone numbers**: ZIP codes, phone patterns
4. **Generic numbers**: Ordinals, quantities without context
5. **Format mismatches**: Dollar value for percentage metric

---

### config/metric_keywords.yaml (545 lines, 45+ metrics)
**Role**: Defines patterns for all supported metrics
**Key concerns**:
- Exclusion patterns may be incomplete
- Required context patterns for some metrics (revenue synonyms)
- Deprecated metrics still in config
- No schema validation

**Example Metric - cm_net_dollar_retention**:
```yaml
cm_net_dollar_retention:
  patterns:
    - '\bnet\s+dollar\s+retention\b'
    - '\bNDR\b'
    - '\bnet\s+retention\b'
  exclusions:
    - '\bgross\s+retention\b'
    - '\bcontribution\s+margin\b'
  specific_patterns:
    - 'net\s+(dollar\s+)?retention'
```

**Example Required Context - cm_gmv**:
```yaml
cm_gmv:
  required_context:
    patterns:
      - '\bcohort\b'
      - '\bper\s+customer\b'
    proximity_chars: 1500
  patterns:
    - '\bGMV\b'
    - '\bgross\s+merchandise\s+value\b'
```

---

### src/review/candidate_generator.py - `_process_segment` (lines 481-847, CC=57)
**Role**: Core extraction logic - finds numbers and matches keywords
**Complexity**: CC=57 (CRITICAL - highest in codebase)
**Coverage**: 98%

**Responsibilities** (in order):
1. Skip definition segments
2. Find all numbers in text
3. Pre-compute keyword matches
4. Pre-compute boundaries (semantic, sentence, table row)
5. For each number:
   - Filter false positives
   - Find nearby keywords (respecting boundaries)
   - Check context prefix if no keywords nearby
   - Validate exclusion patterns
   - Compute distance and features
   - Score confidence
6. Enrich with "respectively" patterns
7. Apply learned rule filtering
8. Type validation (percentage/dollar/count metrics)

**Complexity Sources**:
- 7 major phases (sequential processing)
- 10+ conditional branches per number
- Boundary detection logic (3 types)
- Error handling for each number
- Feature computation with context analysis
- Multiple filtering layers

---

## Review Questions

### 1. False Positive Root Causes
**Question**: What patterns cause the most false positives? Are the filter rules adequate?

**Known FP Sources** (from static analysis summary):
1. **Cross-row matches**: Keyword in one row, value in another (addressed by table row parser)
2. **Post-number units**: "X% increase" matched to percentage metrics (FIX-A context check)
3. **Date-like numbers**: "12 months", "Q1 2023" (filtered by false_positive_filter.py)
4. **Definition sections**: Explanatory text without values (filtered by `contains_definition_flag`)
5. **Revenue synonym ambiguity**: GMV/TCV without cohort context (required_context patterns)

**Coverage Gaps**:
- `value_extractor.py` only 66% covered - missing edge case tests for FP scenarios
- No adversarial testing for malicious/malformed input

### 2. False Negative Gaps
**Question**: What valid metrics are being missed? Are keyword patterns comprehensive?

**Known FN Sources**:
1. **Wide tables**: Row heading >100 chars from values (FIX-5: skip distance filter for tables)
2. **Context prefix**: Keyword in previous segment (Phase 7: check context_prefix)
3. **Synonym gaps**: Valid phrases not in keyword patterns
4. **Exclusion over-filtering**: Legitimate values excluded by broad exclusion patterns

**Current Precision/Recall** (from gold standard):
- Precision: ~91% (good)
- Recall: ~85% (room for improvement)
- F1: ~88%

**Gap Analysis**:
- 15% of valid metrics missed (false negatives)
- Are these systematic (pattern gaps) or edge cases (variant phrasings)?

### 3. Table Row Estimation
**Question**: Is the row position estimation in table_structure.py reliable across HTML variations?

**Reliability Factors**:
1. **Exact text match**: Works when cell text unique and whitespace preserved
2. **Approximate match**: Fallback when exact fails - may introduce errors
3. **Marker-based**: `[ROW]`/`[CELL]` markers more reliable (when present)
4. **Colspan/rowspan**: Complex grid resolution (V2 implementation exists)

**Test Coverage**: 98% for table_structure.py, but integration testing limited

**Edge Cases**:
- Tables with merged cells
- Nested tables
- Tables with images/charts in cells
- Very wide tables (>20 columns)

### 4. Chart/Image Detection
**Question**: How accurate is cohort_chart_detector.py? What's the false positive rate?

**Detection Logic** (from architecture):
- Analyze image dimensions and aspect ratios
- Check nearby text for retention/cohort keywords
- Score relevance based on context

**Unknowns** (requires investigation):
- False positive rate (charts flagged incorrectly)
- False negative rate (charts missed)
- Precision across different chart types
- Handling of decorative images

### 5. LLM Mapping Maintainability
**Question**: The 170+ entry METRIC_NAME_MAPPING is manually maintained. Is this sustainable?

**Current Approach**:
```python
# src/llm/openai_client.py
METRIC_NAME_MAPPING = {
    "total_customers": "cm_customers_period_end",
    "paid_customers": "cm_customers_period_end",
    "active_customers": "cm_active_customers_total",
    # ... 167 more hardcoded entries
}
```

**Concerns**:
1. No versioning - additions/changes not tracked
2. No validation - typos silently break extraction
3. No bidirectional mapping - reverse lookup requires iteration
4. Duplicates manual effort from metric_keywords.yaml
5. Requires code change for new metric synonyms

**Alternative Approaches**:
- Auto-generate from metric_keywords.yaml patterns
- Use LLM for fuzzy matching without hardcoded map
- Validate mapping against keyword config on load

### 6. Exclusion Completeness
**Question**: Are exclusion patterns in metric_keywords.yaml comprehensive enough?

**Example Exclusions**:
```yaml
cm_customers_period_end:
  exclusions:
    - '\bretention\s+rate\b'
    - '\bnet\s+dollar\s+retention\b'
```

**Coverage Analysis Needed**:
1. Are exclusions tested systematically?
2. Do exclusions handle all ambiguous cases?
3. Are there cross-metric conflicts (one metric's pattern is another's exclusion)?
4. How often are exclusions updated vs patterns?

**From gold standard validation** (91% precision):
- 9% false positive rate suggests exclusions work reasonably well
- But are there systematic patterns in the 9% FPs?

---

## Known Extraction Issues

1. **Fractional sequence indices** (html_segmenter.py:940): Float precision could cause collisions
2. **Heading cache**: Never invalidated if DOM changes during processing
3. **Charset encoding**: 80% confidence threshold may reject valid encodings
4. **Cross-row false positives**: Can occur if row boundaries misdetected
5. **Definition merging**: May merge unrelated segments
6. **LLM mapping drift**: 170+ manual entries can become stale
7. **Value extractor coverage**: Only 66% - critical gap for extraction quality

---

## Key Metrics from Gold Standard

Current baseline (from SUMMARY.md and docs):
- **Precision**: ~91% (9% false positives)
- **Recall**: ~85% (15% false negatives)
- **F1**: ~88%
- **Companies**: 12 in gold standard (limited diversity)
- **Tolerance**: 1% regression threshold

**Validation Workflow**:
```bash
pytest -m gold_standard --gold-standard-mode=fresh -v
python scripts/validate_against_gold_standard.py --all --mode fresh
```

---

## Static Analysis Metrics

| File | LOC | CC (Max) | MI | Coverage | Priority |
|------|-----|----------|-----|----------|----------|
| html_segmenter.py | 2,029 | 37 | 0.0 | 84% | P0 |
| value_extractor.py | 582 | 34 | 13.75 | 66% | P0 |
| candidate_generator.py | 400 | 57 | A | 98% | P0 |
| false_positive_filter.py | 750 | 32 | A | 99% | P1 |
| table_structure.py | 250 | 15 | A | 98% | P1 |
| keyword_matching.py | 290 | 46 | A | 98% | P0 |

---

## Output Location
Write findings to: `ops/review_artifacts/claude/D2_findings.json`
