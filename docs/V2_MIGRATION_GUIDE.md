# V2 Extraction Pipeline — Migration Record

This document records the completed migration from the V1 extraction pipeline to V2. V1 has been removed; V2 is the sole active pipeline.

## Overview

The V2 pipeline is a ground-up redesign that improves on V1 in several key areas:

| Aspect | V1 (retired) | V2 (current) |
|--------|----|----|
| **HTML Parsing** | BeautifulSoup (slower) | lxml (10x faster) |
| **Source Locators** | CSS selectors | Stable XPath locators |
| **Table Structure** | Flat text extraction | Full rowspan/colspan with header_path/stub_path |
| **Image Handling** | Basic detection | OCR + Vision integration with chart extraction |
| **Evidence** | Raw text snippets | EvidencePack with highlighted HTML, context |
| **Deduplication** | Per-metric | Identity tuple with alternate_evidence links |
| **False Positive Filter** | V1 FP filter (shared) | V2-native FP filter stage with unit compatibility |
| **Database Schema** | Legacy tables | Normalized v2_* tables with JSONB |

**Migration status (as of 2026-03-11):** Complete. V1 code (`src/extraction/`) has been deleted. All extraction now runs through V2. Current validated scores: Text-only P=95.0%, R=83.5%, F1=88.9%; Image-enabled P=92.3%, R=83.5%, F1=87.7%.

## API

### V2 Pipeline

```python
from src.extraction_v2.pipeline import V2Pipeline, PipelineConfig
from pathlib import Path

# Optional: Configure behavior
config = PipelineConfig(
    enable_section_classification=True,
    enable_image_extraction=True,
    enable_chart_extraction=True,
    min_confidence_auto_accept=0.90,
    value_tolerance=0.02,
)

# Create pipeline
pipeline = V2Pipeline(config=config)

# Process filing (takes HTML path directly)
result = pipeline.process(
    html_path=Path("/path/to/filing.html"),
    filing_id=123,
)

# Result structure
print(result.success)               # bool
print(result.fact_count)            # int
print(result.pending_review_count)  # int
print(result.auto_accepted_count)   # int
print(result.total_duration_ms)     # int

# Access extracted data
for fact in result.facts:
    print(f"{fact.canonical_metric_id}: {fact.value} ({fact.confidence:.1%})")
    print(f"  Source: {fact.source_type.value}")
    print(f"  XPath: {fact.source_locator.dom_locator}")
```

### Persistence

V2 separates extraction from persistence:

```python
from src.extraction_v2.persistence import V2PersistenceAdapter
from src.infra.db import DatabaseAdapter

# After extraction
db = DatabaseAdapter(database_url)
adapter = V2PersistenceAdapter(db)

# Persist all results atomically
persist_result = adapter.persist_pipeline_result(
    result=extraction_result,
    filing_id=123,
)

if persist_result.success:
    print(f"Persisted {persist_result.facts_upserted} facts")
else:
    print(f"Errors: {persist_result.errors}")
```

## Database Schema

All V2 tables use `v2_` prefix:

- `v2_documents` - Filing container with parse metadata
- `v2_segments` - DOM-native segments with XPath locators
- `v2_tables` - Reconstructed tables with span resolution
- `v2_table_cells` - Individual cells with header_path/stub_path
- `v2_image_assets` - Image metadata, OCR results, chart data
- `v2_metric_facts` - Primary output with evidence_pack JSONB

Key schema improvements over V1 (retired):

| Field | V1 (retired) | V2 (current) |
|-------|----|----|
| Source location | `source_segment_id` FK | `source_locator` JSONB with XPath |
| Table context | N/A | `header_path[]`, `stub_path[]` arrays |
| Evidence | `raw_text` | `evidence_pack` JSONB with snippet_html, context |
| Review status | Binary flag | Enum: auto_accepted, pending_review, accepted, rejected |
| Confidence | N/A | Float 0.0-1.0 with scoring formula |

## Data Model Mapping

### V1 MetricValue → V2 MetricFact

```python
# V1 MetricValue fields
metric_value = {
    "filing_id": 123,
    "company_id": 456,
    "metric_id": "cm_net_revenue_retention",
    "source_segment_id": 789,
    "value_numeric": Decimal("115.0"),
    "value_text": "115%",
    "unit": "%",
    "period_start": date(2024, 1, 1),
    "period_end": date(2024, 12, 31),
}

# V2 MetricFact equivalent
metric_fact = MetricFact(
    fact_id="uuid-here",
    doc_id="doc-uuid",
    canonical_metric_id="cm_net_revenue_retention",
    value=115.0,
    value_raw="115%",
    unit=Unit.PERCENT,
    period_type=PeriodType.ANNUAL,
    period_start=date(2024, 1, 1),
    period_end=date(2024, 12, 31),
    source_type=SourceType.HTML_TABLE,
    source_locator=SourceLocator(
        segment_id="seg-uuid",
        table_id="table-uuid",
        cell_row=5,
        cell_col=3,
        dom_locator="/html/body/table[1]/tr[5]/td[3]",
    ),
    evidence_pack=EvidencePack(
        snippet_html="<td>115%</td>",
        header_path=["NRR", "FY2024"],
        stub_path=["Total"],
        context_before="Net revenue retention was...",
        context_after="...compared to 110% in the prior year.",
    ),
    confidence=0.92,
    extraction_method=ExtractionMethod.EXACT_MATCH,
    review_status=ReviewStatus.AUTO_ACCEPTED,
)
```

## Migration Record (Completed 2026-03-02)

The steps below document how the migration was performed. They are preserved for reference; the migration is complete and V1 has been deleted.

### Step 1 (completed): Validate V2 Output

Gold standard validation confirmed V2 was ready:

```bash
# Run gold standard validation
pytest -m gold_standard --gold-standard-mode=fresh -v

# Current scores (as of 2026-03-11):
# Text-only: P=95.0%, R=83.5%, F1=88.9%
# Image-enabled: P=92.3%, R=83.5%, F1=87.7%
```

### Step 2 (completed): Update Downstream Consumers

Update code that reads extraction results:

```python
# Before (V1)
values = db.query("""
    SELECT * FROM metric_values WHERE filing_id = %s
""", (filing_id,))

# After (V2)
facts = db.query("""
    SELECT fact_id, canonical_metric_id, value, unit,
           source_locator, evidence_pack, confidence
    FROM v2_metric_facts WHERE doc_id = %s
""", (filing_id,))

for fact in facts:
    # JSONB fields are auto-parsed
    source = fact["source_locator"]
    evidence = fact["evidence_pack"]
    print(f"XPath: {source['dom_locator']}")
    print(f"Headers: {evidence['header_path']}")
```

### Step 4 (completed): Update Review UI

The V2 review UI is complete and at full feature parity (WP-21, 2026-02-28). The following are already implemented:

- `evidence_pack.snippet_html` displayed with highlighting
- `header_path` / `stub_path` breadcrumb navigation
- Confidence scores with color-coded badges
- All review statuses (`auto_accepted`, `pending_review`, `accepted`, `rejected`, `corrected`)

Access via `http://localhost:5000/v2/review/filings`. See `docs/V2_HUMAN_REVIEW_GUIDE.md` for full UI documentation.

### Step 5 (completed): Cutover

Migration is complete:

1. V2 pipeline is now the sole extraction pipeline
2. V1 code (`src/extraction/`) has been deleted
3. Scheduled jobs run V2 scripts (`run_v2_extraction.py`, `batch_v2_extraction.py`)
4. Gold standard validation continues as ongoing regression guard

## Performance Considerations

### V2 Advantages

- lxml parsing is ~10x faster than BeautifulSoup
- XPath generation is computed once during parsing
- Table reconstruction handles complex tables correctly
- Deduplication reduces downstream processing

### V2 Overhead

- Image triage/OCR adds time if enabled
- More data stored per fact (evidence_pack)
- JSONB serialization has minor overhead

### Recommended Settings

For bulk processing:
```python
config = PipelineConfig(
    enable_image_extraction=False,  # Skip OCR
    enable_chart_extraction=False,
    max_llm_calls_per_document=0,   # Rule-based only
)
```

For full extraction:
```python
config = PipelineConfig(
    enable_image_extraction=True,
    enable_chart_extraction=True,
    max_images_per_document=20,     # Limit OCR calls
)
```

## Phase B Features (2026-02-24)

Three features added after the original 13-stage pipeline was completed.

### Stage 9.5 — Definition Extraction

`src/extraction_v2/stages/definition_extraction.py` runs between MetricFact Construction (Stage 9) and Deduplication (Stage 10). It scans segments within a ±5 sequence window of each metric candidate for DEFINITION and METHODOLOGY content, normalizes the text, and assesses CMASB canonical alignment (`aligned`, `partial`, `not_aligned`, or `unknown`). Results are available via `PipelineResult.definitions`.

**Migration requirement:** Apply SQL migration 11 before using this feature:

```bash
python3 scripts/apply_migrations.py  # applies sql/11_v2_definitions.sql
```

This creates the `v2_metric_definitions` table (UUID primary key, unique constraint on `doc_id + canonical_metric_id`).

### Quality Scoring Adapter

`src/extraction_v2/quality_scoring.py` provides a `V2QualityScorer` class that ports all five V1 quality rubrics (overall, definition, methodology, completeness, comparability) to V2 facts. Scores are written to V1's existing `filing_metric_incidence` table, so downstream analytics queries continue to work without modification.

Quality scoring runs automatically when you use `scripts/run_v2_extraction.py`. To disable:

```bash
python3 scripts/run_v2_extraction.py --filing-id 123 --skip-quality
```

### Batch Extraction Script

`scripts/batch_v2_extraction.py` is the recommended way to process large numbers of filings. It uses `ProcessPoolExecutor` for parallel execution.

```bash
# Basic usage: 4 workers, all pending filings
python3 scripts/batch_v2_extraction.py

# Common options
python3 scripts/batch_v2_extraction.py \
    --workers 8 \
    --batch-size 50 \
    --limit 500 \
    --skip-quality \
    --no-images

# Resume an interrupted run
python3 scripts/batch_v2_extraction.py --resume-from 4521

# Single filing (useful for debugging)
python3 scripts/batch_v2_extraction.py --filing-id 123

# Plan without writing
python3 scripts/batch_v2_extraction.py --dry-run --limit 100
```

Progress is checkpointed to `logs/batch_v2_progress.json` after every `--batch-size` filings. SIGINT (Ctrl-C) triggers graceful shutdown, completing the current batch before exiting.

---

## Troubleshooting

### V2 extracts fewer facts than V1

- V2 has stricter provenance requirements
- Check if V1 had false positives (V2 may correctly reject)
- Review `v1_only` matches in comparison output

### Facts missing evidence_pack

- Ensure `EvidencePack` is populated in Stage 9
- Check for exceptions in fact construction stage

### Confidence scores too low

- Review scoring formula in `FactConstructionStage`
- Check source_type penalties (OCR/CHART have penalties)
- Verify period inference is working

### Database constraint violations

- Ensure `canonical_metric_id` matches `metric_definitions.metric_id`
- Check JSONB structure matches expected schema

## Support

- Review pipeline logs for per-stage errors
- Check `stage_results` in `PipelineResult` for warnings
- File issues with examples and filing paths
