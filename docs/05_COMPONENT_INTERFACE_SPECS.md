

# 05_COMPONENT_INTERFACE_SPECS

Version: 0.1  
Date: 2025-11-15  
Owner: Rob Markey  

## 1. Purpose

This document defines the **component-level interfaces** for the Customer Metrics Filings Analysis system.

It translates the architecture in `04_SYSTEM_ARCHITECTURE.md` and the schema in `03_DATA_MODEL_SPEC.md` into:

- Clear responsibilities and boundaries per component
- Expected inputs and outputs (including DB tables and in-memory objects)
- Function-level interfaces (Python-oriented) for implementation
- Error handling and logging requirements

The goal is to allow different team members to implement components independently while preserving consistency.

---

## 2. Conventions

### 2.1 Language and runtime

- Implementation language: **Python 3.11+** (assumed)
- Database: **Postgres** (via `psycopg` or SQLAlchemy; exact choice to be decided later)
- All component APIs are described as **Python callables** or classes.

### 2.2 General patterns

- Components should be **pure functions or thin classes** where possible:
  - Input: IDs or data objects
  - Output: data objects or DB writes
- Idempotency:
  - Each component must be safe to re-run for a given `filing_id` without creating duplicates or inconsistent state.
- Logging:
  - Use a shared logger (`logging` module) with component-specific child loggers.

### 2.3 Common types (logical)

To keep specs concise, we refer to some shared logical types:

- `FilingRef`:
  - `{ filing_id: int, cik: str, accession_number: str, form_type: str }`
- `SegmentRecord`:
  - A dict-like object representing a row to insert into `source_segments`.
- `MetricValueRecord`:
  - A dict-like object representing a row to insert into `metric_values`.
- `MetricDefinitionRecord`:
  - A dict-like object representing a row to insert into `metric_definitions`.
- `FilingMetricIncidenceRecord`:
  - A dict-like object representing a row to insert into `filing_metric_incidence`.

Implementations can map these to dataclasses, Pydantic models, or plain dicts.

---

## 3. Universe Builder

### 3.1 Responsibility

Build and maintain the universe of in-scope filings (Phase 1: S-1 for first-time issuers).

### 3.2 Interface

```python
class UniverseBuilder:
    def __init__(self, sec_client, db):
        """sec_client: EDGAR API wrapper; db: DB connection/adapter."""

    def build_universe(self, start_date: str, end_date: str) -> int:
        """Discover and upsert companies and filings for the given date range.

        Args:
            start_date: ISO date string, inclusive (e.g., "2015-01-01").
            end_date: ISO date string, inclusive (e.g., "2025-12-31").

        Returns:
            Number of filings marked as in-scope for Phase 1.
        """
```

### 3.3 Inputs

- `start_date`, `end_date`
- EDGAR search/index data (via `sec_client`)

### 3.4 Outputs

- Upserts into `companies` and `filings` tables:
  - Sets `is_in_scope_phase1`, `is_first_time_issuer`, `is_spac`, `offering_type`, `classification_method`.

### 3.5 Error handling & logging

- On network errors: retry with backoff; log with `level=WARNING` and error details.
- On ambiguous classifications: set `classification_method='uncertain'` and log for manual review.

---

## 4. Filing Fetcher

### 4.1 Responsibility

Fetch and cache raw filings from EDGAR for each in-scope `filing_id`.

### 4.2 Interface

```python
class FilingFetcher:
    def __init__(self, sec_client, storage_root: str, db):
        """storage_root: base path or bucket prefix for raw filings."""

    def fetch_filing(self, filing_id: int) -> str:
        """Fetch and cache the raw HTML for a single filing.

        Args:
            filing_id: Internal filing ID.

        Returns:
            Local path (or URI) to the cached HTML file.
        """

    def fetch_all_in_scope(self, max_workers: int = 4) -> None:
        """Fetch all filings where is_in_scope_phase1 = true and processing_status is pending.
        """
```

### 4.3 Inputs

- `filings` rows (`is_in_scope_phase1 = true`)

### 4.4 Outputs

- Raw HTML files in storage
- `filings.processing_status` updated to `fetched` or `fetch_failed`

### 4.5 Error handling & logging

- On HTTP 4xx/5xx: limited retries; mark `fetch_failed` on persistent failure.
- Log each fetch attempt with status and timing.

---

## 5. Filing Normalizer

### 5.1 Responsibility

Normalize raw HTML into clean text and structures ready for segmentation.

### 5.2 Interface

```python
class FilingNormalizer:
    def __init__(self, db):
        pass

    def normalize(self, filing_id: int, html_path: str) -> dict:
        """Normalize the filing HTML.

        Args:
            filing_id: Internal filing ID.
            html_path: Path/URI to the raw HTML file.

        Returns:
            A dict containing normalized representations, e.g.:
            {
                "normalized_text": str,
                "sections": List[dict],  # optional pre-segmentation
                "metadata": dict,
            }
        """
```

### 5.3 Inputs

- `filing_id`
- Path to raw HTML

