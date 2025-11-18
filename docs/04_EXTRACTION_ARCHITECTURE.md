# Metric Extraction Architecture

**Version**: 0.1
**Date**: 2025-11-17
**Status**: Design Document

## Overview

This document specifies the architecture for extracting customer metrics from SEC filings and storing them in the analysis database.

## Architecture Principles

1. **Auditability**: Every extracted value must be traceable to its source segment
2. **Reproducibility**: Re-running extraction on the same filing should produce identical results
3. **Incremental Processing**: Process filings independently; support resume/retry
4. **Quality Tracking**: Capture confidence, alignment, and quality scores throughout
5. **Separation of Concerns**: Segmentation → Classification → Extraction → Storage

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

## Component Specifications

### 1. HTML Segmenter

**Module**: `src/extraction/html_segmenter.py`
**Class**: `HTMLSegmenter`

**Responsibilities**:
- Parse filing HTML into semantic segments
- Extract section headings and build section paths
- Normalize text (remove excess whitespace, decode entities)
- Preserve provenance metadata (HTML selectors, character offsets)

**Input**:
- Filing HTML file path
- Filing metadata (filing_id, company_id)

**Output**:
- List of `SourceSegment` objects ready for database insertion

**Key Methods**:
```python
class HTMLSegmenter:
    def segment_filing(self, filing_id: int, html_path: str) -> List[SourceSegment]:
        """
        Parse filing HTML and return list of source segments.

        Returns:
            List of SourceSegment objects (not yet inserted to DB)
        """

    def extract_section_path(self, element) -> str:
        """Build hierarchical section path from HTML structure."""

    def normalize_text(self, raw_html: str) -> str:
        """Clean and normalize text content."""
```

**Segment Types**:
- `paragraph`: Text paragraphs (default)
- `table`: HTML tables (entire table as one segment)
- `footnote`: Footnotes and endnotes
- `definition_block`: Detected definition sections
- `methodology_block`: Detected calculation methodology sections
- `other`: Fallback

**Design Notes**:
- Start simple: extract all `<p>` tags as paragraphs, all `<table>` tags as tables
- Use BeautifulSoup for HTML parsing
- Sequence index based on document order
- Section path: traverse up DOM to find heading hierarchy
- Keep both raw_text (normalized) and raw_html (original snippet)

### 2. Metric Classifier

**Module**: `src/extraction/metric_classifier.py`
**Class**: `MetricClassifier`

**Responsibilities**:
- Scan source segments for metric-related keywords
- Classify segments as: numeric disclosure, definition, methodology, or none
- Tag segments with candidate_metric_ids (which metrics might be present)
- Assign confidence scores

**Input**:
- List of `SourceSegment` objects (from database or in-memory)

**Output**:
- Updated `SourceSegment` objects with classification flags and candidate_metric_ids

