# Samsara Vision Extraction Analysis

**Date:** 2024-12-24
**Filing:** Samsara Vision Inc (Filing ID: 38)
**Source:** `data/gold_standard/Samsara_Vision_Inc_/filing.html`
**Gold Standard:** `data/gold_standard/Samsara_Vision_Inc_/extracted_values.csv`

## Executive Summary

Resegmentation and extraction on Samsara Vision revealed several systemic issues affecting both precision (false positives extracted) and recall (valid metrics missed). The issues fall into three categories:

1. **Table parsing failures** - Customer concentration table not being processed
2. **Keyword/number disambiguation failures** - Regulatory references misidentified as metrics
3. **Overly restrictive validation** - Valid customer metrics rejected due to strict keyword requirements

---

## Extraction Results

| Metric | Extracted | Gold Standard | Status |
|--------|-----------|---------------|--------|
| Segments | 71 | - | - |
| Metric Values | 5 | 3 | All false positives |
| Definitions | 1 | 0 | False positive |

### What Was Extracted (All False Positives)

| metric_id | value | source_text (truncated) | issue |
|-----------|-------|-------------------------|-------|
| `cm_new_customers_acquired` | 201 | "...interactions with the FDA, either before or after starting our trials...Section 201..." | FDA regulatory reference |
| `cm_new_customers_acquired` | 201 | (duplicate) | Same issue |
| `cm_new_customers_acquired` | 201 | (duplicate) | Same issue |
| `cm_revenue_concentration` | 280 | "...deferred tax assets resulting from tax loss carryforwards..." | Tax/financial text |
| `cm_revenue_concentration` | 280 | (duplicate) | Same issue |

### What Should Have Been Extracted (From Gold Standard)

| metric_id | value | unit | source |
|-----------|-------|------|--------|
| `cm_customer_revenue_concentration` | 40.0 | percent | Customer A row in concentration table |
| `cm_customer_revenue_concentration` | 40.0 | percent | Customer B row in concentration table |
| `cm_customer_revenue_concentration` | 20.0 | percent | Customer C row in concentration table |

---

## Issue 1: Table Parsing Failure

### Problem
The filing contains a customer revenue concentration table with the following structure:

```
                          Year ended December 31,
                          2021        2020
Customer A               39.90%        —
Customer B               39.90%        —
Customer C               20.20%        —
Customer D               [value]       —
```

This table was **not extracted** despite containing clear customer concentration metrics.

### Evidence
No segments with `candidate_metric_ids` containing revenue concentration were found near table content. The gold standard expects 3 values from this table.

### Possible Causes
1. Table not being identified as metric-relevant during segmentation
2. Table structure not being parsed into row-level segments
3. HTML table styling complexity interfering with parsing

### Relevant Code Paths
- `src/extraction/html_segmenter.py` - Table detection and segmentation
- `src/review/table_structure.py` - Row structure parsing

---

## Issue 2: Regulatory Reference Disambiguation (FDA Section 201)

### Problem
The number "201" from FDA regulatory references is being extracted as `cm_new_customers_acquired`.

### Source Text
```
These strategies could be delayed by further interactions with the FDA, either
before or after starting our trials, or by a variety of other factors, including
the final design of the study to be approved by the FDA, and are subject to the
risks and uncertainties set forth under "Risk Factors — Risks Related to
Government Regulation — Our products may be subject to recalls or regulatory
actions under Section 201..."
```

### Why This Happened
1. Segment was classified with `candidate_metric_ids: {cm_new_customers_acquired}`
2. The number "201" was extracted via `rule_text_smart` method
3. No filter exists to exclude regulatory/legal section references

### Suggested Solutions
1. **Context-based filtering**: Detect regulatory context ("FDA", "Section XXX", "21 CFR")
2. **Pattern exclusion**: Exclude numbers immediately following "Section" or similar legal markers
3. **Section-aware classification**: Reduce confidence for numbers in risk factors/regulatory sections

### Relevant Code Paths
- `src/review/keyword_matching.py` - Keyword detection
- `src/review/false_positive_filter.py` - FP detection rules
- `src/extraction/metric_classifier.py` - Segment classification

---

## Issue 3: Tax/Financial Number Leakage

### Problem
The number "280" from tax discussion text is being extracted as `cm_revenue_concentration`.

### Source Text
```
As of December 31, 2021, and 2020, the Company has provided a full valuation
allowance in respect of the Company's deferred tax assets resulting from tax
loss carryforwards and other temporary differences. Realization of deferred
tax assets is dependent upon future earnings, if any, the time and amount of
which are uncertain...
```

### Why This Happened
The segment was misclassified. The "280" appears to be from tax code section references (e.g., IRC Section 280) or financial amounts that leaked through.

### Suggested Solutions
1. **Tax context detection**: Filter segments with tax-related keywords ("deferred tax", "valuation allowance", "tax loss carryforward")
2. **Section detection**: Similar to FDA issue, detect IRC/tax code section references

---

## Issue 4: Valid Customer Metrics Rejected

