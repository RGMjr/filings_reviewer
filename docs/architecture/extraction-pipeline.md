# Metric Extraction Pipeline

**Version:** 2.9
**Last Updated:** 2026-03-02
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

## V1 Pipeline (Legacy)

The V1 extraction pipeline (`src/extraction/`) has been deprecated and removed as of V2.
Full component specifications (HTMLSegmenter, MetricClassifier, SegmentEnricher, ValueExtractor,
DefinitionExtractor, QualityScorer, ExtractionPipeline) are preserved in git history.

See `docs/V2_MIGRATION_GUIDE.md` for migration guidance.

---

## Extraction V2 Pipeline

### Overview

The V2 extraction pipeline (`src/extraction_v2/`) is a complete ground-up redesign with all 13 implementation phases finished. It runs alongside V1 and is the target for new extraction work.

**Version:** `2.0.0-rc1`
**Status:** Production-ready (P=92.8%, R=77.6%, F1=84.5% on gold standard, as of 2026-02-28)
**See also:** `docs/V2_IMPLEMENTATION_ROADMAP.md`, `docs/V2_MIGRATION_GUIDE.md`, `docs/operations/v2-deployment-guide.md`

### Key Architectural Differences

| Aspect | V1 (Production) | V2 (Research) |
|--------|----------------|---------------|
| **Approach** | Text-first, keyword-based | Structure-first, DOM-native |
| **Table Handling** | Text extraction with markers | Full reconstruction (colspan/rowspan) |
| **Image Processing** | Basic detection | OCR + chart extraction via vision models |
| **Provenance** | Segment ID linkage | Complete audit trail (XPath, cell coordinates, EvidencePack) |
| **Data Model** | Normalized database tables | MetricFact + EvidencePack dataclasses |
| **LLM Usage** | Selective (definitions, unstructured text) | Structure-first, LLM fallback only |
| **Status** | Production ready (87% coverage) | Production ready (F1=84.5%) |

### V2 Pipeline Stages

The V2 pipeline implements a 13-stage extraction workflow, plus post-completion enhancements:

```
1.  Ingestion & Parsing         → Segments with XPath locators
2.  Section Classification      → MD&A, Risk Factors, Business, etc.
3.  Table Reconstruction        → header_path, stub_path per cell
4.  Image Triage                → chart, table_image, decorative
5.  OCR & Chart Extraction      → labeled values only (never interpolate)
6.  Metric Candidate Generation → YAML taxonomy matching
7.  Value Binding               → structural link required
7.5 False Positive Filtering    → unit compatibility, decimal-gated count scaling
8.  Period Inference            → from header_path or context
9.  MetricFact Construction     → with complete evidence_pack
9.5 Definition Extraction       → DEFINITION/METHODOLOGY segments near candidates (±5 window), CMASB alignment scoring
10. Deduplication               → by identity tuple (metric, period, cohort, value)
11. Validation & Review Routing → confidence-based (auto-accept/review/reject)
12. Database Persistence        → v2_* tables with idempotent upserts
13. Integration & Validation    → gold standard regression testing
```

### Core Data Models

**MetricFact:** Primary extraction output with full provenance
- Combines extracted value, metric ID, period, cohort, and evidence
- Immutable audit trail from detection to acceptance
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

**ImageAsset:** Extracted image with classification and OCR results
- Classification: chart, table_image, decorative, logo, signature
- Chart type: bar, line, pie, stacked_bar, area
- OCR text extraction for table images
- Vision model analysis for chart values (labeled values only)

### Key Files

- **`models.py`** - Core data models (MetricFact, EvidencePack, Table, Cell, ImageAsset, Segment)
- **`pipeline.py`** - Pipeline orchestrator with 13-stage workflow and configuration
- **`table_reconstructor.py`** - Table reconstruction with colspan/rowspan resolution
- **`stages/ingestion.py`** - HTML parsing with XPath locators and segment extraction

### Design Principles (V2)

1. **Structure-first, LLM-second**: Parse DOM structure before LLM calls (opposite of V1)
2. **No value without provenance**: Every MetricFact includes complete EvidencePack
3. **Fail closed**: Ambiguous cases route to review (never guess)
4. **Charts only when labeled**: Extract only explicit data labels (never interpolate from axis)
5. **Complete table reconstruction**: Full colspan/rowspan resolution before extraction
6. **DOM-native**: XPath locators maintain exact source positions

### When to Use V1 vs V2

**Use V2 for:**
- New filings requiring full provenance tracking (XPath, EvidencePack)
- Filings with complex tables (multi-level headers, merged cells)
- Filings with chart images containing labeled values
- Research requiring audit-grade evidence packs

**Continue using V1 for:**
- Bulk re-processing of the full corpus where speed is critical
- Legacy integrations expecting V1 output format (`metric_values`, `metric_definitions` tables)

### Configuration

V2 pipeline is configured via `PipelineConfig` dataclass:

```python
from src.extraction_v2.pipeline import V2Pipeline, PipelineConfig

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

---

**Last Updated:** 2026-03-02
**Version:** 2.9
**Status:** Production Ready

**Changelog:**
- v2.9 (2026-03-02): Removed V1 component specs (HTMLSegmenter, MetricClassifier, SegmentEnricher, ValueExtractor, DefinitionExtractor, QualityScorer, ExtractionPipeline); replaced with legacy note pointing to git history and V2_MIGRATION_GUIDE.md
- v2.8 (2026-02-26): V2 promoted to 2.0.0-rc1; noted exception architecture (V2FatalError/V2TransientError); added v2-deployment-guide cross-reference
- v2.7 (2026-02-24): Updated V2 gold standard scores to P=78.6%/R=79.2%/F1=78.9% (post-WP-09); added Stage 9.5 Definition Extraction to V2 stage list
- v2.6 (2026-02-20): Removed deleted cohort_chart_detector section; updated V2 stage list (13 stages + FP filter); corrected V2Pipeline class name and process() method; removed config/extraction.yaml reference; added extraction-decisions.md cross-reference; updated V2 from alpha to production-ready
- v2.5 (2026-02-03): Added Extraction V2 Pipeline documentation
- v2.4 (2025-12-26): Added CandidateDetector (EA-2) - unified candidate detection module
- v2.3 (2025-12-26): Added StructureParser (EA-1) and ContextExtractor (EA-3) documentation
- v2.2 (2025-12-17): Added SegmentEnricher configuration system (GR-11)
- v2.1 (2025-12-16): Enhanced HTML segmentation with sentence detection, definition merging, 25K table limit, context enrichment, and list handling
