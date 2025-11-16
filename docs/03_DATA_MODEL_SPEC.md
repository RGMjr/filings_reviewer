# 03_DATA_MODEL_SPEC

Version: 0.1  
Date: 2025-11-15  
Owner: Rob Markey  

## 1. Purpose

This document specifies the **logical data model** for the Customer Metrics Filings Analysis project.

It defines:

- Core entities and tables  
- Keys and relationships  
- Field names, types, and constraints  
- How provenance, quality, and alignment are represented

This schema must:

- Support all analytic needs in `01_ANALYTIC_REQUIREMENTS.md`  
- Use the canonical metric IDs and concepts from `02_METRIC_TAXONOMY_AND_DEFINITIONS.md`  
- Be extensible to Phase 2 (10-Ks and beyond)

Implementation details (e.g., exact SQL DDL, indices) can evolve, but **table grains and keys are contractually stable**.

---

## 2. Design principles

1. **Provenance-first**  
   - Every metric value, definition, and quality score must be traceable back to specific segments in specific filings.

2. **Analysis-first grain**  
   - Tables are designed around the units of analysis in `01_ANALYTIC_REQUIREMENTS.md`:
     - Filing  
     - Filing × metric  
     - Filing × metric × period × cohort × segment  
     - Filing × source segment  

3. **Normalized but practical**  
   - Avoid excessive normalization that makes queries painful.  
   - Accept denormalization for common joins (e.g., keep basic filing metadata on fact tables).

4. **Metric taxonomy alignment**  
   - All metrics use canonical IDs from the taxonomy document.  
   - Mapping from issuer-defined labels to canonical IDs is explicit and stored.

5. **Extensibility**  
   - Schema must accommodate new metrics, filings types, and industries without breaking existing tables.

6. **Postgres-oriented**  
   - Assume a relational DB (Postgres).  
   - Types below are “logical” but aligned with Postgres (e.g., `text`, `numeric`, `timestamptz`, `jsonb`).

---

## 3. Entity overview

Core tables:

1. `companies` – Issuer-level metadata  
2. `filings` – Individual SEC filings  
3. `source_segments` – Segmented units of each filing (paragraphs, tables, footnotes, etc.)  
4. `metrics` – Dimension table of canonical metrics (from taxonomy)  
5. `metric_values` – Extracted numeric metric values (fact table)  
6. `filing_metric_incidence` – Filing × metric incidence and quality scores  
7. `metric_definitions` – Metric definitions and methodologies per filing  

Optional / future:

- `industries` – Industry classification reference  
- `qa_issues` – Detailed QA logs if needed later  

---

## 4. Table specifications

### 4.1 `companies`

**Grain:** One row per issuer (company).

**Purpose:** Central reference for issuer metadata; allows multiple filings per company.

**Fields:**

- `company_id` (PK, `bigserial`) – Internal surrogate key  
- `cik` (`text`, unique, not null) – SEC Central Index Key  
- `company_name` (`text`, not null) – Official issuer name  
- `ticker` (`text`, nullable) – Primary listed ticker (if known)  
- `country_of_domicile` (`text`, nullable)  
- `industry_code` (`text`, nullable) – SIC, GICS, or internal code  
- `industry_classification_source` (`text`, nullable) – e.g., `sic`, `gics`, `manual`  
- `created_at` (`timestamptz`, default now)  
- `updated_at` (`timestamptz`, default now)

**Notes:**

- `cik` is the main join key to filings and external data.  
- Future: additional identifiers (ISIN, LEI) can be added.

---

### 4.2 `filings`

**Grain:** One row per SEC filing document in scope.

**Purpose:** Represent each S-1 (and later 10-K) with classification flags and links to companies.

**Fields:**

- `filing_id` (PK, `bigserial`) – Internal surrogate key  
- `company_id` (FK → `companies.company_id`, not null)  
- `cik` (`text`, not null) – Denormalized for easier joins, must match `companies.cik`  
- `accession_number` (`text`, not null) – SEC accession  
- `form_type` (`text`, not null) – e.g., `S-1`, `S-1/A`, `10-K` (Phase 2)  
- `filing_date` (`date`, not null) – Filing date  
- `period_end_date` (`date`, nullable) – Period of report / fiscal year-end  
- `sec_html_url` (`text`, not null) – Canonical HTML URL  
- `sec_txt_url` (`text`, nullable) – Raw text URL (optional)  

**Classification flags (Phase 1):**

- `is_in_scope_phase1` (`boolean`, not null, default false) – In S-1 first-time issuer universe  
- `is_first_time_issuer` (`boolean`, nullable) – Classified by logic / manual review  
- `is_spac` (`boolean`, nullable)  
- `offering_type` (`text`, nullable) – e.g., `primary`, `secondary`, `mixed`  
- `classification_method` (`text`, nullable) – e.g., `heuristic`, `manual_review`  