### 5.4 Outputs

- In-memory normalized representation passed to `Segmenter`
- Optional: cached normalized content on disk

### 5.5 Error handling & logging

- On parsing error: raise a custom `NormalizationError`; caller sets `processing_status='normalize_failed'`.

---

## 6. Segmenter

### 6.1 Responsibility

Split normalized filings into sections and segments, populate `source_segments`.

### 6.2 Interface

```python
class Segmenter:
    def __init__(self, db):
        pass

    def segment(self, filing_id: int, normalized_doc: dict) -> list[SegmentRecord]:
        """Create segments for a filing.

        Args:
            filing_id: Internal filing ID.
            normalized_doc: Output from FilingNormalizer.

        Returns:
            List of SegmentRecord objects (to be inserted into source_segments).
        """
```

### 6.3 Inputs

- `filing_id`
- `normalized_doc` from Filing Normalizer

### 6.4 Outputs

- A list of `SegmentRecord` objects. Each contains:
  - `filing_id`
  - `segment_type`
  - `section_path`, `section_heading`
  - `sequence_index`
  - `char_start_offset`, `char_end_offset`
  - `raw_text`, `raw_html`

### 6.5 Error handling & logging

- If segmentation fails entirely: raise `SegmentationError`.
- Partial segmentation is allowed; log warnings and still return segments.

---

## 7. Candidate Segment Classifier

### 7.1 Responsibility

Tag segments that likely contain metrics, definitions, or methodologies.

### 7.2 Interface

```python
class CandidateSegmentClassifier:
    def __init__(self, llm_client, metric_taxonomy: dict, db):
        """metric_taxonomy: mapping from metric_id to synonyms and patterns."""

    def classify_segments(self, filing_id: int) -> None:
        """Classify all segments for a filing.

        Side effects:
            Updates source_segments rows with:
            - candidate_metric_ids
            - contains_definition_flag
            - contains_methodology_flag
            - contains_numeric_disclosure_flag
        """
```

### 7.3 Inputs

- `source_segments` rows for `filing_id`
- Metric taxonomy (from `02_METRIC_TAXONOMY_AND_DEFINITIONS.md`)

### 7.4 Outputs

- Updated `source_segments` records (in DB)

### 7.5 Error handling & logging

- On LLM errors: fall back to rule-only classification; log downgraded mode.

---

## 8. Table Extractor

### 8.1 Responsibility

Parse table segments and extract structured metric values.

### 8.2 Interface

```python
class TableExtractor:
    def __init__(self, llm_client, db):
        pass

    def extract_from_filing(self, filing_id: int) -> list[MetricValueRecord]:
        """Extract metric values from table segments for a filing.

        Returns:
            List of MetricValueRecord objects (to insert into metric_values).
        """
```

### 8.3 Inputs

- `source_segments` where `segment_type='table'` and `contains_numeric_disclosure_flag=true`

### 8.4 Outputs

- `MetricValueRecord` instances containing:
  - `filing_id`, `metric_id`
  - `source_segment_id`
  - `value_numeric`, `unit`, `currency`
  - `period_*`, `cohort_*`, `segment_*`
  - `source_type='table'`, `extraction_method`

### 8.5 Error handling & logging

- On table parse error: log with table index and segment ID; optionally create QA warning.

---

## 9. Text Metric Extractor

### 9.1 Responsibility

Extract numeric metric values from narrative segments using LLMs.

### 9.2 Interface

```python
class TextMetricExtractor:
    def __init__(self, llm_client, metric_taxonomy: dict, db):
        pass

    def extract_from_filing(self, filing_id: int) -> list[MetricValueRecord]:
        """Extract metric values from narrative segments for a filing.

        Returns:
            List of MetricValueRecord objects.
        """
```

### 9.3 Inputs

- `source_segments` where `segment_type in ('paragraph', 'footnote', 'other')` and `contains_numeric_disclosure_flag = true`
- Metric taxonomy

### 9.4 Outputs

- `MetricValueRecord` instances with:
  - `source_type='text'`, `extraction_method='llm_text'`

### 9.5 Error handling & logging

- On invalid JSON from LLM: retry once; if still invalid, log and skip those segments with `qa_status='fail'` in a later QA step.

---

## 10. Definition / Methodology Extractor

### 10.1 Responsibility

Extract and normalize metric definitions and calculation methodologies.

### 10.2 Interface

```python
class DefinitionExtractor:
    def __init__(self, llm_client, metric_taxonomy: dict, db):
        pass

    def extract_from_filing(self, filing_id: int) -> list[MetricDefinitionRecord]:
        """Extract metric definitions/methodologies for a filing.

        Returns:
            List of MetricDefinitionRecord objects.
        """
```

### 10.3 Inputs

- `source_segments` where `contains_definition_flag = true` or `contains_methodology_flag = true`
- Metric taxonomy

### 10.4 Outputs

- `MetricDefinitionRecord` instances with:
  - `definition_segment_id`, `methodology_segment_id`
  - Normalized and raw definition/methodology text
  - Preliminary `alignment_flag` if available

