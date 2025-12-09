# Data Model Specification

**Version:** 2.0
**Last Updated:** 2025-12-09
**Status:** Production Schema

---

## Overview

This document defines the complete data model for the Customer Metrics Filings Analysis system, including:

- Core database schema (PostgreSQL)
- Table structures, keys, and relationships
- Field definitions and business meanings
- Data conventions and allowed values

This schema supports all analytic needs defined in the requirements and is extensible to Phase 2 (10-K filings).

---

## Design Principles

### 1. Provenance-First
Every metric value, definition, and quality score must be traceable back to specific segments in specific filings.

### 2. Analysis-First Grain
Tables are designed around units of analysis:
- Filing
- Filing × metric
- Filing × metric × period × cohort × segment
- Filing × source segment

### 3. Normalized but Practical
Avoid excessive normalization that makes queries painful. Accept denormalization for common joins (e.g., keep basic filing metadata on fact tables).

### 4. Metric Taxonomy Alignment
All metrics use canonical IDs from the taxonomy. Mapping from issuer-defined labels to canonical IDs is explicit and stored.

### 5. Extensibility
Schema accommodates new metrics, filing types, and industries without breaking existing tables.

### 6. PostgreSQL-Oriented
Types are aligned with PostgreSQL (text, numeric, timestamptz, jsonb).

---

## Entity Overview

### Core Tables

1. `companies` – Issuer-level metadata
2. `filings` – Individual SEC filings
3. `source_segments` – Segmented units of each filing (paragraphs, tables, footnotes)
4. `metrics` – Dimension table of canonical metrics (from taxonomy)
5. `metric_values` – Extracted numeric metric values (fact table)
6. `filing_metric_incidence` – Filing × metric incidence and quality scores
7. `metric_definitions` – Metric definitions and methodologies per filing

### Relationships Summary

- `companies` 1–N `filings`
- `filings` 1–N `source_segments`
- `metrics` 1–N `metric_values` (via `metric_id`)
- `filings` 1–N `metric_values`
- `filings` 1–N `filing_metric_incidence`
- `filings` 1–N `metric_definitions`
- `source_segments` 1–N `metric_values`
- `source_segments` 1–N `metric_definitions`

Conceptually:
- `source_segments` are the **atomic source units**
- `metric_values` and `metric_definitions` are **facts** derived from segments
- `filing_metric_incidence` summarizes at the filing-metric level

---

## Table Specifications

### 1. `companies`

**Grain:** One row per issuer (company)

**Purpose:** Central reference for issuer metadata; allows multiple filings per company

**Schema:**

```sql
CREATE TABLE companies (
    -- Primary key
    company_id BIGSERIAL PRIMARY KEY,

    -- External identifiers
    cik TEXT NOT NULL UNIQUE,
    company_name TEXT NOT NULL,
    ticker TEXT,

    -- Classification
    country_of_domicile TEXT,
    industry_code TEXT,
    industry_classification_source TEXT,

    -- Metadata
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_companies_cik ON companies(cik);
CREATE INDEX idx_companies_industry ON companies(industry_code);
```

**Field Definitions:**

| Column | Type | Required | Description |
|--------|------|----------|-------------|
| `company_id` | bigserial | yes | Internal surrogate key for the company. Used for joins inside our database. |
| `cik` | text | yes | SEC Central Index Key (10 digits, zero-padded). Primary external identifier and join key to EDGAR. |
| `company_name` | text | yes | Official issuer name as shown in SEC filings. |
| `ticker` | text | no | Primary listed ticker symbol, if known. |
| `country_of_domicile` | text | no | Country where the company is legally domiciled (e.g., `United States`, `Canada`). |
| `industry_code` | text | no | SIC, GICS, or internal industry classification code. |
| `industry_classification_source` | text | no | Source system or convention for `industry_code` (e.g., `sic`, `gics`, `manual`). |
| `created_at` | timestamptz | yes | Timestamp when this row was created. |
| `updated_at` | timestamptz | yes | Timestamp when this row was last updated. |

---

### 2. `filings`

**Grain:** One row per SEC filing document in scope

**Purpose:** Represent each S-1/F-1 (and later 10-K) with classification flags and links to companies

**Schema:**

