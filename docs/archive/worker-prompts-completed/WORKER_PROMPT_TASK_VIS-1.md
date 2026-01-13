# WORKER PROMPT: Task VIS-1 - Chart Extraction Tool Accuracy Evaluation

```
═══════════════════════════════════════════════════════════════════════════════
TASK ID:       VIS-1
TASK NAME:     Evaluate DePlot and LLM Vision accuracy on Slack/Farfetch cohort charts
WORKSTREAM:    Visual Interpretation Research
SOURCE:        ~/.claude/plans/zazzy-snacking-bentley.md (Phase 1)
STATUS:        🟡 PENDING
COMPLETION:    N/A
TIME ESTIMATE: 1-2 hours (download: 15 min, DePlot: 30 min, LLM: 30 min, report: 30 min)
TIME ACTUAL:   N/A
RISK LEVEL:    None (read-only research, no code changes)
TASK SIZE:     S
DEPENDS ON:    None
UNLOCKS:       VIS-2 (tool selection decision)
BLOCKS:        None
PARALLEL WITH: IMG-0-1, IMG-0-2 (independent research tracks)
═══════════════════════════════════════════════════════════════════════════════
```

## Objective

Empirically test chart-to-table extraction tools (Google DePlot and LLM Vision) on actual SEC filing cohort charts from Slack and Farfetch gold standard filings to determine extraction accuracy.

**Business Rationale**: The gold standard contains metrics marked `value_numeric = "chart"` that exist ONLY in images (ARR by cohort, GMV by cohort). Without visual interpretation, these cannot be extracted. This research determines which tool(s) can accurately extract values before investing in pipeline implementation.

**Current Behavior**: `CohortChartDetector` can identify WHERE charts appear but cannot extract WHAT values they contain.

**Desired Behavior**: Empirical accuracy data (precision/recall) for DePlot and LLM Vision on known gold standard charts, with a clear tool recommendation.

## Prerequisites

- None (standalone research task)
- Optional: GPU for faster DePlot inference (CPU works but slower)

## Files to Create

1. **`docs/research/VIS-1-chart-extraction-results.md`** - Research report with findings

## Files to Read (Context Only)

- `data/gold_standard/Slack_Technologies/extracted_values.csv` - Expected Slack values
- `data/gold_standard/Farfetch_Ltd/extracted_values.csv` - Expected Farfetch values
- `~/.claude/plans/zazzy-snacking-bentley.md` - Full exploration context

## Implementation Requirements

### 1. Download Test Images

Download two cohort chart images from SEC EDGAR:

```bash
# Slack ARR by cohort (mdaa2.jpg)
curl -A "CMASB Research contact@example.com" \
  "https://www.sec.gov/Archives/edgar/data/1764925/000162828019007428/mdaa2.jpg" \
  -o /tmp/slack_arr_cohort.jpg

# Farfetch GMV by cohort (g532260g12o45.jpg)
curl -A "CMASB Research contact@example.com" \
  "https://www.sec.gov/Archives/edgar/data/1740915/000119312518252315/g532260g12o45.jpg" \
  -o /tmp/farfetch_gmv_cohort.jpg
```

Verify downloads are valid images (file size > 10KB, not HTML error pages).

### 2. Test Google DePlot

Run DePlot chart-to-table model on both images:

```python
# Install: pip install transformers torch pillow
from transformers import Pix2StructProcessor, Pix2StructForConditionalGeneration
from PIL import Image

processor = Pix2StructProcessor.from_pretrained('google/deplot')
model = Pix2StructForConditionalGeneration.from_pretrained('google/deplot')

for img_path in ['/tmp/slack_arr_cohort.jpg', '/tmp/farfetch_gmv_cohort.jpg']:
    image = Image.open(img_path)
    inputs = processor(
        images=image,
        text="Generate underlying data table of the figure below:",
        return_tensors="pt"
    )
    predictions = model.generate(**inputs, max_new_tokens=512)
    print(f"\n=== {img_path} ===")
    print(processor.decode(predictions[0], skip_special_tokens=True))
```

Document for each image:
- Raw DePlot output (verbatim)
- Whether output is parseable as structured data
- Values extracted vs. values missed
- Any obvious errors

### 3. Test LLM Vision

Upload each image to Claude.ai or ChatGPT with prompt:

