# GI-3: Richness Score Distribution Analysis

## Executive Summary

Analysis of 340 segments across 6 validation filings reveals critical bottlenecks in the richness scoring system:
- **Cohort detection is completely broken**: 0% of segments have `contains_cohort_breakdown=TRUE` despite rich cohort content in the filings
- **Maximum observed score is 7.00**, well below the theoretical maximum of 10.0
- **56% of segments score below 2.0**, indicating the formula heavily penalizes low-confidence segments

**Primary Recommendation**: Fix cohort pattern detection (GI-4) before adjusting weights (GI-6). The +1.5 cohort bonus is never applied, artificially capping achievable scores at 8.5.

## Methodology

- **Data source**: PostgreSQL database, `source_segments` table with goldmine enrichment fields
- **Filings analyzed**: 6 validation filings
  - ID 29: Farfetch Ltd (80 segments, avg 5.69)
  - ID 31: Snowflake (72 segments, avg 1.57)
  - ID 32: Snap (27 segments, avg 1.25)
  - ID 33: DocuSign (3 segments, avg 3.87)
  - ID 34: SUSHI GINZA ONODERA (80 segments, avg 1.97)
  - ID 35: Slack Technologies (78 segments, avg 2.28)
- **Total segments**: 340
- **Analysis date**: 2025-12-17
- **Related**: GI-1 (pattern gaps), GI-2 (Slack ground truth)

## Score Distribution

### Overall Distribution

```
Score Range  |  Count | Visual
------------------------------------------------------------
0.0 - 1.0     |     64 | ████████████████████
1.0 - 2.0     |    127 | ████████████████████████████████████████
2.0 - 3.0     |     42 | █████████████
3.0 - 4.0     |     18 | █████
4.0 - 5.0     |     13 | ████
5.0 - 6.0     |     45 | ██████████████
6.0 - 7.0     |      1 |
7.0 - 8.0     |     30 | █████████
8.0 - 9.0     |      0 |
9.0 - 10.0    |      0 |
```

**Key Observations**:
- Distribution is heavily left-skewed (56% below 2.0)
- Bimodal pattern with peaks at 1.0-2.0 and 7.0-8.0 (primarily Farfetch)
- No segments reach 8.0+ (high-value tier is empty)
- Only 31 segments (9.1%) qualify as goldmines (≥6.0)

### Per-Filing Statistics

| Filing | Company | Segments | Mean | Median | Max | P95 | P99 |
|--------|---------|----------|------|--------|-----|-----|-----|
| 29 | SUSHI GINZA ONODERA | 80 | 1.97 | 1.60 | 5.40 | 3.80 | 4.93 |
| 31 | Farfetch Ltd | 80 | 5.69 | 5.70 | 7.00 | 7.00 | 7.00 |
| 32 | Snowflake | 72 | 1.57 | 1.60 | 4.20 | 2.90 | 3.92 |
| 33 | Snap | 27 | 1.25 | 1.60 | 3.80 | 1.90 | 3.31 |
| 34 | DocuSign | 3 | 3.87 | 4.40 | 4.40 | 4.40 | 4.40 |
| 35 | Slack Technologies | 78 | 2.28 | 1.60 | 6.85 | 5.03 | 5.85 |

### Score Tier Distribution

| Tier | Count | % of Total |
|------|-------|------------|
| Below 2.0 | 191 | 56.2% |
| 2.0 - 3.99 | 60 | 17.6% |
| 4.0 - 5.99 | 58 | 17.1% |
| 6.0 - 7.99 (Goldmine) | 31 | 9.1% |
| 8.0+ (High-Value) | 0 | 0.0% |

### Distribution Analysis

**Farfetch Outlier Effect**: Farfetch (filing 31) dominates the high-scoring segments with an average of 5.69 vs 1.25-2.28 for other filings. This is due to:
- High classifier confidence (many metric-dense segments)
- Strong temporal trend detection
- High metric density

**Slack Underperformance**: Despite having one of the best customer metric disclosures (per GI-2), Slack averages only 2.28. This is caused by:
- 0% cohort detection (missing the +1.5 bonus)
- Many NRR-related segments scoring 5.0-5.55, just below threshold

## Component Contribution Analysis

### Boolean Flags

| Component | % TRUE | Count | Contribution | Bottleneck? |
|-----------|--------|-------|--------------|-------------|
| temporal_trend | 39.7% | 135 | +1.0 | No |
| cohort_breakdown | 0.0% | 0 | +1.5 | **CRITICAL** |
| definition_flag | 69.4% | 236 | +1.0 | No |

**Critical Finding**: The cohort_breakdown flag is NEVER TRUE across all 340 segments. This confirms GI-1's finding that all 9 cohort patterns have 100% miss rate. The +1.5 cohort bonus is completely wasted.

### Numeric Components