**Key Methods**:
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
        """

    def classify_batch(self, segments: List[SourceSegment]) -> List[SourceSegment]:
        """Classify multiple segments efficiently."""
```

**Classification Strategy** (Phase 1 - Rule-Based):

1. **Numeric Disclosure Detection**:
   - Segment contains numbers AND metric-related keywords
   - Keywords: "customers", "users", "cohort", "revenue", "transactions"
   - Set `contains_numeric_disclosure_flag = True`

2. **Definition Detection**:
   - Segment contains definition phrases
   - Patterns: "we define", "defined as", "refers to", "means"
   - Near metric keywords
   - Set `contains_definition_flag = True`

3. **Methodology Detection**:
   - Segment contains calculation phrases
   - Patterns: "calculated as", "calculated by", "determined by", "formula"
   - Set `contains_methodology_flag = True`

4. **Metric ID Tagging**:
   - Match keywords to specific metrics
   - Example: "new customers" → `['cm_new_customers_acquired']`
   - Example: "cohort" + "revenue" → `['cm_revenue_by_cohort']`

**Future Enhancement** (Phase 2 - LLM-Based):
- Use Claude API for semantic classification
- Prompt: "Does this segment contain a definition of customer acquisition?"
- Higher accuracy but slower and more expensive

### 3. Value Extractor

**Module**: `src/extraction/value_extractor.py`
**Class**: `ValueExtractor`

**Responsibilities**:
- Extract numeric values from classified segments
- Parse tables to extract cohort breakdowns
- Extract period information (dates, fiscal periods)
- Parse and normalize cohort labels
- Handle units and currency

**Input**:
- Classified source segments (with `contains_numeric_disclosure_flag = True`)

**Output**:
- List of `MetricValue` objects ready for database insertion

**Key Methods**:
```python
class ValueExtractor:
    def extract_from_segment(self, segment: SourceSegment) -> List[MetricValue]:
        """
        Extract all metric values from a segment.

        Returns:
            List of MetricValue objects (may be multiple values per segment)
        """

    def extract_from_table(self, segment: SourceSegment) -> List[MetricValue]:
        """Extract structured data from table segments."""

    def parse_cohort_label(self, raw_label: str) -> tuple[str, str]:
        """
        Parse cohort label into type and normalized bucket.

        Returns:
            (cohort_type, cohort_bucket_normalized)

        Examples:
            "2021 Cohort" -> ("acquisition", "2021")
            "0-12 months" -> ("tenure", "0-1y")
        """
```

**Extraction Strategies**:

1. **Table Extraction** (Priority):
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

2. **Text Extraction** (Fallback):
   - Use regex to find numbers with context
   - Pattern: "new customers acquired: 1,234"
   - Lower confidence than table extraction

**Cohort Label Normalization**:
```python
# Acquisition cohorts
"2021 Cohort" -> cohort_type="acquisition", normalized="2021"
"Customers acquired in 2022" -> cohort_type="acquisition", normalized="2022"

# Tenure cohorts
"0-12 months" -> cohort_type="tenure", normalized="0-1y"
"1-2 years" -> cohort_type="tenure", normalized="1-2y"
"3+ years" -> cohort_type="tenure", normalized="3y+"
```

### 4. Definition Extractor

**Module**: `src/extraction/definition_extractor.py`
**Class**: `DefinitionExtractor`

**Responsibilities**:
- Extract definition text from definition segments
- Extract methodology/calculation text from methodology segments
- Clean and normalize text
- Assess alignment with CMASB canonical definitions

**Input**:
- Classified source segments (with definition/methodology flags)

**Output**:
- List of `MetricDefinition` objects

**Key Methods**:
```python
class DefinitionExtractor:
    def extract_definition(self, segment: SourceSegment, metric_id: str) -> MetricDefinition:
        """
        Extract definition for a specific metric from a segment.
        """

    def assess_alignment(self, issuer_definition: str, canonical_definition: str) -> str:
        """
        Assess alignment between issuer and CMASB definitions.

        Returns:
            'aligned', 'partial', 'not_aligned', or 'unknown'
        """
```

**Alignment Assessment** (Phase 1 - Simple):
- Keyword overlap between issuer and canonical definitions
- High overlap (>70%) → 'aligned'
- Medium overlap (30-70%) → 'partial'
- Low overlap (<30%) → 'not_aligned'

**Alignment Assessment** (Phase 2 - LLM):
- Use Claude to semantically compare definitions
- Prompt: "Compare these two definitions and assess alignment..."

### 5. Incidence & Quality Scorer

**Module**: `src/extraction/quality_scorer.py`
**Class**: `QualityScorer`

**Responsibilities**:
- Aggregate filing x metric incidence
- Count segments by type for each metric
- Compute quality scores (0-3 scale)
- Identify primary definition/methodology segments
- Set cohort breakdown flags

**Input**:
- All extracted data for a filing (segments, values, definitions)

**Output**:
- List of `FilingMetricIncidence` objects

**Key Methods**:
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
        """

    def compute_overall_quality(self, ...) -> int:
        """Compute overall quality score 0-3."""
```

**Quality Scoring Rubric** (0-3 scale):

**Overall Quality**:
- 0: Metric not disclosed
- 1: Minimal (numeric value only, no definition)
- 2: Moderate (value + definition OR methodology)
- 3: Excellent (value + definition + methodology + cohort breakdown)

**Definition Quality**:
- 0: No definition provided
- 1: Vague or incomplete definition
- 2: Clear definition, mostly aligned
- 3: Comprehensive definition, fully aligned with CMASB

**Methodology Quality**:
- 0: No methodology provided
- 1: Vague calculation description
- 2: Clear calculation method
- 3: Detailed calculation formula with examples

**Completeness**:
- 0: Not disclosed
- 1: Single aggregate number
- 2: Breakdowns by period OR cohort
- 3: Breakdowns by both period AND cohort

**Comparability**:
- 0: Not disclosed
- 1: Definition differs significantly from CMASB
- 2: Definition partially aligned
- 3: Definition fully aligned with CMASB

## Processing Orchestration

### Main Extraction Pipeline

**Module**: `src/extraction/extraction_pipeline.py`
**Class**: `ExtractionPipeline`

**Responsibilities**:
- Orchestrate all extraction stages
- Manage database transactions
- Handle errors and logging
- Support batch processing

**Key Methods**:
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
        """

    def process_batch(self, filing_ids: List[int]) -> BatchResult:
        """Process multiple filings."""
```

**Transaction Strategy**:
- Each filing processed in a single transaction
- Rollback entire filing if any stage fails
- Track processing status in filings table

**Error Handling**:
- Log all errors with full context
- Continue batch processing after individual failures
- Store error details in database (new column: extraction_error_log)

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

