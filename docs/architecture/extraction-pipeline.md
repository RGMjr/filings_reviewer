# Metric Extraction Pipeline

**Version:** 2.1
**Last Updated:** 2025-12-17
**Status:** Production Ready

---

## Overview

This document specifies the architecture and implementation of the metric extraction pipeline. The pipeline transforms SEC filing HTML into structured, analysis-ready metrics data through a series of modular processing stages.

### Pipeline Principles

1. **Auditability:** Every extracted value must be traceable to its source segment
2. **Reproducibility:** Re-running extraction on the same filing produces identical results
3. **Incremental Processing:** Process filings independently; support resume/retry
4. **Quality Tracking:** Capture confidence, alignment, and quality scores throughout
5. **Separation of Concerns:** Segmentation → Classification → Extraction → Storage

---

## Pipeline Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                         FILING HTML INPUT                           │
└────────────────────────────┬────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│  STAGE 1: HTML SEGMENTATION                                         │
│  - Parse HTML structure                                             │
│  - Extract paragraphs, tables, footnotes                            │
│  - Normalize text content                                           │
│  - Generate section paths (e.g., "Item 1. Business > Customers")    │
│  Output: source_segments table (raw text + metadata)                │
└────────────────────────────┬────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│  STAGE 2: METRIC CLASSIFICATION                                     │
│  - Scan segments for metric-related content                         │
│  - Identify: numeric disclosures, definitions, methodologies        │
│  - Tag segments with candidate_metric_ids                           │
│  - Set flags: contains_definition_flag, contains_methodology_flag   │
│  Output: Updated source_segments with classification metadata       │
└────────────────────────────┬────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│  STAGE 2.5: SEGMENT ENRICHMENT (G4-G8)                              │
│  - Compute metric density (metrics per 100 chars)                   │
│  - Detect temporal trends (multi-period data)                       │
│  - Detect cohort breakdowns (customer segmentation)                 │
│  - Count meaningful images/charts                                   │
│  - Compute richness score (0-10 composite)                          │
│  - Identify "goldmine" segments (score >= 6.0)                      │
│  Output: Enriched source_segments with richness metadata            │
└────────────────────────────┬────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│  STAGE 3: VALUE EXTRACTION                                          │
│  - Extract numeric values from classified segments                  │
│  - Parse tables with cohort breakdowns                              │
│  - Extract period information (dates, fiscal periods)               │
│  - Parse cohort labels and normalize                                │
│  Output: metric_values table                                        │
└────────────────────────────┬────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│  STAGE 4: DEFINITION EXTRACTION                                     │
│  - Extract definition text from definition segments                 │
│  - Extract methodology/calculation text                             │
│  - Assess alignment with CMASB canonical definitions                │
│  Output: metric_definitions table                                   │
└────────────────────────────┬────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│  STAGE 5: INCIDENCE & QUALITY SCORING                               │
│  - Aggregate filing x metric incidence                              │
│  - Count segments by type (numeric, definition, methodology)        │
│  - Compute quality scores (0-3)                                     │
│  - Set alignment flags and cohort breakdown flags                   │
│  Output: filing_metric_incidence table                              │
└────────────────────────────┬────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    ANALYSIS-READY DATABASE                          │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Component Specifications

### 1. HTML Segmenter

**Module:** `src/extraction/html_segmenter.py`
**Class:** `HTMLSegmenter`
**Status:** Complete (85% test coverage)

**Responsibilities:**
- Parse filing HTML into semantic segments
- Extract section headings and build section paths
- Normalize text (remove excess whitespace, decode entities)
- Preserve provenance metadata (HTML selectors, character offsets)
- Detect sentence boundaries with SEC-specific abbreviations
- Merge definition segments that span multiple HTML elements
- Handle large tables with 25K character limit
- Enrich segments with context from adjacent content
- Extract list items with intro context

**Interface:**

