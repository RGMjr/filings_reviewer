# Data Model Specification

**Version:** 3.0
**Last Updated:** 2026-04-18
**Status:** Production Schema (V2)

---

## Overview

This document defines the live PostgreSQL schema for the CMASB filings review system as of 2026-04-18, following the V1→V2 cutover (migrations `26_drop_filing_metric_incidence.sql`, `27_drop_v1_metric_tables.sql`, `30_drop_v1_image_review.sql`).

V2 tables (`v2_*`) are the authoritative extraction output for all document types: SEC filings, transcripts, and investor presentations. A small set of V1 tables remains live only to support the legacy review-candidate workflow; their retirement is tracked in `docs/architecture/v1-table-deprecation-plan.md`.

Table structures, keys, enums, and relationships below match the live DB. Where the current Python code or unapplied SQL disagrees with the DB, that drift is called out in [Known Discrepancies](#known-discrepancies).

---

## Design Principles

1. **Provenance-first.** Every `v2_metric_facts` row carries a `source_locator` JSONB pointing to an exact DOM location and an `evidence_pack` JSONB with a renderable snippet. No value without provenance.
2. **Idempotent writes.** The persistence layer upserts against a unique identity index on `v2_metric_facts`, so re-running extraction on the same filing produces stable row counts.
3. **Analysis-first grain.** Tables are keyed to the units of analysis: document, fact (doc × metric × period × scope × cohort × source_type), table × cell, image asset, segment.
4. **Canonical taxonomy.** All facts reference `metrics.metric_id`; issuer-specific definitions live in `v2_metric_definitions` per (doc, metric).
5. **Extensible.** Check-constraint enums on `form_type`, `section_type`, `segment_type`, etc. absorb new document types (SEC 8-K, earnings calls, investor presentations) without table changes.
6. **PostgreSQL-oriented.** Types align to Postgres (`text`, `numeric`, `timestamptz`, `jsonb`, `uuid`, `text[]`).

---

## Entity Map

Tables are grouped into three tiers.

### Shared core

| Table | Purpose |
|-------|---------|
| `companies` | Issuer-level metadata, keyed by CIK |
| `filings` | One row per ingested document (SEC filing, transcript, or investor presentation) |
| `metrics` | Canonical metric taxonomy (`cm_*`) |
| `business_classifications` | Boolean flags per company for pipeline targeting |

### V2 extraction (primary)

| Table | Purpose |
|-------|---------|
| `v2_documents` | Filing-level V2 processing state and transcript/presentation metadata |
| `v2_segments` | DOM-native content blocks with hierarchical `section_path` |
| `v2_tables`, `v2_table_cells` | Reconstructed tables with resolved spans and `header_path`/`stub_path` arrays |
| `v2_image_assets` | Extracted images with classification, OCR/chart results, and review status |
| `v2_metric_facts` | Primary extraction output — every extracted metric with provenance and review status |
| `v2_metric_definitions` | Issuer-specific definition and methodology text, one per (doc, metric) |
| `v2_review_decisions` | Human review decisions on V2 facts (accept/reject/correct) |
| `v2_image_review_decisions` | Human review decisions on V2 images |

### V1 residual (retirement tracked in `v1-table-deprecation-plan.md`)

| Table | Status |
|-------|--------|
| `source_segments` | Live — still consumed by `src/gold_standard/fresh_extractor.py` and V1 candidate-gen |
| `review_candidates` | Live — V1 review workflow; HIGH-difficulty retirement |
| `review_decisions` | Live — one-to-one with `review_candidates` |
| `suppressed_candidates` | Live — suppression logging for V1 candidate-gen |
| `learned_patterns` | Live — candidate-tuning telemetry |

### Relationships (cheat sheet)

- `companies` 1–N `filings`
- `filings` 1–1 `v2_documents` (via `v2_documents.filing_id`, `UNIQUE`)
- `filings` 1–N `v2_metric_facts`, `v2_segments`, `v2_tables`, `v2_image_assets`
- `v2_metric_facts` 1–1 `v2_review_decisions` (via `v2_review_decisions.fact_id`, `UNIQUE`)
- `v2_image_assets` 1–1 `v2_image_review_decisions` (via `UNIQUE img_id`)
- `v2_segments` 0–N `v2_metric_definitions` (definition/methodology segment FKs)
- `filings` 1–N `source_segments` (V1 residual)
- `filings` 1–N `review_candidates` 1–1 `review_decisions` (V1 residual)

**Naming gotcha:** the `doc_id` column on `v2_metric_facts`, `v2_segments`, `v2_tables`, and `v2_image_assets` is a `BIGINT` foreign key to `filings(filing_id)` — **not** to `v2_documents(doc_id)`. `v2_documents.doc_id` is a separate UUID primary key not referenced by any child table. `v2_metric_definitions.doc_id` is `INTEGER` and FKs to `v2_documents(filing_id)` via the `UNIQUE (filing_id)` constraint.

---

## Table Specifications

### Shared core

#### `companies`

**Grain:** One row per issuer.

```sql
CREATE TABLE companies (
    company_id                     BIGSERIAL PRIMARY KEY,
    cik                            TEXT NOT NULL UNIQUE,
    company_name                   TEXT NOT NULL,
    ticker                         TEXT,
    country_of_domicile            TEXT,
    industry_code                  TEXT,
    industry_classification_source TEXT,
    created_at                     TIMESTAMPTZ DEFAULT now(),
    updated_at                     TIMESTAMPTZ DEFAULT now()
);
-- idx_companies_cik, idx_companies_ticker (partial WHERE ticker IS NOT NULL),
-- idx_companies_ticker_unique (UNIQUE, partial WHERE ticker IS NOT NULL)
```

`ticker` is globally unique when set; the partial unique index enforces this.

---

#### `filings`

**Grain:** One row per ingested document. A single company may have many filings. Scope extends beyond SEC S-1/F-1: transcripts and investor presentations are also stored here with `document_type` disambiguating.

```sql
CREATE TABLE filings (
    filing_id              BIGSERIAL PRIMARY KEY,
    company_id             BIGINT NOT NULL REFERENCES companies(company_id),
    cik                    TEXT,
    accession_number       TEXT,
    form_type              TEXT NOT NULL,
    filing_date            DATE NOT NULL,
    period_end_date        DATE,

    -- Source artifacts
    sec_html_url           TEXT,
    sec_txt_url            TEXT,
    html_storage_path      TEXT,
    txt_storage_path       TEXT,
    html_content           TEXT,
    html_fetched_at        TIMESTAMPTZ,
    html_fetch_error       TEXT,

    -- Universe / scope flags (Phase 1)
    is_in_scope_phase1     BOOLEAN NOT NULL DEFAULT FALSE,
    is_first_time_issuer   BOOLEAN,
    is_spac                BOOLEAN,
    is_post_combination    BOOLEAN NOT NULL DEFAULT FALSE,
    is_investment_vehicle  BOOLEAN NOT NULL DEFAULT FALSE,
    is_resource_extraction BOOLEAN NOT NULL DEFAULT FALSE,
    offering_type          TEXT,
    classification_method  TEXT,

    -- Pipeline status
    processing_status      TEXT NOT NULL DEFAULT 'pending',
    processing_notes       TEXT,

    -- Transcript / presentation (non-SEC documents)
    document_type          TEXT NOT NULL DEFAULT 'sec_filing',
    ticker                 TEXT,
    document_date          DATE,
    transcript_source      TEXT,

    created_at             TIMESTAMPTZ DEFAULT now(),
    updated_at             TIMESTAMPTZ DEFAULT now(),

    CONSTRAINT unique_company_accession UNIQUE (company_id, accession_number)
);
```

**`form_type` allowed values** (CHECK `check_form_type`):
`S-1`, `S-1/A`, `F-1`, `F-1/A`, `10-K`, `10-K/A`, `8-K`, `earnings_call`, `investor_presentation`.

**`classification_method` allowed values:** `heuristic`, `manual_review`, `uncertain` (or NULL).

**`offering_type` allowed values:** `primary`, `secondary`, `mixed` (or NULL).

**Key indexes:** `filing_id` PK, `accession_number`, `cik`, `filing_date`, `form_type`, `document_type`, `ticker` (partial), plus several partial indexes gated on scope flags (`is_in_scope_phase1`, `is_spac`, `is_investment_vehicle`, `is_post_combination`, `is_resource_extraction`).

---

#### `metrics`

**Grain:** One row per canonical metric in the CMASB taxonomy.

```sql
CREATE TABLE metrics (
    metric_id       TEXT PRIMARY KEY,
    display_name    TEXT NOT NULL,
    metric_class    TEXT NOT NULL,
    description     TEXT,
    primary_concept TEXT,
    status          TEXT NOT NULL DEFAULT 'active',
    version         INTEGER NOT NULL DEFAULT 1,
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now()
);
```

- `metric_class` ∈ `core`, `extended`, `future`
- `status` ∈ `active`, `deprecated`, `experimental`
- Canonical IDs use `cm_` prefix (e.g., `cm_net_revenue_retention`).

Authoritative metric list: `config/metric_keywords.yaml`. Tier assignments (Tier 1 / Tier 2) live in that file and in `src/gold_standard/v2_validator.py`.

---

#### `business_classifications`

**Grain:** One row per company, holding boolean industry flags used by pipeline targeting.

```sql
CREATE TABLE business_classifications (
    classification_id        SERIAL PRIMARY KEY,
    company_id               INTEGER,
    is_ecommerce_marketplace BOOLEAN DEFAULT FALSE,
    is_platform_network      BOOLEAN DEFAULT FALSE,
    is_healthcare_tech       BOOLEAN DEFAULT FALSE,
    is_media_subscription    BOOLEAN DEFAULT FALSE,
    is_fintech_crypto        BOOLEAN DEFAULT FALSE,
    is_saas_software         BOOLEAN DEFAULT FALSE,
    is_telecom               BOOLEAN DEFAULT FALSE,
    created_at               TIMESTAMPTZ DEFAULT now()
);
```

No FK is declared on `company_id`. Rows are maintained manually or by the universe-builder.

---

### V2 extraction

#### `v2_documents`

**Grain:** One row per filing. Enforced by `UNIQUE (filing_id)`.

```sql
CREATE TABLE v2_documents (
    doc_id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    filing_id            BIGINT NOT NULL UNIQUE,
    parse_version        TEXT NOT NULL DEFAULT '2.0.0',
    segment_count        INTEGER DEFAULT 0,
    table_count          INTEGER DEFAULT 0,
    image_count          INTEGER DEFAULT 0,
    fact_count           INTEGER DEFAULT 0,
    status               TEXT NOT NULL DEFAULT 'pending',
    error_message        TEXT,
    parse_started_at     TIMESTAMPTZ,
    parse_completed_at   TIMESTAMPTZ,
    extract_started_at   TIMESTAMPTZ,
    extract_completed_at TIMESTAMPTZ,

    -- Transcript / presentation metadata
    document_type        VARCHAR(50) NOT NULL DEFAULT 'sec_filing',
    ticker               VARCHAR(10),
    document_date        DATE,
    transcript_source    VARCHAR(200),

    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

`status` ∈ `pending`, `parsing`, `extracting`, `reviewing`, `complete`, `failed`.

`v2_metric_definitions.doc_id` FKs to `v2_documents(filing_id)` — not `doc_id`. All other child tables key on `filings(filing_id)` directly and do not join through `v2_documents`.

---

#### `v2_segments`

**Grain:** One row per DOM-native content block (paragraph, table container, image reference, etc.).

```sql
CREATE TABLE v2_segments (
    segment_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    doc_id          BIGINT NOT NULL,  -- = filings.filing_id
    segment_type    TEXT NOT NULL,
    segment_text    TEXT NOT NULL,
    dom_locator     TEXT NOT NULL,
    section_path    TEXT[],
    section_type    TEXT,
    sequence_idx    INTEGER NOT NULL,
    prev_segment_id UUID REFERENCES v2_segments(segment_id),
    next_segment_id UUID REFERENCES v2_segments(segment_id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

**`segment_type`** (CHECK): `heading`, `paragraph`, `table`, `image_ref`, `caption`, `list`, `footnote`, `definition`, `methodology`, `other`.

**`section_type`** (CHECK): `cover`, `risk_factors`, `mda`, `business`, `financials`, `notes`, `exhibits`, `signatures`, `other`, `unknown`, `prepared_remarks`, `qa`, `operator`, `disclaimer`, `presentation_slide`, `title_slide`, `key_metrics`, `financial_overview`, `guidance`, `appendix`. (Transcript and presentation values were added in migrations 13 and 14.)

Indexes: `doc_id`, `(doc_id, sequence_idx)`, `section_type`, `segment_type`.

---

#### `v2_tables` and `v2_table_cells`

**Grain:**
- `v2_tables`: one row per reconstructed logical table after span resolution.
- `v2_table_cells`: one row per `(table, row, col)` after span expansion. `UNIQUE (table_id, row_idx, col_idx)` guarantees a fully populated grid.

```sql
CREATE TABLE v2_tables (
    table_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    doc_id       BIGINT NOT NULL,  -- = filings.filing_id
    segment_id   BIGINT,
    dom_locator  TEXT NOT NULL,
    section_path TEXT[],
    section_type TEXT,
    row_count    INTEGER NOT NULL,
    col_count    INTEGER NOT NULL,
    header_rows  INTEGER NOT NULL DEFAULT 0,
    stub_cols    INTEGER NOT NULL DEFAULT 0,
    raw_html     TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE v2_table_cells (
    cell_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    table_id    UUID NOT NULL REFERENCES v2_tables(table_id) ON DELETE CASCADE,
    row_idx     INTEGER NOT NULL,
    col_idx     INTEGER NOT NULL,
    cell_text   TEXT NOT NULL,
    is_header   BOOLEAN NOT NULL DEFAULT FALSE,
    is_stub     BOOLEAN NOT NULL DEFAULT FALSE,
    header_path TEXT[],
    stub_path   TEXT[],
    rowspan     INTEGER NOT NULL DEFAULT 1,
    colspan     INTEGER NOT NULL DEFAULT 1,
    dom_locator TEXT
);
```

`header_path` (columns above a cell) and `stub_path` (rows to its left) are populated at reconstruction time and are the substrate for value binding: the extractor binds numeric cells to metrics by matching metric aliases against these arrays rather than by positional heuristics. GIN indexes on both arrays support fast lookups.

`v2_tables.section_type` uses the same CHECK enum as `v2_segments.section_type`.

---

#### `v2_image_assets`

**Grain:** One row per extracted image (chart, table-as-image, decorative, logo, signature).

```sql
CREATE TABLE v2_image_assets (
    img_id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    doc_id              BIGINT NOT NULL,  -- = filings.filing_id
    segment_id          BIGINT,
    filename            TEXT NOT NULL,
    file_path           TEXT,
    width               INTEGER,
    height              INTEGER,
    dom_locator         TEXT NOT NULL,
    nearby_text         TEXT,
    section_path        TEXT[],
    section_type        TEXT,

    -- Classification
    classification      TEXT NOT NULL DEFAULT 'unknown',
    relevance_score     NUMERIC DEFAULT 0,
    predicted_relevance NUMERIC(5,4),

    -- OCR / chart parsing
    ocr_text            TEXT,
    ocr_table_id        UUID REFERENCES v2_tables(table_id),
    chart_type          TEXT,
    chart_data          JSONB,
    detected_metrics    JSONB NOT NULL DEFAULT '[]',  -- [{metric_id, score}], #86

    -- Processing + review
    processed           BOOLEAN NOT NULL DEFAULT FALSE,
    confidence          NUMERIC DEFAULT 0,
    requires_manual     BOOLEAN NOT NULL DEFAULT FALSE,
    review_status       TEXT NOT NULL DEFAULT 'pending',

    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

- `classification` ∈ `chart`, `table_image`, `decorative`, `logo`, `signature`, `unknown`.
- `chart_type` ∈ `bar`, `line`, `pie`, `stacked_bar`, `area`, `unknown` (or NULL).
- `review_status` ∈ `pending`, `reviewed`, `skipped`, `auto_rejected`. `auto_rejected` was added in migration 20 for low-predicted-relevance images.
- `predicted_relevance` (added in migration 19) is a 4-decimal score used to auto-defer low-relevance images from the review queue.
- `section_type` uses the full transcript/presentation enum.
- `detected_metrics` (added in `sql/42_add_detected_metrics_to_v2_image_assets.sql`, chart-presence pivot #86) is a JSONB array of `{metric_id, score}` pairs emitted by `ChartMetricClassifier.classify_all(...)` above `PipelineConfig.chart_presence_min_score`. Under the pivot this replaces per-value chart `v2_metric_facts` rows; reviewers confirm entries via `v2_image_metric_confirmations` (see below).

Indexes on `doc_id`, `classification`, `review_status`, `relevance_score`, `predicted_relevance` (partial), plus `(doc_id, review_status) WHERE review_status='pending'` for the review queue.

---

#### `v2_metric_facts`

**Grain:** One row per extracted fact. Identity is enforced by a partial unique index (see [V2 Fact Model](#v2-fact-model)).

```sql
CREATE TABLE v2_metric_facts (
    fact_id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    doc_id                  BIGINT NOT NULL
                                 REFERENCES filings(filing_id) ON DELETE CASCADE,
    canonical_metric_id     TEXT NOT NULL REFERENCES metrics(metric_id),

    -- Value
    value                   NUMERIC,
    value_raw               TEXT NOT NULL,
    unit                    TEXT NOT NULL,
    currency                TEXT,

    -- Time
    period_type             TEXT,
    period_start            DATE,
    period_end              DATE,

    -- Scope / cohort
    scope                   TEXT DEFAULT 'company',
    scope_detail            TEXT,
    cohort_def              TEXT,
    cohort_type             TEXT,
    customer_type           TEXT,

    -- Provenance
    source_type             TEXT NOT NULL,
    source_locator          JSONB NOT NULL DEFAULT '{}',
    evidence_pack           JSONB NOT NULL DEFAULT '{}',

    -- Quality
    confidence              NUMERIC NOT NULL DEFAULT 0,
    extraction_method       TEXT NOT NULL DEFAULT 'exact_match',
    requires_review         BOOLEAN NOT NULL DEFAULT TRUE,
    review_reason           TEXT,
    review_status           TEXT NOT NULL DEFAULT 'pending_review',

    -- Dedup + cross-source
    alternate_evidence      UUID[],
    primary_fact_id         UUID REFERENCES v2_metric_facts(fact_id),
    cross_source_confirmed  BOOLEAN NOT NULL DEFAULT FALSE,
    confirming_source_types TEXT[] NOT NULL DEFAULT '{}',

    pipeline_version        TEXT NOT NULL DEFAULT '2.0.0',
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

**Enums (CHECK constraints):**

| Column | Allowed values |
|--------|----------------|
| `unit` | `percent`, `currency`, `count`, `ratio`, `basis_points`, `other` |
| `period_type` | `annual`, `quarterly`, `trailing`, `ytd`, `point_in_time`, `other` |
| `scope` | `company`, `segment`, `geography`, `product`, `customer_type`, `cohort`, `other` |
| `source_type` | `html_table`, `ocr_table`, `text`, `chart` |
| `extraction_method` | `exact_match`, `alias_match`, `embedding`, `llm`, `manual` |
| `review_status` | `auto_accepted`, `pending_review`, `accepted`, `rejected`, `corrected` |
| `cohort_type` | `acquisition`, `tenure`, `other`, or NULL |

**Invariants (named CHECK constraints):**
- `valid_period`: `period_start <= period_end` (when both set).
- `valid_currency`: `unit = 'currency'` ⇒ `currency IS NOT NULL`.
- `confidence` ∈ [0, 1].

**Indexes:**
- `idx_v2_metric_facts_identity_unique` — partial UNIQUE index on
  `(doc_id, canonical_metric_id, COALESCE(period_start,'1900-01-01'), COALESCE(period_end,'1900-01-01'), unit, scope, COALESCE(cohort_def,''), COALESCE(customer_type,''))`.
  This is the idempotency guarantee: the persistence layer uses `ON CONFLICT DO UPDATE` against it. See [Known Discrepancies](#known-discrepancies) — the live index is 8 columns, though `sql/23_chart_source_dedup.sql` defines a 9-column variant including `source_type`.
- Secondary indexes on `doc_id`, `canonical_metric_id`, `review_status`, `source_type`, `(period_start, period_end)`, `confidence`, plus GIN indexes on `evidence_pack` and `source_locator` JSONB.

**Trigger:** `v2_metric_facts_updated_at` maintains `updated_at` on any update.

---

#### `v2_metric_definitions`

**Grain:** One row per `(doc_id, canonical_metric_id)` (enforced by `UNIQUE (doc_id, canonical_metric_id)`).

```sql
CREATE TABLE v2_metric_definitions (
    definition_id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    doc_id                      INTEGER NOT NULL
                                    REFERENCES v2_documents(filing_id) ON DELETE CASCADE,
    canonical_metric_id         TEXT NOT NULL,
    definition_text             TEXT,
    definition_text_normalized  TEXT,
    methodology_text            TEXT,
    methodology_text_normalized TEXT,
    definition_segment_id       UUID
                                    REFERENCES v2_segments(segment_id) ON DELETE SET NULL,
    methodology_segment_id      UUID
                                    REFERENCES v2_segments(segment_id) ON DELETE SET NULL,
    alignment_flag              TEXT NOT NULL DEFAULT 'unknown',
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

- `alignment_flag` values used by the pipeline: `aligned`, `partial`, `not_aligned`, `unknown`. (Stored as free-form `TEXT` with a default; no DB-level CHECK.)
- Rows are written by the Definition Extraction stage (`stages/definition_extraction.py`) when `definition` or `methodology` segments are discovered near a candidate.
- Definitions link to the source `v2_segments` rows; retaining the segment join enables provenance lookup.

---

#### `v2_review_decisions`

**Grain:** One row per reviewed fact (enforced by `UNIQUE (fact_id)`).

```sql
CREATE TABLE v2_review_decisions (
    decision_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    fact_id             UUID NOT NULL
                            REFERENCES v2_metric_facts(fact_id) ON DELETE CASCADE,
    decision            TEXT NOT NULL,
    assigned_metric_id  TEXT,
    corrected_value     NUMERIC,
    rejection_reason    TEXT,
    rejection_category  TEXT,
    reviewer_id         TEXT NOT NULL,
    reviewer_notes      TEXT,
    review_time_seconds INTEGER,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

- `decision` ∈ `accept`, `reject`, `correct`.
- `rejection_category` ∈ `wrong_metric`, `not_a_metric`, `wrong_value`, `wrong_period`, `part_of_date`, `duplicate`, `other`. `part_of_date` was added in migration 24 to classify rejections where a digit was extracted from a date fragment.
- **Trigger `v2_review_decision_updates_fact`** automatically promotes `v2_metric_facts.review_status` when a decision is inserted (accept → `accepted`, reject → `rejected`, correct → `corrected`).

---

#### `v2_image_review_decisions`

**Grain:** One row per reviewed image (enforced by `UNIQUE (img_id)`).

```sql
CREATE TABLE v2_image_review_decisions (
    image_decision_id   BIGSERIAL PRIMARY KEY,
    img_id              UUID NOT NULL UNIQUE
                            REFERENCES v2_image_assets(img_id) ON DELETE CASCADE,
    decision            TEXT NOT NULL,
    chart_type          TEXT,
    rejection_reason    TEXT,
    reviewer_id         TEXT,
    reviewer_notes      TEXT,
    review_time_seconds INTEGER,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

Semantic CHECK guards:
- `decision` ∈ `relevant`, `not_relevant`.
- If `decision = 'relevant'` → `chart_type` required (`check_v2_image_relevant_has_chart_type`), one of `cohort_table`, `cohort_parfait`, `line_chart`, `bar_chart`, `stacked_bar`, `other_chart`, `mixed`.
- If `decision = 'not_relevant'` → `rejection_reason` required (`check_v2_image_not_relevant_has_reason`), one of `decorative`, `not_a_chart`, `wrong_subject`, `duplicate`, `unreadable`, `other`.

`cohort_parfait` replaces the earlier `cohort_heatmap` value (migration 15).

---

#### `v2_image_metric_confirmations`

**Grain:** One row per `(img_id, reviewer_id, COALESCE(detected_metric_id, confirmed_metric_id, ''))` — enforced by the unique index below. Added in `sql/43_create_v2_image_metric_confirmations.sql` (chart-presence pivot, #86).

```sql
CREATE TABLE v2_image_metric_confirmations (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    img_id                  UUID NOT NULL
                                REFERENCES v2_image_assets(img_id) ON DELETE CASCADE,
    detected_metric_id      TEXT NULL,   -- what the classifier said (NULL when decision='add')
    confirmed_metric_id     TEXT NULL,   -- what the reviewer says is actually there (NULL when decision='reject')
    decision                TEXT NOT NULL CHECK (decision IN ('accept','reject','correct','add')),
    rejection_reason        TEXT NULL,   -- required when decision='reject'; optional for 'correct'
    reviewer_id             TEXT NOT NULL,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_v2_image_metric_confirmations_img_id
    ON v2_image_metric_confirmations(img_id);

CREATE UNIQUE INDEX idx_v2_image_metric_confirmations_unique
    ON v2_image_metric_confirmations(
        img_id,
        reviewer_id,
        COALESCE(detected_metric_id, confirmed_metric_id, '')
    );
```

Decision semantics (enforced at API level in `src/web/routes/api_unified.py::create_image_metric_confirmations`):

| `decision` | `detected_metric_id` | `confirmed_metric_id` | `rejection_reason` |
|---|---|---|---|
| `accept` | required | `= detected_metric_id` | must be NULL |
| `reject` | required | NULL | required (enum below) |
| `correct` | required | required, `!= detected_metric_id` | optional (free-text) |
| `add` | NULL (reviewer added a missed metric) | required | must be NULL |

Rejection-reason enum (suggested values surfaced in the UI, not a CHECK constraint so free-text "other" remains open): `not_present`, `decorative`, `unrelated_chart`, `similar_metric_misclassified`, `too_low_confidence`, `other`.

Upsert flow: `DatabaseAdapter.insert_image_metric_confirmations(img_id, confirmations, reviewer_id)` (`src/infra/db.py`) uses `ON CONFLICT` on the unique index to update `decision`, `confirmed_metric_id`, `rejection_reason`, `updated_at`. Row-reads go through `DatabaseAdapter.get_image_metric_confirmations(img_id)`.

This table is the reviewer-adjudication surface for `v2_image_assets.detected_metrics` under the chart-presence pivot. It replaces the per-value chart-fact review path that existed pre-#86. Values (when CMASB needs them) enter via `POST /api/v2/missed-metric`, not via this table.

---

### V1 residual

These tables are live but on a retirement path. See `docs/architecture/v1-table-deprecation-plan.md` for migration roadmaps and difficulty assessments. The V2 pipeline does not read them; they support the legacy candidate-review UI and gold-standard tooling.

#### `source_segments`

Paragraph/table/footnote segmentation of SEC filings. Consumed by `src/gold_standard/fresh_extractor.py` and the V1 candidate-generator. Key columns:

```sql
filing_id, segment_type, section_path, section_heading, sequence_index,
html_selector, page_number, raw_text, raw_html,
candidate_metric_ids, contains_definition_flag, contains_methodology_flag,
contains_numeric_disclosure_flag, classifier_confidence,
metric_density, distinct_metric_count, contains_temporal_trend,
contains_cohort_breakdown, image_count, richness_score
```

`segment_type` ∈ `paragraph`, `table`, `footnote`, `definition_block`, `methodology_block`, `other`.

`char_start_offset` and `char_end_offset` are deprecated (INV-1-FIX-v2) — always NULL. Use `html_selector` for source location.

**Retirement:** MEDIUM difficulty; blocked on ensuring V2 segment data is persisted and accessible at review time.

#### `review_candidates`

V1 candidate-generation output: keyword hits with nearby numeric values. Consumed by `src/review/*`, `src/infra/db.py`, and many scripts. `review_status` ∈ `pending`, `in_progress`, `reviewed`, `skipped`. **Retirement:** HIGH difficulty (2–4 weeks).

#### `review_decisions`

V1 reviewer outcome per candidate (`accept`/`reject`/`reclassify`). One-to-one with `review_candidates` via `UNIQUE (candidate_id)`. `rejection_category` shares the V2 enum (including `part_of_date`).

#### `suppressed_candidates`

Logs V1 candidates that were suppressed during generation. Suppression reasons: `lower_confidence`, `cross_sentence`, `duplicate_execution`, `runner_up`. **Retirement:** LOW-MEDIUM, deferred to the `review_candidates` project.

#### `learned_patterns`

Approval-tracked telemetry for candidate-tuning rules. `pattern_type` ∈ `accept_rule`, `reject_rule`, `feature_weight`. `status` ∈ `candidate`, `approved`, `rejected`, `deprecated`.

---

## V2 Fact Model

This section describes how an extraction emits a `v2_metric_facts` row, how identity/dedup works, and how provenance is stored.

### Identity

A fact's identity is the tuple used for upsert-based deduplication. The **live DB index** (`idx_v2_metric_facts_identity_unique`) covers 8 columns:

```
(doc_id, canonical_metric_id,
 COALESCE(period_start, '1900-01-01'), COALESCE(period_end, '1900-01-01'),
 unit, scope, COALESCE(cohort_def, ''), COALESCE(customer_type, ''))
```

`src/extraction_v2/models.py::MetricFact.identity_tuple()` returns these same eight keys plus `source_type` as a ninth element (it also rounds `value` for tolerance comparisons). See [Known Discrepancies](#known-discrepancies).

### Provenance

Every fact carries two JSONB payloads:

**`source_locator`** — machine-readable location:

```json
{
  "segment_id": "…",          // v2_segments.segment_id, if text/footnote
  "table_id":   "…",          // v2_tables.table_id, if table source
  "cell_row":   3,
  "cell_col":   1,
  "text_span":  [120, 156],   // char offsets into segment_text
  "img_id":     "…",          // v2_image_assets.img_id, if chart
  "bbox":       {"x":…,"y":…,"width":…,"height":…},
  "dom_locator":"/html/body/div[2]/table[1]/tr[4]/td[2]"
}
```

**`evidence_pack`** — human-renderable evidence for the review UI:

```json
{
  "snippet_html":   "<td>...<mark>112%</mark>...</td>",
  "header_path":    ["FY2023", "Net Revenue Retention"],
  "stub_path":      ["Enterprise customers"],
  "context_before": "… our cohort of large customers saw ",
  "context_after":  " expansion driven by seat growth.",
  "raw_value_text": "112%",
  "screenshot_path":"…optional cropped image…"
}
```

`header_path` and `stub_path` mirror the `v2_table_cells` arrays, enabling the review UI to reconstruct the logical binding without rejoining to the cells table.

### Source types and cross-source confirmation

`source_type` ∈ `html_table`, `ocr_table`, `text`, `chart`. The `chart` variant is retained in the enum for historical rows and schema compatibility, but the chart-presence pivot (#86) stops emitting new `source_type='chart'` rows — the chart pipeline now writes to `v2_image_assets.detected_metrics` and reviewer adjudications to `v2_image_metric_confirmations`. Any residual rows on main are scheduled for drain in PR #86-4b.

`DeduplicationStage` still annotates text/table facts with `cross_source_confirmed = TRUE` when different text/table sources agree on the same `(metric, period, value)` slot, and records the confirming types in `confirming_source_types` (e.g., `{HTML_TABLE,TEXT}`). The previous CHART↔TEXT/TABLE confirmation branch is dormant post-pivot.

### Chart emission under the presence pivot

Charts produce an image-level *presence* signal, not per-value facts. The chart pipeline path is:

1. `ImageTriageStage` flags an image as `classification='chart'`.
2. Vision → `chart_data` JSONB on `v2_image_assets`.
3. `ChartFactBridgeStage` runs `ChartMetricClassifier.classify_all(chart_data, nearby_text)` and writes `[{metric_id, score}, ...]` to `v2_image_assets.detected_metrics` for scores ≥ `PipelineConfig.chart_presence_min_score`. No `v2_metric_facts` row is emitted.
4. Reviewers adjudicate via `v2_image_metric_confirmations` (accept / reject / correct / add). Values (if needed) come through the manual entry path at `POST /api/v2/missed-metric`.

Gold-standard validation treats chart-native metrics via presence P/R/F1; see `docs/GOLD_STANDARD_SPECIFICATION.md`.

### Definitions

`v2_metric_definitions` holds at most one row per `(doc, metric)`. Rows are populated by the Definition Extraction stage when definition/methodology segments are found near candidate matches. Each definition can reference the originating `v2_segments` row via `definition_segment_id` and `methodology_segment_id`.

---

## Data Conventions

- **Percentages:** stored as raw percentages (37.5 represents 37.5%, not 0.375).
- **Monetary values:** stored in the currency indicated by `currency`; `currency` is required when `unit = 'currency'`.
- **Dates:** ISO-8601 (`YYYY-MM-DD`).
- **CIKs:** zero-padded to 10 digits.
- **Naming:** `lower_snake_case` tables and columns; canonical metric IDs use the `cm_` prefix.
- **JSONB payloads** (`source_locator`, `evidence_pack`, `chart_data`, `learned_patterns.pattern_definition`, `review_candidates.features`) are queryable via Postgres operators; GIN indexes exist where latency matters.

---

## Analysis Views

The live database contains five views. Three of them (prefixed `v_`) still target V1 residual tables.

| View | Over | Purpose |
|------|------|---------|
| `v2_extraction_summary` | `v2_documents`, `filings`, `companies`, `v2_metric_facts` | Per-document extraction statistics: segment/table/image/fact counts, plus pending/accepted/rejected review counts. |
| `v2_facts_pending_review` | `v2_metric_facts`, `filings`, `companies` | Facts with `review_status = 'pending_review'`, ordered by confidence descending. Primary feed for the review UI. |
| `v_review_progress_by_filing` | `review_candidates`, `filings`, `companies` (V1) | V1 candidate-review progress per filing. |
| `v_decision_stats_by_metric` | `review_decisions`, `review_candidates` (V1) | V1 decision mix per suggested metric. |
| `v_rejection_reasons` | `review_decisions`, `review_candidates` (V1) | V1 rejection patterns per metric, with average keyword distance. |

V2-fact-driven analytics views beyond `v2_extraction_summary` and `v2_facts_pending_review` are a pending deliverable; see `docs/architecture/v1-table-deprecation-plan.md`.

---

## Extensibility Notes

**Adding a new metric.** Insert into `metrics`; add keyword patterns to `config/metric_keywords.yaml`. No schema change.

**Adding a new document type.** Extend the `form_type` CHECK on `filings` (pattern: new migration ALTER CONSTRAINT), then add section-type values to the `v2_segments`/`v2_tables`/`v2_image_assets` CHECK lists if the new document has novel section semantics. Migrations 13, 14, 16, 18 are prior examples.

**Versioning a metric definition.** Increment `metrics.version`; historical `v2_metric_facts` rows keep pointing at the same `metric_id`. Document the change in `metrics.description` or a project changelog.

---

## Migration Index

Authoritative DDL ordering. Applied to live DB in the order shown (see `schema_migrations`).

| # | File | Purpose |
|---|------|---------|
| 00 | `00_init_databases.sql` | Initial DB bootstrap |
| 01 | `01_create_schema.sql` | Shared core tables (`companies`, `filings`, `source_segments`, `metrics`) |
| 02 | `02_add_filing_storage.sql` | HTML/text storage columns on `filings` |
| 03 | `03_create_analysis_schema.sql` | V1 analysis tables (now dropped) |
| 04 | `04_seed_metrics_taxonomy.sql` | Seed `metrics` rows |
| 04 | `04_add_post_combination.sql` | `filings.is_post_combination` |
| 05 | `05_add_business_type_exclusions.sql` | Universe-scope flags on `filings` |
| 07 | `07_create_review_schema.sql` | V1 `review_candidates`, `review_decisions` |
| 08 | `08_add_richness_metadata.sql` | Richness columns on `source_segments` |
| 08 | `08_add_suppressed_candidates.sql` | `suppressed_candidates` |
| 09 | `09_create_image_review_schema.sql` | V1 image-review tables (dropped in 30) |
| 09 | `09_v2_schema.sql` | V2 table DDL (`v2_*` primary set) |
| 10 | `10_add_html_content_column.sql` | `filings.html_content` |
| 10 | `10_v2_fact_identity_dedup.sql` | Original 8-column identity index |
| 11 | `11_transcript_support.sql` | Transcript columns on `filings` |
| 11 | `11_v2_definitions.sql` | `v2_metric_definitions` |
| 12 | `12_drop_v1_fk_constraints.sql` | FK cleanup |
| 12 | `12_v2_documents_transcript_columns.sql` | Transcript/presentation cols on `v2_documents` |
| 13 | `13_transcript_section_types.sql` | Transcript values in `section_type` CHECK |
| 14 | `14_presentation_section_types.sql` | Presentation values in `section_type` CHECK |
| 15 | `15_rename_cohort_heatmap_to_parfait.sql` | Rename `cohort_heatmap` → `cohort_parfait` |
| 16 | `16_add_8k_form_type.sql` | Allow `8-K` in `form_type` CHECK |
| 17 | `17_add_cohort_type_to_v2.sql` | `v2_metric_facts.cohort_type` |
| 18 | `18_add_presentation_detection_tier.sql` | `presentation` in V1 image-review detection tier (tables later dropped) |
| 19 | `19_add_predicted_relevance.sql` | `v2_image_assets.predicted_relevance` |
| 20 | `20_add_auto_rejected_status.sql` | `auto_rejected` in `v2_image_assets.review_status` |
| 21 | `21_create_image_cache.sql` | `image_cache` |
| 22 | `22_seed_missing_metrics.sql` | Taxonomy backfill |
| 23 | `23_chart_source_dedup.sql` | 9-column identity index (see Known Discrepancies) |
| 24 | `24_add_part_of_date_rejection_category.sql` | `part_of_date` rejection category |
| 25 | `25_cross_source_confirmation.sql` | `cross_source_confirmed`, `confirming_source_types` |
| 26 | `26_drop_filing_metric_incidence.sql` | **Drops `filing_metric_incidence`** |
| 27 | `27_drop_v1_metric_tables.sql` | **Drops `metric_values`, V1 `metric_definitions`** |
| 28 | `28_extend_v2_image_assets_review.sql` | Review columns on `v2_image_assets` |
| 29 | `29_create_v2_image_review_decisions.sql` | `v2_image_review_decisions` |
| 30 | `30_drop_v1_image_review.sql` | **Drops V1 image-review tables** |

Note: historical duplicate migration numbers (04/08/09/10/11/12) reflect prior splits. Do not add further duplicates.

---

## Known Discrepancies

- **Identity index column count — fix prepared, pending prod apply.** `sql/23_chart_source_dedup.sql` defines `idx_v2_metric_facts_identity_unique` with 9 columns including `source_type`. The live DB index has 8 columns (no `source_type`), likely because a pg_dump schema snapshot taken before sql/23 was applied was used to recreate the DB at some point after the migration was recorded. `sql/33_fix_identity_index.sql` idempotently drops and recreates the index with all 9 columns. See [known issue #13](../known-issues/legacy-013-v2-metric-facts-identity-index-drift.md). Once sql/33 is applied to prod this discrepancy is resolved.

---

## Related Documentation

- **V1 retirement roadmap:** `docs/architecture/v1-table-deprecation-plan.md`
- **Extraction decisions:** `docs/architecture/extraction-decisions.md`
- **Metric taxonomy:** `docs/development/metrics-taxonomy.md`
- **Human review system:** `docs/HUMAN_REVIEW_SYSTEM.md`
- **Gold standard spec:** `docs/GOLD_STANDARD_SPECIFICATION.md`
- **V2 schema DDL (authoritative):** `sql/09_v2_schema.sql` plus migrations 10–30 listed above
- **V2 dataclasses (code-level truth for field meanings):** `src/extraction_v2/models.py`
- **V2 persistence (upsert SQL):** `src/extraction_v2/persistence.py`
