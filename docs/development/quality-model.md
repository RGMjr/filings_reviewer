

# 06_QA_AND_QUALITY_MODEL

Version: 0.1  
Date: 2025-11-15  
Owner: Rob Markey  

## 1. Purpose

This document defines the **quality model** for the CMASB Disclosures Review system.

It answers four questions:

1. What does "good" look like for this dataset?
2. Which quality dimensions do we care about and how do we define them?
3. What numeric quality targets are we aiming for in Phase 1?
4. When do we require manual review vs accepting automated output?

`docs/development/testing.md` will describe **how** we measure and enforce this model (gold standards, tests, and defect process).

---

## 2. Quality philosophy

We are not trying to build a perfect, fully automated system.

We are trying to build a system that:

- Produces **defensible, auditable data** for incidence and quality analyses
- Is transparent about its limitations and uncertainties
- Can be improved iteratively without losing trust

Where automation is fragile, we prefer:

- Clear QA flags and manual review paths over silent failure
- Conservative interpretations over optimistic ones

---

## 3. Quality dimensions

We evaluate quality along six dimensions.

1. **Coverage & completeness**  
   Are all in-scope filings represented, and is the segment universe rich enough to find disclosures?

2. **Incidence detection quality**  
   Do we correctly detect whether a metric is disclosed in a filing?

3. **Numeric extraction accuracy**  
   Are extracted metric values correct and appropriately structured (periods, cohorts, segments)?

4. **Definition & methodology quality**  
   Do we accurately capture and summarize how issuers define and calculate metrics?

5. **Comparability / alignment**  
   Can we reliably judge how closely issuer metrics match canonical CMASB definitions?

6. **Provenance & traceability**  
   Can we always trace results back to precise locations in filings?

Each dimension has:

- A **definition**
- A **unit of measurement**
- Phase 1 **targets** (Pilot and Full-run)
- Thresholds for **manual review** or **blockers**

---

## 4. Coverage & completeness

### 4.1 Definition

Coverage & completeness measures whether:

- All **in-scope filings** are present in the database with a clear status
- For each filing, the **segment universe** is rich enough that a human reviewer would expect we could find metric disclosures if they exist

### 4.2 Measurement

We track:

1. **Filing coverage**
   - `filings` where `is_in_scope_phase1 = true` and `processing_status in ('processed', 'failed')`
   - Count of in-scope filings with no `source_segments` rows (segmentation failure)

2. **Segment completeness (diagnostic)**
   - Average number of segments per filing
   - Distribution of `segment_type` counts per filing
   - Spot-checks: for a labeled subset, compare automated segments vs human segmentation

### 4.3 Targets (Phase 1)

- **Pilot (25–50 filings):**
  - ≥ 95% of in-scope filings reach `processing_status = 'processed'`
  - 0 filings with zero segments unless explicitly flagged as corrupted source

- **Full run (all S-1s 2015–2025):**
  - ≥ 98% of in-scope filings reach `processing_status = 'processed'`
  - All remaining filings are in `processing_status = 'failed'` with a documented reason

### 4.4 Manual review / blockers

- Any filing with `segment_type='table'` count = 0 **and** `segment_type='paragraph'` count < a low threshold (e.g., 50) must be sampled for manual review.
- A systemic pattern of segmentation failure on specific issuers or form variants is a **blocker** before scaling.

---

## 5. Incidence detection quality

### 5.1 Definition

Incidence detection is about answering: **Did this filing disclose metric X?**

Formally, for each `filing_id` × `metric_id`, we set `metric_disclosed_flag` in `filing_metric_incidence`.

### 5.2 Measurement

We measure **precision**, **recall**, and **F1** against a labeled gold-standard sample.

- **Precision (P):**  
  Among filing–metric pairs the system marks as `metric_disclosed_flag = true`, what fraction are truly disclosed?

- **Recall (R):**  
  Among filing–metric pairs that truly disclose a metric, what fraction does the system mark as `true`?

We will compute these per metric class:

- Core metrics (Phase 1 focus)
- Extended metrics (secondary)

### 5.3 Targets (Phase 1)

For **Core Metrics** in the labeled sample:

- **Pilot:**
  - Precision ≥ 0.90
  - Recall ≥ 0.80

- **Full run (target, not gate):**
  - Precision ≥ 0.92
  - Recall ≥ 0.85

For **Extended Metrics** (incidence only):

- Precision ≥ 0.85
- Recall ≥ 0.70

### 5.4 Manual review / blockers