```python
class HTMLSegmenter:
    def segment_filing(self, filing_id: int, html_path: str) -> List[SourceSegment]:
        """
        Parse filing HTML and return list of source segments.

        Pipeline phases:
        1. Parsing: HTML structure extraction
        2. Element extraction: <p>, <table>, <div>, <ul>, <ol>
        3. Composite splitting: Separate text/table from mixed divs
        4. Sentence detection: Store boundaries as metadata
        5. Definition merging: Combine split definitions
        6. Table handling: 25K limit with truncation
        7. Context enrichment: Add overlap + document position
        8. Validation: Apply min/max length filters

        Args:
            filing_id: Database ID of the filing
            html_path: Path to cached HTML file

        Returns:
            List of SourceSegment objects with enhanced metadata
        """

    def extract_section_path(self, element) -> str:
        """Build hierarchical section path from HTML structure."""

    def normalize_text(self, raw_html: str) -> str:
        """Clean and normalize text content."""
```

**Segment Types:**
- `paragraph`: Text paragraphs (default)
- `table`: HTML tables (entire table as one segment)
- `footnote`: Footnotes and endnotes
- `definition_block`: Detected definition sections (may be merged)
- `methodology_block`: Detected calculation methodology sections
- `list_item`: Individual list items with intro context
- `other`: Fallback

**Enhanced Segment Fields:**
- `context_prefix`: Last sentence from previous segment (for context preservation)
- `document_position`: 0.0-1.0 position in document
- `sentence_boundaries`: List of (start, end) tuples for sentences
- `table_truncated_flag`: True if table exceeded 25K limit
- `definition_merged_count`: Number of segments merged for definition

**Design Notes:**
- Uses BeautifulSoup for HTML parsing
- Extracts all `<p>` tags as paragraphs, all `<table>` tags as tables
- Extracts `<ul>`, `<ol>` list items with intro text as context
- Sequence index based on document order
- Section path: traverse up DOM to find heading hierarchy
- Keeps both raw_text (normalized) and raw_html (original snippet)
- Sentence detection uses BoundaryDetector with SEC abbreviations (FY, Q, TTM, NRR, etc.)
- Definition merging: max 3 segments, 2000 chars combined limit
- Tables use higher limit (25K) vs text (10K) for truncation

---

### 2. Metric Classifier

**Module:** `src/extraction/metric_classifier.py`
**Class:** `MetricClassifier`
**Status:** Complete (98% test coverage)

**Responsibilities:**
- Scan source segments for metric-related keywords
- Classify segments as: numeric disclosure, definition, methodology, or none
- Tag segments with candidate_metric_ids (which metrics might be present)
- Assign confidence scores

**Interface:**

```python
class MetricClassifier:
    def classify_segment(self, segment: SourceSegment) -> SourceSegment:
        """
        Classify a single segment.

        Updates:
            - candidate_metric_ids
            - contains_definition_flag
            - contains_methodology_flag
            - contains_numeric_disclosure_flag
            - classifier_confidence

        Returns:
            Updated SourceSegment object
        """

    def classify_batch(self, segments: List[SourceSegment]) -> List[SourceSegment]:
        """Classify multiple segments efficiently."""
```

**Classification Strategy (Rule-Based):**

1. **Numeric Disclosure Detection:**
   - Segment contains numbers AND metric-related keywords
   - Keywords: "customers", "users", "cohort", "revenue", "transactions"
   - Set `contains_numeric_disclosure_flag = True`

2. **Definition Detection:**
   - Segment contains definition phrases
   - Patterns: "we define", "defined as", "refers to", "means"
   - Near metric keywords
   - Set `contains_definition_flag = True`

3. **Methodology Detection:**
   - Segment contains calculation phrases
   - Patterns: "calculated as", "calculated by", "determined by", "formula"
   - Set `contains_methodology_flag = True`

4. **Metric ID Tagging:**
   - Match keywords to specific metrics
   - Example: "new customers" → `['cm_new_customers_acquired']`
   - Example: "cohort" + "revenue" → `['cm_revenue_by_cohort']`

---

