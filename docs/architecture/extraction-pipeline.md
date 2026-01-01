# Metric Extraction Pipeline

**Version:** 2.2
**Last Updated:** 2025-12-26
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
from src.extraction.enricher_config import FormulaWeights

class SegmentEnricher:
    GOLDMINE_THRESHOLD: float = 5.5  # Score threshold for goldmine identification

    def __init__(self, weights: FormulaWeights | None = None) -> None:
        """
        Initialize enricher with optional custom formula weights.
        
        Args:
            weights: Optional FormulaWeights configuration. If None, uses
                     FormulaWeights.default() which matches production behavior.
        """
        self.weights = weights if weights is not None else FormulaWeights.default()

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

**Configuration (GR-11):**

The `FormulaWeights` dataclass in `src/extraction/enricher_config.py` allows configuring
all richness score formula weights. This enables A/B testing different weight combinations
without code changes.

```python
# Use default production weights
enricher = SegmentEnricher()

# Use custom weights for higher precision
enricher = SegmentEnricher(weights=FormulaWeights.high_precision())

# Or customize individual weights
enricher = SegmentEnricher(weights=FormulaWeights(
    confidence_multiplier=4.0,
    goldmine_threshold=6.0,
))
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
| Cohort charts | 0-1.0 | `0.5 per cohort chart candidate (max 1.0)` |

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
- `_detect_cohort_chart_images()`: Cohort chart candidate detection with confidence scoring
- `_compute_richness_score()`: G8 - composite scoring

**Design Notes:**
- Operates on in-memory SourceSegment objects (no database access)
- Mutates segments in place for efficiency
- Richness score computed LAST (depends on other enrichments)
- Logs goldmine statistics after batch processing
- All methods are stateless (patterns compiled at class level)

---

### 2.6. Cohort Chart Detector

**Module:** `src/extraction/cohort_chart_detector.py`
**Class:** `CohortChartDetector`
**Status:** Complete (21 tests covering detection and confidence scoring)

**Responsibilities:**
- Detect cohort analysis charts and visualizations in filing HTML
- Find images with "cohort" keywords in surrounding text (within 1500 chars)
- Calculate confidence scores based on context quality
- Filter decorative images (icons, logos, bullets)
- Complement segment-level detection by analyzing standalone images

**Interface:**

```python
@dataclass
class CohortChartCandidate:
    image_src: str           # Image source URL or filename
    image_alt: str          # Alt text if available
    keyword_matches: List[str]  # Matched cohort keywords
    context_text: str       # Surrounding text (max 1500 chars)
    confidence: float       # Score 0.0-1.0
    position_in_doc: int    # Approximate character position

class CohortChartDetector:
    COHORT_CHART_KEYWORDS = ["cohort"]
    CHART_INDICATOR_KEYWORDS = ["chart", "graph", "figure", "visualization"]
    COHORT_IMAGE_PROXIMITY_CHARS = 1500  # Context window size

    def detect_from_html(self, html_content: str) -> List[CohortChartCandidate]:
        """
        Detect cohort charts from HTML content.

        Process:
        1. Find all <img> tags in HTML
        2. Filter decorative images (icons, logos, bullets)
        3. Extract context window (1500 chars before/after)
        4. Search for cohort keywords in context
        5. Calculate confidence scores
        6. Return candidates sorted by confidence

        Args:
            html_content: Raw HTML from SEC filing

        Returns:
            List of CohortChartCandidate objects
        """

    def detect_from_file(self, html_path: str) -> List[CohortChartCandidate]:
        """Convenience method to detect from HTML file path."""
