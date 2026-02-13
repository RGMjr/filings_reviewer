# POC Results: V2 Pipeline on Earnings Call Transcripts

**Date:** 2026-02-13
**Status:** Complete
**Phase:** 3 of 6

## Executive Summary

The V2 extraction pipeline was run unmodified on 22 earnings call transcripts from 10 companies. Results demonstrate that the pipeline is architecturally compatible with transcript content but has significant recall gaps:

- **79 total facts extracted** across 22 files (avg 3.6/file)
- **Pipeline success rate:** 100% (22/22 files processed without errors)
- **Average processing time:** 72ms per transcript
- **Key finding:** Keyword matching (candidate generation) works well, but value binding and false positive filtering are too conservative for conversational text, resulting in low recall

## Pipeline Behavior Summary

| Stage | Transcripts Behavior | vs SEC Filings |
|-------|---------------------|----------------|
| Ingestion | 22-80 segments/file (avg 43) | Works identically |
| Section Classification | All segments → COVER (no SEC patterns match) | **Degraded** — no section signals |
| Table Reconstruction | 0 tables (correct) | N/A for transcripts |
| Candidate Generation | 1-44 candidates/file — keyword matching works | **Works well** |
| Value Binding | 0-44 bound values — highly variable | **Bottleneck** — text proximity only |
| False Positive Filter | Removes 0-50% of bindings | **Too aggressive** for transcripts |
| Period Inference | 0-62% success rate | **Major gap** — no table headers |
| Deduplication | Effective when facts exist | Works as expected |
| Validation | Passes through | Works as expected |

## Per-Company Results

| Company | Ticker | Files | Total Facts | Avg Facts/File | Candidates (avg) | Binding Rate | Notes |
|---------|--------|-------|-------------|----------------|-------------------|--------------|-------|
| Adobe | ADBE | 2 | 37 | 18.5 | 33 | High | Best performer — dense ARR/subscriber metrics |
| GoDaddy | GDDY | 2 | 17 | 8.5 | 33 | Moderate | Good ARR/ARPU/customer extraction |
| Autodesk | ADSK | 2 | 7 | 3.5 | 13.5 | Moderate | ARR and subscriber counts |
| Microsoft | MSFT | 2 | 6 | 3.0 | 6 | High | M365 subscribers, LinkedIn members |
| Salesforce | CRM | 4 | 8 | 2.0 | 3.75 | Moderate | ARR, paid customers detected |
| PayPal | PYPL | 2 | 3 | 1.5 | 10 | Low | Active accounts mentioned but poorly bound |
| Meta | META | 2 | 1 | 0.5 | 1 | Low | 3.4B DAU not captured; only 1 match |
| EA | EA | 2 | 0 | 0.0 | 2 | None | Gaming-specific language not matched |
| Intuit | INTU | 2 | 0 | 0.0 | 6.5 | None | Candidates found but not bound |
| T-Mobile | TMUS | 2 | 0 | 0.0 | 6.5 | None | Churn/subscriber terms found but filtered |

## Stage-by-Stage Analysis

### Candidate Generation (Stage 6) — Works Well

The keyword matching stage successfully identifies customer metric mentions in transcripts:

- **Total candidates across 22 files:** ~230
- **Candidate hit rate:** Every file with customer metrics generates candidates
- **Keyword coverage:** ARR, subscribers, paid customers, active accounts, churn — all matched
- **Gap:** Meta's "3.4 billion people using at least one of our apps each day" was not matched as DAU/MAU because the phrasing doesn't use standard keywords

### Value Binding (Stage 7) — Major Bottleneck

Value binding is the primary recall bottleneck:

- **Binding rate:** ~40% of candidates get bound to values
- **Root cause:** The binding logic is optimized for table cells with header_path/stub_path context. For text values, it relies on proximity within the same segment.
- **Problem:** In transcripts, a single speaker turn is one large `<p>` element. A candidate at the start of a paragraph may not bind to a value mentioned later in the same paragraph if the distance exceeds the proximity threshold.
- **Example failure:** "churn rate of 0.8%" — "churn rate" matched as candidate but "0.8%" wasn't bound because it fell outside the proximity window

### False Positive Filter (Stage 7.5) — Too Aggressive

The FP filter removes legitimate transcript extractions:

- **Filter rate:** 0-50% of bound values are filtered out
- **Root cause:** FP rules designed for SEC filing contexts (financial statements, accounting line items) incorrectly flag conversational mentions
- **Example:** "we added 1.2 million net new customers" — "net new customers" matched, but the value was filtered because adjacent text contained financial terms

### Period Inference (Stage 8) — Significant Gap

Period inference fails for most transcript values:

- **Success rate:** 0-62% (highly variable)
- **Best case:** Adobe Q4 2024 call — 62% (26/42) of values got periods. This call had explicit "FY2024" and "Q4 2024" mentions in the same sentences as metrics
- **Worst case:** Many files — 0% period inference
- **Root cause:** Strategy 1 (table header_path) is unavailable (no tables). Strategy 2 (text context) partially works but struggles with conversational period references like "this quarter", "fiscal year '25", "year-over-year"
- **Existing pattern gaps:**
  - "fiscal year '25" / "FY'25" — apostrophe year format not matched by FISCAL_YEAR_PATTERN
  - "Q4" without explicit year — needs call date as context
  - "year-over-year" — growth rate context, not period