### 2.5. Segment Enricher (G4-G8)

**Module:** `src/extraction/segment_enricher.py`
**Class:** `SegmentEnricher`
**Status:** Complete (98% test coverage)

**Responsibilities:**
- Compute metric density (unique metrics per 100 characters)
- Count distinct metric IDs per segment
- Detect temporal trends (multi-period data mentions)
- Detect cohort breakdowns (customer segmentation patterns)
- Count meaningful images/charts (filtering decorative elements)
- Compute composite richness score (0-10 scale)
- Identify "goldmine" segments (richness_score >= 6.0)

**Interface:**

```python
class SegmentEnricher:
    GOLDMINE_THRESHOLD: float = 6.0  # Score threshold for goldmine identification

    def enrich_batch(self, segments: List[SourceSegment]) -> List[SourceSegment]:
        """
        Enrich all segments with richness metadata.

        Updates (mutates in place):
            - metric_density: float (metrics per 100 chars)
            - distinct_metric_count: int
            - contains_temporal_trend: bool
            - contains_cohort_breakdown: bool
            - image_count: int
            - richness_score: float (0.0-10.0)

        Returns:
            Same segments list with enrichment fields populated
        """
```

**Richness Score Formula (0-10 points):**

| Component | Points | Calculation |
|-----------|--------|-------------|
| Base confidence | 0-3.0 | `classifier_confidence * 3.0` |
| Metric density | 0-2.0 | `min(distinct_metric_count * 0.5, 2.0)` |
| Temporal trends | 1.0 | `1.0 if contains_temporal_trend else 0` |
| Cohort breakdowns | 1.5 | `1.5 if contains_cohort_breakdown else 0` |
| Definitions | 1.0 | `1.0 if contains_definition_flag else 0` |
| Images | 0-1.5 | `min(image_count * 0.5, 1.5)` |

**Goldmine Identification:**
- Segments with `richness_score >= 6.0` are "goldmines"
- Goldmines represent high-value disclosure sections
- Typically 5-10% of segments in a filing qualify
- Enables prioritized extraction and human review

**Enrichment Methods:**
- `_compute_metric_density()`: G4 - metrics per 100 chars
- `_compute_distinct_metric_count()`: G4 - unique metric count
- `_detect_temporal_trends()`: G5 - multi-year/period detection
- `_detect_cohort_breakdowns()`: G6 - cohort analysis patterns
- `_detect_images()`: G7 - meaningful image/chart count
- `_compute_richness_score()`: G8 - composite scoring

**Design Notes:**
- Operates on in-memory SourceSegment objects (no database access)
- Mutates segments in place for efficiency
- Richness score computed LAST (depends on other enrichments)
- Logs goldmine statistics after batch processing
- All methods are stateless (patterns compiled at class level)

---

### 3. Value Extractor

**Module:** `src/extraction/value_extractor.py`
**Class:** `ValueExtractor`
**Status:** Complete (66% test coverage)

**Responsibilities:**
- Extract numeric values from classified segments
- Parse tables to extract cohort breakdowns
- Extract period information (dates, fiscal periods)
- Parse and normalize cohort labels
- Handle units and currency

**Interface:**

```python
class ValueExtractor:
    def extract_from_segment(self, segment: SourceSegment) -> List[MetricValue]:
        """
        Extract all metric values from a segment.

        Args:
            segment: Classified source segment

        Returns:
            List of MetricValue objects (may be multiple values per segment)
        """

    def extract_from_table(self, segment: SourceSegment) -> List[MetricValue]:
        """Extract structured data from table segments."""

    def parse_cohort_label(self, raw_label: str) -> tuple[str, str]:
        """
        Parse cohort label into type and normalized bucket.

        Args:
            raw_label: Raw cohort label from filing

        Returns:
            (cohort_type, cohort_bucket_normalized)

        Examples:
            "2021 Cohort" -> ("acquisition", "2021")
            "0-12 months" -> ("tenure", "0-1y")
        """
```

