# 01_ANALYTIC_REQUIREMENTS

Version: 0.3
Date: 2026-03-11
Owner: Rob Markey

## 1. Purpose and context

This document defines the analytic requirements for Phase 1 of the Customer Metrics Filings Analysis project.

The project’s purpose is to:

- Assess how often and how well companies already disclose decision-useful customer metrics in SEC filings  
- Demonstrate the need for standardized customer metrics disclosure (CMASB)  
- Identify best-practice examples and gaps by industry and over time  

Phase 1 focuses on S-1 registration statements for first-time issuers of public equity. Later phases will extend to 10-K and other filings.

This document is the primary input to:

- `docs/development/metrics-taxonomy.md`
- `docs/architecture/data-model.md`
- `docs/architecture/system-overview.md`

All system and data design choices must support the analytic needs defined here.

---

## 2. Scope of Phase 1

### 2.1 Time period

- Coverage period: **2015-01-01 through 2025-12-31** (filing date)  

### 2.2 Filing universe

Include:

- All **S-1 registration statements** for companies **issuing public equity for the first time** within the coverage period
- **F-1 registration statements** for **foreign private issuers** (FPIs) issuing public equity for the first time — same customer metric disclosure patterns apply; examples include Farfetch Limited (2018), PropertyGuru Group (2021)

Exclude:

- SPACs and SPAC-like vehicles
- Registration statements that are **purely secondary offerings** (no new capital raised by the company)
- Amendments that do not materially change customer metric disclosures, unless needed to capture the first appearance of such metrics

The system must:

- Maintain an explicit classification for:
  - `is_first_time_issuer`  
  - `is_spac`  
  - `offering_type` (primary / secondary / mixed)  
- Preserve enough metadata and rationale to audit inclusion/exclusion decisions

### 2.3 Document types and sections

For each included S-1, Phase 1 analysis should consider:

- Entire primary S-1 filing (HTML)  
- All sections where customer metrics are likely to appear, including:
  - Prospectus summary  
  - Risk factors  
  - Selected financial data / key metrics sections  
  - MD&A  
  - Business  
  - Footnotes and tables in any of the above  

The system must not rely solely on a single “key metrics” section.

---

## 3. Users and decisions supported

Primary users:

- Rob Markey and CMASB collaborators  
- Potential advisors and funders  
- Academic and practitioner partners

Decisions to support:

- Whether there is sufficient real-world precedent to justify formal customer metrics disclosure standards  
- Which industries and filing types provide the strongest early exemplars  
- How to scope and prioritize CMASB standards (metrics, definitions, and guidance)  
- Where disclosure is absent or weak, for advocacy and case-making

---

## 4. Research questions and hypotheses

### 4.1 Core research questions (Phase 1)

1. **Incidence**  
   - How frequently do S-1 filings disclose each of the proposed core customer metrics?  
   - How many filings disclose none, some, or most of the core metrics?

2. **Quality**  
   - When metrics are disclosed, how clear and decision-useful are:
     - The metric definitions  
     - The calculation methodologies  
     - The completeness of time series and segmentation  
   - How aligned are disclosures to the emerging CMASB conceptual definitions?

3. **Trends over time**  
   - Has the incidence and quality of disclosure improved from 2015 to 2025?

4. **Industry patterns**  
   - Which industries are more likely to disclose decision-useful customer metrics?  
   - Are there distinct disclosure “styles” by industry?

5. **Other customer metrics**  
   - Beyond the proposed CMASB metrics, what other customer-related metrics are commonly disclosed (e.g., MAUs, ARPU, NRR)?

### 4.2 Phase 1 hypotheses (S-1 filings)

From the overview:

1. **Incidence of core metrics**  
   - At least 20% of all S-1 filings disclose **at least 3** of the proposed core metrics  
   - An additional ~15% disclose **1 or 2** of the proposed metrics  

2. **Trend over time**  
   - The incidence of proposed metrics disclosure in S-1 filings has **increased over the last decade**  
   - The **quality** of proposed metrics disclosure has **improved over the last decade**

3. **Industry differences**  
   - Incidence and quality of proposed metrics disclosure are highest in industries such as:
     - Software / SaaS (e.g., Intuit, Figma, Shopify, Medallia)  
     - Subscription media (e.g., Netflix)  
     - Home internet (cable, fixed wireless, fiber, telco: Comcast, Cox, AT&T, T-Mobile, Frontier)  
     - Home broadband television  
     - Home delivery and rideshare (Uber, Instacart, DoorDash)  
     - Investment platforms / brokers (Robinhood, Schwab)  
     - Retail banking  
     - Credit cards (Discover, Amex, Capital One)  
     - Direct-to-consumer retail (The RealReal, CarGurus, Bonobos, Harry’s)

These hypotheses define the minimum analytic capabilities the system must support.

### 4.3 Phase 2 preview (10-K filings) – for planning only

Phase 2 (not in scope to implement now) will extend similar questions and hypotheses to 10-K filings, with expectations that:

- Incidence of proposed metrics in 10-Ks is **lower** than in S-1s  
- Quality and scope of disclosure **decline over time** after IPO for companies that initially disclose  
- Industry patterns broadly mirror those seen in S-1s

Phase 1 design must keep Phase 2 in mind, but deliverables and testing focus on S-1s only.

---

## 5. Metrics and concepts in scope

### 5.1 Core metrics (Phase 1)

Phase 1 focuses on a small set of “Core Metrics” defined in `Proposed Metrics and Definitions_v1.docx`. At minimum, these include:

> Note: Final canonical names and detailed definitions will be maintained in `02_METRIC_TAXONOMY_AND_DEFINITIONS.md`. The list here is conceptual.

Implemented core metrics (canonical IDs defined in `config/metric_keywords.yaml`):

| Canonical ID | Description |
|---|---|
| `cm_new_customers_acquired` | New customers acquired per period |
| `cm_customers_period_end` | Total/paid customer count at period end (stock count) |
| `cm_customers_period_end_by_tenure` | Customers at period end broken down by tenure cohort |
| `cm_revenue_by_cohort` | Revenue attributed to customer acquisition or tenure cohorts |
| `cm_transactions_by_cohort` | Purchase transactions broken down by cohort |
| `cm_purchase_transactions_overall` | Total purchase/order count (no cohort breakdown required) |
| `cm_large_customers_period_end` | Enterprise/large customers above a revenue threshold |

See `02_METRIC_TAXONOMY_AND_DEFINITIONS.md` for full business definitions.

The analytics must:

- Detect whether each core metric is **disclosed** in each filing  
- Capture **numeric values** when disclosed  
- Capture **definitions** and **calculation methodologies** when provided  
- Assess **alignment** of each disclosure with CMASB’s conceptual metric definition

### 5.2 Additional customer metrics

Phase 1 should also record the incidence (yes/no and simple descriptors) of other important customer metrics when they appear, such as:

- Number of active customers / users  
- Monthly or daily active users (MAUs, DAUs)  
- Revenue per active customer / ARPU  
- Retention, churn, NRR/GRR (for Phase 1: incidence and basic extraction only)  
- CAC and payback measures (if available)

Detailed metric definitions and taxonomies for these extended metrics will be secondary to the four core metrics in Phase 1, but the system must be designed to accommodate them.

### 5.3 Core concepts

The analysis and later standards depend on consistent working definitions of:

- Customer  
- Active customer  
- Cohort (e.g., by acquisition period or tenure)  
- Purchase / transaction  
- Retention / churn  
- Revenue (and its link to GAAP figures)  

These will be formalized in `02_METRIC_TAXONOMY_AND_DEFINITIONS.md` and must be referenced in coding, QA, and analysis.

---

## 6. Units of analysis

The system must support multiple analytic grains.

### 6.1 Filing-level

- **Unit**: Filing (S-1)  
- Use cases:
  - Count filings with at least N core metrics disclosed  
  - Track incidence and quality over time and by industry  

### 6.2 Company-level

- **Unit**: Company (CIK / issuer)  
- Use cases:
  - Multiple filings for the same issuer (e.g., S-1/A)  
  - Link Phase 1 (S-1) with Phase 2 (10-K) in future  

### 6.3 Filing–metric level

- **Unit**: Filing × metric  
- Use cases:
  - Incidence of each core metric  
  - Quality scores for each metric in each filing  

### 6.4 Metric-period-cohort level

- **Unit**: Filing × metric × period × cohort × (optional segment)  
- Use cases:
  - Cross-firm comparisons of disclosed values  
  - Construction of cohort tables and charts based on disclosed numbers  

### 6.5 Source segment level

- **Unit**: Filing × source segment (paragraph, table, footnote)  
- Use cases:
  - Audit trails and reproducibility  
  - Understanding how metrics are defined and contextualized in narrative form  

All data models and extraction logic must preserve these grains and enable joins across them.

---

## 7. Required analytic outputs

The system must produce, at minimum, the following logical outputs. Physical implementation (DB tables, CSVs, views) is defined in `docs/architecture/data-model.md`.

### 7.1 Filing-level incidence / quality table

Grain: one row per filing × metric.

Must support:

- Incidence flags:
  - `metric_disclosed_flag` (Y/N)  
  - Count of distinct disclosure segments per metric  
- Quality scores per filing-metric:
  - Overall quality score (e.g., 0–3 or 0–5)  
  - Sub-scores:
    - Definition clarity  
    - Calculation methodology clarity  
    - Completeness (time series, cohorts, segmentation)  
    - Comparability / alignment with CMASB definition  
- Metadata:
  - Filing identifiers (CIK, company name, accession, filing date)  
  - Industry classification  
  - Links to the primary definition/methodology segments  

This table is the primary input to incidence, trend, and industry analyses.

### 7.2 Metric value table

Grain: filing × metric × period × cohort × segment.

Must include:

