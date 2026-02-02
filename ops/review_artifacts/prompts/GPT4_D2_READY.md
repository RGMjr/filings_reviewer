# GPT-4 Code Review: D2 Extraction Quality

**Copy this entire prompt and paste into GPT-4 (or GPT-4o)**

---

You are a senior software engineer reviewing the extraction quality of a system that pulls customer metrics from SEC filings.

## Project Context

- Extracts 45+ customer metrics (retention, churn, ARR, cohort data, etc.)
- **Current Performance**: Precision 91%, Recall 85%, F1 88%
- Pipeline: HTML parsing → keyword matching → value extraction → quality scoring
- Uses LLM (GPT-4o-mini) as fallback when rule-based extraction fails

## Static Analysis - Extraction Complexity

| Function | CC | File | Issue |
|----------|-----|------|-------|
| `_process_segment` | 57 | candidate_generator.py:481 | Core matching logic |
| `find_keywords_near_number` | 46 | keyword_matching.py:523 | Proximity matching |
| `_parse_table_row` | 34 | value_extractor.py:1179 | Table parsing |
| `is_false_positive` | 32 | false_positive_filter.py:722 | FP detection |

**Coverage Gap**: value_extractor.py has only 66% test coverage (critical module)

## Code to Review

### 1. Core Segment Processing (CC=57)
```python
# src/review/candidate_generator.py:481
def _process_segment(self, segment: Segment) -> List[ReviewCandidate]:
    """
    8 sequential phases:
    1. Extract numbers from text
    2. Find keywords near each number
    3. Check same-row constraint (tables)
    4. Apply false positive filters
    5. Extract context window
    6. Deduplicate by (position, metric_id)
    7. Score confidence
    8. Create ReviewCandidate objects
    """
    candidates = []
    numbers = self._extract_numbers(segment.text)  # Regex

    for num in numbers:
        keywords = self._find_keywords_near(num, segment.text)
        for kw in keywords:
            if self._is_same_row(num, kw, segment):  # Table check
                if not self._is_false_positive(num, kw, segment):
                    context = self._extract_context(num, segment)
                    # ... 200+ more lines of logic
```

### 2. Keyword Proximity Matching (CC=46)
```python
# src/review/keyword_matching.py:523
def find_keywords_near_number(
    self,
    number_position: int,
    text: str,
    max_distance: int = 100
) -> List[KeywordMatch]:
    """
    Search for metric keywords within max_distance chars of number.
    Handles:
    - Multiple keyword patterns per metric (45+ metrics)
    - Specific vs general patterns (confidence bonus)
    - Exclusion patterns (reject false matches)
    - Required context patterns (cohort, per-customer)
    """
```

### 3. Table Row Position Estimation
```python
# src/review/table_structure.py
def _find_row_boundaries(self, html: str, text: str) -> List[RowBoundary]:
    """
    Map character positions in extracted text back to HTML table rows.

    3-level fallback:
    1. Exact substring match
    2. Flexible whitespace match
    3. Approximate match (first few words)  # RISKY

    If boundaries wrong, can cause:
    - Cross-row false positives (matching keyword from different row)
    - Missed valid matches (false negatives)
    """
```

### 4. False Positive Filter Rules
```python
# src/review/false_positive_filter.py:722
def is_false_positive(self, number: ParsedNumber, keyword: str, segment: Segment) -> bool:
    """
    Multiple overlapping rules:
    - Date patterns (10 regex)
    - Reference patterns (page, note, section - 15 regex)
    - Year detection (1990-2100)
    - TOC proximity (within 50 chars)
    - Format validation (count vs $ vs %)
    - Min value threshold (default 10)
    - Label-embedded filtering ("Customers > $100K")
    """
```

### 5. LLM Metric Name Mapping (170+ entries)
```python
# src/extraction/value_extractor.py
METRIC_NAME_MAPPING = {
    "new customers": "cm_new_customers_acquired",
    "customers acquired": "cm_new_customers_acquired",
    "total customers": "cm_customers_period_end",
    "paid customers": "cm_customers_period_end",
    "active users": "cm_active_customers_total",
    # ... 170+ more entries
    # Manually maintained, no validation
}
```

### 6. Keyword Configuration (YAML)
```yaml
# config/metric_keywords.yaml (545 lines)
cm_new_customers_acquired:
  patterns:
    - '\bnew\s+customers?\b'
    - '\bcustomers?\s+acquired\b'
  exclusions:
    - '\bacquisition\s+cost\b'  # Avoid CAC confusion
  specific_patterns:
    - '\bnew\s+paid\s+customers\b'  # Higher confidence
```

## Review Questions

1. **False Positive Root Causes**: What patterns cause the 9% false positive rate?
2. **False Negative Gaps**: Why are 15% of valid metrics missed?
3. **Table Row Estimation**: Is the approximate matching fallback safe?
4. **LLM Mapping Maintainability**: 170+ manual entries - sustainable?
5. **Exclusion Completeness**: Are exclusion patterns comprehensive?
6. **Complexity**: Should CC=57 `_process_segment` be decomposed?

## Output Format

```json
{
  "dimension": "D2_EXTRACTION",
  "model": "gpt4",
  "findings": [
    {
      "id": "G-D2-001",
      "severity": "Critical|High|Medium|Low",
      "category": "extraction",
      "title": "Short title",
      "description": "Detailed description with specific patterns/code",
      "file": "path/to/file.py",
      "line_range": "100-150",
      "impact_on_metrics": "Affects precision/recall/F1 by...",
      "recommendation": "What to do",
      "effort": "XS|S|M|L|XL"
    }
  ],
  "summary": "Overall extraction quality assessment"
}
```

Provide 10-15 findings focusing on extraction accuracy improvements.
