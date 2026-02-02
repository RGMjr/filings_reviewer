# GPT-4 Code Review: D3 Code Quality

**Copy this entire prompt and paste into GPT-4**

---

You are a senior software engineer reviewing code quality of a Python SEC filing extraction system.

## Static Analysis Summary

**Codebase Size**: 39,847 LOC source, 81,244 LOC tests
**Test Coverage**: 81.57%
**mypy Errors**: 26 (mostly missing stubs)

### Top 10 Complexity Hotspots

| Rank | Function | CC | File |
|------|----------|-----|------|
| 1 | `_process_segment` | 57 | candidate_generator.py:481 |
| 2 | `find_keywords_near_number` | 46 | keyword_matching.py:523 |
| 3 | `bulk_insert_review_candidates` | 42 | db.py:1421 |
| 4 | `_generate_two_feature_patterns` | 38 | pattern_analyzer.py:1600 |
| 5 | `segment_filing` | 37 | html_segmenter.py:168 |
| 6 | `_validate_config` | 35 | keyword_config.py:82 |
| 7 | `_parse_table_row` | 34 | value_extractor.py:1179 |
| 8 | `is_false_positive` | 32 | false_positive_filter.py:722 |
| 9 | `_split_composite_segment` | 32 | html_segmenter.py:795 |
| 10 | `discover_patterns` | 31 | pattern_analyzer.py:939 |

**22 functions have CC > 20** (high complexity)
**113 functions have CC > 10** (moderate complexity)

### Maintainability Index (MI)

| File | LOC | MI Score | Rating |
|------|-----|----------|--------|
| db.py | 4,006 | 0.0 | Unmaintainable |
| html_segmenter.py | 2,028 | 0.0 | Unmaintainable |
| pattern_analyzer.py | 2,544 | 0.0 | Unmaintainable |
| segment_enricher.py | 1,878 | 15.99 | Low |
| value_extractor.py | 1,547 | 13.75 | Low |

### Type Safety Status

- `src/review/` - mypy --strict (enforced)
- `src/extraction/segment_enricher.py` - mypy --strict (enforced)
- Everything else - basic annotations only

### mypy Errors (26 total)

```
src/llm/prompts.py:77: error: Implicit Optional (context_text: str = None)
src/extraction/extraction_validation.py: 11 errors - List[None] violations
src/infra/sec_client.py:256: error: no-any-return
```

## Code Examples

### High Complexity Function (CC=57)
```python
def _process_segment(self, segment: Segment) -> List[ReviewCandidate]:
    # 400+ lines, 57 decision branches
    # Mix of:
    # - Number extraction
    # - Keyword matching
    # - Table row checking
    # - False positive filtering
    # - Context extraction
    # - Deduplication
    # - Confidence scoring
    # - Object creation
```

### Magic Numbers/Strings
```python
# Hardcoded thresholds scattered throughout:
MAX_KEYWORD_DISTANCE = 100  # chars
MIN_VALUE_THRESHOLD = 10
CONFIDENCE_THRESHOLD = 80  # percent
YEAR_RANGE = (1990, 2100)
TOC_PROXIMITY = 50  # chars
SEGMENT_LIMIT = 200  # for parallel processing
```

### Error Handling Pattern (inconsistent)
```python
# Some modules use exceptions:
raise ExtractionError(f"Failed to parse: {e}")

# Others use return codes:
if error:
    return None, "parse_failed"

# Others silently continue:
try:
    value = extract(text)
except:
    pass  # Ignore and continue
```

## Review Questions

1. **Complexity Decomposition**: How should CC=57 `_process_segment` be refactored?
2. **Type Safety Expansion**: Which modules should get mypy --strict next?
3. **Error Handling**: What's the right error handling strategy?
4. **Magic Values**: Should all thresholds be in config?
5. **Code Duplication**: Are there DRY violations?
6. **Documentation**: Are docstrings accurate?

## Output Format

```json
{
  "dimension": "D3_CODE_QUALITY",
  "model": "gpt4",
  "findings": [
    {
      "id": "G-D3-001",
      "severity": "Critical|High|Medium|Low",
      "category": "quality",
      "title": "Short title",
      "description": "Detailed description",
      "file": "path/to/file.py",
      "line_range": "100-150",
      "code_before": "current problematic code",
      "code_after": "suggested improvement",
      "recommendation": "What to do",
      "effort": "XS|S|M|L|XL"
    }
  ],
  "summary": "Overall code quality assessment"
}
```

Provide 10-15 findings focusing on maintainability and code health.