- Filing identifiers  
- Metric ID  
- Numeric value  
- Units and currency  
- Period start / end and period type (FY, quarter, etc.)  
- Cohort type and cohort bucket (e.g., tenure, signup year)  
- Segment dimension and value (product, geography, customer type, if disclosed)  
- Provenance:
  - Source type: `html_table`, `ocr_table`, `text`, or `chart` (V2 `SourceType` enum)
  - Source locator: XPath-based `dom_locator` (V2 `SourceLocator`)
  - Extraction method: `exact_match`, `alias_match`, `embedding`, `llm`, or `manual` (V2 `ExtractionMethod` enum)
- QA fields:
  - QA status (pass / warning / fail)  
  - QA notes, if any  

This table underpins all quantitative analysis of disclosed metrics.

### 7.3 Definitions and methodology table

Grain: filing × metric × definition version.

Must include:

- Filing and metric identifiers  
- Normalized **definition text**  
- Normalized **calculation methodology text**  
- Source segment IDs for both  
- Alignment flags:
  - Aligned / partial / not aligned with CMASB definition  
- Brief notes explaining any misalignment or ambiguity

This table underpins quality / comparability analyses and supports future standards-setting.

### 7.4 Source segment index

Grain: filing × segment.

Must include:

- Segment ID  
- Filing ID  
- Segment type (paragraph, table, footnote, definition block, methodology block)  
- Section information (e.g., Item path, heading)  
- Location within the document (URL, XPath `dom_locator` via `SourceLocator`; character offsets where available)
- Raw text (and optionally highlighted HTML via `EvidencePack`)
- Detected metric references and roles (definition / numeric / methodology / other)  

This is the core auditability artifact: any metric or quality score must be traceable back to one or more segments in this index.

### 7.5 Analysis-ready views

The system must support, via DB views or reproducible queries:

- Time-series of incidence and quality by year and industry  
- Distribution of “number of core metrics disclosed” per filing  
- Lists of “best exemplar” filings by metric and industry  
- Summary tables for presentations (e.g., % of S-1s disclosing each metric over time)

---

## 8. Quality, auditability, and completeness requirements

### 8.1 Auditability

The dataset must be fully auditable:

- Every metric value, definition, and quality score must be traceable to specific segments in specific filings  
- For any published statistic or chart, it must be possible to:
  - Identify the underlying filings and metrics used  
  - Retrieve the original disclosure language and its location in the filing  

Auditability is **non-negotiable**.

### 8.2 Completeness

For Phase 1, “complete” means:

- All S-1 filings in scope (per Section 2) are either:
  - Successfully processed and represented in the filing-level tables, or  
  - Explicitly listed as failed / excluded with a documented reason  
- For each filing:
  - All apparent disclosures of core metrics are detected and recorded to the best of the system’s ability  
  - Any known limitations (e.g., parsing failures, classification uncertainty) are flagged

### 8.3 Quality targets (initial)

Phase 1 will set **aspirational** (not guaranteed) quality targets:

- Incidence detection for core metrics:
  - Precision: ≥ 90% on labeled sample  
  - Recall: ≥ 80% on labeled sample  
- Metric values:
  - Numerical accuracy: ≥ 95% for clearly tabular disclosures on labeled sample  
- Definitions / methodology:
  - Correct identification of segments containing definitions: ≥ 90% recall on labeled sample  

These targets will be refined in `06_QA_AND_QUALITY_MODEL.md` and validated through a gold-standard labeled set.

---

## 9. Non-functional analytic requirements

### 9.1 Extensibility

The design must:

- Allow addition of new metrics (Phase 2 and beyond) without breaking existing analyses  
- Support extension to 10-Ks and other filings with the same core schema  
- Support revised or expanded metric definitions over time (versioning)

### 9.2 Transparency and explainability

- The system must make it easy to explain:
  - How a metric was detected and extracted  
  - Why a given filing received a particular quality score  
  - Any known limitations or uncertainties in the data  

### 9.3 Reproducibility

- Analytic outputs (tables, charts, statistics) must be reproducible from:
  - The raw data store  
  - The defined transformation logic  
- Any manual interventions (e.g., corrections, overrides) must be recorded and traceable.

---

## 10. Open questions and to-dos

Items resolved during V2 implementation:

- **Final core metric list** — RESOLVED: See Section 5.1 and `02_METRIC_TAXONOMY_AND_DEFINITIONS.md`
- **Quality scoring rubric** — RESOLVED: 0–3 scale per dimension, implemented in `V2QualityScorer`; see `06_QA_AND_QUALITY_MODEL.md`
- **Labeled evaluation set** — RESOLVED: 12-filing gold standard in `data/gold_standard/`; two baselines (text-only, image-enabled)

Remaining open items:

- **Industry classification scheme**: SIC codes used for corpus filtering; GICS mapping deferred to Phase 2 analytics
- **Phase 2 design**: Extension to 10-K filings; schema designed to accommodate but not yet implemented

Cross-references:

- `02_METRIC_TAXONOMY_AND_DEFINITIONS.md` — canonical metric IDs and definitions
- `06_QA_AND_QUALITY_MODEL.md` — quality model and scoring