**Stage 1 Output** (source_segments):
```
segment_id | segment_type | raw_text                          | sequence_index | section_path
-----------|--------------|-----------------------------------|----------------|-------------------
101        | paragraph    | "We define a new customer..."     | 15             | "Item 1. Business"
102        | table        | [table content]                   | 16             | "Item 1. Business"
```

**Stage 2 Output** (classified segments):
```
segment_id | contains_definition | contains_numeric | candidate_metric_ids
-----------|--------------------|-----------------|---------------------------------
101        | TRUE               | TRUE            | ['cm_new_customers_acquired']
102        | FALSE              | TRUE            | ['cm_revenue_by_cohort']
```

**Stage 3 Output** (metric_values):
```
metric_id                    | value_numeric | period_end  | cohort_type | cohort_bucket | source_segment_id
-----------------------------|---------------|-------------|-------------|---------------|------------------
cm_new_customers_acquired    | 12345         | 2024-03-31  | NULL        | NULL          | 101
cm_revenue_by_cohort         | 1234000       | 2024-03-31  | acquisition | 2021          | 102
cm_revenue_by_cohort         | 2345000       | 2024-03-31  | acquisition | 2022          | 102
cm_revenue_by_cohort         | 3456000       | 2024-03-31  | acquisition | 2023          | 102
```

**Stage 4 Output** (metric_definitions):
```
metric_id                    | definition_text_normalized          | alignment_flag | definition_segment_id
-----------------------------|-------------------------------------|----------------|---------------------
cm_new_customers_acquired    | "an individual or organization..."  | aligned        | 101
```

**Stage 5 Output** (filing_metric_incidence):
```
metric_id                    | metric_disclosed | num_numeric_segments | num_definition_segments | quality_overall | has_cohort_breakdown
-----------------------------|------------------|----------------------|-------------------------|-----------------|---------------------
cm_new_customers_acquired    | TRUE             | 1                    | 1                       | 2               | FALSE
cm_revenue_by_cohort         | TRUE             | 1                    | 0                       | 2               | TRUE
```

## Phase 1 Implementation Priority

### Milestone 1: Basic Segmentation (Week 1)
- Implement HTMLSegmenter
- Test on 5-10 sample filings
- Manually verify segment quality

### Milestone 2: Rule-Based Classification (Week 2)
- Implement MetricClassifier with keyword rules
- Focus on 4 core metrics only
- Measure precision/recall on sample set

### Milestone 3: Table Value Extraction (Week 3)
- Implement ValueExtractor for tables
- Parse cohort breakdowns
- Handle period extraction

### Milestone 4: Definition Extraction (Week 4)
- Implement DefinitionExtractor
- Basic alignment assessment
- Test on core metrics

### Milestone 5: Quality Scoring (Week 5)
- Implement QualityScorer
- Compute all quality dimensions
- Generate incidence table

### Milestone 6: Pipeline Integration (Week 6)
- Implement ExtractionPipeline
- Process full sample set (50-100 filings)
- Generate analysis outputs

## Testing Strategy

1. **Unit Tests**: Each component tested independently
2. **Integration Tests**: Full pipeline on sample filings
3. **Golden Set**: Manually annotated filings for validation
4. **Metrics**:
   - Segmentation: count accuracy (manual count vs. automated)
   - Classification: precision/recall on metric detection
   - Extraction: value accuracy (compare to manual extraction)
   - Quality: inter-rater agreement on scores

## Future Enhancements (Phase 2)

1. **LLM-Based Classification**: Replace keyword rules with Claude API
2. **Advanced Table Parsing**: Handle complex multi-header tables
3. **Cross-Filing Validation**: Detect inconsistencies across periods
4. **Entity Resolution**: Link related metrics across filings
5. **Visualization**: Generate metric disclosure heatmaps

## Dependencies

**Python Libraries**:
- BeautifulSoup4: HTML parsing
- pandas: Table data manipulation
- dateutil: Date parsing
- anthropic: Claude API (Phase 2)

**Database**:
- PostgreSQL with existing schema
- DatabaseAdapter from infra.db

## Configuration

**Environment Variables**:
```bash
DATABASE_URL=postgresql://localhost/filings_analysis
ANTHROPIC_API_KEY=sk-ant-... (Phase 2)
```

**Config File** (`config/extraction.yaml`):
```yaml
segmentation:
  min_paragraph_length: 50
  max_segment_length: 10000

classification:
  confidence_threshold: 0.5

extraction:
  table_parser_mode: "pandas"  # or "beautifulsoup"

quality:
  alignment_threshold: 0.7
```

## Monitoring & Logging

**Metrics to Track**:
- Filings processed per hour
- Average segments per filing
- Metrics detected per filing
- Error rate by stage

**Logging**:
- Use Python logging module
- Log level: INFO for pipeline progress, DEBUG for details
- Store extraction logs in database for audit

---

**Next Steps**: Begin implementation of HTMLSegmenter (Milestone 1)
