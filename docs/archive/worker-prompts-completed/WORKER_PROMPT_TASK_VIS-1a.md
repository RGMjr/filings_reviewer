# WORKER PROMPT: Task VIS-1a - Extended Chart Extraction Tool Evaluation

```
═══════════════════════════════════════════════════════════════════════════════
TASK ID:       VIS-1a
TASK NAME:     Extended evaluation: MatCha, WebPlotDigitizer, GPT-4o, and additional chart types
WORKSTREAM:    Visual Interpretation Research
SOURCE:        VIS-1 Critical Evaluation Follow-ups
STATUS:        🟡 PENDING
COMPLETION:    N/A
TIME ESTIMATE: 2-3 hours (MatCha: 45 min, WebPlotDigitizer: 45 min, GPT-4o: 30 min, chart types: 30 min, report update: 30 min)
TIME ACTUAL:   N/A
RISK LEVEL:    None (read-only research, no code changes)
TASK SIZE:     S
DEPENDS ON:    VIS-1 ✅ COMPLETE
UNLOCKS:       VIS-2 (final tool selection decision)
BLOCKS:        None
PARALLEL WITH: IMG-0-2, IMG-0-3 (independent research tracks)
═══════════════════════════════════════════════════════════════════════════════
```

## Objective

Extend VIS-1 research with additional tool evaluations and chart type testing to strengthen the tool selection recommendation for VIS-2.

**Business Rationale**: VIS-1 established that DePlot fails and LLM Vision (Claude) works well on stacked area cohort charts. Before committing to LLM Vision for VIS-2, we should:
1. Confirm MatCha (DePlot alternative) also fails
2. Evaluate WebPlotDigitizer as human-assisted fallback
3. Compare GPT-4o accuracy against Claude for cost/quality tradeoffs
4. Verify LLM Vision works on other SEC chart types (bar, line)

**Current Behavior**: VIS-1 tested only DePlot + Claude on only stacked area charts.

**Desired Behavior**: Comprehensive tool comparison across all viable options and chart types.

## Prerequisites

- VIS-1 complete with research report at `docs/research/VIS-1-chart-extraction-results.md`
- Test images already downloaded at `/tmp/slack_arr_cohort.jpg` and `/tmp/farfetch_gmv_cohort.jpg`

## Files to Create

1. **`docs/research/VIS-1a-extended-evaluation-results.md`** - Extended research report

## Files to Read (Context Only)

- `docs/research/VIS-1-chart-extraction-results.md` - VIS-1 baseline results
- `~/.claude/plans/zazzy-snacking-bentley.md` - Original exploration context

## Implementation Requirements

### 1. Test MatCha Model

Run Google MatCha (chart question answering model) on both test images:

```python
# Install: pip install transformers torch pillow
from transformers import Pix2StructProcessor, Pix2StructForConditionalGeneration
from PIL import Image

processor = Pix2StructProcessor.from_pretrained('google/matcha-chartqa')
model = Pix2StructForConditionalGeneration.from_pretrained('google/matcha-chartqa')

# Question-answering approach
questions = [
    "What cohorts are shown in this chart?",
    "What is the approximate total value in 2017?",
    "What metric does the Y-axis represent?"
]

for img_path in ['/tmp/slack_arr_cohort.jpg', '/tmp/farfetch_gmv_cohort.jpg']:
    image = Image.open(img_path)
    for question in questions:
        inputs = processor(images=image, text=question, return_tensors="pt")
        predictions = model.generate(**inputs, max_new_tokens=256)
        print(processor.decode(predictions[0], skip_special_tokens=True))
```

Document:
- Raw MatCha outputs (verbatim)
- Whether answers are accurate vs hallucinated
- Comparison to DePlot quality
- Whether Q&A approach is better than table extraction

### 2. Evaluate WebPlotDigitizer (Semi-Automated)