| Component | Mean | Median | Max | Contribution Range | Notes |
|-----------|------|--------|-----|-------------------|-------|
| classifier_confidence | 0.44 | 0.20 | 1.00 | 0-3.0 pts | Low median drives low base scores |
| distinct_metric_count | 0.90 | 0.00 | 7.00 | 0-2.0 pts | Median of 0 indicates many metric-sparse segments |
| image_count | 0.02 | 0.00 | 3.00 | 0-1.5 pts | Almost no visual content detected |

### Key Finding: Classifier Confidence is the Dominant Factor

With a mean of 0.44 and median of 0.20, classifier confidence contributes 0.6-1.32 points on average (0.20-0.44 × 3.0). Since many segments have low confidence, they start with a low base score before any bonuses.

**Score Composition Example** (typical segment):
- Base: 0.20 × 3.0 = 0.60 points
- Metrics: 0 × 0.5 = 0.00 points
- Temporal: FALSE = 0.00 points
- Cohort: FALSE = 0.00 points (NEVER TRUE)
- Definition: TRUE = 1.00 points
- Images: 0 × 0.5 = 0.00 points
- **Total: 1.60** (exactly the median)

## Theoretical vs Observed Maximum

| Metric | Value |
|--------|-------|
| Theoretical max (formula allows) | 10.0 |
| Achievable max (without cohort) | 8.5 |
| Observed max (in data) | 7.00 |
| Gap from theoretical | 3.00 points |
| Gap from achievable | 1.50 points |

### Why Segments Can't Reach Max

1. **Cohort detection = 0%** → missing +1.5 points universally
2. **Low image detection** → mean 0.02 vs max possible 1.5 points
3. **Metric count capped** → few segments reach the 4+ metrics needed for full 2.0 bonus
4. **Confidence variability** → only segments with 1.0 confidence can reach 3.0 base points

### Maximum Score Breakdown (Best Observed: 7.00)

Farfetch segments reaching 7.00 likely have:
- confidence: 1.00 × 3.0 = 3.00
- metrics: 4 × 0.5 = 2.00 (capped)
- temporal: TRUE = 1.00
- cohort: FALSE = 0.00 (pattern failure)
- definition: TRUE = 1.00
- images: 0 × 0.5 = 0.00
- **Total: 7.00**

If cohort detection worked, these could reach 8.50.

## Ground Truth Comparison (Slack)

Using GI-2 ground truth (25 goldmines identified):

### Detection by Threshold

| Threshold | Segments Above | % of Total | GT Recall Est. |
|-----------|----------------|------------|----------------|
| 4.0 | 14 | 17.9% | ~56% |
| 5.0 | 5 | 6.4% | ~20% |
| 5.5 | 2 | 2.6% | ~8% |
| 6.0 | 1 | 1.3% | **4%** |
| 7.0 | 0 | 0.0% | 0% |
| 8.0 | 0 | 0.0% | 0% |

### Top 10 Slack Segments by Richness

| Rank | Seg ID | Score | Conf | Metrics | Temporal | Cohort | Definition | Images |
|------|--------|-------|------|---------|----------|--------|------------|--------|
| 1 | 8744 | 6.85 | 0.95 | 4 | ✓ | - | ✓ | 0 |
| 2 | 8745 | 5.55 | 0.85 | 4 | - | - | ✓ | 0 |
| 3 | 8746 | 5.25 | 0.75 | 4 | ✓ | - | - | 0 |
| 4 | 8747 | 5.20 | 0.90 | 1 | ✓ | - | ✓ | 0 |
| 5 | 8748 | 5.00 | 1.00 | 2 | - | - | ✓ | 0 |
| 6 | 8752 | 4.10 | 0.70 | 2 | ✓ | - | - | 0 |
| 7 | 8751 | 4.10 | 0.70 | 2 | ✓ | - | - | 0 |
| 8 | 8750 | 4.10 | 0.70 | 2 | ✓ | - | - | 0 |
| 9 | 8749 | 4.10 | 0.70 | 2 | ✓ | - | - | 0 |
| 10 | 8756 | 4.10 | 0.70 | 2 | ✓ | - | - | 0 |

**Key Observation**: All top 10 segments have `cohort=FALSE` despite Slack's famous cohort ARR analysis. If cohort detection worked, segment 8744 could reach 8.35 (6.85 + 1.5).

### Slack Component Analysis

| Component | % TRUE | Contribution when TRUE |
|-----------|--------|------------------------|
| temporal_trend | 24.4% | +1.0 |
| cohort_breakdown | 0.0% | +1.5 |
| definition_flag | 60.3% | +1.0 |

### GI-2 Cross-Reference

