# V2 Extraction Pipeline Implementation Roadmap

**Version**: 1.1
**Created**: 2026-01-23
**Updated**: 2026-02-03
**Status**: In Progress (Phases 0-3, 6 Complete)

## Executive Summary

The V2 extraction pipeline is a ground-up redesign that addresses V1 limitations while preserving its best patterns. Key improvements:

1. **10x faster HTML parsing** via lxml (vs BeautifulSoup)
2. **Stable XPath locators** for every source element
3. **Full table structure** with header_path/stub_path binding
4. **OCR/Vision integration** for chart/table image extraction
5. **1-click evidence packs** for human review
6. **Semantic section classification** (MD&A, Risk Factors, etc.)

---

## Implementation Phases

### Phase 0: Foundation ✅ COMPLETE (2026-01-23)

**Deliverables:**
- [x] Data models (`src/extraction_v2/models.py`) - 663 lines
- [x] Pipeline orchestrator (`src/extraction_v2/pipeline.py`) - 732 lines
- [x] Database schema (`sql/09_v2_schema.sql`) - 423 lines
- [x] Unit tests (45 tests passing)

**Key Models:**
- `MetricFact`: Primary output with provenance + evidence
- `EvidencePack`: snippet_html, header_path, stub_path, context
- `SourceLocator`: segment_id, table_id, cell coords, dom_locator
- `Table`, `Cell`: Grid structure with span resolution
- `Segment`: DOM-native block with section classification
- `ImageAsset`: Chart/table image with OCR/vision results
- `Document`: Filing container

---

### Phase 1: Ingestion & Parsing (Stage 1) ✅ COMPLETE (2026-01-30)

**Goal**: Parse HTML to Segments with stable XPath locators

**Tasks:**
1. [x] Create `src/extraction_v2/stages/ingestion.py`
2. [x] Implement lxml-based HTML parser
   - Use `lxml.html.parse()` for DOM tree
   - Generate XPath for every element
   - Extract text content with structure markers
3. [x] Port segment detection from V1 `html_segmenter.py`
   - Paragraph detection (min 50 chars)
   - Table detection with div-wrapper deduplication
   - Definition/methodology block detection
4. [x] Extract `ImageAsset` objects
   - Store nearby text (caption + context)
   - Compute initial relevance score
5. [x] Create `Segment` objects with:
   - `dom_locator` (XPath)
   - `segment_type` (paragraph, table, etc.)
   - `text` with `[CELL]`/`[ROW]` markers
   - `sequence` (document order)
6. [x] Add tests for lxml parsing (56 tests passing)

**Dependencies:** None (first stage)

**Estimated Complexity:** L (2-4 hours)

**Files to Create:**
- `src/extraction_v2/stages/__init__.py`
- `src/extraction_v2/stages/ingestion.py`
- `tests/unit/extraction_v2/test_ingestion.py`

**V1 Code to Reference:**
- `src/extraction/html_segmenter.py` (segment detection patterns)
- `src/extraction/structure_parser.py` (text markers)

---

### Phase 2: Section Classification (Stage 2) ✅ COMPLETE (2026-01-31)

**Goal**: Classify segments into semantic SEC sections

**Tasks:**
1. [x] Create `src/extraction_v2/stages/section_classification.py`
2. [x] Implement section detectors:
   - Cover page (first N segments, company info)
   - Risk Factors (heading pattern + risk vocabulary)
   - MD&A ("Management's Discussion", revenue/growth terms)
   - Business (company description, products, customers)
   - Financials (financial statements, numbers-heavy)
   - Notes (footnote patterns, exhibits)
3. [x] Assign `section_path` (hierarchical) and `section_type` (enum)
4. [x] Filter irrelevant sections (Exhibits, Signatures, Legal)
5. [x] Add tests for section classification

**Dependencies:** Phase 1 (needs Segments)

**Estimated Complexity:** M (1-2 hours)

**Files to Create:**
- `src/extraction_v2/stages/section_classification.py`
- `tests/unit/extraction_v2/test_section_classification.py`

---

### Phase 3: Table Reconstruction (Stage 3) ✅ COMPLETE (2026-02-02)

**Goal**: Full colspan/rowspan resolution with header_path/stub_path

**Tasks:**
1. [x] Create `src/extraction_v2/stages/table_reconstruction.py`
2. [x] Implement span resolution algorithm:
   - Build 2D grid from `<table>` HTML
   - Expand rowspan/colspan to fill logical cells
   - Validate: no gaps, no overlaps