```sql
CREATE TABLE filings (
    -- Primary key
    filing_id BIGSERIAL PRIMARY KEY,

    -- Company link
    company_id BIGINT NOT NULL REFERENCES companies(company_id),
    cik TEXT NOT NULL,

    -- Filing identification
    accession_number TEXT NOT NULL UNIQUE,
    form_type TEXT NOT NULL,
    filing_date DATE NOT NULL,
    period_end_date DATE,

    -- SEC URLs
    sec_html_url TEXT NOT NULL,
    sec_txt_url TEXT,

    -- Classification flags (Phase 1)
    is_in_scope_phase1 BOOLEAN NOT NULL DEFAULT false,
    is_first_time_issuer BOOLEAN,
    is_spac BOOLEAN,
    offering_type TEXT,
    classification_method TEXT,

    -- Processing status
    processing_status TEXT NOT NULL DEFAULT 'pending',
    processing_notes TEXT,

    -- Metadata
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_filings_company ON filings(company_id);
CREATE INDEX idx_filings_cik ON filings(cik);
CREATE INDEX idx_filings_date ON filings(filing_date);
CREATE INDEX idx_filings_scope ON filings(is_in_scope_phase1) WHERE is_in_scope_phase1 = true;
CREATE INDEX idx_filings_status ON filings(processing_status);
```

**Field Definitions:**

| Column | Type | Required | Description |
|--------|------|----------|-------------|
| `filing_id` | bigserial | yes | Internal surrogate key for the filing. Used as the primary join key throughout the system. |
| `company_id` | bigint | yes | Foreign key to `companies.company_id`. |
| `cik` | text | yes | Denormalized copy of the company CIK for easier joins. Must match `companies.cik`. |
| `accession_number` | text | yes | SEC accession number for the filing. Unique per filing across EDGAR. |
| `form_type` | text | yes | SEC form type (e.g., `S-1`, `F-1`, `S-1/A`, `10-K` in Phase 2). |
| `filing_date` | date | yes | Date the filing was submitted to the SEC. |
| `period_end_date` | date | no | Period of report / fiscal year-end used in the filing, where available. |
| `sec_html_url` | text | yes | Canonical SEC HTML URL for the filing body. Used as input to ingestion. |
| `sec_txt_url` | text | no | URL to raw text version of the filing, if used. |
| `is_in_scope_phase1` | boolean | yes | True if the filing is in the Phase 1 universe (S-1/F-1 for first-time issuers; no SPACs or secondary-only offerings). |
| `is_first_time_issuer` | boolean | no | True if this filing corresponds to the company's first public equity issuance. |
| `is_spac` | boolean | no | True if the issuer is a SPAC (special purpose acquisition company). Phase 1 excludes these. |
| `offering_type` | text | no | High-level classification: `primary`, `secondary`, `mixed`. |
| `classification_method` | text | no | How classification flags were determined: `heuristic`, `manual_review`, `uncertain`. |
| `processing_status` | text | yes | Current state: `pending`, `fetched`, `segmented`, `processed`, `failed`. |
| `processing_notes` | text | no | Free-text notes about errors or special handling. |

---

### 3. `source_segments`

**Grain:** One row per segment of a filing (paragraph, table, footnote, etc.)

**Purpose:** Provide the audit trail and anchor for all extracted metrics and definitions

**Schema:**

```sql
CREATE TABLE source_segments (
    -- Primary key
    source_segment_id BIGSERIAL PRIMARY KEY,

    -- Filing reference
    filing_id BIGINT NOT NULL REFERENCES filings(filing_id),

    -- Segment metadata
    segment_type TEXT NOT NULL,
    section_path TEXT,
    section_heading TEXT,
    sequence_index INTEGER NOT NULL,

    -- Location/provenance
    html_selector TEXT,
    char_start_offset INTEGER,
    char_end_offset INTEGER,
    page_number INTEGER,

    -- Content
    raw_text TEXT NOT NULL,
    raw_html TEXT,

    -- Classification metadata
    candidate_metric_ids TEXT[],
    contains_definition_flag BOOLEAN NOT NULL DEFAULT false,
    contains_methodology_flag BOOLEAN NOT NULL DEFAULT false,
    contains_numeric_disclosure_flag BOOLEAN NOT NULL DEFAULT false,
    classifier_confidence NUMERIC,

    -- Metadata
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_segments_filing ON source_segments(filing_id);
CREATE INDEX idx_segments_type ON source_segments(segment_type);
CREATE INDEX idx_segments_numeric ON source_segments(filing_id)
    WHERE contains_numeric_disclosure_flag = true;
```