## Measured Recall & Precision (Against Manual Annotations)

77 customer metrics were manually annotated across 8 transcripts (one per company with annotations: ADBE, ADSK, CRM, GDDY, META, MSFT, PYPL, TMUS).

### Aggregate Results

| Metric | Value |
|--------|-------|
| Total annotations | 77 |
| True positives | 17 |
| False negatives | 60 |
| False positives | 10 |
| **Recall** | **22.1%** |
| **Precision** | **63.0%** |
| **F1** | **32.7%** |

### Per-Company Results (Annotated Files)

| Company | Ticker | Annotations | TP | FN | FP | Recall | Precision | F1 |
|---------|--------|-------------|----|----|-----|--------|-----------|------|
| Adobe | ADBE | 11 | 4 | 7 | 2 | 36.4% | 66.7% | 47.1% |
| Autodesk | ADSK | 3 | 3 | 0 | 2 | 100% | 60.0% | 75.0% |
| Salesforce | CRM | 5 | 3 | 2 | 0 | 60.0% | 100% | 75.0% |
| GoDaddy | GDDY | 7 | 4 | 3 | 3 | 57.1% | 57.1% | 57.1% |
| Meta | META | 8 | 0 | 8 | 0 | 0% | — | 0% |
| Microsoft | MSFT | 16 | 3 | 13 | 0 | 18.8% | 100% | 31.6% |
| PayPal | PYPL | 13 | 0 | 13 | 3 | 0% | 0% | 0% |
| T-Mobile | TMUS | 14 | 0 | 14 | 0 | 0% | — | 0% |

### Key Observations

- **SaaS companies perform well:** ADSK (100%), CRM (60%), GDDY (57%), ADBE (36%) — these use standard ARR/subscriber vocabulary
- **Non-SaaS companies fail entirely:** META (0%), PYPL (0%), TMUS (0%) — domain-specific language not in keyword patterns
- **Precision is high where extraction occurs:** CRM (100%), MSFT (100%), ADBE (67%) — when facts are extracted, they're mostly correct
- **22.1% aggregate recall is well below the 50% target** but the gap analysis shows a clear path to improvement

**Why recall is low:**
1. **Vocabulary gaps** — Meta ("people using apps daily"), T-Mobile ("postpaid net adds"), PayPal ("active accounts") use non-standard language (accounts for ~35/60 FN)
2. **Value binding failures** — Keywords matched but values not bound due to narrow proximity windows (accounts for ~15/60 FN)
3. **FP filter over-filtering** — Legitimate values removed by SEC-tuned financial term adjacency rules (accounts for ~10/60 FN)

## Performance

| Metric | Value |
|--------|-------|
| Avg processing time | 72ms/file |
| Min processing time | 44ms (MSFT — short transcript) |
| Max processing time | 91ms (ADBE — long transcript) |
| Avg segments | 43 segments/file |
| Memory footprint | Negligible (no images, no large tables) |

Processing speed is excellent — 10x faster than SEC filings (which average 500-800ms due to table reconstruction and image processing).

## Key Findings

1. **Pipeline is architecturally sound for transcripts.** All 22 files processed without errors. The stage-based architecture handles the absence of tables and images gracefully.

2. **Keyword matching is the strong foundation.** Candidate generation works — the metric_keywords.yaml vocabulary covers earnings call language well for SaaS companies.

3. **Value binding needs adaptation.** Text-proximity binding needs wider search windows and sentence-level context awareness for conversational text.

4. **False positive filter needs transcript-specific rules.** Current rules are tuned for SEC filings. Transcripts need relaxed filtering or a separate rule set.

5. **Period inference needs transcript-aware patterns.** "Fiscal year '25", "this quarter", and "Q4" without explicit year are common in calls but not matched by current regex patterns.

6. **Industry-specific vocabulary gaps exist.** Companies like Meta, T-Mobile, and Intuit use domain-specific metric names that aren't in metric_keywords.yaml.

## Recommendations for Reaching 50% Recall

To close the gap from 22% to 50% recall:

| Change | Est. Impact | Effort |
|--------|-------------|--------|
| Widen text proximity window in value binding | +10% recall | Small |
| Add transcript-specific FP filter relaxations | +5% recall | Small |
| Add "fiscal year '25" pattern to period inference | +5% recall | Small |
| Add call-date fallback to period inference | +5% recall | Medium |
| Add "people using apps", "monthly actives" to MAU patterns | +3% recall | Small |
| Add telecom vocabulary ("postpaid adds", "subscribers") | +3% recall | Small |
| Sentence-level value binding (not just character proximity) | +5% recall | Medium |

Combined impact: estimated +28-36% recall improvement → **50-58% total recall**
