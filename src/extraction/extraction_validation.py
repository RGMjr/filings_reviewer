"""
Extraction Validation Module

Provides post-extraction validation to catch common extraction errors:
1. Unit validation - Ensure units match metric types
2. Range validation - Ensure values are within expected ranges
3. Keyword validation - Ensure metric keyword appears in source
4. Quote validation - Reject extractions without verified quotes

This module is designed to filter out false positives before storing extractions.
"""

import logging
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class ValidationResult(Enum):
    """Result of validation check."""

    PASS = "pass"
    FAIL_UNIT = "fail_unit"
    FAIL_RANGE = "fail_range"
    FAIL_KEYWORD = "fail_keyword"
    FAIL_QUOTE = "fail_quote"
    WARN = "warn"


@dataclass
class ValidationIssue:
    """Describes a validation issue found."""

    result: ValidationResult
    metric_id: str
    value: float
    unit: str | None
    message: str
    source_preview: str | None = None


# Metric unit rules: metric_id -> (allowed_units, expected_unit_category)
METRIC_UNIT_RULES: dict[str, tuple[list[str], str]] = {
    # Revenue/Money metrics - should be currency
    "cm_customer_acquisition_cost": (
        ["dollars", "usd", "$", "millions", "thousands", "billions", None],
        "currency",
    ),
    "cm_revenue_per_customer": (
        ["dollars", "usd", "$", "millions", "thousands", "billions", None],
        "currency",
    ),
    "cm_expansion_revenue": (
        ["dollars", "usd", "$", "millions", "thousands", "billions", "percent", "%", None],
        "currency_or_percent",
    ),
    "cm_ltv": (["dollars", "usd", "$", "millions", "thousands", None], "currency"),
    "cm_revenue_by_cohort": (
        ["dollars", "usd", "$", "millions", "thousands", "billions", None],
        "currency",
    ),
    "cm_revenue_concentration": (
        ["percent", "%", "dollars", "usd", "$", "millions", None],
        "percent_or_currency",
    ),
    # Rate/Percentage metrics - should be percent
    "cm_customer_retention_rate": (["percent", "%", None], "percent"),
    "cm_churn_rate": (["percent", "%", None], "percent"),
    "cm_net_revenue_retention": (["percent", "%", None], "percent"),
    "cm_gross_revenue_retention": (["percent", "%", None], "percent"),
    "cm_gross_margin_by_cohort": (["percent", "%", None], "percent"),
    "cm_ltv_cac_ratio": (["ratio", "x", "times", None], "ratio"),
    # Count metrics - should be count/number
    "cm_active_customers_total": (
        ["count", "customers", "users", "thousands", "millions", None],
        "count",
    ),
    "cm_new_customers_acquired": (
        ["count", "customers", "users", "thousands", "millions", None],
        "count",
    ),
    "cm_customers_by_tenure": (
        ["count", "customers", "users", "thousands", "millions", None],
        "count",
    ),
    "cm_transactions_by_cohort": (
        ["count", "transactions", "thousands", "millions", None],
        "count",
    ),
}

# Metric range rules: metric_id -> (min_value, max_value, typical_min, typical_max)
METRIC_RANGE_RULES: dict[str, tuple[float | None, float | None, float, float]] = {
    # Retention/NRR typically 50-200%
    "cm_customer_retention_rate": (0, 100, 50, 99),
    "cm_net_revenue_retention": (0, 300, 80, 180),
    "cm_gross_revenue_retention": (0, 100, 50, 99),
    # Churn typically 0-50%
    "cm_churn_rate": (0, 100, 0.1, 30),
    # Gross margin typically 0-100%
    "cm_gross_margin_by_cohort": (-50, 100, 20, 90),
    # LTV:CAC ratio typically 1-10x
    "cm_ltv_cac_ratio": (0, 100, 1, 10),
    # Customer counts - wide range but not astronomical
    "cm_active_customers_total": (0, 1e12, 100, 1e9),
    "cm_new_customers_acquired": (0, 1e12, 10, 1e8),
    # CAC typically $10 - $10,000
    "cm_customer_acquisition_cost": (0, 1e9, 10, 10000),
    # Revenue concentration typically 1-100%
    "cm_revenue_concentration": (0, 100, 1, 50),
}