**Meta:**

- `processing_status` (`text`, not null, default `pending`) – e.g., `pending`, `processed`, `failed`  
- `processing_notes` (`text`, nullable)  
- `created_at` (`timestamptz`, default now)  
- `updated_at` (`timestamptz`, default now)

**Notes:**

- Phase 1 scope is defined primarily by `form_type` + `is_in_scope_phase1`.  
- Phase 2 can reuse this table for 10-Ks with `is_in_scope_phase2` if needed.

---

### 4.3 `source_segments`

**Grain:** One row per **segment** of a filing (paragraph, table, footnote, etc.).

**Purpose:** Provide the audit trail and anchor for all extracted metrics and definitions.

**Fields:**

- `source_segment_id` (PK, `bigserial`) – Internal surrogate key  
- `filing_id` (FK → `filings.filing_id`, not null)  

**Segment metadata:**

- `segment_type` (`text`, not null) – Enum-like: `paragraph`, `table`, `footnote`, `definition_block`, `methodology_block`, `other`  
- `section_path` (`text`, nullable) – Logical item path, e.g., `"Item 1. Business > Customers"`  
- `section_heading` (`text`, nullable) – Human-readable heading text  
- `sequence_index` (`integer`, not null) – Order of segment within the filing (0-based or 1-based)  

**Location / provenance:**

- `html_selector` (`text`, nullable) – XPath, CSS selector, or internal pointer  
- `char_start_offset` (`integer`, nullable) – Start character index in normalized filing text  
- `char_end_offset` (`integer`, nullable) – End character index  
- `page_number` (`integer`, nullable) – If mapped to PDF pages  

**Content:**

- `raw_text` (`text`, not null) – Normalized visible text  
- `raw_html` (`text`, nullable) – Original HTML snippet (optional; can be large)  

**LLM / classification metadata:**

- `candidate_metric_ids` (`text[]`, nullable) – List of possible metric IDs mentioned (from classifier)  
- `contains_definition_flag` (`boolean`, not null, default false)  
- `contains_methodology_flag` (`boolean`, not null, default false)  
- `contains_numeric_disclosure_flag` (`boolean`, not null, default false)  
- `classifier_confidence` (`numeric`, nullable) – 0–1  

**Meta:**

- `created_at` (`timestamptz`, default now)  
- `updated_at` (`timestamptz`, default now)

**Notes:**

- All downstream tables reference `source_segment_id` for traceability.  
- `segment_type` and flags can be refined progressively.

---

### 4.4 `metrics`

**Grain:** One row per **canonical metric ID** in the taxonomy.

**Purpose:** Dimension table for metrics; ties DB to `02_METRIC_TAXONOMY_AND_DEFINITIONS.md`.

**Fields:**

- `metric_id` (PK, `text`) – Canonical ID, e.g., `cm_new_customers_acquired`  
- `display_name` (`text`, not null) – Human-readable label  
- `metric_class` (`text`, not null) – `core`, `extended`, `future`  
- `description` (`text`, nullable) – Short description  
- `primary_concept` (`text`, nullable) – e.g., `acquisition`, `cohort_revenue`  
- `status` (`text`, not null, default `active`) – `active`, `deprecated`, `experimental`  
- `version` (`integer`, not null, default 1) – Metric definition version  
- `created_at` (`timestamptz`, default now)  
- `updated_at` (`timestamptz`, default now)

**Notes:**

- Any change to metric definition that affects comparability should increment `version`.  
- This table is typically seeded from the taxonomy doc.

---

### 4.5 `metric_values`

**Grain:** One row per **filing × metric × period × cohort × segment (optional)** value.

**Purpose:** Main fact table for quantitative analysis of disclosed metrics.

**Fields:**

- `metric_value_id` (PK, `bigserial`) – Internal surrogate key  
- `filing_id` (FK → `filings.filing_id`, not null)  
- `company_id` (FK → `companies.company_id`, not null) – Denormalized for convenience  
- `metric_id` (FK → `metrics.metric_id`, not null)  

**Provenance:**

- `source_segment_id` (FK → `source_segments.source_segment_id`, not null)  
- `source_type` (`text`, not null) – `table`, `text`, `footnote`, `other`  
- `extraction_method` (`text`, not null) – e.g., `rule_table`, `llm_table`, `llm_text`, `manual_review`  

**Value:**

- `value_numeric` (`numeric`, nullable) – Primary numeric value  
- `value_text` (`text`, nullable) – If value is not purely numeric, or for safety copies  
- `unit` (`text`, nullable) – E.g., `count`, `%`, `usd`, `basis_points`, `per_customer`  
- `currency` (`text`, nullable) – ISO code when monetary  

