# D2: Extraction Quality Review Context

## Dimension Focus
False positives, false negatives, keyword patterns, table parsing, chart detection, value extraction accuracy.

## Primary Files to Review

### src/extraction/html_segmenter.py (2,029 LOC)
**Role**: Parses filing HTML into segments (paragraphs, tables, footnotes)
**Key concerns**:
- 6 sub-phases of complex processing
- Character encoding detection with fallback cascade
- Heading cache that's never invalidated
- Fractional sequence indices for composite segments

### src/extraction/value_extractor.py (582 LOC)
**Role**: Extracts numeric values from segments
**Key concerns**:
- Only 66% test coverage (lowest of core modules)
- LLM metric name mapping with 170+ manual entries
- LLM-first extraction with rule-based fallback

### src/review/table_structure.py (250 LOC)
**Role**: Row-aware table parsing for same-row validation
**Key concerns**:
- Text position estimation can be brittle
- Whitespace normalization differences
- Approximate matching fallback

### src/review/false_positive_filter.py (750 LOC)
**Role**: Filter false positives (dates, references, page numbers)
**Key concerns**:
- Multiple overlapping rules
- Hard to debug which rule triggered
- Format validation (count vs dollar vs percentage)

### config/metric_keywords.yaml (545 lines)
**Role**: Defines patterns for 45+ metrics
**Key concerns**:
- Exclusion patterns may be incomplete
- Required context patterns for some metrics
- Deprecated metrics still in config

## Review Questions

1. **False Positive Root Causes**: What patterns cause the most false positives? Are the filter rules adequate?

2. **False Negative Gaps**: What valid metrics are being missed? Are keyword patterns comprehensive?

3. **Table Row Estimation**: Is the row position estimation in table_structure.py reliable across HTML variations?

4. **Chart/Image Detection**: How accurate is cohort_chart_detector.py? What's the false positive rate?

5. **LLM Mapping Maintainability**: The 170+ entry METRIC_NAME_MAPPING is manually maintained. Is this sustainable?

6. **Exclusion Completeness**: Are exclusion patterns in metric_keywords.yaml comprehensive enough?

## Known Extraction Issues

1. **Fractional sequence indices** (html_segmenter.py:940): Float precision could cause collisions
2. **Heading cache**: Never invalidated if DOM changes during processing
3. **Charset encoding**: 80% confidence threshold may reject valid encodings
4. **Cross-row false positives**: Can occur if row boundaries misdetected
5. **Definition merging**: May merge unrelated segments

## Key Metrics from Gold Standard

Current baseline (from docs):
- Precision: ~91%
- Recall: ~85%
- F1: ~88%

## Output Location
Write findings to: `ops/review_artifacts/claude/D2_findings.json`