3. [x] Identify header rows:
   - `<th>` elements
   - First row(s) with non-numeric text
   - Bold/styled rows
4. [x] Identify stub columns:
   - First column(s) with labels
   - Semantic patterns ("Total", metric names)
5. [x] Compute for each cell:
   - `header_path`: all headers above (column headers)
   - `stub_path`: all stubs to left (row labels)
6. [x] Store `Table` objects in context
7. [x] Add comprehensive tests (11 new tests, 87% coverage)

**Dependencies:** Phase 1 (needs Segments with table HTML)

**Estimated Complexity:** L (2-4 hours)

**Files to Create:**
- `src/extraction_v2/stages/table_reconstruction.py`
- `tests/unit/extraction_v2/test_table_reconstruction.py`

**V1 Code to Reference:**
- `src/extraction/structure_parser.py` (TableRowParser)
- `src/review/table_structure.py` (row parsing)

---

### Phase 4: Image Triage (Stage 4)

**Goal**: Classify and prioritize images for extraction

**Tasks:**
1. [ ] Create `src/extraction_v2/stages/image_triage.py`
2. [ ] Classify images:
   - Chart (bar, line, pie patterns)
   - Table image (gridded, OCR needed)
   - Decorative (logos, icons, bullets)
   - Signature/legal
3. [ ] Score relevance:
   - Keyword proximity (1500 chars)
   - Section context (MD&A > Cover)
   - Caption analysis
4. [ ] Filter decorative images:
   - Size filters (min 100x100)
   - Naming patterns (logo, icon, bullet)
5. [ ] Queue relevant images for OCR/Vision
6. [ ] Add tests

**Dependencies:** Phase 1 (needs ImageAsset objects)

**Estimated Complexity:** M (1-2 hours)

**Files to Create:**
- `src/extraction_v2/stages/image_triage.py`
- `tests/unit/extraction_v2/test_image_triage.py`

**V1 Code to Reference:**
- `src/extraction/cohort_chart_detector.py`
- `src/extraction/segment_enricher.py` (_detect_cohort_chart_images)

---

### Phase 5: OCR & Chart Extraction (Stage 5)

**Goal**: Extract values from relevant images

**Tasks:**
1. [ ] Create `src/extraction_v2/stages/ocr_chart_extraction.py`
2. [ ] Implement PaddleOCR integration for table images:
   - OCR text extraction
   - Table structure reconstruction
   - Create `Table` objects from OCR results
3. [ ] Implement Claude Vision integration for charts:
   - Extract title, axis labels
   - Extract ONLY explicitly labeled values
   - NEVER interpolate from axis readings
4. [ ] Handle extraction failures:
   - Set `requires_manual_capture = True`
   - Store partial results with low confidence
5. [ ] Add cost controls:
   - Max images per document
   - Max LLM/OCR calls
6. [ ] Add tests (mock OCR/Vision responses)

**Dependencies:** Phase 4 (needs prioritized images)

**Estimated Complexity:** XL (4+ hours - external API integration)

**Files to Create:**
- `src/extraction_v2/stages/ocr_chart_extraction.py`
- `tests/unit/extraction_v2/test_ocr_chart.py`

**External Dependencies:**
- PaddleOCR library
- Claude Vision API (via existing `src/llm/openai_client.py` pattern)

---

### Phase 6: Candidate Generation (Stage 6) ✅ COMPLETE (2026-02-03)

**Goal**: Find metric mentions in all content

**Tasks:**
1. [x] Create `src/extraction_v2/stages/candidate_generation.py`
2. [x] Port YAML taxonomy loading from V1:
   - Use `src/extraction/keyword_config.py`
   - Load patterns, exclusions, required_context
3. [x] Scan all content:
   - Segment text
   - Table cell text (header_path + stub_path)
4. [x] Apply filters:
   - Exclusion patterns
   - Required context with proximity-based checking
   - Deduplication for overlapping patterns
5. [x] Create candidate objects with:
   - metric_id
   - source_locator (where found)
   - match_text
   - confidence score
6. [x] Add tests (42 tests, 96% coverage)

**Dependencies:** Phase 3 (tables) ✅

**Estimated Complexity:** M (1-2 hours)

**Files to Create:**
- `src/extraction_v2/stages/candidate_generation.py`
- `tests/unit/extraction_v2/test_candidate_generation.py`

