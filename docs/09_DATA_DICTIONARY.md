# 09_DATA_DICTIONARY

Version: 0.1  
Date: 2025-11-15  
Owner: Rob Markey  

## 1. Purpose

This document defines the **business meaning** of fields used in:

- The filing registry CSV (gold-standard and pilot sets)
- Core relational tables defined in `03_DATA_MODEL_SPEC.md`
- Planned gold-standard label tables (`gs_*`)

It is the **single source of truth** for what each column means, allowed values, and how fields should be interpreted in analysis.

For structural details (keys, relationships, types), see:

- `03_DATA_MODEL_SPEC.md`
- `02_METRIC_TAXONOMY_AND_DEFINITIONS.md`
- `06_QA_AND_QUALITY_MODEL.md`

---

## 2. Conventions

### 2.1 Naming

- Table names: `lower_snake_case` (e.g., `metric_values`).
- Column names: `lower_snake_case`.
- Canonical metric IDs: `cm_` prefix, `lower_snake_case` (e.g., `cm_new_customers_acquired`).

### 2.2 Types (logical)

- `text` – free-form string.
- `integer` – whole-number count.
- `numeric` – decimal number (monetary, ratios, percentages).
- `date` – calendar date (no time zone).
- `timestamptz` – timestamp with time zone.
- `boolean` – `true` / `false`.

### 2.3 Value conventions

- Percentages are stored as **raw percentages** (e.g., 37.5, not 0.375).
- Monetary values are stored in **base currency units** (e.g., USD).
- All dates are ISO-8601 (`YYYY-MM-DD`).

---

## 3. Filing registry CSV

This covers the small **filing registry** CSV used for gold-standard selection and tracking (for example, the 10 initial S-1/F-1 filings).

Suggested file path: `data/filing_registry.csv`.

### 3.1 Columns

| Column | Type | Required | Description |
|--------|------|----------|-------------|
| `company` | text | yes | Issuer name, as shown on the cover of the S-1/F-1 (e.g., "Shopify Inc."). Should match or be easily mappable to `companies.company_name`. |
| `ticker` | text | yes | Stock ticker at or after IPO (e.g., `SHOP`). Use `NULL` or empty if unknown at time of registry creation. |
| `cik` | text | yes | SEC Central Index Key. This is the **primary external join key** to EDGAR and to `companies.cik`. |
| `form_type` | text | yes | SEC form type for the filing (e.g., `S-1`, `F-1`). Should match `filings.form_type`. |
| `filing_date` | date | yes | Date the filing was submitted to the SEC, as shown on EDGAR. Should match `filings.filing_date`. |
| `edgar_html_url` | text | yes | Direct URL to the primary HTML S-1/F-1 document on SEC EDGAR (not the index page). Used as input to the Filing Fetcher. |
| `business_model` | text | yes | Short, human-readable description of the company’s primary business model (e.g., "Cloud infrastructure monitoring and analytics SaaS"). Used for sampling and stratification, not for analysis. |
| `has_tenure_cohorts` | text (enum) | yes | Indicates whether the filing contains **cohort-style disclosures** (e.g., revenue or billings by customer acquisition year or tenure). Allowed values: `yes`, `no`, `unknown`. Initial gold set uses `yes`. |
| `has_customer_count_metrics` | text (enum) | yes | Indicates whether the filing discloses explicit **customer / merchant / active account counts**, including variants such as "active merchants" or "customers > $100k ARR". Allowed values: `yes`, `no`, `unknown`. Initial gold set uses `yes`. |

### 3.2 Usage notes

- This CSV is primarily for **sampling and tracking**, not for direct analytics.
- Each registry row should map unambiguously to a `filings` row using (`cik`, `filing_date`, `form_type`) or an explicit `filing_id` once assigned.

---

## 4. Core relational tables

This section summarizes the business meaning of key fields in the core tables.

For full structural details, see `03_DATA_MODEL_SPEC.md`.

