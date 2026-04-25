# Metric Extraction Pipeline

**Version:** 3.1
**Last Updated:** 2026-04-25
**Status:** Production (V2 Pipeline, presence-pivot mid-rollout)

---

> **Pivot status (2026-04-25):** The pipeline's primary scoring surface is **presence** — per-`(doc_id, canonical_metric_id)` records emitted by the final stage `MetricPresenceStage` and persisted to `v2_text_metric_presence`. Per-value `MetricFact` rows continue as **advisory evidence** for text/table sources; chart pipelines emit presence-only signals (`v2_image_assets.detected_metrics`) and never auto-emit per-value chart facts. Chart-presence pivot is **live** (#86, 2026-04-23). Text-presence PR1 **landed** (#182, 2026-04-16). PR2–PR5 pending. See [`docs/operations/text-pipeline-presence-pivot-plan.md`](../operations/text-pipeline-presence-pivot-plan.md) for the rollout plan.

## Overview

This document specifies the architecture and implementation of the metric extraction pipeline. The pipeline transforms SEC filing HTML into structured, analysis-ready **presence** signals (with advisory facts as evidence) through a series of modular processing stages.

**V2 is the sole production pipeline.** V1 has been retired and the `src/extraction/` package has been deleted. See the [Appendix](#appendix-v1-pipeline-retired) at the bottom of this document for V1 stage documentation.

### Pipeline Principles

1. **Auditability:** Every presence row points back to evidence — `evidence_segment_ids` and `advisory_fact_ids` (JSONB arrays on `v2_text_metric_presence`) for text; `v2_image_metric_confirmations` joined to `v2_image_assets` for charts. Every advisory `MetricFact` carries a complete `EvidencePack`.
2. **Reproducibility:** Re-running extraction on the same filing produces identical results. Presence rows are upserted on `(doc_id, canonical_metric_id)`; facts upsert on the 8-column identity index.
3. **Incremental Processing:** Process filings independently; support resume/retry
4. **Quality Tracking:** Capture confidence, alignment, and quality scores throughout. **Primary metric: presence-F1.** Value-correctness is advisory under the pivot.
5. **Structure-first, LLM-second:** Parse DOM structure before LLM calls

---

## V2 Pipeline Overview

The V2 pipeline (`src/extraction_v2/`) implements up to a 16-stage extraction workflow (image stages and `IMAGE_CLASSIFY` are conditional). It is the production pipeline for all SEC filing, transcript, and presentation extraction. The final stage, `MetricPresenceStage`, aggregates signals from text facts, chart `detected_metrics`, and metric definitions into per-`(doc_id, canonical_metric_id)` presence records.

**Module:** `src/extraction_v2/pipeline.py`
**Class:** `V2Pipeline`
**Status:** Production

```
┌─────────────────────────────────────────────────────────────────────┐
│                         FILING HTML INPUT                           │
└────────────────────────────┬────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│  STAGE 1: INGESTION                                                 │
│  - Parse HTML structure                                             │
│  - Extract segments with XPath locators                             │
│  - Build section paths and document positions                       │
│  Output: Segments with XPath locators                               │
└────────────────────────────┬────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│  STAGE 2: SECTION CLASSIFICATION                                    │
│  - Classify sections: MD&A, Risk Factors, Business, etc.            │
│  - Tag segments with section type metadata                          │
│  Output: Segments with section_type labels                          │
└────────────────────────────┬────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│  STAGE 3: TABLE RECONSTRUCTION                                      │
│  - Full colspan/rowspan resolution                                  │
│  - Build header_path and stub_path per cell                         │
│  - Enables precise value-to-header binding                          │
│  Output: Reconstructed Table objects with cell coordinates          │
└────────────────────────────┬────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│  STAGE 4: IMAGE TRIAGE                                              │
│  - Classify images: chart, table_image, decorative, logo, signature │
│  - Filter decorative/non-informative images                         │
│  Output: ImageAsset objects with classification                     │
└────────────────────────────┬────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│  STAGE 5: OCR & CHART EXTRACTION                                    │
│  - OCR text extraction for table images                             │
│  - Vision model analysis for charts (labeled values only)           │
│  - Never interpolates from axes — explicit data labels only         │
│  Output: ImageAsset objects with extracted values                   │
└────────────────────────────┬────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│  STAGE 5a: CHART FACT BRIDGE  (presence-only, no LLM, no facts)     │
│  - ChartMetricClassifier scores chart_data + nearby_text against    │
│    YAML keyword patterns                                            │
│  - Emits [{metric_id, score}, ...] to v2_image_assets.detected_metrics│
│    for scores >= chart_presence_min_score (default 0.5)             │
│  Output: ImageAsset.detected_metrics populated; no MetricFact rows  │
└────────────────────────────┬────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│  STAGE 5b: IMAGE CLASSIFY  (Vision API, gated by ENABLE_METRIC_CLASSIFY)│
│  - Sends chart images to Vision API for metric classification       │
│  - Writes audit trail to v2_image_classifications (append-only)     │
│  - Independent signal from rule-based detected_metrics above        │
│  Output: ImageClassificationRecord rows; no MetricFact rows         │
└────────────────────────────┬────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│  STAGE 6: CANDIDATE GENERATION                                      │
│  - Match YAML taxonomy keywords to segments                         │
│  - Identify metric candidates with positions                        │
│  Output: Candidate list with metric IDs and positions               │
└────────────────────────────┬────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│  STAGE 7: VALUE BINDING                                             │
│  - Link candidate keywords to numeric values                        │
│  - Require structural link (same row/cell for tables)               │
│  - Apply distance thresholds for text segments                      │
│  Output: Bound (keyword, value) pairs with confidence               │
└────────────────────────────┬────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│  STAGE 8: FALSE POSITIVE FILTER                                     │
│  - Filter years, dates, page numbers, fiscal year labels            │
│  - Apply rule-based false positive detection                        │
│  Output: Filtered candidate set                                     │
└────────────────────────────┬────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│  STAGE 9: PERIOD INFERENCE                                          │
│  - Infer reporting period from header_path or surrounding context   │
│  - Normalize period labels (fiscal quarters, annual, etc.)          │
│  Output: Candidates with period_start, period_end                   │
└────────────────────────────┬────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│  STAGE 10: FACT CONSTRUCTION                                        │
│  - Assemble MetricFact with complete EvidencePack                   │
│  - Attach XPath locator, cell coordinates, raw quote                │
│  - Set confidence score                                             │
│  Output: MetricFact objects with EvidencePack                       │
└────────────────────────────┬────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│  STAGE 11: DEFINITION EXTRACTION                                    │
│  - Extract definition and methodology text from definition segments │
│  - Assess alignment with CMASB canonical definitions                │
│  Output: MetricFact objects with definition fields populated        │
└────────────────────────────┬────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│  STAGE 12: DEDUPLICATION                                            │
│  - Deduplicate by identity tuple (metric, period, cohort, value)    │
│  - Prefer highest-confidence source when duplicates exist           │
│  Output: Deduplicated MetricFact list                               │
└────────────────────────────┬────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│  STAGE 13: VALIDATION                                               │
│  - Route facts by confidence: auto-accept / review / reject         │
│  - Thresholds: auto-accept ≥ 0.90, review 0.15-0.90, reject < 0.15 │
│  Output: Validated facts with review_routing label                  │
└────────────────────────────┬────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│  STAGE 14: METRIC PRESENCE  (final; primary scoring surface)        │
│  - Aggregates signals from deduplicated facts, chart                │
│    detected_metrics, and definitions                                │
│  - One row per (doc_id, canonical_metric_id);                       │
│    score = MAX across contributing signals                          │
│  - evidence_segment_ids = union of contributing segment IDs;        │
│    advisory_fact_ids = JSONB list of contributing fact IDs          │
│  Output: MetricPresence list → upserted to v2_text_metric_presence  │
└────────────────────────────┬────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    ANALYSIS-READY DATABASE                          │
│  Presence rows (primary) + advisory facts + reviewer confirmations  │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Chart Fact Bridge — Metric-Presence Emission

The `ChartFactBridgeStage` runs after Stage 13 (Validation) and emits image-level *metric-presence* records. For each processed image with `chart_data` above the vision-confidence threshold, it calls `ChartMetricClassifier.classify_all(chart, nearby_text)` and writes the resulting `[{metric_id, score}, ...]` list to `v2_image_assets.detected_metrics` (JSONB, default `[]`) for scores ≥ `PipelineConfig.chart_presence_min_score`.

Under the chart-presence pivot (#86, 2026-04-23) the stage does **not** emit per-value `MetricFact` rows. Reviewers adjudicate detections via `v2_image_metric_confirmations` (accept / reject / correct / add); values, when CMASB needs them, come through the manual entry path (`POST /api/v2/missed-metric`).

### Classifier-supported metrics

The classifier currently scores against these metric ids (see `_SUPPORTED_METRICS` in `src/extraction_v2/chart/metric_classifier.py`):

- `cm_balance_by_cohort`
- `cm_gross_margin_by_cohort`
- `cm_revenue_by_cohort`
- `cm_transactions_by_cohort`
- `cm_ltv_to_cac_ratio`

New metrics join by extending `_SUPPORTED_METRICS` and tuning cohort / metric gates. No changes to the bridge stage itself are needed per-metric.

### Config

| Field | Default | Purpose |
|-------|---------|---------|
| `chart_image_min_confidence` | `0.6` | Skip images below this vision-model confidence score |
| `chart_presence_min_score` | `0.5` | Minimum classifier score to emit a `(metric_id, score)` pair into `detected_metrics` |
| `enable_chart_candidate_emission` | `False` | Gates `_scan_chart` in `candidate_generation.py`. Leave `False`; re-enabling resurrects chart-annotation false positives. |

### Retired mechanics (pre-#86)

The per-value value-emission path — `CohortParser` regime dispatch, `unit_inference`, Phase 3 hallucination guards (label-required / axis-range / cohort-year / fact-review-threshold), LTV/CAC tenure-bucket bypass into `MetricFact` rows — is no longer in use. The `CohortParser` class was removed in PR 4a; historical references to its regimes (`series-year`, `elapsed-period`, `annotations-only`, `customer-type`) may appear in resolved known-issues fragments but do not reflect current pipeline behavior.

---

## Metric Presence Stage — Final Aggregation

`MetricPresenceStage` (`src/extraction_v2/stages/metric_presence.py`, `PipelineStage.METRIC_PRESENCE`) runs as the final stage after `ValidationStage`. It aggregates extraction signals across all surfaces — deduplicated text/table/OCR facts, chart `detected_metrics`, and metric definitions — into one `MetricPresence` record per `(doc_id, canonical_metric_id)`.

The stage is the **primary scoring surface** for the Tier 1 regression gate under the presence-first pivot. See `docs/operations/text-pipeline-presence-pivot-plan.md`.

### Sources and scoring

| Source | Score contribution | Evidence contribution |
|---|---|---|
| Deduplicated `MetricFact` (text/html_table/ocr_table/chart) | `MAX(fact.confidence)` | `evidence_segment_ids` ← `fact.source_locator.segment_id`; `advisory_fact_ids` ← `fact.fact_id`; `advisory_value_count` += 1 per fact |
| Chart `ImageAsset.detected_metrics` (rule-based; from `ChartFactBridgeStage`) | `MAX(detected.score)` | None — chart-only presences have empty `evidence_segment_ids` (evidence lives on `v2_image_assets`) |
| `v2_metric_definitions` rows | Floor `_DEFINITION_ONLY_PRESENCE_SCORE = 0.5` (matches `chart_presence_min_score`) | `evidence_segment_ids` ← `definition_segment_id`, `methodology_segment_id` |

`detected_at_stage` records which source first surfaced the metric (`fact_construction`, `chart_fact_bridge`, or `definition_extraction`).

### Persistence

`V2PersistenceAdapter._persist_presence_in_tx(cur, presences, filing_id) -> int` upserts presences on `(doc_id, canonical_metric_id)`. Called from `persist_pipeline_result` as step 8 (after facts, definitions, and image classifications). Idempotent; never touches `v2_metric_facts` or `v2_review_decisions`. The `presence_only=True` kwarg on `persist_pipeline_result` skips the fact-write step entirely while still upserting presences and image-related rows.

### Invariants (downstream PRs depend on these)

- One record per `(doc_id, canonical_metric_id)`; duplicates from multiple sources collapse into a single row by MAX score and unioned evidence.
- `advisory_fact_ids` is a JSONB array of fact IDs, **not** a foreign key. Facts may be deleted by `force=True` re-extraction without cascading to presence — presence is a doc-level claim independent of which specific fact rows currently back it.
- Presence rows are upserted, never deleted by the persistence layer; only `filings.filing_id` CASCADE removes them.
- `presence_only=True` does NOT bypass the image re-classification guard inside `_persist_images_in_tx`; that guard remains orthogonal.

---

## Core Data Models

**MetricPresence:** Primary scoring output (per filing × metric)
- Aggregates evidence from text facts, chart detections, and definitions
- Persisted to `v2_text_metric_presence` (sql/46), upserted on `(doc_id, canonical_metric_id)`
- Carries `evidence_segment_ids` and `advisory_fact_ids` JSONB pointers back to source

**MetricFact:** Advisory per-value evidence with full provenance
- Combines extracted value, metric ID, period, cohort, and evidence pack
- Audit trail from detection to acceptance (text/html_table/ocr_table sources)
- Under the chart-presence pivot, the chart pipeline does not auto-emit per-value chart facts; values for chart metrics enter via `POST /api/v2/missed-metric` when CMASB needs them
- Replaces V1's separate `metric_values` and `metric_definitions` tables

**EvidencePack:** Audit-grade proof for every extracted value
- Source type (HTML table, OCR table, text, chart)
- XPath locator for exact DOM position
- Cell coordinates for table values (header_path, stub_path)
- Surrounding context with structural markup
- Raw text quote for verification

**Table:** Reconstructed table with header/stub path binding
- Full colspan/rowspan resolution
- header_path: e.g., `"Revenue" > "Q4 2024"`
- stub_path: e.g., `"Customer Metrics" > "New Customers"`
- Enables precise value-to-header binding
- Column-scan broadcasting is guarded by two complementary checks:
  1. `_stub_matches_different_metric` in `value_binding.py` — suppresses binding when the row stub starts with another tracked metric's specific_pattern.
  2. `_stub_is_financial_line_item` / `_FINANCIAL_LINE_ITEM_STUB_RE` in `value_binding.py` — suppresses binding when the row stub is a financial statement line item (margin, EBITDA, gross profit, accounts payable, etc.) that should never bind to a customer/count metric. Allow-list in `_FINANCIAL_LINE_ITEM_STUB_ALLOW` for metrics whose stubs legitimately contain these terms. Defense-in-depth FP rule `_rule_stub_financial_line_item` in `false_positive_filter.py` provides a second layer.

**ImageAsset:** Extracted image with classification and OCR results
- Classification: chart, table_image, decorative, logo, signature
- Chart type: bar, line, pie, stacked_bar, area
- OCR text extraction for table images
- Vision model analysis for chart values (labeled values only)

---

## Key Files

- **`src/extraction_v2/models.py`** — Core data models (MetricFact, EvidencePack, Table, Cell, ImageAsset, Segment, **MetricPresence**, ImageClassificationRecord, DetectedMetric)
- **`src/extraction_v2/pipeline.py`** — Pipeline orchestrator with up-to-16-stage workflow and configuration
- **`src/extraction_v2/persistence.py`** — Database write layer (V2PersistenceAdapter; `presence_only` kwarg skips fact write)
- **`src/extraction_v2/table_reconstructor.py`** — Table reconstruction with colspan/rowspan resolution
- **`src/extraction_v2/stages/ingestion.py`** — HTML parsing with XPath locators and segment extraction
- **`src/extraction_v2/stages/metric_presence.py`** — Final stage; aggregates facts/charts/definitions into per-(doc, metric) presence
- **`src/extraction_v2/stages/chart_fact_bridge.py`** — Rule-based chart-presence emission to `v2_image_assets.detected_metrics`
- **`src/extraction_v2/stages/image_classify.py`** — Vision-API metric classifier; gated by `ENABLE_METRIC_CLASSIFY`
- **`src/extraction_v2/stages/`** — One module per pipeline stage

---

## Design Principles

1. **Presence-first, values advisory**: The primary scoring surface is `MetricPresence` (per-`(doc_id, metric_id)`). Per-value `MetricFact` rows are advisory evidence; chart pipelines emit presence-only signals.
2. **Structure-first, LLM-second**: Parse DOM structure before LLM calls
3. **No claim without provenance**: Every presence row carries `evidence_segment_ids` + `advisory_fact_ids`. Every advisory `MetricFact` includes a complete `EvidencePack`.
4. **Fail closed**: Ambiguous cases route to review (never guess)
5. **Charts only when labeled**: Stage 5 extracts only explicit data labels (never interpolates from axes)
6. **Complete table reconstruction**: Full colspan/rowspan resolution before extraction
7. **DOM-native**: XPath locators maintain exact source positions

---

## Configuration

V2 pipeline is configured via `PipelineConfig` dataclass:

```python
from src.extraction_v2.pipeline import V2Pipeline, PipelineConfig
from pathlib import Path

config = PipelineConfig(
    enable_section_classification=True,
    enable_image_extraction=True,
    enable_chart_extraction=True,
    min_confidence_auto_accept=0.90,
    min_confidence_no_review=0.85,
    max_confidence_auto_reject=0.15,
    max_table_rows=1000,
    max_images_per_document=50,
    batch_size=10,
    max_llm_calls_per_document=100,
    save_evidence_screenshots=True,
    evidence_screenshot_dir="evidence_v2/"
)

pipeline = V2Pipeline(config=config)
result = pipeline.process(html_path=Path("filing.html"), filing_id=123)
```

**Environment Variables:**
```bash
DATABASE_URL=postgresql://user:password@localhost/filings_analysis
OPENAI_API_KEY=sk-...  # For LLM-enhanced extraction and OCR
```

---

## Related Documentation

- **System Architecture:** `docs/architecture/system-overview.md` — High-level design
- **Data Model:** `docs/architecture/data-model.md` — Database schemas
- **LLM Integration:** `docs/architecture/llm-integration.md` — OpenAI integration details
- **Quality Model:** `docs/development/quality-model.md` — QA scoring framework
- **Metrics Taxonomy:** `docs/development/metrics-taxonomy.md` — Canonical metric definitions

---

## Appendix: V1 Pipeline (Retired)

> **V1 is retired and `src/extraction/` has been fully deleted.** The V1 segmenter (`html_segmenter.py`) was preserved in `src/shared/` as legacy reference material until 2026-04-20, when it too was deleted (see KNOWN_ISSUES #32). The companion modules `exceptions.py` and `validators.py` are still used independently by V2 (`src/shared/extraction_exceptions.py`, `src/shared/segment_validators.py`). All other V1 source files described below (`keyword_config.py`, `models.py`, `metric_classifier.py`, `segment_enricher.py`, `enricher_config.py`, `cohort_chart_detector.py`, `value_extractor.py`, `definition_extractor.py`, `quality_scorer.py`, `extraction_pipeline.py`, `structure_parser.py`, `candidate_detector.py`, `context_extractor.py`) have been **deleted** from the repository. The component specifications below are preserved as historical documentation only — the files no longer exist and the code cannot be run.

The V1 pipeline implemented a 5-stage extraction workflow (HTML Segmentation → Metric Classification → Segment Enrichment → Value Extraction → Definition Extraction → Quality Scoring). The stage descriptions below are preserved for historical reference.

---

### V1 Component Specifications

#### 1. HTML Segmenter

**Module:** `src/extraction/html_segmenter.py` (deleted)
**Class:** `HTMLSegmenter`
**Status:** Retired — file deleted 2026-04-20 (KNOWN_ISSUES #32)

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

#### 2. Metric Classifier

**Module:** `src/extraction/metric_classifier.py` (deleted)
**Class:** `MetricClassifier`
**Status:** Retired — file deleted

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

#### 2.5. Segment Enricher (G4-G8)

**Module:** `src/extraction/segment_enricher.py` (deleted)
**Class:** `SegmentEnricher`
**Status:** Retired — file deleted

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
# V1 only — src/extraction/ deleted in V2 migration
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

---

#### 2.6. Cohort Chart Detector

**Module:** `src/extraction/cohort_chart_detector.py` (deleted)
**Class:** `CohortChartDetector`
**Status:** Retired — file deleted

**Responsibilities:**
- Detect cohort analysis charts and visualizations in filing HTML
- Find images with "cohort" keywords in surrounding text (within 1500 chars)
- Calculate confidence scores based on context quality
- Filter decorative images (icons, logos, bullets)

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

---

#### 3. Value Extractor

**Module:** `src/extraction/value_extractor.py` (deleted)
**Class:** `ValueExtractor`
**Status:** Retired — file deleted

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
        """Extract all metric values from a segment."""

    def extract_from_table(self, segment: SourceSegment) -> List[MetricValue]:
        """Extract structured data from table segments."""

    def parse_cohort_label(self, raw_label: str) -> tuple[str, str]:
        """
        Parse cohort label into type and normalized bucket.

        Examples:
            "2021 Cohort" -> ("acquisition", "2021")
            "0-12 months" -> ("tenure", "0-1y")
        """
```

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

#### 4. Definition Extractor

**Module:** `src/extraction/definition_extractor.py` (deleted)
**Class:** `DefinitionExtractor`
**Status:** Retired — file deleted

**Responsibilities:**
- Extract definition text from definition segments
- Extract methodology/calculation text from methodology segments
- Clean and normalize text
- Assess alignment with CMASB canonical definitions

**Interface:**

```python
class DefinitionExtractor:
    def extract_definition(self, segment: SourceSegment, metric_id: str) -> MetricDefinition:
        """Extract definition for a specific metric from a segment."""

    def assess_alignment(self, issuer_definition: str, canonical_definition: str) -> str:
        """
        Assess alignment between issuer and CMASB definitions.

        Returns:
            'aligned', 'partial', 'not_aligned', or 'unknown'
        """
```

**Alignment Assessment:**
- Keyword overlap between issuer and canonical definitions
- High overlap (>70%) → 'aligned'
- Medium overlap (30-70%) → 'partial'
- Low overlap (<30%) → 'not_aligned'

---

#### 5. Quality Scorer

**Module:** `src/extraction/quality_scorer.py` (deleted)
**Class:** `QualityScorer`
**Status:** Retired — file deleted

**Responsibilities:**
- Aggregate filing x metric incidence
- Count segments by type for each metric
- Compute quality scores (0-3 scale)
- Identify primary definition/methodology segments
- Set cohort breakdown flags

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

---

#### V1 Main Extraction Pipeline

**Module:** `src/extraction/extraction_pipeline.py` (deleted)
**Class:** `ExtractionPipeline`
**Status:** Retired — file deleted

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
        """Run full V1 extraction pipeline for a single filing (retired)."""

    def process_batch(self, filing_ids: List[int]) -> BatchResult:
        """Process multiple filings (retired)."""
```

---

#### V1 Supporting Modules

**Structure Parser (EA-1)**
- **Module:** `src/extraction/structure_parser.py` (deleted)
- Parses HTML while preserving DOM structure for position mapping
- Tracks table row and cell boundaries during HTML-to-text conversion

**Candidate Detector (EA-2)**
- **Module:** `src/extraction/candidate_detector.py` (deleted)
- Unified metric candidate detection consolidating CandidateGenerator and ValueExtractor
- Integrates FalsePositiveFilter; uses StructureParser for table-aware row validation

**Context Extractor (EA-3)**
- **Module:** `src/extraction/context_extractor.py` (deleted)
- Extracts clean context around metric values with table awareness
- Uses StructureParser to respect row boundaries in table segments

---

**Last Updated:** 2026-04-07
**Version:** 3.0
**Status:** Production (V2), Retired (V1)

**Changelog:**
- v3.0 (2026-04-07): V2 promoted to production; V1 pipeline moved to retired appendix
- v2.5 (2026-02-03): Added Extraction V2 Pipeline documentation (experimental research implementation)
- v2.4 (2025-12-26): Added CandidateDetector (EA-2) — unified candidate detection module
- v2.3 (2025-12-26): Added StructureParser (EA-1) and ContextExtractor (EA-3) documentation
- v2.2 (2025-12-17): Added SegmentEnricher configuration system (GR-11)
- v2.1 (2025-12-16): Enhanced HTML segmentation with sentence detection, definition merging, 25K table limit, context enrichment, and list handling