**V1 Code to Reuse:**
- `src/extraction/keyword_config.py` (import directly)
- `src/review/false_positive_filter.py` (import directly)

---

### Phase 7: Value Binding (Stage 7)

**Goal**: Link metric keywords to numeric values

**Tasks:**
1. [ ] Create `src/extraction_v2/stages/value_binding.py`
2. [ ] Implement table binding:
   - Find metric in header_path or stub_path
   - Bind value from data cell
   - Store header_path/stub_path in evidence
3. [ ] Implement text binding:
   - Find number within N words of keyword
   - Validate same sentence/paragraph
4. [ ] Implement chart binding:
   - Use axis labels from ChartData
   - Only labeled values (no interpolation)
5. [ ] **RULE: No binding without structural link**
6. [ ] Output `BoundValue` objects:
   - candidate reference
   - value (numeric)
   - unit (%, $, count)
   - binding confidence
7. [ ] Add tests

**Dependencies:** Phase 3 (header_path), Phase 6 (candidates)

**Estimated Complexity:** L (2-4 hours)

**Files to Create:**
- `src/extraction_v2/stages/value_binding.py`
- `tests/unit/extraction_v2/test_value_binding.py`

**V1 Code to Reference:**
- `src/extraction/value_extractor.py` (binding logic)
- `src/extraction/structure_parser.py` (same-row validation)

---

### Phase 8: Period Inference (Stage 8)

**Goal**: Determine time period for each value

**Tasks:**
1. [ ] Create `src/extraction_v2/stages/period_inference.py`
2. [ ] Extract from table headers:
   - "FY 2024", "Q3 2025"
   - "Year Ended December 31"
   - Column date patterns
3. [ ] Extract from text context:
   - "For the year ended..."
   - "As of March 31, 2025"
4. [ ] Validate against filing fiscal period
5. [ ] Flag ambiguous periods for review
6. [ ] Add tests

**Dependencies:** Phase 7 (bound values with source context)

**Estimated Complexity:** M (1-2 hours)

**Files to Create:**
- `src/extraction_v2/stages/period_inference.py`
- `tests/unit/extraction_v2/test_period_inference.py`

**V1 Code to Reference:**
- `src/extraction/context_extractor.py` (period patterns)

---

### Phase 9: Fact Construction (Stage 9)

**Goal**: Build MetricFact with full provenance

**Tasks:**
1. [ ] Create `src/extraction_v2/stages/fact_construction.py`
2. [ ] Assemble MetricFact:
   - All fields from BoundValue
   - source_locator from binding
   - source_type (HTML_TABLE, TEXT, CHART)
3. [ ] Compute confidence score:
   - Base from binding confidence
   - Bonuses: high-value section, specific_pattern match
   - Penalties: OCR source, ambiguous period
4. [ ] Generate EvidencePack:
   - snippet_html (highlighted value)
   - header_path, stub_path (if table)
   - context_before, context_after (if text)
   - screenshot_path (if chart)
5. [ ] Add tests

**Dependencies:** Phase 7, Phase 8

**Estimated Complexity:** M (1-2 hours)

**Files to Create:**
- `src/extraction_v2/stages/fact_construction.py`
- `tests/unit/extraction_v2/test_fact_construction.py`

---

### Phase 10: Deduplication (Stage 10)

**Goal**: Merge duplicate facts, link alternates

**Tasks:**
1. [ ] Create `src/extraction_v2/stages/deduplication.py`
2. [ ] Group by identity tuple:
   - (metric_id, period_start, period_end, unit, value±2%, scope, cohort, customer_type)
3. [ ] Select primary by source quality:
   - HTML_TABLE > TEXT > OCR_TABLE > CHART
4. [ ] Link alternates:
   - Store in `alternate_evidence` list
   - Preserve all source_locators
5. [ ] Add tests

**Dependencies:** Phase 9

**Estimated Complexity:** S (30-60 min)

**Files to Create:**
- `src/extraction_v2/stages/deduplication.py`
- `tests/unit/extraction_v2/test_deduplication.py`

---

### Phase 11: Validation & Review Routing (Stage 11)

**Goal**: Route facts by confidence

**Tasks:**
1. [ ] Create `src/extraction_v2/stages/validation.py`
2. [ ] Implement routing rules:
   - confidence >= 0.90: auto_accept
   - confidence < 0.15: auto_reject candidate
   - else: pending_review
