# HRV-3 Slack Filing - False Positive Pattern Analysis

**Generated**: 2025-12-26
**Based On**: 20 reviewed candidates (18 accept, 2 reject) + 108 unreviewed
**Reviewer Feedback**: "Many false positives and metric misclassifications, focused on high-scoring metrics"

---

## Summary of Key Findings

Based on your review decisions and analysis of unreviewed candidates, I've identified **5 major false positive patterns** affecting the Slack filing review:

1. **Financial Statement Line Items** (41+ candidates) - HIGH IMPACT
2. **Balance Sheet Items as Deferred Revenue** (24+ candidates) - HIGH IMPACT
3. **Cross-Row Table Contamination** (18+ candidates) - MEDIUM IMPACT
4. **Threshold/Definition Values as Metrics** (9+ candidates) - MEDIUM IMPACT
5. **Percentage Values for Count Metrics** (1+ candidates) - LOW IMPACT

---

## Pattern 1: Financial Statement Line Items ⚠️ HIGH IMPACT

**False Positives**: 41+ candidates
**Metric Affected**: `cm_gross_margin_overall` (Gross profit keyword)
**Confidence Range**: 0.0 - 0.18 (mostly very low)

### Description
System detects "Gross profit" in financial statements (income statement, P&L) and extracts **every number in the table**, not recognizing that these are financial accounting line items, not customer metrics.

### Examples

| Value | Context | Why False Positive |
|-------|---------|-------------------|
| 400,552 | "Revenue [CELL] $ [CELL] 400,552 [ROW] Cost of revenue [CELL] 51,301 [ROW] Gross profit [CELL] $..." | Revenue total, not gross margin metric |
| 349,251 | "Revenue [CELL] $ [CELL] 220,544 [CELL] $ [CELL] 400,552 [ROW] Cost of revenue(1) [CELL] 15,517 [CELL] 26,364 [CELL] 51,301 [ROW] Gross profit [CELL] $ [CELL] 89,636 [CELL] $ [CELL] 194,180 [CELL] $ [CELL] 349,251" | Gross profit dollar amount, not margin % |
| 180,008 | "Revenue [CELL] $ [CELL] 220,544 [CELL] $ [CELL] 400,552 [CELL] $ [CELL] 180,008 [CELL] 82 [CELL] % [ROW] Cost of revenue [CELL] 26,364 [CELL] 51,301 [CELL] 24,937 [CELL] 95 [ROW] Gross profit..." | Revenue change ($), not margin |
| 82%, 95%, 110% | "$ [CELL] 180,008 [CELL] 82 [CELL] % [ROW]... [CELL] 95 [ROW]... [CELL] 110 [CELL] %" | Growth rates for revenue/costs |

### Root Cause
1. **No financial statement context detection** - System doesn't recognize consolidated statements of operations
2. **No distinction between margin % vs dollar amounts** - "Gross profit" can be $ or %
3. **Table structure issues** - Every cell value near "Gross profit" is extracted

