

# 07_TEST_STRATEGY_AND_FIX_PROCESS

Version: 0.1  
Date: 2025-11-15  
Owner: Rob Markey  

## 1. Purpose

This document defines the **testing strategy** and **fix process** for the Customer Metrics Filings Analysis system.

It translates the quality model in `06_QA_AND_QUALITY_MODEL.md` into:

- Concrete tests (unit, integration, end-to-end)
- A gold-standard labeling plan
- Release gates and regression testing rules
- A process for logging, triaging, and fixing defects

Goal: make quality measurable, repeatable, and improvable over time.

---

## 2. Testing principles

1. **Quality model–driven**  
   Tests are designed explicitly to measure the dimensions and targets in `06_QA_AND_QUALITY_MODEL.md`.

2. **Small, labeled core; large, automated perimeter**  
   We maintain a **small, carefully labeled gold-standard set** and a **large, automatically processed universe**.

3. **Idempotent, filing-level tests**  
   Most integration and E2E tests run at the `filing_id` level so they can be repeated safely.

4. **Regression-first mindset**  
   Every critical defect discovered in production should result in a regression test that would catch it next time.

---

## 3. Test types and scope

We use four main test types:

1. **Unit tests** – Functions or classes in isolation.
2. **Component integration tests** – Each pipeline component with a small set of real filings.
3. **End-to-end (E2E) tests** – Full pipeline for selected filings, asserting DB outputs.
4. **Quality evaluation tests** – Comparison of outputs vs gold-standard labels.

Each quality dimension from `06_QA_AND_QUALITY_MODEL.md` is covered by at least one of these.

---

## 4. Gold-standard labeling plan

### 4.1 Purpose

The gold-standard set is used to:

- Measure incidence precision/recall
- Measure numeric extraction accuracy
- Evaluate definition and alignment quality
- Validate changes before release

### 4.2 Size and composition (Phase 1)

Initial target:

- **Total filings:** 40–60
- Composition:
  - 20–30 SaaS / subscription-oriented issuers
  - 10–15 transaction-heavy consumer businesses (e.g., marketplaces, rideshare, e-commerce)
  - 10–15 financial services (banking, cards, investment platforms) where available
- Time distribution:
  - At least 10 filings from 2015–2018
  - At least 10 filings from 2019–2021
  - At least 10 filings from 2022–2025

We may expand or rebalance as we learn.

### 4.3 Labeling tasks

For each gold-standard filing, a human reviewer will:

1. **Filing-level checks**
   - Confirm filing metadata (form type, filing_date, company).

2. **Incidence labels** (per metric_id)
   - For each **core** metric:
     - `true_disclosed_flag`: yes/no
     - If yes, list sections/locations where it is disclosed.

3. **Metric value labels** (for a subset of metrics)
   - For selected metrics and cohorts:
     - Exact numeric values
     - Period and cohort details
     - Units and currency
     - Whether value is from a table or narrative

4. **Definition and methodology labels**
   - Identify and copy the segments where each core metric is defined or its method is described.
   - Provide a short human-written summary of the definition.

5. **Alignment labels**
   - For each core metric, label alignment against canonical definition:
     - `aligned`, `partial`, `not_aligned`, `unknown`

6. **Quality grades** (optional for Phase 1 pilot)
   - For each core metric in that filing, give 0–3 scores for:
     - Definition clarity
     - Methodology clarity
     - Completeness
     - Comparability

### 4.4 Storage of gold-standard labels

- Gold-standard labels will be stored in **separate tables or CSVs**, not mixed with production tables, e.g.:
  - `gs_filing_metric_incidence`
  - `gs_metric_values`
  - `gs_metric_definitions`
- Each row must include:
  - `filing_id`, `metric_id`
  - Source references (URLs, locations) sufficient to validate labels

---

## 5. Unit tests

### 5.1 Scope

Unit tests cover pure logic and small functions, including:

- HTML normalization helpers
- Section and heading detection heuristics
- Table parsing utilities
- Keyword-based candidate detection
- Data model utilities (e.g., key generation, idempotency checks)

### 5.2 Examples

- **Segmenter utilities**
  - Given sample HTML, assert that heading patterns produce expected `section_path`.

- **Metric taxonomy utilities**
  - Given metric synonyms, assert correct mapping from phrases to `metric_id`.

- **Range and consistency checks**
  - Given sample `metric_values` records, assert QA rules detect out-of-range or inconsistent values.

### 5.3 Requirements

- Unit tests should run fast (< 1s each) and be part of the default test suite.
- Code coverage for utility modules should be high (target 80%+).

---

## 6. Component integration tests

### 6.1 Scope

Component integration tests exercise one component end-to-end against **real filings** and the database.

Each core component from `05_COMPONENT_INTERFACE_SPECS.md` should have integration tests:

- `UniverseBuilder`
- `FilingFetcher`
- `FilingNormalizer`
- `Segmenter`
- `CandidateSegmentClassifier`
- `TableExtractor`
- `TextMetricExtractor`
- `DefinitionExtractor`
- `QAEngine`
- `Loader`

### 6.2 Examples

- **Segmenter integration test**
  - Input: 1–3 real S-1 HTML files.
  - Asserts:
    - `source_segments` is populated.
    - There are non-zero `paragraph` and `table` segments.
    - Section headings contain expected strings (e.g., "Item 1. Business").

- **TableExtractor integration test**
  - Input: a filing with a known cohort revenue table.
  - Asserts:
    - At least one `metric_values` row with `metric_id='cm_revenue_by_cohort'` exists.
    - Values and periods approximately match expectations (within known tolerance).