### 10.5 Error handling & logging

- On LLM failures: log; create records with `alignment_flag='unknown'` where appropriate.

---

## 11. QA Engine

### 11.1 Responsibility

Evaluate and score the quality of metric disclosures and values.

### 11.2 Interface

```python
class QAEngine:
    def __init__(self, llm_client, db):
        pass

    def run_for_filing(self, filing_id: int) -> list[FilingMetricIncidenceRecord]:
        """Compute QA statuses and incidence for all metrics in a filing.

        Returns:
            List of FilingMetricIncidenceRecord objects to upsert.
        """
```

### 11.3 Inputs

- `metric_values` for `filing_id`
- `metric_definitions` for `filing_id`
- `source_segments` as needed for context

### 11.4 Outputs

- `filing_metric_incidence` rows:
  - Incidence flags
  - Counts of segments
  - Quality scores
  - Notes and flags
- Updated QA fields on `metric_values` and `metric_definitions`

### 11.5 Error handling & logging

- On LLM scoring failure: log; fall back to rule-only quality assessment where possible.

---

## 12. Loader

### 12.1 Responsibility

Persist component outputs into the database with referential integrity and idempotency.

### 12.2 Interface

```python
class Loader:
    def __init__(self, db):
        pass

    def upsert_source_segments(self, segments: list[SegmentRecord]) -> None:
        """Insert or update source_segments for a filing."""

    def insert_metric_values(self, values: list[MetricValueRecord]) -> None:
        """Insert metric_values records; handle deduplication/idempotency per filing."""

    def upsert_metric_definitions(self, defs: list[MetricDefinitionRecord]) -> None:
        """Upsert metric_definitions records."""

    def upsert_filing_metric_incidence(self, incidences: list[FilingMetricIncidenceRecord]) -> None:
        """Upsert filing_metric_incidence records."""
```

### 12.3 Inputs

- Lists of records from Segmenter, Table/Text Extractors, Definition Extractor, QA Engine

### 12.4 Outputs

- Persisted DB rows

### 12.5 Error handling & logging

- Use transactions per filing or per batch; rollback on failure.
- On constraint violation: log details (filing, metric, segment) and raise a domain-specific exception for the Orchestrator.

---

## 13. Orchestrator

### 13.1 Responsibility

Coordinate the full pipeline across many filings.

### 13.2 Interface

```python
class Orchestrator:
    def __init__(
        self,
        db,
        filing_fetcher: FilingFetcher,
        normalizer: FilingNormalizer,
        segmenter: Segmenter,
        classifier: CandidateSegmentClassifier,
        table_extractor: TableExtractor,
        text_extractor: TextMetricExtractor,
        definition_extractor: DefinitionExtractor,
        qa_engine: QAEngine,
        loader: Loader,
        telemetry
    ):
        pass

    def process_filing(self, filing_id: int) -> None:
        """Run the full pipeline for a single filing.

        Should:
            - Update filings.processing_status appropriately
            - Log all major steps and errors
        """

    def process_all_in_scope(self, max_workers: int = 4) -> None:
        """Run the pipeline over all in-scope filings with optional parallelism."""
```

### 13.3 Inputs

- `filings` rows (scope defined by `is_in_scope_phase1` and `processing_status`)

### 13.4 Outputs

- Updated DB tables and statuses
- Logs and telemetry events

### 13.5 Error handling & logging

- Catch component-specific exceptions, mark filings as `failed` when necessary, and continue with others.
- Emit structured logs per filing with timings and error summaries.

---

## 14. Telemetry & Cost Tracker

### 14.1 Responsibility

Collect and expose run-level and component-level metrics, including LLM usage and costs.

### 14.2 Interface

```python
class Telemetry:
    def __init__(self, db=None):
        pass

    def record_llm_call(self, filing_id: int, component: str, tokens_in: int, tokens_out: int, model: str) -> None:
        """Record LLM usage for cost tracking."""

    def record_stage_time(self, filing_id: int, component: str, elapsed_seconds: float) -> None:
        """Record per-component timing."""

    def summarize_run(self) -> dict:
        """Return a summary of key metrics for the last run."""
```

### 14.3 Inputs

- Events from Orchestrator and LLM wrappers

### 14.4 Outputs

- Optional: `run_metrics` table
- In-memory or file-based reports

### 14.5 Error handling & logging

- Telemetry failures must never stop the main pipeline; log and continue.

---

## 15. Testing guidelines per component

For each component, implement:

- **Unit tests**
  - Verify correct behavior on normal inputs
  - Verify error conditions raise the expected exceptions
- **Integration tests**
  - For Universe Builder: end-to-end test with a small EDGAR sample
  - For Segmenter: verify segmentation on a few real S-1 HTML files
  - For Extractors: validate against a labeled gold standard for a handful of filings
- **Idempotency tests**
  - Running the same component twice for a filing should not create duplicate rows or inconsistent states

More detailed test cases will be defined in `07_TEST_STRATEGY_AND_FIX_PROCESS.md`.