**Extraction Strategies:**

1. **Table Extraction (Priority):**
   - Most reliable for cohort breakdowns
   - Parse table headers to identify: metric, period, cohort dimension
   - Parse rows to extract values
   - Example table structure:
     ```
     Cohort          | Q1 2024 | Q2 2024
     ---------------|---------|--------
     2021 Cohort    | 1,234   | 1,456
     2022 Cohort    | 2,345   | 2,567
     ```

2. **LLM-Enhanced Text Extraction (Fallback):**
   - Use GPT-4o-mini for unstructured text
   - Prompt with metric names and context
   - Parse JSON response with validation
   - Lower confidence than table extraction
   - Quote verification ensures accuracy

**Cohort Label Normalization:**
```python
# Acquisition cohorts
"2021 Cohort" -> cohort_type="acquisition", normalized="2021"
"Customers acquired in 2022" -> cohort_type="acquisition", normalized="2022"

# Tenure cohorts
"0-12 months" -> cohort_type="tenure", normalized="0-1y"
"1-2 years" -> cohort_type="tenure", normalized="1-2y"
"3+ years" -> cohort_type="tenure", normalized="3y+"
```

---

### 4. Definition Extractor

**Module:** `src/extraction/definition_extractor.py`
**Class:** `DefinitionExtractor`
**Status:** Complete (89% test coverage)

**Responsibilities:**
- Extract definition text from definition segments
- Extract methodology/calculation text from methodology segments
- Clean and normalize text
- Assess alignment with CMASB canonical definitions

**Interface:**

```python
class DefinitionExtractor:
    def extract_definition(self, segment: SourceSegment, metric_id: str) -> MetricDefinition:
        """
        Extract definition for a specific metric from a segment.

        Args:
            segment: Source segment containing definition
            metric_id: Canonical metric ID

        Returns:
            MetricDefinition object
        """

    def assess_alignment(self, issuer_definition: str, canonical_definition: str) -> str:
        """
        Assess alignment between issuer and CMASB definitions.

        Args:
            issuer_definition: Definition from filing
            canonical_definition: CMASB standard definition

        Returns:
            'aligned', 'partial', 'not_aligned', or 'unknown'
        """
```

**Alignment Assessment (Current - Simple):**
- Keyword overlap between issuer and canonical definitions
- High overlap (>70%) → 'aligned'
- Medium overlap (30-70%) → 'partial'
- Low overlap (<30%) → 'not_aligned'

**LLM-Enhanced Extraction:**
- Uses GPT-4o-mini for semantic extraction
- Prompt asks for definition text, methodology, and calculation details
- Structured JSON response with quote verification
- Fallback to rule-based if LLM fails

---

### 5. Quality Scorer

**Module:** `src/extraction/quality_scorer.py`
**Class:** `QualityScorer`
**Status:** Complete (100% test coverage)

**Responsibilities:**
- Aggregate filing x metric incidence
- Count segments by type for each metric
- Compute quality scores (0-3 scale)
- Identify primary definition/methodology segments
- Set cohort breakdown flags

**Interface:**

```python
class QualityScorer:
    def score_filing_metric(
        self,
        filing_id: int,
        metric_id: str,
        segments: List[SourceSegment],
        values: List[MetricValue],
        definitions: List[MetricDefinition]
    ) -> FilingMetricIncidence:
        """
        Compute incidence and quality scores for a filing x metric pair.

        Args:
            filing_id: Database ID of filing
            metric_id: Canonical metric ID
            segments: All segments for this filing-metric
            values: All extracted values
            definitions: All extracted definitions

        Returns:
            FilingMetricIncidence object with scores
        """

    def compute_overall_quality(self, ...) -> int:
        """Compute overall quality score 0-3."""
```

**Quality Scoring Rubric (0-3 scale):**

**Overall Quality:**
- 0: Metric not disclosed
- 1: Minimal (numeric value only, no definition)
- 2: Moderate (value + definition OR methodology)
- 3: Excellent (value + definition + methodology + cohort breakdown)