```

**Confidence Scoring:**

| Component | Points | Condition |
|-----------|--------|-----------|
| Base score | 0.6 | Cohort keyword found near image |
| Chart keywords | +0.15 | Context contains "chart", "graph", "figure" |
| Retention context | +0.10 | Context mentions "retention" or "revenue" |
| Multiple keywords | +0.10 | 2+ cohort keyword matches |
| **Maximum** | **0.95** | All bonuses applied |

**Decorative Image Filtering:**

Images are excluded if they match any pattern:
- Size: `width < 50px` or `height < 50px`
- Filename: Contains "icon", "logo", "bullet", "arrow", "spacer"
- Alt text: Generic terms like "bullet point", "decorative"

**Use Cases:**

1. **ARR by Cohort Charts**: Revenue retention visualizations (e.g., Slack S-1)
2. **LTV/CAC by Cohort**: Customer economics charts (e.g., Farfetch F-1)
3. **Retention Curves**: Cohort retention over time
4. **Net Revenue Retention**: NRR breakdowns by customer cohort

**Design Notes:**
- Complements segment-level detection (which misses standalone images)
- HTMLSegmenter captures images within segments, but not all images are segmented
- Stores results in `extra_metadata["cohort_chart_candidates"]` at segment level
- Filing-level detector provides comprehensive image analysis
- No database access - operates on HTML strings

**Example Output:**

```python
# Slack S-1: ARR by Cohort chart
CohortChartCandidate(
    image_src="mdaa2.jpg",
    image_alt="ARR by Cohort",
    keyword_matches=["cohort"],
    context_text="The following chart shows our annual recurring revenue by customer cohort...",
    confidence=0.85,
    position_in_doc=125000
)
```

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

## Supporting Modules (EA-1, EA-3)

### Structure Parser (EA-1)

**Module:** `src/extraction/structure_parser.py`
**Status:** Complete (98% test coverage)

**Responsibilities:**
- Parse HTML while preserving DOM structure for position mapping
- Track table row and cell boundaries during HTML-to-text conversion
- Map text positions back to source DOM elements
- Support table-aware candidate detection and context extraction

**Interface:**

```python
class StructureParser:
    CELL_MARKER = " [CELL] "
    ROW_MARKER = " [ROW] "

    def __init__(self, html: str):
        """Parse HTML and build position mappings."""

    def get_text(self) -> str:
        """Return normalized text with [CELL] and [ROW] markers."""

    def are_in_same_row(self, pos1: int, pos2: int) -> bool:
        """Check if two text positions are in the same table row."""

    def are_in_same_cell(self, pos1: int, pos2: int) -> bool:
        """Check if two text positions are in the same table cell."""

    def get_row_at_position(self, position: int) -> Optional[RowSpan]:
        """Get the table row containing a given position."""

    def get_element_at_position(self, text_pos: int) -> Optional[Tag]:
        """Get DOM element containing a given text position."""
```

**Design Notes:**
- Preserves structural information during HTML-to-text conversion
- Enables accurate position mapping between text and DOM
- Foundation for table-aware extraction (EA-2) and context extraction (EA-3)
- Does NOT modify existing extraction pipelines (integration in future tasks)

---

### Candidate Detector (EA-2)

**Module:** `src/extraction/candidate_detector.py`
**Status:** Complete (97% test coverage, 47 tests)

**Responsibilities:**
- Unified metric candidate detection for extraction and review
- Consolidates detection logic from CandidateGenerator and ValueExtractor
- Integrates FalsePositiveFilter for filtering years, dates, page numbers
- Uses StructureParser (EA-1) for table-aware row validation
- Provides configurable keyword lists and distance thresholds
- Calculates confidence scores based on proximity and structure

**Interface:**

```python
from src.extraction.candidate_detector import CandidateDetector, DetectedCandidate

class CandidateDetector:
    MAX_KEYWORD_DISTANCE: int = 100  # Max chars between keyword and value

    def __init__(
        self,
        use_false_positive_filter: bool = True,
        use_row_validation: bool = True,
        keywords: Optional[List[str]] = None,
        max_keyword_distance: int = 100,
    ):
        """
        Initialize the candidate detector.

        Args:
            use_false_positive_filter: Filter years, dates, page numbers
            use_row_validation: Require same table row for matches
            keywords: Custom keywords (default: DEFAULT_KEYWORDS)
            max_keyword_distance: Max distance for keyword-value match
        """

    def detect(
        self,
        text: str,
        html: Optional[str] = None,
        segment_type: str = "paragraph",
    ) -> List[DetectedCandidate]:
        """
        Detect metric candidates in text.

        Args:
            text: The text content to analyze
            html: Optional HTML for structure-aware detection in tables
            segment_type: Type of segment ("paragraph", "table", etc.)

        Returns:
            List of detected candidates with positions and confidence
        """

    def detect_in_segment(self, segment: Dict[str, Any]) -> List[DetectedCandidate]:
        """Convenience method to detect from segment dict."""