**Time dimensions:**

- `period_start` (`date`, nullable)  
- `period_end` (`date`, nullable)  
- `period_type` (`text`, nullable) – `fy`, `quarter`, `month`, `ttm`, `since_inception`, etc.  

**Cohort dimensions:**

- `cohort_type` (`text`, nullable) – `acquisition`, `tenure`, `other`  
- `cohort_bucket_raw` (`text`, nullable) – Issuer’s label, e.g., `"2021 Cohort"`, `"0–1 years"`  
- `cohort_bucket_normalized` (`text`, nullable) – Normalized form if we standardize buckets  

**Customer segmentation dimensions (optional):**

- `segment_dimension` (`text`, nullable) – e.g., `customer_type`, `product`, `geography`  
- `segment_value` (`text`, nullable) – e.g., `enterprise`, `SMB`, `US`  

**Quality / alignment:**

- `qa_status` (`text`, not null, default `unreviewed`) – `unreviewed`, `pass`, `warning`, `fail`  
- `qa_notes` (`text`, nullable)  
- `alignment_flag` (`text`, nullable) – `aligned`, `partial`, `not_aligned` (w.r.t canonical def)  

**Meta:**

- `created_at` (`timestamptz`, default now)  
- `updated_at` (`timestamptz`, default now)

**Notes:**

- Multiple rows for the same filing-metric-period-cohort are allowed if they have different segments or segment dimensions.  
- Any “canonical” roll-up (e.g., one value per filing-metric-period) should be implemented as a **view**, not by deduping records.

---

### 4.6 `filing_metric_incidence`

**Grain:** One row per **filing × metric**.

**Purpose:** Support incidence and quality analyses at the filing-metric level.

**Fields:**

- `filing_metric_incidence_id` (PK, `bigserial`)  
- `filing_id` (FK → `filings.filing_id`, not null)  
- `company_id` (FK → `companies.company_id`, not null)  
- `metric_id` (FK → `metrics.metric_id`, not null)  

**Incidence:**

- `metric_disclosed_flag` (`boolean`, not null) – True if **any** metric_values or definition/methodology segments are present  
- `num_numeric_segments` (`integer`, not null, default 0) – Count of distinct segments with numeric disclosures  
- `num_definition_segments` (`integer`, not null, default 0) – Segments that contain definitions  
- `num_methodology_segments` (`integer`, not null, default 0)  

**Primary segments:**

- `primary_definition_segment_id` (FK → `source_segments.source_segment_id`, nullable)  
- `primary_methodology_segment_id` (FK → `source_segments.source_segment_id`, nullable)  

**Quality scores (LLM- or human-derived):**

- `quality_overall_score` (`integer`, nullable) – e.g., 0–3 or 0–5, to be defined in QA doc  
- `quality_definition_score` (`integer`, nullable)  
- `quality_methodology_score` (`integer`, nullable)  
- `quality_completeness_score` (`integer`, nullable)  
- `quality_comparability_score` (`integer`, nullable)  

**Notes and flags:**

- `quality_notes` (`text`, nullable)  
- `has_cohort_breakdown_flag` (`boolean`, not null, default false)  
- `has_tenure_breakdown_flag` (`boolean`, not null, default false)  
- `has_acquisition_cohort_flag` (`boolean`, not null, default false)  

**Meta:**

- `created_at` (`timestamptz`, default now)  
- `updated_at` (`timestamptz`, default now)

**Constraints:**

- Unique constraint on (`filing_id`, `metric_id`) – one row per filing-metric pair.

---

### 4.7 `metric_definitions`

**Grain:** One row per **filing × metric × definition_version_in_filing**.

**Purpose:** Capture issuer-specific definitions and calculation methodology text, plus alignment to canonical standards.

**Fields:**

- `metric_definition_id` (PK, `bigserial`)  
- `filing_id` (FK → `filings.filing_id`, not null)  
- `company_id` (FK → `companies.company_id`, not null)  
- `metric_id` (FK → `metrics.metric_id`, not null)  
- `definition_version_in_filing` (`integer`, not null, default 1) – If they revise definition over time within the same filing (rare, but possible)  

**Content:**

- `definition_text_normalized` (`text`, nullable) – Cleaned summary of definition  
- `methodology_text_normalized` (`text`, nullable) – Cleaned summary of calculation method  
- `definition_raw_text` (`text`, nullable) – Raw extracted text snippet (can be truncated)  
- `methodology_raw_text` (`text`, nullable)  

**Provenance:**

- `definition_segment_id` (FK → `source_segments.source_segment_id`, nullable)  
- `methodology_segment_id` (FK → `source_segments.source_segment_id`, nullable)  

**Alignment:**