- **QAEngine integration test**
  - Input: a filing with known good and weak metric disclosures.
  - Asserts:
    - `filing_metric_incidence` rows exist for core metrics.
    - Quality scores follow expected ordering (e.g., best-exemplar > weak-exemplar).

### 6.3 Requirements

- Integration tests should be runnable locally with a small subset of filings.
- They should not depend on external network calls (use cached HTML).

---

## 7. End-to-end (E2E) tests

### 7.1 Scope

E2E tests run the **full pipeline** for selected filings:

- From `filings` metadata
- Through fetch/normalize/segment/classify/extract/QA/load
- To final records in `metric_values`, `metric_definitions`, `filing_metric_incidence`

### 7.2 Design

- Use **5–10 filings** from the gold-standard set as E2E fixtures.
- For each:
  - Run `Orchestrator.process_filing(filing_id)`.
  - Compare DB outputs to expected gold-standard labels.

### 7.3 Assertions

For each E2E filing, we assert:

- `processing_status` = `processed`.
- No unexpected `segment_type` distributions (e.g., not zero tables if the filing clearly has tables).
- For a selected subset of metrics and cohorts:
  - `metric_disclosed_flag` matches gold-standard.
  - `metric_values` match gold-standard within tolerance.
  - `metric_definitions` exist where expected.

---

## 8. Quality evaluation tests

These tests compute metrics defined in `06_QA_AND_QUALITY_MODEL.md` using gold-standard labels.

### 8.1 Incidence evaluation

- Compute precision, recall, and F1 for each core metric:
  - Compare `filing_metric_incidence.metric_disclosed_flag` vs `gs_filing_metric_incidence.true_disclosed_flag`.

### 8.2 Numeric accuracy evaluation

- For a labeled subset of `metric_values`:
  - Exact numeric match rate
  - Contextual correctness rate

### 8.3 Definition and alignment evaluation

- For `metric_definitions` in gold-standard filings:
  - Definition segment recall
  - Alignment classification accuracy and Cohen’s kappa vs human labels

### 8.4 Automation

- Implement a dedicated script or test module (e.g., `tests/test_quality_eval.py`) that:
  - Loads gold-standard tables
  - Runs evaluation queries
  - Prints or asserts metrics against thresholds from `06_QA_AND_QUALITY_MODEL.md`

---

## 9. Release gates and CI

### 9.1 Release gates (pre-production)

Before a major run or public use of the data, CI must:

- Run unit and integration tests
- Run E2E tests on the small fixture set
- Run quality evaluation tests on gold-standard data

If any of the following fail, the release is blocked:

- Coverage, incidence, numeric accuracy, or definition recall gates in Section 12 of `06_QA_AND_QUALITY_MODEL.md` are not met.
- E2E tests fail for any of the fixture filings.

### 9.2 Continuous integration setup

- Use a standard test runner (e.g., `pytest`).
- Tag tests:
  - `unit` (fast, always run)
  - `integration` (medium, run in CI)
  - `e2e` and `quality_eval` (slower, run on main branch or before releases)

---

## 10. Fix process and defect lifecycle

### 10.1 Defect logging

For any discovered defect (from tests or manual review), log:

- Filing ID(s) affected
- Component(s) responsible (e.g., Segmenter, TableExtractor)
- Metric(s) affected
- Symptoms (wrong incidence, value, definition, etc.)
- Severity:
  - **Critical** – Misleads headline results or large parts of the dataset
  - **High** – Affects core metrics or many filings, but with workarounds
  - **Medium** – Localized errors or extended metrics
  - **Low** – Cosmetic or rare corner cases

Defects can be tracked in an issue system (e.g., GitHub issues, Jira) with a consistent template.

### 10.2 Fix implementation

For each defect:

1. Write a failing test that reproduces the issue:
   - Unit, integration, or E2E depending on scope.
2. Implement the fix in the relevant component.
3. Confirm the new test passes and does not break existing tests.

### 10.3 Regression tests

- Any **critical** or **high** severity defect must produce a new regression test.
- Regression tests should:
  - Use the minimal filing/segment needed to reproduce the issue.
  - Run as part of the regular test suite.

### 10.4 Data correction

For defects found after data has been generated:

- Decide whether:
  - To re-run the pipeline for the affected filings, or
  - To manually correct `metric_values` and mark `extraction_method = 'manual_review'`.
- Document any manual corrections separately for transparency.

---

## 11. Versioning and change management

### 11.1 Code and prompts

- Treat extraction prompts as **versioned artifacts**:
  - Changes to prompts for key components (TableExtractor, TextMetricExtractor, DefinitionExtractor, QAEngine) should be:
    - Committed with clear messages
    - Linked to tests demonstrating the impact

### 11.2 Schema and taxonomy

- Changes to:
  - `03_DATA_MODEL_SPEC.md`
  - `02_METRIC_TAXONOMY_AND_DEFINITIONS.md`
- Must be:
  - Documented in a changelog
  - Assessed for impact on tests and gold-standard interpretation

### 11.3 Gold-standard updates

- When we add new filings or metrics to the gold-standard set:
  - Update corresponding `gs_*` tables/CSVs
  - Re-run quality evaluation tests

---

## 12. Initial implementation priorities

Before large-scale implementation, focus on:

1. **Create small, high-quality gold-standard set** (10–15 filings) and labels.
2. **Implement a basic E2E pipeline** for those filings.
3. **Build evaluation scripts** to compute:
   - Incidence precision/recall
   - Numeric match rates
   - Definition recall
4. Iterate on extraction and prompts until Phase 1 pilot gates (Section 12 of `06_QA_AND_QUALITY_MODEL.md`) are met.

Once those are stable, we can:

- Expand the gold-standard set
- Harden regression tests
- Scale to the full S-1 universe.