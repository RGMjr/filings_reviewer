"""
Prompt templates for LLM-based metric extraction.

This module contains carefully crafted prompts for:
- Value extraction (from tables and text)
- Definition extraction
- Methodology extraction
"""

import json
from typing import Any


class PromptTemplates:
    """Collection of prompt templates for metric extraction."""

    # System messages
    SYSTEM_VALUE_EXTRACTION = """You are an expert at extracting customer metrics from SEC S-1 and F-1 filings.

PRIORITY METRICS (focus on these first):

Core Metrics:
- New customers acquired (new adds, net new customers, customer growth)
- Customer count by tenure/acquisition cohort (customers segmented by when they joined)
- Revenue by cohort (revenue broken down by acquisition vintage)
- Transactions/purchases by cohort (transaction counts per cohort)

Extended Metrics:
- Customer acquisition cost (CAC)
- Active customers/users (MAU, DAU, active customer count)
- Customer retention rate / churn rate / attrition rate
- Net revenue retention (NRR) / Net dollar retention (NDR)
- Revenue per customer (ARPU, revenue per user)
- Revenue concentration (top customers, major customers)
- Gross margin (especially by cohort)
- Expansion/cross-sell metrics (products per customer, upsell)

Also extract:
- Customer lifetime value (LTV, CLV)
- LTV to CAC ratio
- Any other customer-related metrics disclosed

PAY SPECIAL ATTENTION TO:
- Cohort breakdowns (e.g., "2021 Cohort", "Year 1", "0-12 months")
- Tenure segmentation (e.g., "customers by age", "time since acquisition")
- Tables with cohort structures (row/column headers showing vintages or time periods)

Extract data precisely as disclosed. Do not infer or calculate values not explicitly stated.

CRITICAL: Only extract HISTORICAL data explicitly stated in the filing.
Do not extract: forward-looking projections, industry benchmarks, or hypothetical examples.

Ensure metric_name matches the value type (counts for customer numbers, percentages for rates).

CRITICAL - COMMON ERRORS TO AVOID:
1. DO NOT extract a number just because it appears near a metric keyword.
   WRONG: Text says "LTV:CAC Ratio of 8x. Revenue grew 83%." → Extract CAC=83%
   RIGHT: No CAC value is stated, so do not extract CAC.

2. The quote MUST contain BOTH the metric name/abbreviation AND the value.
   WRONG: Quote "Revenue grew 83%" for metric "CAC"
   RIGHT: Quote "Our CAC was $150" for metric "CAC"

3. If a metric is mentioned but no specific value is given, do NOT extract anything."""

    SYSTEM_DEFINITION_EXTRACTION = """You are an expert at extracting metric definitions from SEC filings.

Your task is to find and extract how companies define their customer metrics. Look for:
- Explicit definitions ("We define X as...")
- Calculation methodologies ("X is calculated by...")
- Measurement descriptions ("We measure X as...")

Extract the exact wording used in the filing."""

    @staticmethod
    def value_extraction_from_text(segment_text: str, metric_names: str) -> str:
        """
        Prompt for extracting metric values from text segments.

        Args:
            segment_text: The text segment to analyze
            metric_names: Comma-separated list of metric names to look for

        Returns:
            Formatted prompt
        """
        return f"""Extract customer metric values from this SEC filing text.

STRICT RULES - ONLY extract values that meet ALL criteria:
1. The text EXPLICITLY states the value IS the metric (not just near a keyword)
2. The value is HISTORICAL (not projected, expected, or hypothetical)
3. You can find an EXACT quote where the metric name and value appear together

CRITICAL: Do NOT extract a value just because it appears near a metric keyword.
The text must explicitly state the value represents the metric.

CORRECT extraction example:
"Our customer acquisition cost was $150 per customer" → CAC = $150
"We had 500,000 active users" → active_users = 500,000

INCORRECT extraction (do NOT do this):
Text: "We discuss CAC and our revenue was $10M" → DO NOT extract CAC = $10M
The revenue value is near CAC but does NOT represent CAC.

Metrics to look for: {metric_names}

TEXT SEGMENT:
{segment_text}

For each metric value you find, provide:
1. metric_name: The canonical metric type
2. value: The numeric value
3. units: Must match the metric type (CAC→dollars, retention→percent, customers→count)
4. period: The time period stated
5. cohort_label: If cohort-specific
6. quote: REQUIRED - The EXACT sentence explicitly stating "[metric] was/is [value]"

UNIT RULES:
- Customer Acquisition Cost: must be in dollars/currency, NOT percent
- Retention Rate, NRR, Churn: must be in percent
- Customer counts: must be in count/thousands/millions, NOT percent

Return a JSON array. If no valid metrics found, return [].

Example output:
[
  {{
    "metric_name": "monthly_active_users",
    "value": "10.5",
    "units": "millions",
    "period": "December 31, 2023",
    "cohort_label": null,
    "quote": "As of December 31, 2023, we had 10.5 million monthly active users."
  }}
]"""

    @staticmethod
    def value_extraction_from_table(
        table_text: str, table_html: str, metric_names: str
    ) -> str:
        """
        Prompt for extracting metric values from table segments.

        Args:
            table_text: The table content as text
            table_html: The table HTML for structure
            metric_names: Comma-separated list of metric names

        Returns:
            Formatted prompt
        """
        return f"""Extract customer metric values from this SEC filing table.

STRICT RULES - ONLY extract values that meet ALL criteria:
1. The row/column headers EXPLICITLY identify the metric type
2. The value CLEARLY represents the metric (not a different measure)
3. Units match the metric type (see rules below)

CRITICAL: The table header or row label MUST explicitly name the metric.
Do NOT infer metrics from context - they must be explicitly labeled.

UNIT RULES (values with wrong units are INVALID):
- Customer Acquisition Cost: dollars/currency only, NOT percent
- Retention Rate, NRR, Churn Rate: percent only
- Customer counts: count/thousands/millions, NOT percent
- Revenue: dollars/currency

Metrics to look for: {metric_names}

TABLE TEXT:
{table_text}

TABLE HTML (for structure):
{table_html[:1000]}...

For each valid metric value, provide:
1. metric_name: The canonical metric type from the list above
2. value: The numeric value
3. units: Must match metric type requirements
4. period: Time period from column header
5. cohort_label: If cohort-specific (e.g., "2021 Cohort")
6. row_label: The EXACT row label from the table
7. column_label: The EXACT column label from the table
8. quote: The cell value as it appears in the table

SKIP these:
- Totals when individual values are available
- Pro forma figures when GAAP exists
- Values where the metric type is ambiguous

Return a JSON array. If no valid metrics found, return [].

Example output:
[
  {{
    "metric_name": "net_revenue_retention",
    "value": "130",
    "units": "percent",
    "period": "Year 2",
    "cohort_label": "2021 Cohort",
    "row_label": "2021 Cohort",
    "column_label": "NRR Year 2",
    "quote": "130%"
  }}
]"""

    @staticmethod
    def definition_extraction(segment_text: str, metric_names: str) -> str:
        """
        Prompt for extracting metric definitions.

        Args:
            segment_text: The text segment to analyze
            metric_names: Comma-separated list of metric names

        Returns:
            Formatted prompt
        """
        return f"""Analyze the following text segment and extract any customer metric definitions.

Metrics to look for: {metric_names}

TEXT SEGMENT:
{segment_text}

Extract all metric definitions you find. Look for phrases like:
- "We define X as..."
- "X means..."
- "X refers to..."
- "We measure X as..."
- "X is calculated by..."

For each definition, provide:
1. metric_name: The type of metric being defined
2. definition_text: The exact definition as stated in the filing
3. includes_calculation: true if it explains how the metric is calculated
4. quote: The EXACT text from the filing containing the definition - copy verbatim, do not paraphrase

Return your response as a JSON array of objects. If no definitions found, return an empty array [].

Example output:
[
  {{
    "metric_name": "monthly_active_users",
    "definition_text": "users who have logged in at least once in a calendar month",
    "includes_calculation": false,
    "quote": "We define monthly active users as users who have logged in at least once in a calendar month."
  }},
  {{
    "metric_name": "net_revenue_retention",
    "definition_text": "the revenue from existing customers at the end of the period divided by revenue from those same customers at the beginning",
    "includes_calculation": true,
    "quote": "Net revenue retention is calculated as the revenue from existing customers at the end of the period divided by revenue from those same customers at the beginning of the period."
  }}
]"""

    @staticmethod
    def classification_prompt(segment_text: str) -> str:
        """
        Prompt for classifying segments by content type.

        Args:
            segment_text: The text segment to analyze

        Returns:
            Formatted prompt
        """
        return f"""Analyze this text segment from an SEC filing and classify what types of customer metric content it contains.

TEXT SEGMENT:
{segment_text}

Classify the segment by marking which types of content are present:
1. contains_numeric_values: Does it contain specific numeric metric values? (not just mentioning metrics)
2. contains_definition: Does it define what a metric means?
3. contains_methodology: Does it explain how a metric is calculated or measured?
4. metric_categories: List the types of metrics mentioned (e.g., ["active_users", "retention", "churn"])

Return your response as a JSON object:
{{
  "contains_numeric_values": true/false,
  "contains_definition": true/false,
  "contains_methodology": true/false,
  "metric_categories": ["category1", "category2", ...]
}}

Example:
{{
  "contains_numeric_values": true,
  "contains_definition": true,
  "contains_methodology": false,
  "metric_categories": ["monthly_active_users", "customer_count"]
}}"""

    @staticmethod
    def parse_json_response(response_text: str) -> Any:
        """
        Parse JSON response from LLM, handling common issues.

        Args:
            response_text: Raw response from LLM

        Returns:
            Parsed JSON object

        Raises:
            ValueError: If JSON cannot be parsed
        """
        # Remove markdown code blocks if present
        text = response_text.strip()
        if text.startswith("```json"):
            text = text[7:]
        if text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]

        text = text.strip()

        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            # Try to find JSON in the response
            import re

            json_match = re.search(r"\[.*\]|\{.*\}", text, re.DOTALL)
            if json_match:
                try:
                    return json.loads(json_match.group(0))
                except json.JSONDecodeError:
                    pass

            raise ValueError(f"Failed to parse JSON response: {e}\n\nResponse: {text}")

    @staticmethod
    def validate_value_extraction_response(data: Any) -> bool:
        """
        Validate that value extraction response has correct structure.

        Args:
            data: Parsed JSON response

        Returns:
            True if valid, False otherwise
        """
        if not isinstance(data, list):
            return False

        for item in data:
            if not isinstance(item, dict):
                return False
            # Check required fields
            required = ["metric_name", "value", "period"]
            if not all(field in item for field in required):
                return False

        return True

    @staticmethod
    def validate_definition_extraction_response(data: Any) -> bool:
        """
        Validate that definition extraction response has correct structure.

        Args:
            data: Parsed JSON response

        Returns:
            True if valid, False otherwise
        """
        if not isinstance(data, list):
            return False

        for item in data:
            if not isinstance(item, dict):
                return False
            # Check required fields
            required = ["metric_name", "definition_text", "quote"]
            if not all(field in item for field in required):
                return False

        return True