### 4.1 `companies`

Represents each issuer (company).

| Column | Type | Description |
|--------|------|-------------|
| `company_id` | integer (PK) | Internal surrogate key for the company. Used for joins inside our database. |
| `cik` | text | SEC Central Index Key. Primary external identifier and join key to EDGAR. |
| `company_name` | text | Official issuer name as shown in SEC filings. |
| `ticker` | text | Primary listed ticker symbol, if known. |
| `country_of_domicile` | text | Country where the company is legally domiciled (e.g., `United States`, `Canada`). |
| `industry_code` | text | SIC, GICS, or internal industry classification code. |
| `industry_classification_source` | text | Source system or convention for `industry_code` (e.g., `sic`, `gics`, `manual`). |
| `created_at` | timestamptz | Timestamp when this row was created. |
| `updated_at` | timestamptz | Timestamp when this row was last updated. |

### 4.2 `filings`

Represents each SEC filing document in scope.

| Column | Type | Description |
|--------|------|-------------|
| `filing_id` | integer (PK) | Internal surrogate key for the filing. Used as the primary join key throughout the system. |
| `company_id` | integer (FK) | Link to `companies.company_id`. |
| `cik` | text | Denormalized copy of the company CIK for easier joins. Must match `companies.cik`. |
| `accession_number` | text | SEC accession number for the filing. Unique per filing across EDGAR. |
| `form_type` | text | SEC form type (e.g., `S-1`, `F-1`, `S-1/A`, `10-K` in Phase 2). |
| `filing_date` | date | Date the filing was submitted to the SEC. |
| `period_end_date` | date | Period of report / fiscal year-end used in the filing, where available. |
| `sec_html_url` | text | Canonical SEC HTML URL for the filing body. Used as input to ingestion. |
| `sec_txt_url` | text | URL to raw text version of the filing, if used. |
| `is_in_scope_phase1` | boolean | True if the filing is in the Phase 1 universe (S-1/F-1 for first-time issuers; no SPACs or secondary-only offerings). |
| `is_first_time_issuer` | boolean | True if this filing corresponds to the company’s first public equity issuance. May require heuristics or manual review. |
| `is_spac` | boolean | True if the issuer is a SPAC (special purpose acquisition company). Phase 1 excludes these. |
| `offering_type` | text | High-level classification of the offering (e.g., `primary`, `secondary`, `mixed`). |
| `classification_method` | text | How `is_first_time_issuer`, `is_spac`, and `offering_type` were determined (e.g., `heuristic`, `manual_review`, `uncertain`). |
| `processing_status` | text | Current processing state of the filing in our pipeline (e.g., `pending`, `fetched`, `processed`, `fetch_failed`, `normalize_failed`, `segment_failed`, `load_failed`). |
| `processing_notes` | text | Free-text notes about errors or special handling for this filing. |
| `created_at` | timestamptz | Timestamp when this row was created. |
| `updated_at` | timestamptz | Timestamp when this row was last updated. |

### 4.3 `source_segments`

Represents atomic segments (paragraphs, tables, footnotes) of each filing used for extraction and audit.

