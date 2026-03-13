"""
Chart extraction prompt library for two-pass Vision API extraction.

Pass 1 (classification): Identify chart type, axis scales, legend entries — no value extraction.
Pass 2 (extraction): Type-specific extraction using Pass 1 context as structured priors.

All Pass 2 prompt functions accept a `pass1_context` dict and an optional
`interpolation_enabled` bool. When interpolation_enabled=True, instructions are
added to capture approximate values read from axis positions, marked with
`interpolated: true` and per-point `confidence`.
"""

from __future__ import annotations


def get_classification_prompt() -> str:
    """
    Pass 1 prompt: identify chart type, axis scales, legend, data label presence.

    Instructs the model to NOT extract values — only classify structure.

    Returns:
        Prompt string for Vision API Pass 1.
    """
    return """Analyze this chart image and identify its structural properties. Do NOT extract data values.

Your task is ONLY to classify the chart and describe its structure so a second pass can extract values accurately.

Return a JSON object with EXACTLY these keys:
- chart_type: One of "bar", "line", "pie", "stacked_bar", "area", "unknown" (string)
- has_data_labels: true if numeric values are printed directly on bars/lines/points, false otherwise (boolean)
- x_label: X-axis label text, empty string if not present (string)
- y_label: Y-axis label text, empty string if not present (string)
- y_min: Minimum Y-axis value from the axis scale, null if not readable (number or null)
- y_max: Maximum Y-axis value from the axis scale, null if not readable (number or null)
- y_ticks: List of Y-axis tick values visible on the axis scale (array of numbers, empty if not readable)
- x_categories: List of X-axis categories or date labels visible on the axis (array of strings, empty if not readable)
- legend_entries: List of series names from the legend (array of strings, empty if no legend)
- estimated_series_count: Number of distinct data series visible (integer)
- confidence: Your confidence in this classification, 0.0-1.0 (float)

IMPORTANT:
- Do NOT include actual data values in this response
- Focus on axis scale tick marks and min/max values — these are critical for accurate extraction
- If you cannot determine a value, use null or empty array rather than guessing

Example output:
{
  "chart_type": "area",
  "has_data_labels": false,
  "x_label": "Year",
  "y_label": "GMV (USDm)",
  "y_min": 0,
  "y_max": 1000,
  "y_ticks": [0, 200, 400, 600, 800, 1000],
  "x_categories": ["2015", "2016", "2017"],
  "legend_entries": ["New Consumers", "Existing Consumers"],
  "estimated_series_count": 2,
  "confidence": 0.9
}
"""


def _interpolation_instructions() -> str:
    """Return interpolation instructions to append when enabled."""
    return """
INTERPOLATION ENABLED: For data points without explicit labels, you MAY read approximate
values from axis positions. For any interpolated point, set:
  - "interpolated": true
  - "confidence": your per-point confidence (0.0-1.0, typically 0.5-0.8 for interpolated values)
For explicitly labeled points, set "interpolated": false and "confidence": 0.95.
"""


def _axis_context_block(pass1_context: dict) -> str:
    """Format Pass 1 axis/legend context as a structured prior for the prompt."""
    y_min = pass1_context.get("y_min")
    y_max = pass1_context.get("y_max")
    y_ticks = pass1_context.get("y_ticks", [])
    x_categories = pass1_context.get("x_categories", [])
    legend_entries = pass1_context.get("legend_entries", [])
    x_label = pass1_context.get("x_label", "")
    y_label = pass1_context.get("y_label", "")
    has_data_labels = pass1_context.get("has_data_labels", False)

    parts = ["CHART CONTEXT FROM PASS 1 CLASSIFICATION:"]
    if x_label:
        parts.append(f"- X-axis label: {x_label}")
    if y_label:
        parts.append(f"- Y-axis label: {y_label}")
    if y_min is not None or y_max is not None:
        parts.append(f"- Y-axis range: {y_min} to {y_max}")
    if y_ticks:
        parts.append(f"- Y-axis ticks: {y_ticks}")
    if x_categories:
        parts.append(f"- X categories: {x_categories}")
    if legend_entries:
        parts.append(f"- Legend entries: {legend_entries}")
    parts.append(
        f"- Data labels present: {'YES — extract labeled values' if has_data_labels else 'NO — no explicit labels'}"
    )
    return "\n".join(parts)