**Segment Types:**
- `paragraph` - Text paragraphs
- `table` - HTML tables (entire table as one segment)
- `footnote` - Footnotes and endnotes
- `definition_block` - Detected definition sections
- `methodology_block` - Detected calculation methodology sections
- `other` - Fallback

**Field Definitions:**

| Column | Type | Required | Description |
|--------|------|----------|-------------|
| `source_segment_id` | bigserial | yes | Internal surrogate key for the segment. |
| `filing_id` | bigint | yes | Foreign key to `filings.filing_id`. |
| `segment_type` | text | yes | Type of segment (see enum above). |
| `section_path` | text | no | Logical path within filing (e.g., `Item 1. Business > Customers`). |
| `section_heading` | text | no | Heading text associated with the segment's section. |
| `sequence_index` | integer | yes | Ordering of segment within the filing (0-based). |
| `html_selector` | text | no | XPath/CSS selector for precise location. |
| `char_start_offset` | integer | no | Start character index in normalized filing text. |
| `char_end_offset` | integer | no | End character index in normalized filing text. |
| `page_number` | integer | no | Page number in PDF, if available. |
| `raw_text` | text | yes | Normalized plain text (visible content only). |
| `raw_html` | text | no | Original HTML snippet. May be large. |
| `candidate_metric_ids` | text[] | no | List of `metric_id` values the classifier believes may be present. |
| `contains_definition_flag` | boolean | yes | True if segment likely contains metric definitions. |
| `contains_methodology_flag` | boolean | yes | True if segment likely describes metric calculations. |
| `contains_numeric_disclosure_flag` | boolean | yes | True if segment likely contains numeric values. |
| `classifier_confidence` | numeric | no | Confidence score (0–1) of the classification. |

---

### 4. `metrics`

**Grain:** One row per canonical metric ID in the taxonomy

**Purpose:** Dimension table for metrics; ties DB to metric taxonomy

**Schema:**

```sql
CREATE TABLE metrics (
    -- Primary key
    metric_id TEXT PRIMARY KEY,

    -- Display
    display_name TEXT NOT NULL,
    metric_class TEXT NOT NULL,
    description TEXT,
    primary_concept TEXT,

    -- Status
    status TEXT NOT NULL DEFAULT 'active',
    version INTEGER NOT NULL DEFAULT 1,

    -- Metadata
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_metrics_class ON metrics(metric_class);
CREATE INDEX idx_metrics_status ON metrics(status);
```

**Metric Classes:**
- `core` - Priority metrics for Phase 1
- `extended` - Additional metrics
- `future` - Planned metrics

**Field Definitions:**

| Column | Type | Required | Description |
|--------|------|----------|-------------|
| `metric_id` | text | yes | Canonical ID (e.g., `cm_new_customers_acquired`). |
| `display_name` | text | yes | Human-readable label. |
| `metric_class` | text | yes | Classification: `core`, `extended`, `future`. |
| `description` | text | no | Short description of what the metric measures. |
| `primary_concept` | text | no | Primary business concept (e.g., `acquisition`, `cohort_revenue`). |
| `status` | text | yes | Status: `active`, `deprecated`, `experimental`. |
| `version` | integer | yes | Metric definition version (increment when definition changes). |

---

### 5. `metric_values`

**Grain:** One row per filing × metric × period × cohort × segment value

**Purpose:** Main fact table for quantitative analysis of disclosed metrics

**Schema:**

```sql
CREATE TABLE metric_values (
    -- Primary key
    metric_value_id BIGSERIAL PRIMARY KEY,

    -- Foreign keys
    filing_id BIGINT NOT NULL REFERENCES filings(filing_id),
    company_id BIGINT NOT NULL REFERENCES companies(company_id),
    metric_id TEXT NOT NULL REFERENCES metrics(metric_id),

    -- Provenance
    source_segment_id BIGINT NOT NULL REFERENCES source_segments(source_segment_id),
    source_type TEXT NOT NULL,
    extraction_method TEXT NOT NULL,

    -- Value
    value_numeric NUMERIC,
    value_text TEXT,
    unit TEXT,
    currency TEXT,

    -- Time dimensions
    period_start DATE,
    period_end DATE,
    period_type TEXT,

    -- Cohort dimensions
    cohort_type TEXT,
    cohort_bucket_raw TEXT,
    cohort_bucket_normalized TEXT,

    -- Segmentation dimensions
    segment_dimension TEXT,
    segment_value TEXT,

    -- Quality/alignment
    qa_status TEXT NOT NULL DEFAULT 'unreviewed',
    qa_notes TEXT,
    alignment_flag TEXT,

    -- Metadata
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_values_filing_metric ON metric_values(filing_id, metric_id);
CREATE INDEX idx_values_metric_period ON metric_values(metric_id, period_end);
CREATE INDEX idx_values_source ON metric_values(source_segment_id);
```