- If core-metric precision < 0.85 in the pilot, we **do not scale** until fixed.
- If recall for a specific core metric in a target industry < 0.70, we must:
  - Either improve detection or
  - Explicitly disclose the limitation in analysis outputs

---

## 6. Numeric extraction accuracy

### 6.1 Definition

Numeric extraction accuracy measures the correctness of entries in `metric_values`:

- `value_numeric`
- `unit` and `currency`
- Time fields (`period_start`, `period_end`, `period_type`)
- Cohort fields (`cohort_type`, `cohort_bucket_raw`)
- Segment fields (`segment_dimension`, `segment_value`)

### 6.2 Measurement

On a labeled sample, we compare each system-created `metric_values` row to a human-labeled reference.

Metrics:

1. **Exact numeric match rate**
   - Fraction of system values where `value_numeric` equals the reference (within a tolerance for rounding).

2. **Contextual correctness**
   - Fraction of values where **all contextual fields** (period, cohort, unit) match the reference.

We measure separately for:

- Table-derived values (`source_type='table'`)
- Text-derived values (`source_type='text'`)

### 6.3 Targets (Phase 1)

For **table-derived core metrics**:

- **Pilot:**
  - Exact numeric match rate ≥ 0.95
  - Contextual correctness ≥ 0.90

- **Full run (target):**
  - Exact numeric match rate ≥ 0.97
  - Contextual correctness ≥ 0.93

For **text-derived metrics** (core + extended):

- Exact numeric match rate ≥ 0.90
- Contextual correctness ≥ 0.85

### 6.4 Manual review / blockers

- Any systematic pattern where values from a specific component (e.g., a table layout pattern) fall below 0.90 exact match must trigger:
  - A bug investigation
  - A regression test before the next run

- For published quantitative comparisons by cohort, we must:
  - Base them on **table-derived** metrics where possible, or
  - Clearly disclose when text-derived values are used.

---

## 7. Definition & methodology quality

### 7.1 Definition

Definition & methodology quality is about how well we:

- Identify segments where issuers **define** a metric or its underlying concepts
- Extract and normalize those definitions into `metric_definitions`

### 7.2 Measurement

On a labeled sample, we measure:

1. **Definition segment recall**
   - Among all segments that truly contain a definition, what fraction are:
     - Flagged with `contains_definition_flag = true`, and
     - Result in at least one `metric_definitions` row?

2. **Definition correctness**
   - For sampled `metric_definitions` rows, a human grader scores whether the normalized definition and methodology:
     - Preserve the issuer’s meaning
     - Omit no major qualifying clauses

Definition correctness can be graded as:

- 2 = Accurate and complete enough for comparability
- 1 = Mostly accurate, minor omissions or wording issues
- 0 = Misleading or materially incomplete

### 7.3 Targets (Phase 1)

- Definition segment recall ≥ 0.90 on labeled sample
- Average definition correctness score ≥ 1.5 (on 0–2 scale), with ≥ 80% of rows scoring 2

### 7.4 Manual review / blockers

- If definition recall < 0.80 for core metrics, we must:
  - Improve candidate detection prompts/rules, or
  - Explicitly state that definitional analysis is partial

- Any metric where normalized definitions are frequently scored 0 should be:
  - Excluded from comparability claims
  - Flagged in analysis outputs

---

## 8. Comparability / alignment

### 8.1 Definition

Comparability/alignment expresses how closely an issuer’s metric matches the **canonical definition** for that metric in `02_METRIC_TAXONOMY_AND_DEFINITIONS.md`.

We store this as `alignment_flag` in:

- `metric_values` (optional)
- `metric_definitions`
- `filing_metric_incidence` (summary)

Values:

- `aligned` – Materially consistent with canonical definition
- `partial` – Overlaps but has notable differences
- `not_aligned` – Related but materially different
- `unknown` – Definition not clear enough to judge

### 8.2 Measurement

On labeled sample:

- Human annotators assign a “true” alignment category.
- We measure agreement between system-assigned alignment_flag and human labels (accuracy and Cohen’s kappa).

### 8.3 Targets (Phase 1)

- Overall alignment classification accuracy ≥ 0.80 on labeled sample
- Cohen’s kappa ≥ 0.60 (moderate agreement)

### 8.4 Manual review / blockers

- For high-profile examples in presentations or publications, alignment categories should be **manually confirmed**.
- If kappas fall below 0.5, we should:
  - Treat alignment flags as **diagnostic only**, not as hard evidence
  - Avoid strong comparability claims based purely on automated alignment