def get_bar_chart_prompt(pass1_context: dict, interpolation_enabled: bool = False) -> str:
    """
    Pass 2 prompt for bar charts (grouped or simple).

    Args:
        pass1_context: Classification result from Pass 1.
        interpolation_enabled: If True, allow approximate axis-read values.

    Returns:
        Prompt string for Vision API Pass 2.
    """
    axis_block = _axis_context_block(pass1_context)
    interp = _interpolation_instructions() if interpolation_enabled else ""
    return f"""Analyze this bar chart and extract all data values.

{axis_block}
{interp}
Use the axis context above to correctly interpret bar heights. The Y-axis range and tick marks
tell you the scale — use them to validate or read values.

Return a JSON object with:
- chart_type: "bar"
- title: Chart title if visible (string, empty if not)
- x_axis_label: X-axis label (string)
- y_axis_label: Y-axis label (string)
- confidence: Overall extraction confidence 0.0-1.0 (float)
- series: Array of series objects, each with:
  - name: Series name from legend (string)
  - points: Array of data point objects, each with:
    - x: Category or date label (string)
    - y: Numeric value (number)
    - label: The explicit label text shown on the bar, null if none (string or null)
    - interpolated: false for labeled values, true for axis-read approximations (boolean)
    - confidence: Per-point confidence 0.0-1.0 (float)
- annotations: Array of text annotations/callouts, each with:
  - text: Full annotation text (string)
  - value: Parsed numeric value or null (number or null)
  - unit: "percent", "currency", "count", or "" (string)
  - category: Category/segment reference (string)
  - period: Time period if mentioned (string)

RULES:
1. Each bar group corresponds to one X category
2. Different colored bars in same group are different series
3. Bar height corresponds to Y value — use axis ticks to read unlabeled bars only if interpolation is enabled
4. Validate extracted values against axis range: flag outliers
"""


def get_line_chart_prompt(pass1_context: dict, interpolation_enabled: bool = False) -> str:
    """
    Pass 2 prompt for line charts.

    Args:
        pass1_context: Classification result from Pass 1.
        interpolation_enabled: If True, allow approximate axis-read values.

    Returns:
        Prompt string for Vision API Pass 2.
    """
    axis_block = _axis_context_block(pass1_context)
    interp = _interpolation_instructions() if interpolation_enabled else ""
    return f"""Analyze this line chart and extract all data values.

{axis_block}
{interp}
Use the axis context to interpret data point positions on the Y axis.

Return a JSON object with:
- chart_type: "line"
- title: Chart title if visible (string, empty if not)
- x_axis_label: X-axis label (string)
- y_axis_label: Y-axis label (string)
- confidence: Overall extraction confidence 0.0-1.0 (float)
- series: Array of series objects (one per line), each with:
  - name: Series name from legend (string)
  - points: Array of data point objects, each with:
    - x: Category or date label (string)
    - y: Numeric value (number)
    - label: The explicit label text shown at this point, null if none (string or null)
    - interpolated: false for labeled values, true for axis-read approximations (boolean)
    - confidence: Per-point confidence 0.0-1.0 (float)
- annotations: Array of text annotations/callouts (same schema as above)

RULES:
1. Each distinct line is a separate series with its own legend entry
2. Data points are where the line changes direction or where labels appear
3. Use axis ticks to read point positions only if interpolation is enabled
"""