**Definition Quality:**
- 0: No definition provided
- 1: Vague or incomplete definition
- 2: Clear definition, mostly aligned
- 3: Comprehensive definition, fully aligned with CMASB

**Methodology Quality:**
- 0: No methodology provided
- 1: Vague calculation description
- 2: Clear calculation method
- 3: Detailed calculation formula with examples

**Completeness:**
- 0: Not disclosed
- 1: Single aggregate number
- 2: Breakdowns by period OR cohort
- 3: Breakdowns by both period AND cohort

**Comparability:**
- 0: Not disclosed
- 1: Definition differs significantly from CMASB
- 2: Definition partially aligned
- 3: Definition fully aligned with CMASB

---

## Processing Orchestration

### Main Extraction Pipeline

**Module:** `src/extraction/extraction_pipeline.py`
**Class:** `ExtractionPipeline`
**Status:** Complete (91% test coverage)

**Responsibilities:**
- Orchestrate all extraction stages
- Manage database transactions
- Handle errors and logging
- Support batch processing

**Interface:**

```python
class ExtractionPipeline:
    def __init__(self, db: DatabaseAdapter):
        self.db = db
        self.segmenter = HTMLSegmenter()
        self.classifier = MetricClassifier()
        self.value_extractor = ValueExtractor()
        self.definition_extractor = DefinitionExtractor()
        self.quality_scorer = QualityScorer()

    def process_filing(self, filing_id: int) -> ProcessingResult:
        """
        Run full extraction pipeline for a single filing.

        Steps:
            1. Segment HTML
            2. Classify segments
            3. Extract values
            4. Extract definitions
            5. Compute quality scores
            6. Write all to database

        Args:
            filing_id: Database ID of filing to process

        Returns:
            ProcessingResult with status and statistics
        """

    def process_batch(self, filing_ids: List[int]) -> BatchResult:
        """Process multiple filings."""
```

**Transaction Strategy:**
- Each filing processed in a single transaction
- Rollback entire filing if any stage fails
- Track processing status in filings table
- Statuses: `pending`, `fetched`, `segmented`, `processed`, `failed`

**Error Handling:**
- Log all errors with full context
- Continue batch processing after individual failures
- Store error details in `processing_notes` column
- Classify errors: transient (retry), permanent (skip), extraction (manual review)

---

## Data Flow Example

For a filing containing:

```
Section: Item 1. Business

"We define a new customer as an individual or organization that completes
their first purchase transaction during the reporting period. New customers
acquired during Q1 2024 totaled 12,345."

[TABLE]
Revenue by Customer Cohort (in thousands)
Cohort          | Q1 2024 | Q4 2023
----------------|---------|--------
2021 Cohort     | $1,234  | $1,189
2022 Cohort     | $2,345  | $2,201
2023 Cohort     | $3,456  | $3,123
```

**Stage 1 Output (source_segments):**

```
segment_id | segment_type | raw_text                          | sequence_index | section_path
-----------|--------------|-----------------------------------|----------------|-------------------
101        | paragraph    | "We define a new customer..."     | 15             | "Item 1. Business"
102        | table        | [table content]                   | 16             | "Item 1. Business"
```

**Stage 2 Output (classified segments):**

```
segment_id | contains_definition | contains_numeric | candidate_metric_ids
-----------|--------------------|-----------------|---------------------------------
101        | TRUE               | TRUE            | ['cm_new_customers_acquired']
102        | FALSE              | TRUE            | ['cm_revenue_by_cohort']
```

**Stage 3 Output (metric_values):**

```
metric_id                    | value_numeric | period_end  | cohort_type | cohort_bucket | source_segment_id
-----------------------------|---------------|-------------|-------------|---------------|------------------
cm_new_customers_acquired    | 12345         | 2024-03-31  | NULL        | NULL          | 101
cm_revenue_by_cohort         | 1234000       | 2024-03-31  | acquisition | 2021          | 102
cm_revenue_by_cohort         | 2345000       | 2024-03-31  | acquisition | 2022          | 102
cm_revenue_by_cohort         | 3456000       | 2024-03-31  | acquisition | 2023          | 102
```