Test WebPlotDigitizer (https://automeris.io/WebPlotDigitizer/) manually:

1. Open WebPlotDigitizer in browser
2. Load Farfetch GMV chart (has Y-axis scale)
3. Calibrate axes (set 2010=0, 2017=7 on X; 0=0, 1000=1000 on Y)
4. Use "2D (X-Y) Plot" extraction mode
5. Trace the top boundary of each cohort band
6. Export data points

Document:
- Calibration effort required (time, difficulty)
- Extracted values vs visual estimates
- Accuracy for the 2017 total GMV (~920-950)
- Suitability for batch processing (verdict: suitable / not suitable)
- Note: Slack chart cannot be calibrated (no Y-axis) - document this limitation

### 3. Test GPT-4o Vision

Upload both images to ChatGPT (GPT-4o) with the same prompt used for Claude in VIS-1:

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

Document:
- Raw GPT-4o output (verbatim)
- Comparison to Claude output from VIS-1
- Any hallucinations or errors
- Notable differences in extraction approach or quality

### 4. Test Additional Chart Types

Find 2-3 different chart types from SEC filings in the database and test with LLM Vision:

Suggested chart types to find (search in gold standard filings):
- **Bar chart**: Customer count by period
- **Line chart**: Growth rate over time
- **Table-as-image**: Embedded tables rendered as images

For each chart:
1. Download image from SEC
2. Test with Claude Vision (same structured extraction prompt)
3. Document accuracy and any failure modes

### 5. Update Research Report

Create `docs/research/VIS-1a-extended-evaluation-results.md` with structure:

```markdown
# VIS-1a: Extended Chart Extraction Tool Evaluation

## Test Setup
- Date: YYYY-MM-DD
- Reference: VIS-1 baseline results

## MatCha Results

### Slack ARR Chart
[Q&A results for each question]

### Farfetch GMV Chart
[Q&A results for each question]

**Verdict**: [Better/Worse/Same as DePlot]

## WebPlotDigitizer Results

### Farfetch GMV Chart (Manual Calibration)
- Calibration time: [X minutes]
- Extracted values: [table]
- Accuracy: [comparison to visual estimates]

### Slack ARR Chart
- **Cannot calibrate** (no Y-axis scale)

**Verdict**: [Suitable/Not suitable for batch processing]

## GPT-4o Vision Results

### Slack ARR Chart
[Raw output, comparison to Claude]

### Farfetch GMV Chart
[Raw output, comparison to Claude]

**Comparison to Claude**:
| Aspect | Claude | GPT-4o |
|--------|--------|--------|
| Hallucination rate | X | Y |
| Value accuracy | X | Y |
| Structure understanding | X | Y |

**Verdict**: [Prefer Claude/Prefer GPT-4o/No significant difference]

## Additional Chart Types

### [Chart Type 1]: [Source]
[Results]

### [Chart Type 2]: [Source]
[Results]

**Verdict**: [LLM Vision generalizes well/poorly to other chart types]

## Updated Recommendation

**Final tool recommendation for VIS-2**: [Tool(s)]

**Rationale**: [Updated based on extended evaluation]

**Confidence level**: [High/Medium/Low]

## Appendix: Raw Outputs
[All raw outputs preserved]
```

## Acceptance Criteria

- [ ] MatCha tested on both images with raw outputs documented
- [ ] WebPlotDigitizer tested on Farfetch chart with calibration process documented
- [ ] GPT-4o tested on both images with comparison to Claude
- [ ] At least 2 additional chart types tested with LLM Vision
- [ ] Extended research report created at `docs/research/VIS-1a-extended-evaluation-results.md`
- [ ] Final tool recommendation updated (or confirmed) based on extended evaluation
- [ ] **NO source code changes made**

## Do NOT

- Modify any Python source files in `src/`
- Add dependencies to `requirements.txt`
- Create database migrations
- Implement extraction pipeline (that's VIS-2+)
- Skip WebPlotDigitizer just because it's manual - it's a valid fallback option
- Test charts that don't exist in the gold standard (stick to known filings)

## Verification Commands

```bash
# Verify MatCha model can be loaded
python3 -c "from transformers import Pix2StructProcessor; Pix2StructProcessor.from_pretrained('google/matcha-chartqa')"

# Verify report created
cat docs/research/VIS-1a-extended-evaluation-results.md | head -50

# Verify no code changes
git diff --name-only src/  # Should be empty
```

## Critical Evaluation Phase

**Task Size: S - Standard evaluation**

After completing research:
1. Verify report contains all required sections (MatCha, WebPlotDigitizer, GPT-4o, additional charts)
2. Check that all raw outputs are preserved in appendix
3. Ensure final recommendation is data-driven (not opinion)
4. Verify WebPlotDigitizer evaluation is fair (note manual effort required)
5. **User Approval**: Present findings before finalizing

## Reference

- **Issue source**: VIS-1 Critical Evaluation Follow-ups
- **Dependencies**: VIS-1 ✅ (baseline research complete)
- **Related**:
  - `docs/research/VIS-1-chart-extraction-results.md`
  - `~/.claude/plans/zazzy-snacking-bentley.md`
- **Tools**:
  - MatCha: https://huggingface.co/google/matcha-chartqa
  - WebPlotDigitizer: https://automeris.io/WebPlotDigitizer/
  - GPT-4o: https://chat.openai.com

---

**Last Updated**: 2026-01-11
**Format Version**: 2.6
