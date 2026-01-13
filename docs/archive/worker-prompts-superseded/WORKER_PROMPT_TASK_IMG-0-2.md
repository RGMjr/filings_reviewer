# WORKER PROMPT: Task IMG-0-2 - Chart Image Sample Analysis

```
═══════════════════════════════════════════════════════════════════════════════
TASK ID:       IMG-0-2
TASK NAME:     Manually analyze chart image sample to classify types and assess extraction value
WORKSTREAM:    Image Extraction Discovery
SOURCE:        .claude/plans/flickering-tumbling-kernighan.md
STATUS:        🟡 PENDING
COMPLETION:    N/A
TIME ESTIMATE: 2-3 hours (sampling: 30 min, analysis: 90 min, documentation: 30 min)
TIME ACTUAL:   N/A
RISK LEVEL:    None (manual analysis)
TASK SIZE:     M
DEPENDS ON:    IMG-0-1
UNLOCKS:       IMG-0-3
BLOCKS:        IMG-0-3
PARALLEL WITH: None
═══════════════════════════════════════════════════════════════════════════════
```

## Objective

Manually analyze a sample of discovered chart images to classify types, assess metric extraction value, and identify overlap with text-extracted values.

**Business Rationale**: The discovery script (IMG-0-1) tells us HOW MANY images exist. This task answers: Are they WORTH extracting? What types are they? Do they contain unique data not already in the text?

**Current Behavior**: We have a CSV inventory of chart images but no understanding of their contents.

**Desired Behavior**: A documented analysis with classification distribution, value assessment, and clear go/no-go recommendation data.

## Prerequisites

- IMG-0-1 complete (chart_image_inventory.csv exists)
- Access to SEC EDGAR to view actual images

## Files to Create

1. **`data/discovery/chart_image_analysis.csv`** - Detailed analysis of sampled images
2. **`docs/analysis/IMG-0-2_CHART_ANALYSIS.md`** - Summary analysis report

## Files to Read (Context Only)

- `data/discovery/chart_image_inventory.csv` - Output from IMG-0-1
- `data/gold_standard/metrics.csv` - Compare chart values against known extracted metrics

## Implementation Requirements

### Sampling Strategy

1. **Sample Size**: Analyze 30-50 images (representative sample)
   - At least 3 images per filing (if available)
   - Prioritize high-confidence cohort detections
   - Include some low/no-confidence images for comparison

2. **For Each Sampled Image, Record**:
   ```
   image_id, filing_id, image_url,
   chart_type (bar/line/cohort/table/pie/infographic/other),
   contains_metrics (yes/no),
   metric_types (customer_count, revenue, retention, etc.),
   values_in_text (yes/no/partial),
   extraction_difficulty (easy/medium/hard),
   notes
   ```

### Classification Categories

1. **Chart Types**:
   - `bar_simple` - Single-series bar chart
   - `bar_stacked` - Multi-series stacked bar
   - `line_simple` - Single-series line chart
   - `line_multi` - Multi-series line chart
   - `cohort_heatmap` - Cohort retention/revenue heatmap
   - `table_image` - Table rendered as image
   - `pie` - Pie chart
   - `infographic` - Mixed graphics/text
   - `other` - Decorative or uncategorizable

2. **Extraction Difficulty**:
   - `easy` - Clear axes, readable labels, simple structure
   - `medium` - Some ambiguity but interpretable
   - `hard` - Complex structure, overlapping elements, poor quality

3. **Value Overlap Assessment**:
   - `yes` - All chart values found in filing text
   - `partial` - Some values in text, some unique to chart
   - `no` - Chart contains unique data not in text

### Analysis Report Structure

```markdown
# IMG-0-2: Chart Image Analysis Report

## Executive Summary
- Total images analyzed: N
- Distribution by chart type: [table]
- % with extractable metrics: X%
- % with unique (not-in-text) values: Y%
- Recommendation: [GO / NO-GO / CONDITIONAL]

## Findings by Chart Type
[For each type: count, example filing, extraction feasibility]

## Value Assessment
- High-value images (unique metrics): N (X%)
- Duplicate images (values in text): N (X%)
- Decorative/low-value images: N (X%)

## Extraction Difficulty Distribution
- Easy: N%
- Medium: N%
- Hard: N%

## Recommendations
[Based on findings, recommend approach for Phase 1 or recommend not proceeding]
```

## Acceptance Criteria

- [ ] 30-50 images manually reviewed and classified
- [ ] Analysis CSV with all required columns
- [ ] Summary report with distribution statistics
- [ ] Overlap assessment (chart vs text values) for each image
- [ ] Clear extraction difficulty ratings
- [ ] Preliminary recommendation documented

## Do NOT

- Build automated classification (this is manual analysis)
- Download and store images locally (view via SEC EDGAR URLs)
- Modify any code files
- Make final go/no-go decision (that's IMG-0-3)

## Verification Commands

```bash
# Verify analysis CSV exists and has expected columns
head -1 data/discovery/chart_image_analysis.csv

# Count analyzed images
wc -l data/discovery/chart_image_analysis.csv

# Verify report exists
cat docs/analysis/IMG-0-2_CHART_ANALYSIS.md | head -50
```

---

**Last Updated**: 2026-01-11
**Format Version**: 2.6