# Keywords that should appear in source for each metric
METRIC_KEYWORDS: dict[str, list[str]] = {
    "cm_customer_acquisition_cost": [
        "acquisition cost",
        "cac",
        "cost to acquire",
        "customer acquisition",
        "cost per customer",
        "cost per acquisition",
    ],
    "cm_net_revenue_retention": [
        "net revenue retention",
        "nrr",
        "net dollar retention",
        "ndr",
        "dollar-based net retention",
        "net retention",
    ],
    "cm_customer_retention_rate": ["retention rate", "customer retention", "retention", "retain"],
    "cm_churn_rate": ["churn", "attrition", "cancellation rate", "customer loss"],
    "cm_new_customers_acquired": [
        "new customer",
        "customer acquired",
        "new user",
        "customer addition",
        "net new",
        "acquired",
    ],
    "cm_active_customers_total": [
        "active customer",
        "active user",
        "total customer",
        "customer count",
        "paying customer",
        "subscriber",
        "core customer",
    ],
    "cm_expansion_revenue": ["expansion", "upsell", "cross-sell", "upgrade", "expansion revenue"],
    "cm_gross_margin_by_cohort": ["gross margin", "margin", "cohort", "gross profit"],
    "cm_revenue_by_cohort": ["cohort", "revenue", "vintage", "acquisition year"],
    "cm_revenue_concentration": [
        "concentration",
        "top customer",
        "largest customer",
        "major customer",
    ],
    "cm_ltv": ["lifetime value", "ltv", "clv", "customer lifetime"],
    "cm_ltv_cac_ratio": ["ltv", "cac", "ratio", "lifetime value"],
}


def normalize_unit(unit: str | None) -> str | None:
    """Normalize unit string for comparison."""
    if not unit:
        return None

    unit_lower = unit.lower().strip()

    # Map common variations
    unit_mapping = {
        "$": "dollars",
        "usd": "dollars",
        "dollar": "dollars",
        "%": "percent",
        "pct": "percent",
        "percentage": "percent",
        "x": "times",
        "multiple": "times",
    }

    return unit_mapping.get(unit_lower, unit_lower)


def validate_unit(metric_id: str, unit: str | None, value: float) -> ValidationResult:
    """
    Validate that unit is appropriate for metric type.

    Args:
        metric_id: Metric identifier
        unit: Extracted unit
        value: Extracted value (used for context)

    Returns:
        ValidationResult
    """
    if metric_id not in METRIC_UNIT_RULES:
        return ValidationResult.PASS  # No rule defined

    allowed_units, _ = METRIC_UNIT_RULES[metric_id]
    normalized_unit = normalize_unit(unit)

    # Check if unit is in allowed list
    if normalized_unit in allowed_units:
        return ValidationResult.PASS

    # Special case: "millions" might indicate currency for CAC
    if normalized_unit == "millions" and metric_id in [
        "cm_customer_acquisition_cost",
        "cm_expansion_revenue",
        "cm_revenue_per_customer",
    ]:
        return ValidationResult.PASS

    # Special case: count metrics with "millions" is OK
    if normalized_unit in ["millions", "thousands", "billion"] and metric_id in [
        "cm_active_customers_total",
        "cm_new_customers_acquired",
    ]:
        return ValidationResult.PASS

    return ValidationResult.FAIL_UNIT


