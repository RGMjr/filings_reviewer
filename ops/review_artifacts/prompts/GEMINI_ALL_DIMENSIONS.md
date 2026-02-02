# Gemini Code Review: All 6 Dimensions

**Gemini 1.5 Pro has ~1M token context - use this single prompt to review all dimensions at once.**

---

You are a comprehensive code reviewer analyzing a Python SEC filing extraction system. Review all 6 dimensions in a single pass.

## Project Overview

**Purpose**: Extract customer metrics (retention, churn, ARR, cohort data) from SEC S-1/F-1 IPO filings to support the Customer Metrics Accounting Standards Board (CMASB).

**Scale**:
- 39,847 LOC source code
- 81,244 LOC tests (2:1 ratio)
- 81.57% test coverage
- 7,304 target filings (2015-2025)
- Processing: 9-17 seconds per filing

**Current Performance**:
- Precision: 91%
- Recall: 85%
- F1: 88%

## Static Analysis Summary

### Complexity Hotspots (Top 10)

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

### Maintainability (MI=0 means unmaintainable)

| File | LOC | MI Score |
|------|-----|----------|
| db.py | 4,006 | 0.0 |
| html_segmenter.py | 2,028 | 0.0 |
| pattern_analyzer.py | 2,544 | 0.0 |

### Test Failures

**19 failing tests** in `tests/unit/web/test_api_images_routes.py` - all returning 409 CONFLICT.

### Coverage Gaps

- extraction_v2/: 0% (new pipeline)
- value_extractor.py: 66% (core extraction)

## Architecture Overview

```
src/
├── infra/           # DB (4,006 LOC), HTTP, SEC client
├── extraction/      # V1 pipeline (20 files, production)
├── extraction_v2/   # V2 pipeline (6 files, 0% coverage)
├── review/          # Human review (20 files, 98% coverage)
├── web/             # Flask UI
└── llm/             # OpenAI integration
```

**Pipeline Flow**:
```
HTML → Segmentation → Classification → Enrichment → Value Extraction (LLM) → Quality Scoring → DB
```

**Known Issues**:
1. Circular dependency: extraction ↔ review
2. V1 vs V2 strategy undefined
3. db.py monolith (4,006 LOC, 50+ methods)

## Dimension-Specific Questions

### D1: Architecture
1. Is db.py (4,006 LOC) acceptable? How to decompose?
2. What's the V1 → V2 migration strategy?
3. How serious is the circular dependency?

### D2: Extraction Quality
1. What causes 9% false positives?
2. What causes 15% false negatives?
3. Is table row estimation reliable?
4. Is the 170+ entry LLM mapping sustainable?

### D3: Code Quality
1. How should CC=57 `_process_segment` be refactored?
2. Which modules need mypy --strict?
3. Are error handling patterns consistent?

### D4: Testing
1. Why are 19 image route tests failing?
2. Why is extraction_v2 at 0% coverage?
3. Is 12-company gold standard representative?

### D5: Performance
1. Can LLM caching reduce the 50-70% bottleneck?
2. What's blocking filing parallelization?
3. Are there N+1 query patterns?

### D6: Security
1. Is no authentication acceptable?
2. How bad is the weak SECRET_KEY default?
3. Should APIs have CSRF/rate limiting?

## Output Format

Return findings for ALL 6 dimensions in a single JSON response:

```json
{
  "review_summary": {
    "overall_health": "A-F grade",
    "critical_count": 0,
    "high_count": 0,
    "medium_count": 0,
    "low_count": 0,
    "top_3_priorities": ["...", "...", "..."]
  },
  "dimensions": {
    "D1_ARCHITECTURE": {
      "findings": [
        {
          "id": "M-D1-001",
          "severity": "Critical|High|Medium|Low",
          "title": "...",
          "description": "...",
          "file": "...",
          "recommendation": "...",
          "effort": "XS|S|M|L|XL"
        }
      ],
      "summary": "..."
    },
    "D2_EXTRACTION": { ... },
    "D3_CODE_QUALITY": { ... },
    "D4_TESTING": { ... },
    "D5_PERFORMANCE": { ... },
    "D6_SECURITY": { ... }
  },
  "cross_cutting_concerns": [
    {
      "theme": "...",
      "affected_dimensions": ["D1", "D3"],
      "recommendation": "..."
    }
  ]
}
```

Provide 5-10 findings per dimension (30-60 total), with emphasis on cross-cutting concerns that span multiple dimensions.