**Source Types:**
- `table` - Extracted from HTML table
- `text` - Extracted from narrative text
- `footnote` - Extracted from footnote
- `other` - Other source

**Extraction Methods:**
- `rule_table` - Rule-based table extraction
- `rule_text` - Rule-based text extraction
- `llm_text` - LLM-based text extraction (GPT-4o-mini)
- `llm_table` - LLM-enhanced table extraction
- `manual_review` - Manual correction/addition

**Cohort Types:**
- `acquisition` - Grouped by acquisition/signup period
- `tenure` - Grouped by customer age/tenure
- `other` - Other cohort dimension

**QA Status:**
- `unreviewed` - Not yet QA checked
- `pass` - Passed QA checks
- `warning` - QA warnings present
- `fail` - Failed QA validation

---

### 6. `filing_metric_incidence`

**Grain:** One row per filing × metric

**Purpose:** Support incidence and quality analyses at the filing-metric level

**Schema:**

```sql
CREATE TABLE filing_metric_incidence (
    -- Primary key
    filing_metric_incidence_id BIGSERIAL PRIMARY KEY,

    -- Foreign keys
    filing_id BIGINT NOT NULL REFERENCES filings(filing_id),
    company_id BIGINT NOT NULL REFERENCES companies(company_id),
    metric_id TEXT NOT NULL REFERENCES metrics(metric_id),

    -- Incidence
    metric_disclosed_flag BOOLEAN NOT NULL,
    num_numeric_segments INTEGER NOT NULL DEFAULT 0,
    num_definition_segments INTEGER NOT NULL DEFAULT 0,
    num_methodology_segments INTEGER NOT NULL DEFAULT 0,

    -- Primary segments
    primary_definition_segment_id BIGINT REFERENCES source_segments(source_segment_id),
    primary_methodology_segment_id BIGINT REFERENCES source_segments(source_segment_id),

    -- Quality scores (0-3 scale)
    quality_overall_score INTEGER,
    quality_definition_score INTEGER,
    quality_methodology_score INTEGER,
    quality_completeness_score INTEGER,
    quality_comparability_score INTEGER,

    -- Flags
    alignment_flag TEXT,
    quality_notes TEXT,
    has_cohort_breakdown_flag BOOLEAN NOT NULL DEFAULT false,
    has_tenure_breakdown_flag BOOLEAN NOT NULL DEFAULT false,
    has_acquisition_cohort_flag BOOLEAN NOT NULL DEFAULT false,

    -- Metadata
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),

    -- Unique constraint
    CONSTRAINT unique_filing_metric UNIQUE (filing_id, metric_id)
);

CREATE INDEX idx_incidence_metric ON filing_metric_incidence(metric_id);
CREATE INDEX idx_incidence_disclosed ON filing_metric_incidence(metric_id)
    WHERE metric_disclosed_flag = true;
```

**Quality Score Scale (0-3):**

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

### 7. `metric_definitions`

**Grain:** One row per filing × metric × definition_version

**Purpose:** Capture issuer-specific definitions and calculation methodology text, plus alignment to canonical standards

**Schema:**

```sql
CREATE TABLE metric_definitions (
    -- Primary key
    metric_definition_id BIGSERIAL PRIMARY KEY,

    -- Foreign keys
    filing_id BIGINT NOT NULL REFERENCES filings(filing_id),
    company_id BIGINT NOT NULL REFERENCES companies(company_id),
    metric_id TEXT NOT NULL REFERENCES metrics(metric_id),
    definition_version_in_filing INTEGER NOT NULL DEFAULT 1,

    -- Content
    definition_text_normalized TEXT,
    methodology_text_normalized TEXT,
    definition_raw_text TEXT,
    methodology_raw_text TEXT,

    -- Provenance
    definition_segment_id BIGINT REFERENCES source_segments(source_segment_id),
    methodology_segment_id BIGINT REFERENCES source_segments(source_segment_id),

    -- Alignment
    alignment_flag TEXT,
    alignment_notes TEXT,

    -- Metadata
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_definitions_filing_metric ON metric_definitions(filing_id, metric_id);
CREATE INDEX idx_definitions_metric ON metric_definitions(metric_id);
```