3. [ ] Set review_reason for flagged facts
4. [ ] Validate schema completeness
5. [ ] Add tests

**Dependencies:** Phase 9, Phase 10

**Estimated Complexity:** S (30-60 min)

**Files to Create:**
- `src/extraction_v2/stages/validation.py`
- `tests/unit/extraction_v2/test_validation.py`

**Note:** Stage 11 stub already exists in `pipeline.py`

---

### Phase 12: Database Persistence

**Goal**: Store V2 facts in PostgreSQL

**Tasks:**
1. [ ] Create `src/extraction_v2/persistence.py`
2. [ ] Implement upsert for all V2 tables:
   - v2_documents
   - v2_segments
   - v2_tables, v2_table_cells
   - v2_image_assets
   - v2_metric_facts
3. [ ] Use JSONB for:
   - source_locator
   - evidence_pack
   - extra_metadata
4. [ ] Ensure idempotent (re-runs safe)
5. [ ] Add integration tests

**Dependencies:** All stages, database schema

**Estimated Complexity:** M (1-2 hours)

**Files to Create:**
- `src/extraction_v2/persistence.py`
- `tests/integration/extraction_v2/test_persistence.py`

---

### Phase 13: Integration & Validation

**Goal**: End-to-end pipeline testing

**Tasks:**
1. [ ] Create end-to-end test with real filing
2. [ ] Compare V2 output against V1 baseline
3. [ ] Run gold standard validation
4. [ ] Performance benchmarks (V2 vs V1)
5. [ ] Document migration path

**Dependencies:** All phases

**Estimated Complexity:** L (2-4 hours)

---

## Dependency Graph

```
Phase 1 (Ingestion)
    ├── Phase 2 (Section Classification)
    ├── Phase 3 (Table Reconstruction)
    │       └── Phase 7 (Value Binding)
    │               └── Phase 8 (Period Inference)
    │                       └── Phase 9 (Fact Construction)
    │                               └── Phase 10 (Deduplication)
    │                                       └── Phase 11 (Validation)
    └── Phase 4 (Image Triage)
            └── Phase 5 (OCR & Chart)
                    └── Phase 6 (Candidate Generation)
                            └── Phase 7 (Value Binding) [joins]

Phase 12 (Persistence) ← All stages
Phase 13 (Integration) ← All phases
```

---

## Recommended Implementation Order

### Sprint 1: Core Pipeline (Phases 1-3, 6-7)
1. Phase 1: Ingestion (lxml parsing, XPath)
2. Phase 3: Table Reconstruction (spans, header_path)
3. Phase 6: Candidate Generation (YAML matching)
4. Phase 7: Value Binding (table + text)

### Sprint 2: Enrichment (Phases 2, 8-11)
1. Phase 2: Section Classification
2. Phase 8: Period Inference
3. Phase 9: Fact Construction
4. Phase 10-11: Deduplication + Validation

### Sprint 3: Images (Phases 4-5)
1. Phase 4: Image Triage
2. Phase 5: OCR & Chart Extraction

### Sprint 4: Production (Phases 12-13)
1. Phase 12: Database Persistence
2. Phase 13: Integration & Validation

---

## Quality Gates

Each phase must pass before moving to next:

1. **Unit tests passing** (pytest)
2. **Type checking** (mypy --strict on new modules)
3. **Code coverage** >= 80% for new code
4. **Gold standard validation** (if extraction changes)
5. **Code review** (self-review checklist)

---

## V1 Modules to Reuse (Import Directly)

These V1 modules are stable and should be imported into V2:

| Module | Purpose | Import As |
|--------|---------|-----------|
| `src/extraction/keyword_config.py` | YAML taxonomy | `from src.extraction.keyword_config import get_metric_keywords` |
| `src/review/false_positive_filter.py` | Date/year filtering | `from src.review.false_positive_filter import FalsePositiveFilter` |
| `src/review/number_parsing.py` | Number extraction | `from src.review.number_parsing import parse_number` |
| `src/extraction/quality_scorer.py` | Quality dimensions | Adapt for V2 facts |

---

## Next Steps

1. **Create Worker Prompt** for Phase 1 (Ingestion)
2. **Populate `ops/DEVELOPMENT_PLAN.md`** with Phase 1 acceptance criteria
3. **Start Ralph** in develop mode

---

## Changelog

| Date | Version | Changes |
|------|---------|---------|
| 2026-01-23 | 1.0 | Initial roadmap based on V1 analysis |
