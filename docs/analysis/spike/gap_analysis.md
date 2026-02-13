# Gap Analysis: V2 Pipeline for Non-SEC Documents

**Date:** 2026-02-13
**Status:** Complete
**Phase:** 4 of 6

## Stage-by-Stage Assessment

### Stage 1: Ingestion & Parsing

| Dimension | Transcripts | Presentations (estimated) |
|-----------|-------------|---------------------------|
| **Status** | Works | Depends on converter quality |
| **Input format** | HTML (converted from text) | HTML (converted from PDF/PPTX) |
| **Segments extracted** | 22-80 per file | ~20-50 per file (est.) |
| **Quality** | Good — speaker turns become segments | Variable — PDF text extraction lossy |
| **Changes needed** | None | PDF/PPTX converter needed upstream |

**Finding:** The ingestion stage is format-agnostic. It parses whatever HTML is provided. The quality depends entirely on the upstream conversion.

### Stage 2: Section Classification

| Dimension | Transcripts | Presentations (estimated) |
|-----------|-------------|---------------------------|
| **Status** | **Fails gracefully** | **Fails gracefully** |
| **Pattern matching** | 0 SEC patterns match | 0 SEC patterns match |
| **Result** | All segments → COVER | All segments → COVER |
| **Impact** | No section-based confidence boost | No section-based confidence boost |
| **Changes needed** | New patterns for Operator/Remarks/Q&A | New patterns for slide sections |

**Finding:** Section classification fails silently — all segments get `SectionType.COVER` which doesn't break downstream stages but removes a quality signal. The pipeline's `enable_section_classification=True/False` flag already provides a clean toggle.

**Specific gaps:**
- No patterns for "Prepared Remarks", "Question-and-Answer Session"
- No speaker-role detection (CEO, CFO, Analyst)
- No slide-section patterns ("Key Metrics", "Business Highlights", "Financial Overview")

**Recommendation:** Add a `document_type` parameter to the pipeline context. When `document_type='transcript'`, use a separate set of section patterns. When `document_type='presentation'`, use slide-section patterns. Default to current SEC patterns.

### Stage 3: Table Reconstruction

| Dimension | Transcripts | Presentations (estimated) |
|-----------|-------------|---------------------------|
| **Status** | **Graceful no-op** | Likely partial |
| **Tables found** | 0 (correct — no tables) | Some if PDF has extractable tables |
| **Changes needed** | None | May need to handle text-box "tables" |

**Finding:** Transcripts have zero tables, so this stage correctly produces zero output. No changes needed for transcript support. Presentations may have table-like layouts that are rendered as positioned text rather than `<table>` elements, which would require a different reconstruction approach.

### Stage 4: Image Triage

| Dimension | Transcripts | Presentations (estimated) |
|-----------|-------------|---------------------------|
| **Status** | **N/A** (disabled) | Works as-is |
| **Images found** | 0 | Many (charts, photos, logos) |
| **Changes needed** | None | None (already has chart detection) |

**Finding:** Transcripts are pure text — image triage is correctly skipped when `enable_image_extraction=False`. Presentations would benefit from the existing image/chart pipeline.

### Stage 5: OCR & Chart Extraction

| Dimension | Transcripts | Presentations (estimated) |
|-----------|-------------|---------------------------|
| **Status** | **N/A** (disabled) | Works as-is |
| **Changes needed** | None | May need chart-specific tuning |

### Stage 6: Candidate Generation — WORKS

| Dimension | Transcripts | Presentations (estimated) |
|-----------|-------------|---------------------------|
| **Status** | **Works** | **Works** |
| **Candidates/file** | 1-44 (avg ~10) | Similar (est.) |
| **Keyword coverage** | Good for SaaS vocabulary | Good |
| **Changes needed** | Industry-specific patterns | None |

**Finding:** Keyword matching is the strongest stage for transcript support. The `metric_keywords.yaml` patterns match conversational language well for SaaS/subscription companies.

**Specific gaps (transcript-specific):**
1. **Meta-specific language:** "people using at least one of our apps each day" → should match DAU. Add patterns like `\bpeople\s+using\b.*\bdaily\b` to `cm_daily_active_users`
2. **Telecom language:** "postpaid phone net customer additions" → not matched. Add telecom-specific patterns
3. **Gaming language:** "live services player base" → not matched by `cm_active_customers_total`
4. **Fintech language:** "active accounts" partially matched, but "monthly active unique accounts" not consistently caught

### Stage 7: Value Binding — MAJOR GAP

| Dimension | Transcripts | Presentations (estimated) |
|-----------|-------------|---------------------------|
| **Status** | **Partial — bottleneck** | **Unknown** |
| **Binding rate** | ~40% of candidates | Unknown |
| **Primary cause** | No table headers; text proximity too narrow | Slide layout differences |
| **Changes needed** | Wider proximity, sentence-aware binding | Layout-aware binding |

**Finding:** Value binding is the primary recall bottleneck for transcripts. The stage is designed for two binding strategies:

1. **Table binding** (primary for SEC filings): Uses `header_path`/`stub_path` to structurally link values to metrics. Unavailable for transcripts.
2. **Text proximity binding** (secondary): Searches for numeric values within `N` characters of the keyword match. Works but is limited.