| Column | Type | Description |
|--------|------|-------------|
| `source_segment_id` | integer (PK) | Internal surrogate key for the segment. |
| `filing_id` | integer (FK) | Link to `filings.filing_id`. |
| `segment_type` | text | Type of segment: `paragraph`, `table`, `footnote`, `definition_block`, `methodology_block`, `other`. |
| `section_path` | text | Logical path within the filing (e.g., `Item 1. Business > Customers`). Not guaranteed unique. |
| `section_heading` | text | Heading text associated with the segment’s section. |
| `sequence_index` | integer | Ordering of the segment within the filing (0- or 1-based; consistent within a run). |
| `html_selector` | text | XPath/CSS selector or other pointer into the HTML, for precise location. Optional but preferred. |
| `char_start_offset` | integer | Start character index in the normalized filing text. Used for precise audit. |
| `char_end_offset` | integer | End character index in the normalized filing text. |
| `page_number` | integer | Page number in the PDF, if available. Optional. |
| `raw_text` | text | Normalized plain text for the segment (visible content only). |
| `raw_html` | text | Original HTML snippet for the segment, if stored. May be large. |
| `candidate_metric_ids` | text[] | List of `metric_id` values the classifier believes may be present in this segment. Used to target extraction. |
| `contains_definition_flag` | boolean | True if the segment likely contains metric definitions. |
| `contains_methodology_flag` | boolean | True if the segment likely describes how metrics are calculated. |
| `contains_numeric_disclosure_flag` | boolean | True if the segment likely contains numeric values relevant to metrics. |
| `classifier_confidence` | numeric | Confidence score (0–1) of the classification for this segment. |
| `created_at` | timestamptz | Timestamp when this row was created. |
| `updated_at` | timestamptz | Timestamp when this row was last updated. |

### 4.4 `metrics`

Dimension table for canonical metric IDs.

| Column | Type | Description |
|--------|------|-------------|
| `metric_id` | text (PK) | Canonical ID from the taxonomy (e.g., `cm_new_customers_acquired`). |
| `display_name` | text | Human-readable label for the metric. |
| `metric_class` | text | Bucket: `core`, `extended`, or `future` (Phase 2+). |
| `description` | text | Short description of the metric’s meaning. |
| `primary_concept` | text | Main concept the metric captures (e.g., `acquisition`, `cohort_revenue`). |
| `status` | text | Lifecycle status: `active`, `deprecated`, `experimental`. |
| `version` | integer | Metric definition version. Increment when the definition changes in a way that affects comparability. |
| `created_at` | timestamptz | Timestamp when this row was created. |
| `updated_at` | timestamptz | Timestamp when this row was last updated. |

### 4.5 `metric_values`

Fact table for numeric metric values extracted from filings.

| Column | Type | Description |
|--------|------|-------------|
| `metric_value_id` | integer (PK) | Internal surrogate key for the metric value. |
| `filing_id` | integer (FK) | Link to `filings.filing_id`. |
| `company_id` | integer (FK) | Link to `companies.company_id`. Denormalized for convenience. |
| `metric_id` | text (FK) | Canonical metric ID from `metrics.metric_id`. |
| `source_segment_id` | integer (FK) | Link to `source_segments.source_segment_id` indicating where this value was found. |
| `source_type` | text | Source of the metric: `table`, `text`, `footnote`, `other`. |
| `extraction_method` | text | How the value was extracted: `rule_table`, `llm_table`, `llm_text`, `manual_review`, etc. |
| `value_numeric` | numeric | The numeric value of the metric, in base units (not scaled). |
| `value_text` | text | Original textual representation of the value (e.g., "37.5%", "$1.2 billion"), if captured. |
| `unit` | text | Unit of the value (e.g., `count`, `%`, `usd`, `basis_points`, `per_customer`). |
| `currency` | text | ISO currency code for monetary metrics (e.g., `USD`), if available. |
| `period_start` | date | Start date of the period the metric covers, if applicable. |
| `period_end` | date | End date of the period the metric covers, if applicable. |
| `period_type` | text | Type of period (e.g., `fy`, `quarter`, `month`, `ttm`, `since_inception`). |
| `cohort_type` | text | Type of cohort used: `acquisition`, `tenure`, or `other`. |
| `cohort_bucket_raw` | text | Issuer’s own label for the cohort (e.g., `2019 Cohort`, `0–1 years`). |
| `cohort_bucket_normalized` | text | Normalized cohort label where we standardize buckets (e.g., `0-1_years_tenure`). Optional. |
| `segment_dimension` | text | Dimension along which the metric is further segmented (e.g., `customer_type`, `product`, `geography`). Optional. |
| `segment_value` | text | Specific segment value (e.g., `enterprise`, `SMB`, `US`). Optional. |
| `qa_status` | text | QA state for this value: `unreviewed`, `pass`, `warning`, `fail` (see `06_QA_AND_QUALITY_MODEL.md`). |
| `qa_notes` | text | Free-text notes about QA checks or manual corrections. |
| `alignment_flag` | text | Optional alignment classification for this specific value: `aligned`, `partial`, `not_aligned`, `unknown`. Typically used at the definition/incidence level; per-value alignment is optional. |
| `created_at` | timestamptz | Timestamp when this row was created. |
| `updated_at` | timestamptz | Timestamp when this row was last updated. |