- `alignment_flag` (`text`, nullable) – `aligned`, `partial`, `not_aligned`, `unknown`  
- `alignment_notes` (`text`, nullable)  

**Meta:**

- `created_at` (`timestamptz`, default now)  
- `updated_at` (`timestamptz`, default now)

**Notes:**

- Multiple definition rows per filing-metric are allowed if different versions appear (e.g., inconsistent wording across sections).  
- `filing_metric_incidence` can reference the “primary” definition via `primary_definition_segment_id`.

---

## 5. Relationships summary

Core relationships:

- `companies` 1–N `filings`  
- `filings` 1–N `source_segments`  
- `metrics` 1–N `metric_values` (via `metric_id`)  
- `filings` 1–N `metric_values`  
- `filings` 1–N `filing_metric_incidence`  
- `filings` 1–N `metric_definitions`  
- `source_segments` 1–N `metric_values`  
- `source_segments` 1–N `metric_definitions`  

Conceptually:

- `source_segments` are the **atomic source units**.  
- `metric_values` and `metric_definitions` are **facts** derived from segments.  
- `filing_metric_incidence` summarizes at the filing-metric level.

---

## 6. Analysis-ready views (logical)

These are logical views to be implemented in SQL later.

### 6.1 `v_filing_metric_incidence`

Joins:

- `filings`  
- `companies`  
- `filing_metric_incidence`  
- `metrics`

Purpose:

- Support incidence and quality queries by year, industry, form type, etc.

Key columns:

- Filing metadata (company name, CIK, filing date, form type, industry)  
- Metric metadata (metric_id, display_name, metric_class)  
- Incidence and quality fields

### 6.2 `v_metric_values_cohort`

Joins:

- `metric_values`  
- `filings`  
- `companies`  
- `metrics`

Purpose:

- Cohort analysis of disclosed metrics (e.g., revenue by cohort, customers by tenure).

Key columns:

- Company, filing, metric  
- Period and cohort fields  
- Segment dimensions  
- QA and alignment flags

### 6.3 `v_metric_definitions`

Joins:

- `metric_definitions`  
- `filings`  
- `companies`  
- `metrics`

Purpose:

- Comparability analysis of definitions and methodologies across firms.

---

## 7. Open questions

To finalize v1.0 of the schema:

1. **Industry classification approach**  
   - Do we maintain an `industries` reference table, or simply store codes on `companies`?  

2. **Canonical tenure bucket normalization**  
   - Do we define a standard set of tenure buckets now (`0–1`, `1–2`, `2–3`, `3–5`, `5+` years) and store mapping rules in `cohort_bucket_normalized`?  

3. **ARR/MRR vs GAAP revenue representation**  
   - Do we need a field on `metric_values` to distinguish GAAP vs non-GAAP revenue sources?  

4. **Granularity of QA logging**  
   - Is `qa_status` + `qa_notes` sufficient, or do we need a separate `qa_issues` table with one row per check (rule/LLM) per metric_value?  

5. **Handling re-stated filings**  
   - How do we represent amended filings (`S-1/A`) where metric disclosures differ materially from the original S-1?

These will be specified in more detail as we write:

- `04_SYSTEM_ARCHITECTURE.md`  
- `05_COMPONENT_INTERFACE_SPECS.md`  
- `06_QA_AND_QUALITY_MODEL.md`  

---

## 8. Appendices

### 8.1 Example ID conventions

- `*_id` fields are surrogate keys (`bigserial`) except:
  - `metrics.metric_id` which is a semantic key (string)  
- External IDs:
  - `cik`, `accession_number` used for aligning with EDGAR  

### 8.2 Example Postgres DDL (sketch)

> Note: This is illustrative only. Final DDL may differ.

```sql
CREATE TABLE companies (
  company_id BIGSERIAL PRIMARY KEY,
  cik TEXT NOT NULL UNIQUE,
  company_name TEXT NOT NULL,
  ticker TEXT,
  country_of_domicile TEXT,
  industry_code TEXT,
  industry_classification_source TEXT,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE filings (
  filing_id BIGSERIAL PRIMARY KEY,
  company_id BIGINT NOT NULL REFERENCES companies(company_id),
  cik TEXT NOT NULL,
  accession_number TEXT NOT NULL,
  form_type TEXT NOT NULL,
  filing_date DATE NOT NULL,
  period_end_date DATE,
  sec_html_url TEXT NOT NULL,
  sec_txt_url TEXT,
  is_in_scope_phase1 BOOLEAN NOT NULL DEFAULT FALSE,
  is_first_time_issuer BOOLEAN,
  is_spac BOOLEAN,
  offering_type TEXT,
  classification_method TEXT,
  processing_status TEXT NOT NULL DEFAULT 'pending',
  processing_notes TEXT,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);