def validate_range(metric_id: str, value: float, unit: str | None) -> ValidationResult:
    """
    Validate that value is within expected range for metric type.

    Args:
        metric_id: Metric identifier
        value: Extracted value
        unit: Extracted unit (used for context)

    Returns:
        ValidationResult
    """
    if metric_id not in METRIC_RANGE_RULES:
        return ValidationResult.PASS  # No rule defined

    min_val, max_val, typical_min, typical_max = METRIC_RANGE_RULES[metric_id]

    # Adjust value if it's in millions/billions
    adjusted_value = value
    if unit:
        unit_lower = unit.lower()
        if "million" in unit_lower:
            adjusted_value = value * 1_000_000
        elif "billion" in unit_lower:
            adjusted_value = value * 1_000_000_000
        elif "thousand" in unit_lower:
            adjusted_value = value * 1_000

    # Check hard limits
    if min_val is not None and adjusted_value < min_val:
        return ValidationResult.FAIL_RANGE
    if max_val is not None and adjusted_value > max_val:
        return ValidationResult.FAIL_RANGE

    # For percentages, check if value looks like it should be a percentage
    if metric_id in [
        "cm_customer_retention_rate",
        "cm_churn_rate",
        "cm_net_revenue_retention",
        "cm_gross_margin_by_cohort",
    ]:
        # If unit is not percent but value is in 0-100 range, might be OK
        # If value is > 100 and not NRR, likely wrong
        if value > 100 and metric_id != "cm_net_revenue_retention":
            return ValidationResult.FAIL_RANGE

    return ValidationResult.PASS


def validate_keyword_in_source(metric_id: str, source_text: str) -> ValidationResult:
    """
    Validate that relevant keywords appear in source text.

    Args:
        metric_id: Metric identifier
        source_text: Source text segment

    Returns:
        ValidationResult
    """
    if metric_id not in METRIC_KEYWORDS:
        return ValidationResult.PASS  # No keywords defined

    keywords = METRIC_KEYWORDS[metric_id]
    source_lower = source_text.lower()

    # Check if any keyword appears
    for keyword in keywords:
        if keyword.lower() in source_lower:
            return ValidationResult.PASS

    return ValidationResult.FAIL_KEYWORD


def validate_quote(quote: str | None, value: float, source_text: str) -> ValidationResult:
    """
    Validate that quote is present and contains the value.

    Args:
        quote: Extracted quote
        value: Extracted value
        source_text: Original source text

    Returns:
        ValidationResult
    """
    if not quote or len(quote.strip()) < 10:
        return ValidationResult.FAIL_QUOTE

    # Check if the numeric value appears in the quote
    value_str = str(int(value)) if value == int(value) else str(value)
    value_variations = [
        value_str,
        f"{value:,.0f}",
        f"{value:,.1f}",
        f"{value:,.2f}",
    ]

    found_value = any(v in quote for v in value_variations)

    if not found_value:
        # Try with common number formats
        formatted = f"{value:,.0f}".replace(",", "")  # e.g., "1000000"
        if formatted not in quote.replace(",", "").replace(" ", ""):
            return ValidationResult.WARN  # Value not clearly in quote

    return ValidationResult.PASS


def validate_quote_contains_metric_keyword(
    metric_id: str,
    quote: str | None,
    value: float,
) -> tuple[ValidationResult, str]:
    """
    Validate that quote contains BOTH metric keyword AND the extracted value.

    This is the critical check to prevent extracting unrelated nearby numbers.
    For example, text "LTV:CAC Ratio >8x. Growth was 83%." should NOT
    extract CAC=83% because "Growth was 83%" doesn't contain "CAC".

    Args:
        metric_id: Metric identifier (e.g., "cm_customer_acquisition_cost")
        quote: Extracted quote from LLM
        value: Extracted numeric value

    Returns:
        Tuple of (ValidationResult, reason_message)
    """
    if not quote:
        return ValidationResult.FAIL_QUOTE, "No quote provided"

    if metric_id not in METRIC_KEYWORDS:
        # No keywords defined for this metric - skip validation
        return ValidationResult.PASS, "No keyword rules for metric"

    keywords = METRIC_KEYWORDS[metric_id]
    quote_lower = quote.lower()

    # Check if at least one keyword appears in the quote
    found_keyword = None
    for keyword in keywords:
        if keyword.lower() in quote_lower:
            found_keyword = keyword
            break

    if not found_keyword:
        return (
            ValidationResult.FAIL_KEYWORD,
            f"Quote missing metric keyword for {metric_id}. Expected one of: {keywords[:3]}...",
        )

    # Check if the numeric value appears in the quote
    value_str = str(int(value)) if value == int(value) else str(value)
    value_variations = [
        value_str,
        f"{value:,.0f}",
        f"{value:,.1f}",
        f"{value:g}",  # Removes trailing zeros
    ]

    # Also check without commas
    quote_no_commas = quote.replace(",", "")
    found_value = any(v in quote or v in quote_no_commas for v in value_variations)

    if not found_value:
        return (
            ValidationResult.WARN,
            f"Quote contains keyword '{found_keyword}' but value {value} not clearly present",
        )

    return ValidationResult.PASS, f"Quote validated: contains '{found_keyword}' and value"