---

## 9. Provenance & traceability

### 9.1 Definition

Provenance means we can always trace any analytic result back to:

- A specific `metric_values` or `metric_definitions` row
- The underlying `source_segments`
- A specific SEC filing (`filings.sec_html_url` and location in the HTML)

### 9.2 Measurement

We check:

- For a random sample of `metric_values` rows, can we:
  - Follow `source_segment_id` to a segment with non-empty `raw_text` and either `html_selector` or offsets?
- For a random sample of `filing_metric_incidence` records, can we:
  - Identify at least one definition/methodology segment when `metric_disclosed_flag = true`?

### 9.3 Targets (Phase 1)

- ≥ 99% of `metric_values` rows have a valid `source_segment_id` pointing to a non-empty segment.
- ≥ 95% of sampled filing–metric pairs with `metric_disclosed_flag = true` have at least one definitional or numeric segment easily retrievable.

### 9.4 Manual review / blockers

- Any patterns where `source_segment_id` is missing or broken must be treated as a **data integrity bug**, not just a QA warning.

---

## 10. QA states and flags

### 10.1 Per-value QA (`metric_values.qa_status`)

We standardize `qa_status` values:

- `unreviewed` – Default after extraction, before QA
- `pass` – Passes all applicable rule-based checks
- `warning` – Data is plausible but some checks failed or LLM uncertainty is high
- `fail` – Data is likely wrong or inconsistent

Rule-based checks may include:

- Allowed value ranges (e.g., percentages 0–100)
- Unit consistency with metric type
- Internal checks (e.g., sum of cohort counts within 5% of total if both are available)

### 10.2 Filing–metric quality scores (not currently persisted)

A 0–3 integer rubric was previously persisted to the `filing_metric_incidence` table alongside dimension scores (`quality_overall_score`, `quality_definition_score`, `quality_methodology_score`, `quality_completeness_score`, `quality_comparability_score`). The table was dropped on 2026-04-18 (see `docs/architecture/v1-table-deprecation-plan.md`); the scoring module was removed in the same wave. If/when quality scoring is reintroduced, it will target a V2-native table rather than porting the V1 rubric.

### 10.3 Use in analysis

- For incidence analyses:
  - We include all filing–metric pairs that have at least one extracted `MetricFact` or `MetricDefinition`.

- For cohort-based quantitative analyses:
  - We prioritize facts with `cohort_def` set and table-derived provenance.

---

## 11. Manual review triggers

We want to keep human review targeted and high-leverage.

Manual review should be triggered when:

1. **New pattern or model change**
   - After any major change to extraction logic or prompts, we re-evaluate on the labeled sample and spot-check new filings.

2. **Systemic QA warnings or failures**
   - A cluster of `warning` or `fail` statuses for a specific metric, industry, or layout pattern.

3. **High-stakes outputs**
   - Any filing highlighted as a best-practice exemplar in a report or presentation.
   - Any metric used in a headline statistic (e.g., “X% of S-1s disclose cohort revenue by tenure”).

4. **Data surprises**
   - Outliers that are surprising even if QA status is `pass` (e.g., extremely high churn, negative retention).

Manual review outcomes must be recorded via:

- Updated `metric_values` and `metric_definitions` rows with `extraction_method = 'manual_review'`
- Updated `qa_status` and quality scores

---

## 12. Release gates for Phase 1

Before moving from pilot to full Phase 1 run:

1. **Coverage**
   - Pilot sample: ≥ 95% of in-scope filings processed

2. **Incidence detection (core metrics)**
   - Precision ≥ 0.90, recall ≥ 0.80 on labeled sample

3. **Numeric extraction (table-derived core metrics)**
   - Exact numeric match ≥ 0.95

4. **Definitions**
   - Definition segment recall ≥ 0.90

If these gates are not met, the system is not ready for a full Phase 1 run. We then:

- Identify failure modes (by component and pattern)
- Add tests and fixes (to be detailed in `docs/development/testing.md`)
- Re-run the pilot sample until gates are satisfied

---

## 13. Open questions

Open items to refine in later iterations:

1. Exact size and composition of the labeled gold-standard sample:
   - How many filings?
   - Which industries and years?

2. Whether to weight different quality dimensions when computing an overall quality index.

3. How aggressively to use LLM-based scoring vs rule-only scoring for quality.

4. How to communicate uncertainty and QA flags in external publications (visual conventions, footnotes).

These will be specified in coordination with:

- `docs/development/testing.md`
- CMASB stakeholder expectations