| GT # | Description | Segment ID | Current Score | Target | Gap |
|------|-------------|------------|---------------|--------|-----|
| 3 | NRR 143% disclosure | 8745 | 5.55 | ≥7.0 | -1.45 |
| 4 | NRR trend table (171%→152%→143%) | 8744 | 6.85 | ≥8.0 | -1.15 |
| 5 | NRR methodology definition | 8746 | 5.25 | ≥6.0 | -0.75 |
| 7 | Paid Customer growth (37K→59K→88K) | 8744 | 6.85 | ≥7.0 | ✓ |
| 10 | DAU definition | 8761/8778 | 3.90 | ≥4.0 | -0.10 |

**System Performance**:
- Ground truth goldmines: 25
- System detected (≥6.0): 1
- **Recall: 4%**
- Average score of detectable GT goldmines: ~5.2

**Components most commonly missing on GT goldmines**:
1. `cohort_breakdown` (100% missing)
2. Insufficient classifier confidence for NRR/definition segments
3. Missing retention-specific keyword bonus

## Weight Adjustment Recommendations

### Recommendation 1: Add retention metric keyword bonus

- **Current**: No explicit NRR/retention boost
- **Proposed**: +1.0 if segment contains "Net Dollar Retention" or "dollar-based retention"
- **Rationale**: 87 snippets in GI-1 contain retention language. NRR is Slack's signature metric. GI-2 shows NRR segments score 5.0-5.55 but should be 6.5+.
- **Impact**: Would increase Slack goldmine scores by ~1.0, moving 5.55→6.55

### Recommendation 2: Implement cohort pattern detection fixes (GI-4 prerequisite)

- **Current**: +1.5 for cohort_breakdown but NEVER triggered (0% detection)
- **Proposed**: Add missing patterns per GI-1 analysis:
  - `r"fiscal year \d{4} cohort"` (32 snippets)
  - `r"ARR.{0,30}cohort"` (1 snippet)
  - `r"net\s+dollar\s+retention"` (87 snippets)
- **Rationale**: GI-1 confirms all 9 current cohort patterns have 100% miss rate against 479 cohort-related snippets.
- **Impact**: Would unlock +1.5 points for ~10% of segments, enabling scores to reach 8.5+

### Recommendation 3: Increase definition bonus with metric context

- **Current**: +1.0 for definition_flag
- **Proposed**: +1.5 if (definition_flag AND distinct_metric_count >= 2)
- **Rationale**: GI-2 shows definitions combined with metrics (e.g., DAU definition with 10M value) score only 3.90. These are high-value disclosures.
- **Impact**: Would affect ~30% of definition segments, increasing their scores by 0.5

### Recommendation 4: Add usage metric keyword bonus

- **Current**: No explicit DAU/MAU/engagement boost
- **Proposed**: +0.5 if segment contains "daily active users", "monthly active users", or "engagement"
- **Rationale**: GI-2 shows Slack's "10 million daily active users" segment scores 3.90. Usage metrics are core customer metrics.
- **Impact**: Would increase usage-related segment scores by ~0.5

## Threshold Recommendations

| Threshold | Current | Proposed | Rationale |
|-----------|---------|----------|-----------|
| GOLDMINE_THRESHOLD | 6.0 | 5.5 | GI-2 shows 5.0 captures 5x more goldmines than 6.0 (20% vs 4% recall). 5.5 balances precision/recall. |
| HIGH_VALUE_THRESHOLD | 8.0 | 7.5 | No segments reach 8.0; lowering to 7.5 enables meaningful high-value tier with current scores |

### Alternative: Keep Thresholds, Fix Detection

If cohort patterns are fixed (GI-4) and retention bonus is added, scores will naturally increase:
- Current top Slack segment: 6.85
- With cohort bonus: 8.35
- With retention bonus: 7.85

This could make the 6.0 threshold appropriate without lowering it.

## Appendix: Raw Data

### Score Distribution Raw

| Bin | Count | Cumulative % |
|-----|-------|--------------|
| 0.0-1.0 | 64 | 18.8% |
| 1.0-2.0 | 127 | 56.2% |
| 2.0-3.0 | 42 | 68.5% |
| 3.0-4.0 | 18 | 73.8% |
| 4.0-5.0 | 13 | 77.6% |
| 5.0-6.0 | 45 | 90.9% |
| 6.0-7.0 | 1 | 91.2% |
| 7.0-8.0 | 30 | 100.0% |
| 8.0-9.0 | 0 | 100.0% |
| 9.0-10.0 | 0 | 100.0% |

### Summary Statistics

| Statistic | Value |
|-----------|-------|
| Count | 340 |
| Mean | 2.79 |
| Median | 1.60 |
| Std Dev | 2.04 |
| Min | 0.00 |
| Max | 7.00 |
| P25 | 1.60 |
| P75 | 4.10 |
| P90 | 6.10 |
| P95 | 7.00 |
| P99 | 7.00 |

---

**Generated by**: `scripts/gi3_richness_analysis.py`
**Date**: 2025-12-17
**Task**: GI-3 (Analyze Richness Score Distribution)