```
Extract all data series from this cohort chart as a structured table. Include:
- Chart title/description (if visible)
- Metric type (ARR, GMV, retention, etc.)
- For each data series:
  - Cohort label (e.g., "FY2015 cohort")
  - Values by time period with years
  - Units (dollars, millions, percent)

Return as a markdown table.
```

Document for each image:
- LLM used (Claude 3.5 Sonnet / GPT-4o / etc.)
- Raw output (verbatim)
- Values extracted vs. expected
- Any hallucinations or errors

### 4. Calculate Accuracy Metrics

**Expected values from gold standard**:

Slack (`data/gold_standard/Slack_Technologies/extracted_values.csv`):
- Row with `metric_id = cm_arr` and `value_numeric = chart`
- Notes describe: ARR by cohort for FY2015-FY2019

Farfetch (`data/gold_standard/Farfetch_Ltd/extracted_values.csv`):
- Row with `metric_id = cm_revenue_by_cohort` and `value_numeric = chart`
- Notes describe: GMV by consumer cohort for 2017

For each tool on each image, calculate:
- **Precision**: (correct values extracted) / (total values extracted)
- **Recall**: (correct values extracted) / (total values in chart)
- **Structure**: Did it identify cohort groupings correctly? (Yes/Partial/No)

### 5. Write Research Report

Create `docs/research/VIS-1-chart-extraction-results.md` with structure:

```markdown
# VIS-1: Chart Extraction Tool Accuracy Evaluation

## Test Setup
- Date: YYYY-MM-DD
- Images: Slack ARR cohort, Farfetch GMV cohort
- Tools: DePlot (google/deplot), [LLM model]

## DePlot Results

### Slack ARR Chart
**Raw Output**:
[paste verbatim]

**Parsed Values**:
| Cohort | FY2015 | FY2016 | FY2017 | FY2018 | FY2019 |
|--------|--------|--------|--------|--------|--------|
| ... | ... | ... | ... | ... | ... |

**Accuracy**: Precision X%, Recall X%
**Notes**: [observations]

### Farfetch GMV Chart
[same structure]

## LLM Vision Results
[same structure for each image]

## Comparison Summary

| Tool | Slack Precision | Slack Recall | Farfetch Precision | Farfetch Recall |
|------|-----------------|--------------|--------------------| ----------------|
| DePlot | X% | X% | X% | X% |
| LLM Vision | X% | X% | X% | X% |

## Recommendation

**Recommended tool for VIS-2**: [DePlot / LLM Vision / Hybrid / Neither]

**Rationale**: [2-3 sentences explaining choice]

## Failure Modes
- [List systematic issues discovered]

## Next Steps
- [Recommendations for VIS-2]
```

## Acceptance Criteria

- [ ] Both chart images downloaded from SEC and verified as valid
- [ ] DePlot tested on both images with raw output documented
- [ ] LLM Vision tested on both images with raw output documented
- [ ] Precision/recall calculated for each tool × image combination
- [ ] Research report created at `docs/research/VIS-1-chart-extraction-results.md`
- [ ] Clear tool recommendation made based on empirical results
- [ ] **NO source code changes made**

## Do NOT

- Modify any Python source files in `src/`
- Add dependencies to `requirements.txt`
- Create database migrations
- Implement extraction pipeline (that's VIS-2+)
- Commit changes to `main` branch

## Verification Commands

```bash
# Verify images downloaded
ls -la /tmp/slack_arr_cohort.jpg /tmp/farfetch_gmv_cohort.jpg

# Verify report created
cat docs/research/VIS-1-chart-extraction-results.md | head -50

# Verify no code changes
git diff --name-only  # Should only show docs/research/ if anything
```

## Critical Evaluation Phase

**Task Size: S - Standard evaluation**

After completing research:
1. Verify report contains all required sections
2. Check that accuracy metrics are calculated correctly
3. Ensure recommendation is supported by data (not opinion)
4. Consider if additional tools worth testing (WebPlotDigitizer, MatCha)
5. **User Approval**: Present findings before finalizing

## Reference

- **Issue source**: Visual Metric Interpretation Exploration (`~/.claude/plans/zazzy-snacking-bentley.md`)
- **Gold standard**: `data/gold_standard/Slack_Technologies/`, `data/gold_standard/Farfetch_Ltd/`
- **Tools**:
  - DePlot: https://huggingface.co/google/deplot
  - MatCha: https://huggingface.co/google/matcha-chartqa
  - WebPlotDigitizer: https://automeris.io/WebPlotDigitizer/

---

**Last Updated**: 2026-01-11
**Format Version**: 2.6