**Root causes of failures:**
- **Large segments:** A single speaker turn becomes one `<p>` element. The CFO's 5,000-word remarks are a single segment, so proximity windows are too narrow to catch all metrics
- **Separated keyword and value:** "Our ARR grew to $900 million" works, but "We're very pleased with the ARR performance. It reached $900 million this quarter" fails because the value is in a different sentence from the keyword
- **Approximate values:** "about $20 million", "roughly 120%" — the "about"/"roughly" prefix may interfere with number parsing

**Recommendations:**
1. Split large `<p>` segments into sentence-level segments for transcripts (in converter or ingestion)
2. Widen proximity window from current value to 2-3x for text source types
3. Add sentence-boundary-aware binding (bind value to keyword if in same or adjacent sentence)

### Stage 7.5: False Positive Filter — OVER-FILTERING

| Dimension | Transcripts | Presentations (estimated) |
|-----------|-------------|---------------------------|
| **Status** | **Too aggressive** | Likely similar |
| **Filter rate** | 0-50% of bound values | Unknown |
| **Changes needed** | Transcript-specific rules | May need adjustments |

**Finding:** The FP filter is tuned for SEC filing contexts where financial statement line items frequently match customer metric patterns. In transcripts, the same patterns incorrectly filter legitimate conversational mentions.

**Specific over-filtering patterns:**
- Revenue/financial term adjacency rules fire on CEO remarks that discuss both financial and customer metrics in the same paragraph
- Employee count exclusions are too broad ("`75,000 employees`" near "`paid customers`" in same segment)
- The `DOLLAR_ONLY_METRICS` check may reject percentage values that appear near dollar values in conversational text

**Recommendation:** Add a `source_document_type` signal to the FP filter. When processing transcripts, relax segment-level co-occurrence rules and rely more on sentence-level context.

### Stage 8: Period Inference — SIGNIFICANT GAP

| Dimension | Transcripts | Presentations (estimated) |
|-----------|-------------|---------------------------|
| **Status** | **Mostly fails** | **Unknown** |
| **Success rate** | 0-62% per file | Unknown |
| **Primary cause** | No table headers; text patterns insufficient | Slide titles as headers? |
| **Changes needed** | Transcript-specific patterns + call-date fallback | Slide-title parsing |

**Finding:** Period inference is the second-biggest gap. The stage has three strategies:

1. **Table header_path** (confidence 0.9): Unavailable — no tables
2. **Text context** (confidence 0.5-0.7): Partially works
3. **Filing fiscal period fallback** (confidence 0.3): Requires `fiscal_year`/`fiscal_period` on Document, which isn't populated for non-SEC documents

**Text pattern gaps:**
- `"fiscal year '25"` / `"FY'25"` — apostrophe + 2-digit year not matched by FISCAL_YEAR_PATTERN (pattern requires `\s` or `'` but the combo doesn't match the actual format)
- `"Q4"` without year — QUARTER_PATTERN requires a year component
- `"this quarter"` / `"last quarter"` — relative references need document date context
- `"year-over-year"` — growth context, not period. But adjacent periods could be inferred

**Recommendations:**
1. Add a `document_date` parameter to PipelineContext (the call date)
2. Add fallback: when no period found but `document_date` is set, infer "current quarter" from the date
3. Fix FISCAL_YEAR_PATTERN to match `"FY'25"` format
4. Add `"Q4"` without year pattern that uses document_date year

### Stages 9-11: Fact Construction, Dedup, Validation — WORK

| Dimension | Transcripts | Presentations (estimated) |
|-----------|-------------|---------------------------|
| **Status** | **Work as expected** | **Work as expected** |
| **Changes needed** | None | None |

**Finding:** These stages are format-agnostic and work correctly on transcript-derived facts. Deduplication is particularly valuable for transcripts where executives frequently repeat the same metric.

## Summary: What Works vs What Needs Change

### Works Out of Box (no changes)
- Ingestion (HTML parsing)
- Table reconstruction (graceful no-op)
- Candidate generation (keyword matching)
- Fact construction
- Deduplication
- Validation & review routing

### Needs Configuration Changes (no code)
- Section classification (add transcript patterns to enum/config)
- Period inference (add text patterns for conversational temporal language)
- Metric keywords (add industry-specific patterns to YAML)

### Needs Code Changes
- **Value binding:** Wider proximity + sentence-level awareness for text sources
- **False positive filter:** Document-type-aware rule relaxation
- **Pipeline context:** Add `document_type` and `document_date` fields
- **Period inference:** Add document-date fallback strategy

### Needs New Code (upstream)
- **Transcript-to-HTML converter** (spike version exists, needs hardening)
- **PDF-to-HTML converter** (for presentations — new development)
- **Document fetcher abstraction** (protocol for fetching from different sources)

## Effort Estimates

| Change Category | Effort | Impact on Recall |
|-----------------|--------|-----------------|
| Keyword pattern additions | 1-2 hours | +5-10% |
| Value binding proximity tuning | 2-4 hours | +10-15% |
| Period inference pattern fixes | 2-4 hours | +5-10% |
| FP filter transcript rules | 2-4 hours | +5% |
| Pipeline context additions | 1-2 hours | Enabling |
| Section classification patterns | 2-4 hours | +3% (confidence) |
| Transcript converter hardening | 4-8 hours | Enabling |
| PDF converter (presentations) | 8-16 hours | Enabling |
| **Total** | **~22-44 hours** | **~30-40% recall gain** |