def get_pie_chart_prompt(pass1_context: dict, interpolation_enabled: bool = False) -> str:
    """
    Pass 2 prompt for pie/donut charts.

    Args:
        pass1_context: Classification result from Pass 1.
        interpolation_enabled: If True, allow estimated slice percentages.

    Returns:
        Prompt string for Vision API Pass 2.
    """
    axis_block = _axis_context_block(pass1_context)
    interp = _interpolation_instructions() if interpolation_enabled else ""
    return f"""Analyze this pie/donut chart and extract all slice values.

{axis_block}
{interp}
Pie chart slices should sum to 100% (or the total value if not percentage).

Return a JSON object with:
- chart_type: "pie"
- title: Chart title if visible (string, empty if not)
- x_axis_label: "" (pie charts have no X axis)
- y_axis_label: "" (pie charts have no Y axis)
- confidence: Overall extraction confidence 0.0-1.0 (float)
- series: One series representing the pie, with:
  - name: "pie" or chart title
  - points: Array of slice objects, each with:
    - x: Slice label/category (string)
    - y: Slice value (percentage or absolute, as shown) (number)
    - label: The explicit label shown on or near the slice, null if none (string or null)
    - interpolated: false for labeled slices, true for visually estimated slices (boolean)
    - confidence: Per-slice confidence 0.0-1.0 (float)
- annotations: Array of text annotations/callouts (same schema as above)

RULES:
1. Slice values should sum to 100 if percentages, or total value if absolute
2. Include slice label AND percentage if both are visible
3. Warn in your confidence score if slices don't sum to ~100%
"""


def get_stacked_bar_prompt(pass1_context: dict, interpolation_enabled: bool = False) -> str:
    """
    Pass 2 prompt for stacked bar charts.

    Args:
        pass1_context: Classification result from Pass 1.
        interpolation_enabled: If True, allow approximate axis-read values.

    Returns:
        Prompt string for Vision API Pass 2.
    """
    axis_block = _axis_context_block(pass1_context)
    interp = _interpolation_instructions() if interpolation_enabled else ""
    return f"""Analyze this stacked bar chart and extract all segment values.

{axis_block}
{interp}
In a stacked bar chart, each bar is divided into colored segments stacked on top of each other.
Each segment represents a different series/category.

Return a JSON object with:
- chart_type: "stacked_bar"
- title: Chart title if visible (string, empty if not)
- x_axis_label: X-axis label (string)
- y_axis_label: Y-axis label (string)
- confidence: Overall extraction confidence 0.0-1.0 (float)
- series: Array of series objects (one per stack segment color), each with:
  - name: Series name from legend (string)
  - points: Array of data point objects, each with:
    - x: Category or date label (string)
    - y: Segment value (absolute height of this segment, not cumulative) (number)
    - label: The explicit label shown in the segment, null if none (string or null)
    - interpolated: false for labeled segments, true for axis-estimated heights (boolean)
    - confidence: Per-point confidence 0.0-1.0 (float)
- annotations: Array of text annotations/callouts (same schema as above)

RULES:
1. Report INDIVIDUAL segment heights, not cumulative stack heights
2. Each color in the stack legend corresponds to one series
3. If labeled with percentages: report percentages; if labeled with absolutes: report absolutes
4. Use the Y-axis range to validate total bar heights
"""


