# GPT-4 Code Review: D1 Architecture

**Copy this entire prompt and paste into GPT-4 (or GPT-4o)**

---

You are a senior software engineer conducting an architecture code review of a production Python system that extracts customer metrics from SEC S-1/F-1 filings.

## Project Context

- **Size**: 39,847 LOC source, 81,244 LOC tests (2:1 test ratio)
- **Coverage**: 81.57%
- **Architecture**: 6-stage extraction pipeline + human review system
- **Database**: PostgreSQL with psycopg3
- **LLM**: OpenAI GPT-4o-mini for extraction fallback

## Static Analysis Findings

**Critical Complexity Hotspots:**
1. `_process_segment` (CC=57) - candidate_generator.py:481
2. `find_keywords_near_number` (CC=46) - keyword_matching.py:523
3. `bulk_insert_review_candidates` (CC=42) - db.py:1421

**Maintainability Issues:**
- `db.py`: 4,006 LOC, MI=0.0 (unmaintainable)
- `html_segmenter.py`: 2,028 LOC, MI=0.0
- `pattern_analyzer.py`: 2,544 LOC, MI=0.0

## Files to Review

### src/infra/db.py (4,006 LOC - Largest File)
```python
# Database adapter with 50+ methods
# Key concerns:
# - Single file handling ALL database operations
# - Mix of CRUD, queries, schema, migrations
# - Complex bulk_insert_review_candidates (CC=42)

class DatabaseAdapter:
    def __init__(self, connection_string: str):
        self.connection_string = connection_string
        self._pool: Pool | None = None

    # 50+ methods for:
    # - Company/filing CRUD
    # - Segment storage
    # - Metric value storage
    # - Review candidate management
    # - Pattern learning
    # - Batch operations
```

### src/extraction/extraction_pipeline.py (619 LOC)
```python
class ExtractionPipeline:
    """
    6-stage pipeline:
    1. HTML Segmentation (HTMLSegmenter)
    2. Metric Classification (MetricClassifier)
    3. Segment Enrichment (SegmentEnricher)
    4. Tiered Segment Selection
    5. Value Extraction (ValueExtractor)
    6. Quality Scoring (QualityScorer)
    """

    def extract(self, filing_id: int, html_content: str) -> ExtractionResult:
        # Stage 1: Parse HTML into segments
        segments = self._segmenter.segment_filing(html_content)

        # Stage 2: Classify segments
        classified = self._classifier.classify_segments(segments)

        # Stage 2b: Enrich with metadata
        enriched = self._enricher.enrich_segments(classified)

        # Stage 2c: Select top segments by tier
        selected = self._select_segments_tiered(enriched)  # CC=30

        # Stage 3: Extract values
        values = self._extractor.extract_values(selected)

        # Stage 4-6: Definitions, quality, store
        ...
```

### Circular Dependency Detected
```
src/extraction/html_segmenter.py imports from src/review/boundary_detection.py
src/review/ modules import from src/extraction/
```

### V1 vs V2 Pipeline
```
src/extraction/     - V1 pipeline (production, 85% coverage)
src/extraction_v2/  - V2 pipeline (development, 0% coverage)
                    - No migration strategy documented
                    - Unclear which to use
```

## Review Questions

1. **Module Boundaries**: Are module boundaries clear? Is there inappropriate coupling?
2. **db.py Monolith**: Is 4,006 LOC in one file acceptable? How should it be decomposed?
3. **Data Flow**: Is the 6-stage pipeline data flow clear and maintainable?
4. **Circular Dependencies**: How serious is the extraction↔review circular dependency?
5. **V1/V2 Strategy**: What's the right migration strategy? Coexist or replace?
6. **Config Approach**: Is YAML for keyword patterns scalable?

## Output Format

Return your findings as JSON:

```json
{
  "dimension": "D1_ARCHITECTURE",
  "model": "gpt4",
  "findings": [
    {
      "id": "G-D1-001",
      "severity": "Critical|High|Medium|Low",
      "category": "architecture",
      "title": "Short title",
      "description": "Detailed description",
      "file": "path/to/file.py",
      "line_range": "100-150",
      "code_before": "problematic pattern",
      "code_after": "suggested improvement",
      "recommendation": "What to do",
      "effort": "XS|S|M|L|XL"
    }
  ],
  "summary": "Overall architecture assessment"
}
```

Provide 8-15 findings covering the key architectural concerns.
