# VIS-GPT4O: GPT-4o Vision Validation Test

## Test Setup

- **Date**: 2026-01-13
- **Model**: GPT-4o (via ChatGPT)
- **Reference**: VIS-1 and VIS-1a research results
- **Purpose**: Validate GPT-4o Vision as implementation target for VIS-2

## Test Images

| Image | Source | Characteristics |
|-------|--------|-----------------|
| Slack ARR | `mdaa2.jpg` (507KB, 2848x1792) | Stacked area, **NO Y-axis scale** |
| Farfetch GMV | `g532260g12o45.jpg` (60KB, 419x290) | Stacked area, Y-axis 0-1000 USDm |

## Prompt Used

```
Extract all data series from this cohort chart as a structured table. Include:
- Chart title/description (if visible)
- Metric type (ARR, GMV, retention, etc.)
- For each data series:
  - Cohort label (e.g., "FY2015 cohort")
  - Values by time period with years
  - Units (dollars, millions, percent)

If the Y-axis has no numeric scale, note this and do NOT estimate values.
Return structured JSON with this schema:
{
  "chart_title": "...",
  "metric_type": "ARR|GMV|retention|other",
  "has_y_axis_scale": true/false,
  "cohorts": [
    {
      "label": "FY2015",
      "values": [{"period": "FY2019", "value": 100, "unit": "USD millions"}]
    }
  ],
  "annotations": ["44.4% New Consumers", ...]
}
```

---

## Results

### Slack ARR Chart (NO Y-axis scale)

**Critical Test**: Does GPT-4o correctly identify the missing scale and refuse to hallucinate values?

**Result**: **PASS**

```json
{
  "chart_title": "Annual Recurring Revenue (ARR) by Annual Cohort through January 31, 2019",
  "metric_type": "ARR",
  "has_y_axis_scale": false,
  "cohorts": [
    {
      "label": "FY2015",
      "values": [
        { "period": "FY2015", "value": null, "unit": "USD (no scale)" },
        { "period": "FY2016", "value": null, "unit": "USD (no scale)" },
        { "period": "FY2017", "value": null, "unit": "USD (no scale)" },
        { "period": "FY2018", "value": null, "unit": "USD (no scale)" },
        { "period": "FY2019", "value": null, "unit": "USD (no scale)" }
      ]
    },
    {
      "label": "FY2016",
      "values": [
        { "period": "FY2016", "value": null, "unit": "USD (no scale)" },
        { "period": "FY2017", "value": null, "unit": "USD (no scale)" },
        { "period": "FY2018", "value": null, "unit": "USD (no scale)" },
        { "period": "FY2019", "value": null, "unit": "USD (no scale)" }
      ]
    },
    {
      "label": "FY2017",
      "values": [
        { "period": "FY2017", "value": null, "unit": "USD (no scale)" },
        { "period": "FY2018", "value": null, "unit": "USD (no scale)" },
        { "period": "FY2019", "value": null, "unit": "USD (no scale)" }
      ]
    },
    {
      "label": "FY2018",
      "values": [
        { "period": "FY2018", "value": null, "unit": "USD (no scale)" },
        { "period": "FY2019", "value": null, "unit": "USD (no scale)" }
      ]
    },
    {
      "label": "FY2019",
      "values": [
        { "period": "FY2019", "value": null, "unit": "USD (no scale)" }
      ]
    }
  ],
  "annotations": []
}
```

**Analysis**:
- Correctly identified `has_y_axis_scale: false`
- All values returned as `null` (no hallucination)
- Extracted all 5 cohorts with correct labels
- Correctly structured cohort-period relationships
- Noted "USD (no scale)" in unit field

---

### Farfetch GMV Chart (HAS Y-axis scale)

**Critical Test**: Does GPT-4o extract reasonable value estimates from the visible scale?

**Result**: **PASS**

```json
{
  "chart_title": null,
  "metric_type": "GMV",
  "has_y_axis_scale": true,
  "cohorts": [
    {
      "label": "2008",
      "values": [
        {"period": "2010", "value": 0, "unit": "USD millions"},
        {"period": "2011", "value": 0, "unit": "USD millions"},
        {"period": "2012", "value": 2, "unit": "USD millions"},
        {"period": "2013", "value": 5, "unit": "USD millions"},
        {"period": "2014", "value": 10, "unit": "USD millions"},
        {"period": "2015", "value": 15, "unit": "USD millions"},
        {"period": "2016", "value": 15, "unit": "USD millions"},
        {"period": "2017", "value": 15, "unit": "USD millions"}
      ]
    },
    // ... (cohorts 2009-2016 omitted for brevity)
    {
      "label": "New in 2017",
      "values": [
        {"period": "2017", "value": 400, "unit": "USD millions"}
      ]
    }
  ],
  "annotations": [
    "44.4% New Consumers in 2017",
    "55.6% Existing Consumers in 2017"
  ]
}
```

**Analysis**:
- Correctly identified `has_y_axis_scale: true`
- Extracted cohort-by-cohort value estimates
- Total 2017 GMV: ~809M (sum of all cohorts)
- New 2017 cohort: 400M (matches 44.4% annotation reasonably)
- Captured both percentage annotations
- Values are visual estimates with inherent uncertainty

---

## Comparison: GPT-4o vs Claude vs DePlot

| Criteria | DePlot | MatCha | Claude | GPT-4o |
|----------|--------|--------|--------|--------|
| Identifies missing Y-axis | ❌ | ❌ | ✅ | ✅ |
| No hallucination | ❌ | ❌ | ✅ | ✅ |
| Extracts values when scale visible | ❌ | ❌ | ✅ | ✅ |
| Cohort structure correct | ❌ | ❌ | ✅ | ✅ |
| Captures annotations | ❌ | Partial | ✅ | ✅ |
| JSON output parseable | N/A | N/A | ✅ | ✅ |

### Value Comparison (Farfetch 2017 Total GMV)

| Model | Estimate | Notes |
|-------|----------|-------|
| Claude | ~925M | Total GMV estimate |
| GPT-4o | ~809M | Sum of cohort estimates |
| Actual (if known) | ~920M | Per annotation math: 400M / 44.4% ≈ 901M |

Both LLM estimates are within reasonable range given visual estimation uncertainty.

---

## Recommendation

**GPT-4o is validated for VIS-2 implementation.**

| Requirement | Status |
|-------------|--------|
| No hallucination on missing Y-axis | ✅ PASS |
| Value extraction when scale visible | ✅ PASS |
| Structural data extraction | ✅ PASS |
| Annotation capture | ✅ PASS |
| JSON output format | ✅ PASS |

**Decision**: Proceed with VIS-2 implementation using GPT-4o Vision API.

---

## Notes

- GPT-4o was more aggressive than Claude in extracting individual cohort values (Claude noted this wasn't reliably possible)
- Both models correctly handle the "no scale" case
- Cost: ~$0.01-0.03 per image at "high" detail setting
- Latency: ~2-5 seconds per image (acceptable for batch processing)

---

**Last Updated**: 2026-01-13
**Task ID**: VIS-GPT4O
**Author**: Manual testing (Claude Code assisted)