**Alignment Flags:**
- `aligned` - Definition matches CMASB canonical definition
- `partial` - Definition partially aligned with CMASB
- `not_aligned` - Definition differs significantly from CMASB
- `unknown` - Alignment not assessed

---

## Data Conventions

### Value Conventions

- **Percentages:** Stored as raw percentages (e.g., 37.5, not 0.375)
- **Monetary values:** Stored in base currency units (e.g., USD)
- **Dates:** ISO-8601 format (`YYYY-MM-DD`)
- **CIKs:** 10 digits, zero-padded (e.g., `0001234567`)

### Naming Conventions

- **Table names:** `lower_snake_case` (e.g., `metric_values`)
- **Column names:** `lower_snake_case`
- **Canonical metric IDs:** `cm_` prefix, `lower_snake_case` (e.g., `cm_new_customers_acquired`)

### Types (Logical)

- `text` – Free-form string
- `integer` – Whole-number count
- `numeric` – Decimal number (monetary, ratios, percentages)
- `date` – Calendar date (no time zone)
- `timestamptz` – Timestamp with time zone
- `boolean` – `true` / `false`
- `text[]` – Array of text values

---

## Analysis-Ready Views

These logical views support common analytic queries:

### v_filing_metric_incidence

Joins filing, company, metric, and incidence data for analysis by year, industry, form type.

```sql
CREATE OR REPLACE VIEW v_filing_metric_incidence AS
SELECT
    fmi.*,
    f.filing_date,
    f.form_type,
    c.company_name,
    c.cik,
    c.ticker,
    c.industry_code,
    m.display_name AS metric_name,
    m.metric_class
FROM filing_metric_incidence fmi
JOIN filings f ON fmi.filing_id = f.filing_id
JOIN companies c ON fmi.company_id = c.company_id
JOIN metrics m ON fmi.metric_id = m.metric_id;
```

### v_metric_values_cohort

Comprehensive view for cohort analysis with all dimensions.

```sql
CREATE OR REPLACE VIEW v_metric_values_cohort AS
SELECT
    mv.*,
    f.filing_date,
    f.form_type,
    c.company_name,
    c.cik,
    c.ticker,
    m.display_name AS metric_name,
    m.metric_class
FROM metric_values mv
JOIN filings f ON mv.filing_id = f.filing_id
JOIN companies c ON mv.company_id = c.company_id
JOIN metrics m ON mv.metric_id = m.metric_id;
```

### v_metric_definitions

View for comparability analysis of definitions across firms.

```sql
CREATE OR REPLACE VIEW v_metric_definitions AS
SELECT
    md.*,
    f.filing_date,
    c.company_name,
    m.display_name AS metric_name
FROM metric_definitions md
JOIN filings f ON md.filing_id = f.filing_id
JOIN companies c ON md.company_id = c.company_id
JOIN metrics m ON md.metric_id = m.metric_id;
```

---

## Extensibility Notes

### Adding New Metrics

1. Insert row into `metrics` table with new `metric_id`
2. Update metric classifier keyword patterns
3. No schema changes required

### Adding Filing Types (Phase 2: 10-K)

1. Add filings with `form_type = '10-K'`
2. Add new scope flag (e.g., `is_in_scope_phase2`) to `filings`
3. Update Universe Builder logic
4. Adjust classifier patterns for 10-K sections
5. No other schema changes required

### Versioning Metric Definitions

When metric definition changes that affect comparability:
1. Increment `metrics.version`
2. Keep historical data linked to old version
3. Document change in `metrics.description` or separate changelog

---

## Related Documentation

- **System Architecture:** `docs/architecture/system-overview.md` - High-level design
- **Extraction Pipeline:** `docs/architecture/extraction-pipeline.md` - Component details
- **Metric Taxonomy:** `docs/development/metrics-taxonomy.md` - Canonical metric definitions
- **Quality Model:** `docs/development/quality-model.md` - Quality scoring framework

---

**Last Updated:** 2025-12-09
**Version:** 2.0
**Status:** Production Schema