```

**DetectedCandidate Dataclass:**

```python
@dataclass
class DetectedCandidate:
    keyword: str              # Matched keyword text
    keyword_position: int     # Character position of keyword
    value: Decimal           # Parsed numeric value
    value_position: int       # Character position of value
    unit: Optional[str]       # Detected unit (count, currency, %)
    confidence: float         # Score 0.0-1.0
    same_row: bool           # True if in same table row
    same_cell: bool          # True if in same table cell
    raw_text: str            # Surrounding context
```

**Confidence Scoring:**

| Factor | Points |
|--------|--------|
| Base score | 0.5 |
| Distance < 20 chars | +0.3 |
| Distance < 50 chars | +0.15 |
| Same cell (tables) | +0.15 |
| Same row (tables) | +0.05 |

**Design Notes:**
- Integrates with StructureParser for table-aware detection
- Only applies row validation when table structure is detected
- Falls back gracefully on invalid/missing HTML
- Does NOT modify existing CandidateGenerator or ValueExtractor (integration in future tasks)
- mypy --strict compliant

---

### Context Extractor (EA-3)

**Module:** `src/extraction/context_extractor.py`
**Status:** Complete (97% test coverage)

**Responsibilities:**
- Extract clean context around metric values with table awareness
- Use StructureParser to respect row boundaries in table segments
- Remove [CELL] and [ROW] markers from output
- Extract column and row headers for table values
- Provide character-based context windows for paragraphs

**Interface:**

```python
from src.extraction.context_extractor import ContextExtractor, ExtractedContext

class ContextExtractor:
    def __init__(
        self,
        context_chars: int = 100,
        include_headers: bool = True,
    ):
        """Initialize context extractor with configuration."""

    def extract(
        self,
        text: str,
        position: int,
        html: Optional[str] = None,
        segment_type: str = "paragraph",
    ) -> ExtractedContext:
        """
        Extract context around a position in text.

        For table segments with HTML, uses row-based extraction.
        For paragraphs, uses character-based windows.
        """

    def extract_row_context(
        self,
        text: str,
        position: int,
        parser: StructureParser,
    ) -> ExtractedContext:
        """Extract full row as context for table values."""

    def format_table_context(
        self,
        row_text: str,
        column_header: Optional[str] = None,
        row_header: Optional[str] = None,
    ) -> str:
        """Format table context for display with headers."""
```

**ExtractedContext Dataclass:**

```python
@dataclass
class ExtractedContext:
    text: str                       # Clean text without markers
    row_text: Optional[str]         # Full row text (with markers)
    column_header: Optional[str]    # Column header from first row
    row_header: Optional[str]       # Row header from first cell
    position_start: int             # Start position in original text
    position_end: int               # End position in original text
```

**Performance:**
- Average extraction time: 0.32ms (31x faster than 10ms requirement)
- Minimal memory allocation
- Efficient with cached StructureParser instances

**Design Notes:**
- Replaces [CELL] markers with ` | ` separators
- Removes [ROW] markers completely
- Normalizes whitespace in output
- Graceful fallback to character-based extraction on errors
- Does NOT integrate with ValueExtractor yet (Phase 2 integration task)

---

## Related Documentation

- **System Architecture:** `docs/architecture/system-overview.md` - High-level design
- **Data Model:** `docs/architecture/data-model.md` - Database schemas
- **LLM Integration:** `docs/architecture/llm-integration.md` - OpenAI integration details
- **Quality Model:** `docs/development/quality-model.md` - QA scoring framework
- **Metrics Taxonomy:** `docs/development/metrics-taxonomy.md` - Canonical metric definitions

---

**Last Updated:** 2025-12-26
**Version:** 2.4
**Status:** Production Ready

**Changelog:**
- v2.4 (2025-12-26): Added CandidateDetector (EA-2) - unified candidate detection module
- v2.3 (2025-12-26): Added StructureParser (EA-1) and ContextExtractor (EA-3) documentation
- v2.2 (2025-12-17): Added SegmentEnricher configuration system (GR-11)
- v2.1 (2025-12-16): Enhanced HTML segmentation with sentence detection, definition merging, 25K table limit, context enrichment, and list handling