### Fix Recommendation
**Priority: HIGH** - Implement HRV-10 and HRV-11 from system improvements:
- Detect financial statement patterns: "Consolidated Statements of Operations", "Income Statement", etc.
- Filter out line item keywords: "Revenue", "Cost of revenue", "Operating expenses", "Net income"
- For `cm_gross_margin_overall`, only accept **percentage values** (e.g., 82%, 85%), not dollar amounts
- Consider deprecating gross profit as a customer metric (it's a financial metric)

---

## Pattern 2: Balance Sheet Items as Deferred Revenue ⚠️ HIGH IMPACT

**False Positives**: 24+ candidates
**Metric Affected**: `cm_deferred_revenue`
**Confidence Range**: 0.0 - 0.15 (very low)

### Description
System detects "Deferred revenue" keyword in balance sheet and extracts **all balance sheet line items** including total assets, working capital, etc.

### Examples

| Value | Context | Why False Positive |
|-------|---------|-------------------|
| 1,198,956 | "Total assets [CELL] 697,780 [CELL] 1,198,956 [CELL] 1,198,956 [ROW] Working capital..." | Total assets, not deferred revenue |
| 965,221 | "Working capital [CELL] 440,258 [CELL] 650,324 [CELL] 650,324 [ROW] Total assets [CELL] 697,780 [CELL] 1,198,956 [CELL] 1,198,956 [ROW] ... Deferred revenue..." | Total assets from earlier in table |
| 650,324 | "Cash, cash equivalents, and marketable securities... Working capital [CELL] 440,258 [CELL] 650,324" | Working capital, not deferred revenue |
| 357,350, 332,398 | "Total assets$697,780 $1,198,956 LIABILITIES AND STOCKHOLDERS' EQUITY Current liabilities: Accounts payable$7,056 $16,613... Deferred revenue..." | Other liabilities being misattributed |

### Root Cause
1. **No balance sheet context filter** - System treats all numbers near "Deferred revenue" as candidates
2. **Table row bleeding** - Numbers from different rows are matched to wrong keywords
3. **Missing line item exclusions** - "Total assets", "Working capital" should be excluded

### Fix Recommendation
**Priority: HIGH** - Implement HRV-10 and HRV-11:
- Detect balance sheet patterns: "Consolidated Balance Sheet Data", "ASSETS", "LIABILITIES"
- Filter line item keywords: "Total assets", "Working capital", "Cash and cash equivalents", "Accounts payable"
- For deferred revenue, require number to be in **same table row** as "Deferred revenue" keyword
- Consider if deferred revenue is actually a customer metric (may be financial metric)

---

## Pattern 3: Cross-Row Table Contamination ⚠️ MEDIUM IMPACT

**False Positives**: 18+ candidates
**Metric Affected**: `cm_net_revenue_retention`, `cm_arr`
**Confidence Range**: 0.05 - 0.25

### Description
In tables with multiple metrics, the system matches numbers from **different rows** to the wrong keyword. Example: "Paid Customers" counts being attributed to "Net Dollar Retention Rate".

### Examples

| Value | Keyword | Context | Why False Positive |
|-------|---------|---------|-------------------|
| 37,000 | "Retention Rate171% 152% 143%" | "Paid Customers [CELL] 37,000 [CELL] 59,000 [CELL] 88,000 [ROW] Paid Customers >$100,000 [CELL] 135 [CELL] 298 [CELL] 575 [ROW] Net Dollar Retention Rate [CELL] 171% [CELL] 152% [CELL] 143%" | **This is paid customer count**, not retention rate |
| 59,000 | "Retention Rate171% 152% 143%" | Same table | Paid customer count |
| 88,000 | "Retention Rate171% 152% 143%" | Same table | Paid customer count |
| 135 | "Net Dollar Retention" | Same table | **Count of customers >$100k**, not retention % |
| 298 | "Net Dollar Retention" | Same table | Count of customers >$100k |
| 575 | "Net Dollar Retention" | Same table | Count of customers >$100k |

### Visual Example
```
Table structure:
┌─────────────────────────┬────────┬────────┬────────┐
│                         │  2017  │  2018  │  2019  │
├─────────────────────────┼────────┼────────┼────────┤
│ Paid Customers          │ 37,000 │ 59,000 │ 88,000 │ ← THESE ARE CUSTOMER COUNTS
│ Paid Customers >$100k   │    135 │    298 │    575 │ ← THESE ARE CUSTOMER COUNTS
│ Net Dollar Retention    │   171% │   152% │   143% │ ← THESE ARE RETENTION %
└─────────────────────────┴────────┴────────┴────────┘

System is matching 37,000, 59,000, 88,000 to "Net Dollar Retention"
because the keyword appears later in the same table!
```

### Root Cause
1. **Table-aware matching insufficient** - System doesn't properly restrict to same row
2. **Keyword distance calculation flawed** - Numbers 2-3 rows away are considered "close"
3. **Type checking missing** - Retention rate should be %, not integer counts

### Fix Recommendation
**Priority: MEDIUM** - Already partially addressed in EA-3, but needs strengthening:
- **Strict row boundary enforcement** - Only match numbers in same `[ROW]...` block as keyword
- **Type validation** - For `cm_net_revenue_retention`, require percentage format (e.g., "143%", "1.43")
- **Reject integer values** for retention metrics unless they have % suffix
- Add confidence penalty for cross-row matches

---

## Pattern 4: Threshold/Definition Values as Metrics ⚠️ MEDIUM IMPACT

**False Positives**: 9+ candidates
**Metric Affected**: `cm_arr` primarily
**Confidence Range**: 0.10 - 0.73

### Description
Numbers that represent **thresholds** or **definitions** (e.g., "$100,000 ARR threshold", "companies with 250-5,000 employees") are being extracted as if they're metric values.

### Examples from Rejected Candidates

| Value | Context | Why False Positive | Reviewer Decision |
|-------|---------|-------------------|-------------------|
| $100,000 | "annual recurring revenue, or ARR, of each cohort... For example, the fiscal year 2015 cohort represents all Paid Customers that purchased their first subscription from us during the fiscal year ended January 31, 2015." | **ARR threshold for customer segmentation**, not an ARR value | ✅ **REJECTED** |
| 450,000 | "third-party applications and allow for easy integrations... During the three months ended January 3" | Context mentions apps/integrations, not DAU value | ✅ **REJECTED** |

### Examples from Unreviewed Candidates

| Value | Keyword | Context | Why False Positive |
|-------|---------|---------|-------------------|
| $100,000 | "annual recurring revenue" (ARR) | "We measure the number of Paid Customers > **$100,000** of annual recurring revenue, or ARR, as a gauge..." | Definition of customer segment threshold |
| 250 | "ARR" | "companies that have **250** – 5,000 employees" | Employee count range, not ARR |
| 10 | "ARR" | "companies that have more than **5,000** employees" | Employee threshold for market sizing |
| 40% | "ARR" | Context about ARR growth rate | Percentage, not ARR dollar value |

### Root Cause
1. **No definition detection** - Phrases like "We define", "We measure", ">$100,000 of ARR" indicate definitions
2. **No range detection** - "250 - 5,000" is a range, not a metric value
3. **Wrong metric attribution** - Employee counts being tagged as ARR

### Fix Recommendation
**Priority: MEDIUM** - Implement HRV-13 (definition-only mode) and HRV-9 (growth rate detection):
- Detect definition phrases: "We define X as", "We measure X as", "X is defined as"
- Flag candidates with ">" or "<" near metric keywords as thresholds (e.g., ">$100,000 of ARR")
- Detect ranges: "X - Y employees", "between X and Y"
- For ARR specifically, reject percentages (those are growth rates)
- **Option**: Create separate "definition" candidates for documentation, but don't count as values

---

## Pattern 5: Percentage Values for Count Metrics ⚠️ LOW IMPACT

**False Positives**: 1+ candidates
**Metric Affected**: `cm_arr`
**Confidence Range**: 0.10

### Description
Percentage values (e.g., "40%") being matched to count/dollar metrics like ARR.

### Example

| Value | Keyword | Context | Why False Positive |
|-------|---------|---------|-------------------|
| 40% | "ARR" | "We had 575 Paid Customers >$100,000 of ARR as of January 31... **40%** growth..." | Growth rate, not ARR value |

### Root Cause
- **No type validation** - ARR should be dollar amount, not percentage

### Fix Recommendation
**Priority: LOW** - Implement HRV-8 (percentage filter for count metrics):
- For count/dollar metrics (`cm_arr`, `cm_tcv`, `cm_customer`), **reject percentage values**
- Percentages are either growth rates or retention metrics
- Add type validation: ARR must match `$X` or `X million` patterns

---

## Pattern 6: DAU False Positives (From Rejected Candidates)

**False Positives**: 1 confirmed, likely 4-5 total
**Metric Affected**: `cm_daily_active_users`

### Example from Rejected

| Value | Context | Why False Positive |
|-------|---------|-------------------|
| 450,000 | "third-party applications and allow for easy integrations with an organization's internally-developed software. During the three months ended January 3" | Mentions "applications" not "daily active users" - context mismatch |

### Unreviewed Candidates

| Value | Confidence | Context Preview |
|-------|-----------|-----------------|
| 500,000 | 0.685 | Need to review full context |
| 150 | 0.685 | Need to review full context |

### Note
One DAU candidate was **accepted** (10 million), suggesting this is the real DAU metric. The 450,000 and potentially 500,000 are likely false positives from wrong context.

---

## Impact Assessment

### By False Positive Count

| Pattern | FP Count | % of Unreviewed | Priority |
|---------|----------|-----------------|----------|
| Financial Statement Line Items | 41 | 38% | **HIGH** |
| Balance Sheet Items | 24 | 22% | **HIGH** |
| Cross-Row Table Contamination | 18 | 17% | **MEDIUM** |
| Threshold/Definition Values | 9 | 8% | **MEDIUM** |
| Percentage for Count Metrics | 1 | <1% | **LOW** |
| **Total Identified FPs** | **93** | **86%** | |

### Implications

If the pattern continues:
- **Unreviewed candidates**: 108
- **Estimated true positives**: ~15-20 (14%)
- **Estimated false positives**: ~88-93 (86%)

This matches your observation: "Many false positives... I skipped many false positives, focusing on high scoring metrics."

---

## Metric Misclassification Analysis

### Wrong Metric Assignments

Based on cross-row contamination pattern:

| Actual Metric | System Classified As | Count | Fix Needed |
|---------------|---------------------|-------|------------|
| Paid Customers (count) | `cm_net_revenue_retention` | 6 | Row-level matching |
| Paid Customers >$100k (count) | `cm_net_revenue_retention` | 6 | Row-level matching |
| Paid Customers >$100k (count) | `cm_arr` | 3 | Row-level matching |
| Revenue ($) | `cm_gross_margin_overall` | 10+ | Financial filter |
| Total Assets ($) | `cm_deferred_revenue` | 5+ | Balance sheet filter |

---

## Recommended System Improvements (Priority Order)

### 1. HIGH PRIORITY - Foundational Filters

#### HRV-10: Financial Statement Line Item Patterns (3-4h)
- Detect: "Consolidated Statements of Operations", "Income Statement", "Statement of Cash Flows"
- Exclude line items: "Revenue", "Cost of revenue", "Operating expenses", "Net income", "Total revenue"
- **Expected Impact**: Eliminate 41 FPs (38%)

#### HRV-11: Financial Statement Context Filter (2-3h)
- Dependency: HRV-10
- Apply financial context filter to reject candidates
- **Expected Impact**: Eliminate 41 FPs (38%)

#### Similar: Balance Sheet Context Filter (2-3h)
- Detect: "Consolidated Balance Sheet", "ASSETS", "LIABILITIES AND STOCKHOLDERS' EQUITY"
- Exclude: "Total assets", "Working capital", "Cash and cash equivalents", "Accounts payable"
- **Expected Impact**: Eliminate 24 FPs (22%)

### 2. MEDIUM PRIORITY - Table Structure

#### Enhanced Row-Level Matching (2-3h)
- Strengthen EA-3 table-aware matching
- **Strict row boundaries**: Only match numbers within same `[ROW]...[CELL]...[ROW]` block
- Add confidence penalty for cross-row matches
- **Expected Impact**: Eliminate 18 FPs (17%)

#### Type Validation by Metric (1-2h)
- `cm_net_revenue_retention`: Require percentage format (%, or decimal 1.0-2.0)
- `cm_arr`, `cm_tcv`: Require dollar amounts, reject percentages
- `cm_customer`: Require integers, reject percentages and decimals
- **Expected Impact**: Eliminate 10+ FPs (9%)

### 3. MEDIUM PRIORITY - Definition Detection

#### HRV-13: Definition-Only Mode (1-2h)
- Detect definition phrases: "We define", "We measure", "is defined as"
- Detect thresholds: ">$X", "<$X", "at least $X"
- Flag as definition-only (separate from value candidates)
- **Expected Impact**: Eliminate 9 FPs (8%), improve documentation

#### HRV-9: Growth Rate Detection (2-3h)
- Detect growth patterns: "X% growth", "increased by X%", "grew X%"
- Separate growth metrics from base metrics
- **Expected Impact**: Reduce misclassification, cleaner metrics

---

## Validation Against Gold Standard

### Current Status
- **Reviewed**: 20 candidates (18 accept, 2 reject)
- **Accepted rate**: 90% (18/20)
- **Gold standard**: 41 Slack metrics expected

### Estimated Performance (Based on Patterns)

| Metric | Estimated Value | Calculation |
|--------|----------------|-------------|
| True Positives | ~18-20 | Your accepted candidates |
| False Positives | ~88-93 | Pattern analysis of unreviewed |
| False Negatives | ~21-23 | 41 gold - ~18-20 found |
| **Precision** | **~17-19%** | TP / (TP + FP) = 18 / (18 + 88) |
| **Recall** | **~44-49%** | TP / (TP + FN) = 18 / 41 |

### Target After System Improvements

If we eliminate ~93 FPs through patterns above:

| Metric | Target Value | Improvement |
|--------|-------------|-------------|
| True Positives | ~25-30 | +7-12 from better recall |
| False Positives | ~15-20 | -73 from filters |
| **Precision** | **~60-70%** | +43-51 pp |
| **Recall** | **~61-73%** | +12-29 pp |

---

## Next Steps

### Immediate (Manual Review)
1. Continue reviewing high-confidence candidates (0.5+)
2. Skip obvious FP patterns (financial statements, balance sheets)
3. Document any new patterns encountered

### After Review Complete
1. Run validation script to get precise metrics
2. Compare accepted candidates vs gold standard
3. Identify specific false negatives (missed metrics)

### Implementation Priority
1. **HRV-10 + HRV-11**: Financial statement filters (HIGH IMPACT - 60% of FPs)
2. **Balance sheet filter**: Similar to HRV-11 (HIGH IMPACT - 22% of FPs)
3. **Row-level matching**: Enhance table awareness (MEDIUM IMPACT - 17% of FPs)
4. **HRV-13**: Definition detection (MEDIUM IMPACT - 8% of FPs + better docs)

---

**Analysis Date**: 2025-12-26
**Analyst**: Claude Code
**Data Source**: 128 candidates (20 reviewed, 108 unreviewed), filing_id=35