def validate_extraction(
    metric_id: str, value: float, unit: str | None, quote: str | None, source_text: str
) -> list[ValidationIssue]:
    """
    Run all validation checks on an extraction.

    Args:
        metric_id: Metric identifier
        value: Extracted numeric value
        unit: Extracted unit
        quote: Extracted quote from LLM
        source_text: Original source text

    Returns:
        List of validation issues found (empty if all pass)
    """
    issues = []
    source_preview = source_text[:100] + "..." if len(source_text) > 100 else source_text

    # Unit validation
    unit_result = validate_unit(metric_id, unit, value)
    if unit_result == ValidationResult.FAIL_UNIT:
        issues.append(
            ValidationIssue(
                result=unit_result,
                metric_id=metric_id,
                value=value,
                unit=unit,
                message=f"Unit '{unit}' not valid for {metric_id}",
                source_preview=source_preview,
            )
        )

    # Range validation
    range_result = validate_range(metric_id, value, unit)
    if range_result == ValidationResult.FAIL_RANGE:
        issues.append(
            ValidationIssue(
                result=range_result,
                metric_id=metric_id,
                value=value,
                unit=unit,
                message=f"Value {value} out of expected range for {metric_id}",
                source_preview=source_preview,
            )
        )

    # Keyword validation
    keyword_result = validate_keyword_in_source(metric_id, source_text)
    if keyword_result == ValidationResult.FAIL_KEYWORD:
        issues.append(
            ValidationIssue(
                result=keyword_result,
                metric_id=metric_id,
                value=value,
                unit=unit,
                message=f"No keywords for {metric_id} found in source",
                source_preview=source_preview,
            )
        )

    # Quote validation
    quote_result = validate_quote(quote, value, source_text)
    if quote_result == ValidationResult.FAIL_QUOTE:
        issues.append(
            ValidationIssue(
                result=quote_result,
                metric_id=metric_id,
                value=value,
                unit=unit,
                message="Quote missing or too short",
                source_preview=source_preview,
            )
        )

    return issues


def should_reject_extraction(issues: list[ValidationIssue]) -> bool:
    """
    Determine if extraction should be rejected based on issues.

    Args:
        issues: List of validation issues

    Returns:
        True if extraction should be rejected
    """
    if not issues:
        return False

    # Reject if any FAIL result
    fail_results = [
        ValidationResult.FAIL_UNIT,
        ValidationResult.FAIL_RANGE,
        ValidationResult.FAIL_KEYWORD,
        ValidationResult.FAIL_QUOTE,
    ]

    for issue in issues:
        if issue.result in fail_results:
            return True

    return False


def get_rejection_reason(issues: list[ValidationIssue]) -> str:
    """
    Get human-readable rejection reason.

    Args:
        issues: List of validation issues

    Returns:
        Rejection reason string
    """
    if not issues:
        return ""

    reasons = [issue.message for issue in issues if issue.result.value.startswith("fail")]
    return "; ".join(reasons)