### 4.6 `filing_metric_incidence`

Summary table at the **filing × metric** level, including incidence and quality scores.

| Column | Type | Description |
|--------|------|-------------|
| `filing_metric_incidence_id` | integer (PK) | Internal surrogate key for the filing–metric pair. |
| `filing_id` | integer (FK) | Link to `filings.filing_id`. |
| `company_id` | integer (FK) | Link to `companies.company_id`. |
| `metric_id` | text (FK) | Canonical metric ID from `metrics.metric_id`. |
| `metric_disclosed_flag` | boolean | True if the filing discloses this metric in any segment (numeric value or explicit definition). False otherwise. |
| `num_numeric_segments` | integer | Number of distinct `source_segments` that contain numeric values for this metric. |
| `num_definition_segments` | integer | Number of distinct segments that contain definitions for this metric. |
| `num_methodology_segments` | integer | Number of distinct segments that describe methodology for this metric. |
| `primary_definition_segment_id` | integer (FK) | Segment chosen as the primary definition location for this metric in this filing. Optional. |
| `primary_methodology_segment_id` | integer (FK) | Segment chosen as the primary methodology location for this metric in this filing. Optional. |
| `quality_overall_score` | integer | Overall quality score (0–3) for this metric in this filing. Higher is better. |
| `quality_definition_score` | integer | Score (0–3) capturing quality of the definition text (clarity, specificity). |
| `quality_methodology_score` | integer | Score (0–3) capturing quality of methodology disclosure. |
| `quality_completeness_score` | integer | Score (0–3) capturing how complete the disclosure is (coverage of cohorts, periods, etc.). |
| `quality_comparability_score` | integer | Score (0–3) capturing how comparable this disclosure is to other issuers (e.g., adherence to canonical definitions). |
- `alignment_flag` (`text`, nullable) – Summary alignment classification at the filing–metric level: `aligned`, `partial`, `not_aligned`, `unknown`.
| `quality_notes` | text | Free-text notes about quality, context, or anomalies for this filing–metric pair. |
| `has_cohort_breakdown_flag` | boolean | True if the metric is disclosed with any customer cohort breakdown in this filing. |
| `has_tenure_breakdown_flag` | boolean | True if the metric is disclosed with a **tenure** cohort breakdown. |
| `has_acquisition_cohort_flag` | boolean | True if the metric is disclosed with **acquisition-year** cohort breakdowns. |
| `created_at` | timestamptz | Timestamp when this row was created. |
| `updated_at` | timestamptz | Timestamp when this row was last updated. |

### 4.7 `metric_definitions`

Captures issuer-specific metric definitions and methodologies.