def get_area_chart_prompt(pass1_context: dict, interpolation_enabled: bool = False) -> str:
    """
    Pass 2 prompt for area charts (stacked or overlapping).

    Args:
        pass1_context: Classification result from Pass 1.
        interpolation_enabled: If True, allow approximate axis-read values.

    Returns:
        Prompt string for Vision API Pass 2.
    """
    axis_block = _axis_context_block(pass1_context)
    interp = _interpolation_instructions() if interpolation_enabled else ""
    return f"""Analyze this area chart and extract all data values.

{axis_block}
{interp}
Area charts show filled regions under lines. They may be stacked (areas don't overlap) or
overlapping. The Y axis shows cumulative height for stacked, or individual series height for overlapping.

Return a JSON object with:
- chart_type: "area"
- title: Chart title if visible (string, empty if not)
- x_axis_label: X-axis label (string)
- y_axis_label: Y-axis label (string)
- confidence: Overall extraction confidence 0.0-1.0 (float)
- series: Array of series objects (one per filled area/color), each with:
  - name: Series name from legend (string)
  - points: Array of data point objects, each with:
    - x: Category or date label (string)
    - y: Value at this point (for stacked: individual layer height, not cumulative) (number)
    - label: The explicit label shown at this point, null if none (string or null)
    - interpolated: false for labeled points, true for axis-read approximations (boolean)
    - confidence: Per-point confidence 0.0-1.0 (float)
- annotations: Array of text annotations/callouts (same schema as above)

RULES:
1. For stacked area: report each layer's individual height (subtract lower boundary)
2. For overlapping area: report each series' absolute Y value
3. Annotations like "44.4% New Consumers" are common in cohort area charts — capture all of them
"""


def get_generic_chart_prompt(pass1_context: dict, interpolation_enabled: bool = False) -> str:
    """
    Pass 2 fallback prompt for unknown chart types.

    Args:
        pass1_context: Classification result from Pass 1.
        interpolation_enabled: If True, allow approximate axis-read values.

    Returns:
        Prompt string for Vision API Pass 2.
    """
    axis_block = _axis_context_block(pass1_context)
    interp = _interpolation_instructions() if interpolation_enabled else ""
    return f"""Analyze this chart and extract ONLY explicitly labeled data values.

{axis_block}
{interp}
DEFINITIONS:
- "data labels" = numeric values printed directly on data points (bars, lines, pie slices)
- "annotations" = floating text overlays, callouts, or percentage breakdowns

Return a JSON object with:
- chart_type: Your best guess of chart type (string)
- title: Chart title if visible (string, empty if not)
- x_axis_label: X-axis label (string)
- y_axis_label: Y-axis label (string)
- confidence: Extraction confidence 0.0-1.0 (float)
- series: Array of series objects, each with:
  - name: Series name from legend (string)
  - points: Array of data point objects, each with:
    - x: Category or date label (string)
    - y: Numeric value (number)
    - label: The explicit label text shown on chart, null if none (string or null)
    - interpolated: false for labeled values, true for axis-read approximations (boolean)
    - confidence: Per-point confidence 0.0-1.0 (float)
- annotations: Array of text annotations/callouts, each with:
  - text: Full annotation text (string)
  - value: Parsed numeric value or null (number or null)
  - unit: "percent", "currency", "count", or "" (string)
  - category: Category/segment reference (string)
  - period: Time period if mentioned (string)

RULES:
1. If no explicit labels exist and interpolation is disabled, return empty series
2. Always capture annotations — floating text with numbers
3. Use axis context from Pass 1 to validate values
"""


# Map from chart_type string to Pass 2 prompt function
_PROMPT_DISPATCH: dict[str, object] = {
    "bar": get_bar_chart_prompt,
    "line": get_line_chart_prompt,
    "pie": get_pie_chart_prompt,
    "stacked_bar": get_stacked_bar_prompt,
    "area": get_area_chart_prompt,
}


def get_pass2_prompt(
    chart_type: str, pass1_context: dict, interpolation_enabled: bool = False
) -> str:
    """
    Select and return the appropriate Pass 2 prompt for the given chart type.

    Args:
        chart_type: Chart type string from Pass 1 (e.g., "bar", "line", "pie").
        pass1_context: Full Pass 1 classification result dict.
        interpolation_enabled: If True, embed interpolation instructions.

    Returns:
        Prompt string for Vision API Pass 2.
    """
    fn = _PROMPT_DISPATCH.get(chart_type, get_generic_chart_prompt)
    return fn(pass1_context, interpolation_enabled=interpolation_enabled)  # type: ignore[call-arg]