**Stage 4 Output (metric_definitions):**

```
metric_id                    | definition_text_normalized          | alignment_flag | definition_segment_id
-----------------------------|-------------------------------------|----------------|---------------------
cm_new_customers_acquired    | "an individual or organization..."  | aligned        | 101
```

**Stage 5 Output (filing_metric_incidence):**

```
metric_id                    | metric_disclosed | num_numeric_segments | num_definition_segments | quality_overall | has_cohort_breakdown
-----------------------------|------------------|----------------------|-------------------------|-----------------|---------------------
cm_new_customers_acquired    | TRUE             | 1                    | 1                       | 2               | FALSE
cm_revenue_by_cohort         | TRUE             | 1                    | 0                       | 2               | TRUE
```

---

## Component Testing

### Test Strategy

1. **Unit Tests:** Each component tested independently
2. **Integration Tests:** Full pipeline on sample filings
3. **Golden Set:** Manually annotated filings for validation

**Coverage:**
- Segmentation: Count accuracy (manual count vs. automated)
- Classification: Precision/recall on metric detection
- Extraction: Value accuracy (compare to manual extraction)
- Quality: Inter-rater agreement on scores

**Test Files:**
- `tests/unit/extraction/test_html_segmenter.py`
- `tests/unit/extraction/test_metric_classifier.py`
- `tests/unit/extraction/test_value_extractor.py`
- `tests/unit/extraction/test_definition_extractor.py`
- `tests/unit/extraction/test_quality_scorer.py`
- `tests/unit/extraction/test_extraction_pipeline.py`

---

## Configuration

**Environment Variables:**
```bash
DATABASE_URL=postgresql://user:password@localhost/filings_analysis
OPENAI_API_KEY=sk-...  # For LLM-enhanced extraction
```

**Config File (`config/extraction.yaml`):**
```yaml
segmentation:
  min_paragraph_length: 50
  max_segment_length: 10000
  table_max_length: 25000  # Higher limit for tables
  enable_sentence_detection: true
  enable_definition_merging: true
  definition_lookahead_max: 3  # Max segments to merge
  definition_max_combined_length: 2000
  context_overlap_sentences: 1  # Sentences from prev segment
  calculate_document_position: true

classification:
  confidence_threshold: 0.5

extraction:
  table_parser_mode: "pandas"  # or "beautifulsoup"
  llm_enabled: true
  llm_model: "gpt-4o-mini"

quality:
  alignment_threshold: 0.7
```

---

## Performance Characteristics

**Processing Time (per filing):**
- Segmentation: ~1-2 seconds
- Classification: ~0.5-1 seconds
- Table extraction: ~2-3 seconds
- LLM extraction: ~5-10 seconds (if used)
- Quality scoring: ~0.5 seconds
- **Total: ~9-17 seconds per filing**

**Memory Usage:**
- Average filing: ~5-10 MB in memory
- Peak during large table processing: ~50 MB

**Database Operations:**
- Segments per filing: 100-500 average
- Values per filing: 10-100 average
- Definitions per filing: 5-20 average

---

## Related Documentation

- **System Architecture:** `docs/architecture/system-overview.md` - High-level design
- **Data Model:** `docs/architecture/data-model.md` - Database schemas
- **LLM Integration:** `docs/architecture/llm-integration.md` - OpenAI integration details
- **Quality Model:** `docs/development/quality-model.md` - QA scoring framework
- **Metrics Taxonomy:** `docs/development/metrics-taxonomy.md` - Canonical metric definitions

---

**Last Updated:** 2025-12-16
**Version:** 2.1
**Status:** Production Ready

**Changelog:**
- v2.1 (2025-12-16): Enhanced HTML segmentation with sentence detection, definition merging, 25K table limit, context enrichment, and list handling