| Column | Type | Description |
|--------|------|-------------|
| `metric_definition_id` | integer (PK) | Internal surrogate key for the metric definition record. |
| `filing_id` | integer (FK) | Link to `filings.filing_id`. |
| `company_id` | integer (FK) | Link to `companies.company_id`. |
| `metric_id` | text (FK) | Canonical metric ID from `metrics.metric_id`. |
| `definition_version_in_filing` | integer | Version counter in case multiple, distinct definitions for the same metric appear in one filing. Usually 1. |
| `definition_text_normalized` | text | Cleaned, normalized summary of the issuer’s definition for this metric. Used for comparability assessment. |
| `methodology_text_normalized` | text | Cleaned summary of how the issuer calculates the metric (inputs, inclusions/exclusions). |
| `definition_raw_text` | text | Raw text span extracted from the filing containing the definition (may include legal language). |
| `methodology_raw_text` | text | Raw text span containing methodology details. |
| `definition_segment_id` | integer (FK) | Segment containing the main definition. |
| `methodology_segment_id` | integer (FK) | Segment containing the main methodology text. |
| `alignment_flag` | text | Alignment classification of this definition vs canonical standard: `aligned`, `partial`, `not_aligned`, `unknown`. |
| `alignment_notes` | text | Free-text notes explaining why alignment was scored as it was. |
| `created_at` | timestamptz | Timestamp when this row was created. |
| `updated_at` | timestamptz | Timestamp when this row was last updated. |

---

## 5. Gold-standard label tables (`gs_*`)

Gold-standard tables hold **human-labeled reference data** for evaluation and testing. They are not part of the production schema but must follow consistent definitions.

Names are indicative; exact naming may vary (`gs_filing_metric_incidence`, `gs_metric_values`, `gs_metric_definitions`).

### 5.1 `gs_filing_metric_incidence`

Per filing–metric labels for incidence and alignment.

Key columns:

- `filing_id` – as in production.
- `metric_id` – canonical ID.
- `true_disclosed_flag` – human judgment on whether the filing actually discloses this metric.
- `true_alignment_flag` – human-labeled alignment (`aligned`, `partial`, `not_aligned`, `unknown`).
- `label_notes` – explanation of ambiguous cases.

### 5.2 `gs_metric_values`

Per metric value labels, used to assess numeric accuracy.

Key columns:

- `filing_id`, `metric_id` – as in production.
- `value_numeric_true` – true numeric value.
- `unit_true`, `currency_true` – true unit and currency.
- `period_start_true`, `period_end_true`, `period_type_true` – true period details.
- `cohort_type_true`, `cohort_bucket_true` – true cohort details.
- `source_type_true` – `table` or `text` (where the human took the label from).

### 5.3 `gs_metric_definitions`

Per filing–metric definitions and methodology labels.

Key columns:

- `filing_id`, `metric_id` – as in production.
- `definition_raw_text_true` – human-captured raw definition segments.
- `methodology_raw_text_true` – human-captured raw methodology segments.
- `definition_summary_true` – human-written normalized definition summary.
- `alignment_true` – human-labeled alignment category.

---

## 6. QA-related fields and values

Certain fields have **controlled vocabularies** defined in `06_QA_AND_QUALITY_MODEL.md`. This section centralizes them.

### 6.1 `metric_values.qa_status`

Allowed values:

- `unreviewed` – Default after extraction; QA checks not yet applied.
- `pass` – Passed all relevant rule-based checks.
- `warning` – Value is plausible but some checks failed or uncertainty is high.
- `fail` – Value is likely wrong or inconsistent.

### 6.2 `alignment_flag`

Used in:

- `metric_values` (optional per value)
- `metric_definitions`
- `filing_metric_incidence` (summary; preferred for analysis)

Allowed values:

- `aligned`
- `partial`
- `not_aligned`
- `unknown`

### 6.3 Quality scores (0–3)

Used in `filing_metric_incidence`:

- `quality_overall_score`
- `quality_definition_score`
- `quality_methodology_score`
- `quality_completeness_score`
- `quality_comparability_score`

Interpretation:

- `3` – Strong disclosure.
- `2` – Adequate disclosure.
- `1` – Weak or incomplete disclosure.
- `0` – No usable disclosure.

---

## 7. Change management

- Any changes to field meanings or allowed values in this document must be:
  - Reflected in `03_DATA_MODEL_SPEC.md` and vice versa.
  - Evaluated for impact on existing data and tests.
- When a change affects comparability or QA logic, update:
  - `06_QA_AND_QUALITY_MODEL.md`
  - `07_TEST_STRATEGY_AND_FIX_PROCESS.md`