### Problem
The LLM correctly identified valid customer metrics but they were rejected by post-processing validation.

### Metric 1: 600 Patients

**Source Text:**
```
To date, there are approximately 150 provider teams, and our WA IMT has been
implanted in more than 600 patients who participated in the program.
```

**Rejection Reason:**
```
Quote-keyword validation failed for cm_active_customers_total=600:
Quote missing metric keyword for cm_active_customers_total.
Expected one of: ['active customer', 'active user', 'total customer']
Quote: 'Our WA IMT has been implanted in more than 600 patients who
participated in the program.'
```

**Analysis:**
- "600 patients" is a valid customer/user metric for a medical device company
- Patients ARE the end customers for Samsara Vision's IMT product
- The keyword list is too narrow for healthcare/medical device companies

### Metric 2: 150 Provider Teams

**Rejection Reason:**
```
Could not map LLM metric name 'provider_teams' to canonical ID. Candidates: []
```

**Analysis:**
- "Provider teams" are effectively B2B customers/distribution partners
- No canonical metric ID exists for this concept
- Could map to `cm_active_customers_total` or a new B2B-specific metric

### Suggested Solutions

1. **Expand keyword lists for industry context:**
   - Healthcare: "patient", "provider", "physician", "clinic", "hospital"
   - B2B: "partner", "team", "account", "enterprise"

2. **Add metric synonyms to canonical mapping:**
   - `provider_teams` → `cm_active_customers_total` or `cm_enterprise_customers`
   - `patients` → `cm_active_customers_total` (for healthcare companies)

3. **Industry-aware validation:**
   - Detect company industry from filing content
   - Apply industry-specific keyword expansion

### Relevant Code Paths
- `src/review/keyword_matching.py` - Keyword validation logic
- `src/extraction/metric_classifier.py` - Metric ID mapping
- `src/review/config.py` - Keyword configuration

---

## Issue 5: Segment Classification Accuracy

### Problem
The segment containing the key customer metrics was classified as `methodology_block` with no `candidate_metric_ids`.

**Segment ID:** 23134
**Segment Type:** `methodology_block`
**Candidate Metric IDs:** `{}`  (empty)

**Full Segment Text:**
```
When a patient is found to be a candidate for the WA IMT under the respective
labels (as determined by healthcare professionals), the patient needs to undergo
pre-surgical testing and a variety of medical pre-checks...

[...long description of patient journey...]

To date, there are approximately 150 provider teams, and our WA IMT has been
implanted in more than 600 patients who participated in the program. We began
domestic commercialization of our WA IMT in 2012...
```

### Analysis
- This segment contains both methodology description AND concrete customer metrics
- Classification as pure `methodology_block` caused metric detection to be skipped
- The segment is very long (~4000 chars) combining multiple concepts

### Suggested Solutions
1. **Segment splitting**: Break long segments at topic boundaries
2. **Multi-label classification**: Allow segments to have multiple types
3. **Number-triggered re-evaluation**: When numbers are present, re-evaluate for metric content regardless of segment type

---

## Database Schema Note

During this analysis, a constraint issue was discovered and fixed:

```sql
-- The check_extraction_method constraint was missing 'rule_text_smart'
ALTER TABLE metric_values DROP CONSTRAINT check_extraction_method;
ALTER TABLE metric_values ADD CONSTRAINT check_extraction_method
  CHECK (extraction_method IN ('rule_table', 'llm_table', 'llm_text', 'manual_review', 'rule_text_smart'));
```

Ensure this migration is tracked in `sql/` if not already present.

---

## Recommended Priority Order

1. **HIGH: Table parsing** - Missing all gold standard values
2. **HIGH: Regulatory/tax context filtering** - Multiple false positives per filing
3. **MEDIUM: Industry-aware keyword expansion** - Valid metrics being rejected
4. **MEDIUM: Segment classification refinement** - Metric-containing segments miscategorized
5. **LOW: Metric ID mapping expansion** - Edge cases for non-standard metric names

---

## Test Cases for Validation

When solutions are implemented, verify against:

1. **Table extraction:** Extract 40%, 40%, 20% from customer concentration table
2. **FDA filtering:** Reject "201" from "Section 201" references
3. **Tax filtering:** Reject numbers from tax/deferred asset discussions
4. **Patient metrics:** Accept "600 patients" as valid customer count
5. **Provider metrics:** Map "150 provider teams" to appropriate canonical ID

---

## Related Files

- Filing HTML: `data/gold_standard/Samsara_Vision_Inc_/filing.html`
- Gold standard: `data/gold_standard/Samsara_Vision_Inc_/extracted_values.csv`
- Extraction pipeline: `src/extraction/extraction_pipeline.py`
- Segmenter: `src/extraction/html_segmenter.py`
- Metric classifier: `src/extraction/metric_classifier.py`
- Keyword matching: `src/review/keyword_matching.py`
- False positive filter: `src/review/false_positive_filter.py`
- Table structure: `src/review/table_structure.py`
