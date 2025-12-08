"""
Unit tests for ValueExtractor.

These cover basic text extraction behavior and guard against regressions in the
extraction_method flag expected by the analysis schema.
"""

from decimal import Decimal
from datetime import date

from src.extraction.models import SourceSegment
from src.extraction.value_extractor import (
    ValueExtractor,
    verify_quote_in_source,
    _normalize_text,
)


def build_segment(**overrides) -> SourceSegment:
    """Helper to construct a SourceSegment with sensible defaults."""
    defaults = {
        "filing_id": 1,
        "segment_type": "paragraph",
        "raw_text": "Placeholder",
        "sequence_index": 0,
        "candidate_metric_ids": [],
        "contains_numeric_disclosure_flag": True,
    }
    defaults.update(overrides)
    return SourceSegment(**defaults)


# =============================================================================
# Text Extraction Tests (existing + new)
# =============================================================================


def test_extract_from_text_returns_llm_text_method():
    """Text extraction should populate values with the allowed extraction method."""
    segment = build_segment(
        raw_text="We had approximately 1,500 daily active users (DAUs).",
        candidate_metric_ids=["cm_daily_active_users"],
    )

    extractor = ValueExtractor()
    values = extractor.extract_from_text(segment, company_id=42)

    assert len(values) == 1
    value = values[0]
    assert value.metric_id == "cm_daily_active_users"
    assert value.extraction_method == "llm_text"
    assert value.value_numeric == Decimal("1500")


def test_extract_from_text_handles_missing_candidate_metrics():
    """Segments without candidate metric ids should not raise errors."""
    # Explicitly set candidate_metric_ids to None to simulate legacy data.
    segment = build_segment(
        raw_text="Customers spent $10 million during FY 2024.",
        candidate_metric_ids=None,
    )

    extractor = ValueExtractor()
    values = extractor.extract_from_text(segment, company_id=99)

    assert values == []


def test_extract_from_segment_skips_non_numeric_segments():
    """Segments without numeric disclosure flag should return empty list."""
    segment = build_segment(
        raw_text="We value our customers.",
        contains_numeric_disclosure_flag=False,
        candidate_metric_ids=["cm_daily_active_users"],
    )

    extractor = ValueExtractor()
    values = extractor.extract_from_segment(segment, company_id=1)

    assert values == []


# =============================================================================
# Number Parsing Tests (_parse_number)
# =============================================================================


def test_parse_number_basic():
    """Parse simple numbers without formatting."""
    extractor = ValueExtractor()

    assert extractor._parse_number("123") == Decimal("123")
    assert extractor._parse_number("1234567") == Decimal("1234567")
    assert extractor._parse_number("0") == Decimal("0")


def test_parse_number_with_commas():
    """Parse numbers with comma separators."""
    extractor = ValueExtractor()

    assert extractor._parse_number("1,234") == Decimal("1234")
    assert extractor._parse_number("1,234,567") == Decimal("1234567")
    assert extractor._parse_number("10,000,000") == Decimal("10000000")


def test_parse_number_with_currency():
    """Parse numbers with currency symbols."""
    extractor = ValueExtractor()

    assert extractor._parse_number("$1,234") == Decimal("1234")
    assert extractor._parse_number("$ 1,234") == Decimal("1234")
    assert extractor._parse_number("$10.50") == Decimal("10.50")


def test_parse_number_with_scale_indicators():
    """Parse numbers with million/billion/thousand indicators."""
    extractor = ValueExtractor()

    assert extractor._parse_number("1.5 million") == Decimal("1500000")
    assert extractor._parse_number("2.3 billion") == Decimal("2300000000")
    assert extractor._parse_number("500 thousand") == Decimal("500000")
    assert extractor._parse_number("$10 million") == Decimal("10000000")


def test_parse_number_with_decimals():
    """Parse decimal numbers."""
    extractor = ValueExtractor()

    assert extractor._parse_number("123.45") == Decimal("123.45")
    assert extractor._parse_number("1,234.567") == Decimal("1234.567")
    assert extractor._parse_number("0.25") == Decimal("0.25")


def test_parse_number_negative():
    """Parse negative numbers."""
    extractor = ValueExtractor()

    assert extractor._parse_number("-123") == Decimal("-123")
    assert extractor._parse_number("-1,234.56") == Decimal("-1234.56")
    assert extractor._parse_number("-$500") == Decimal("-500")


def test_parse_number_percentage():
    """Parse percentages (strip % symbol)."""
    extractor = ValueExtractor()

    assert extractor._parse_number("25%") == Decimal("25")
    assert extractor._parse_number("12.5%") == Decimal("12.5")
    assert extractor._parse_number("100%") == Decimal("100")


def test_parse_number_invalid():
    """Return None for unparseable text."""
    extractor = ValueExtractor()

    assert extractor._parse_number("abc") is None
    assert extractor._parse_number("N/A") is None
    assert extractor._parse_number("--") is None
    assert extractor._parse_number("") is None


# =============================================================================
# Period Extraction Tests (_extract_period_from_text)
# =============================================================================


def test_extract_period_quarter_pattern():
    """Extract period from quarter patterns like Q1 2024."""
    extractor = ValueExtractor()

    assert extractor._extract_period_from_text("Q1 2024") == date(2024, 3, 31)
    assert extractor._extract_period_from_text("Q2 2023") == date(2023, 6, 30)
    assert extractor._extract_period_from_text("Q3 2022") == date(2022, 9, 30)
    assert extractor._extract_period_from_text("Q4 2021") == date(2021, 12, 31)


def test_extract_period_fiscal_year_pattern():
    """Extract period from fiscal year patterns like FY 2023."""
    extractor = ValueExtractor()

    assert extractor._extract_period_from_text("FY 2023") == date(2023, 12, 31)
    assert extractor._extract_period_from_text("FY2022") == date(2022, 12, 31)
    assert extractor._extract_period_from_text("fy 2024") == date(2024, 12, 31)


def test_extract_period_year_only():
    """Extract period from standalone year like 2024."""
    extractor = ValueExtractor()

    assert extractor._extract_period_from_text("2024") == date(2024, 12, 31)
    assert extractor._extract_period_from_text("2020") == date(2020, 12, 31)


def test_extract_period_embedded_in_text():
    """Extract period from text containing period references."""
    extractor = ValueExtractor()

    text = "As of Q1 2024, we had 1,500 customers."
    assert extractor._extract_period_from_text(text) == date(2024, 3, 31)

    text = "For fiscal year FY 2023, revenue was $10M."
    assert extractor._extract_period_from_text(text) == date(2023, 12, 31)


def test_extract_period_no_match():
    """Return None when no period pattern found."""
    extractor = ValueExtractor()

    assert extractor._extract_period_from_text("No period here") is None
    assert extractor._extract_period_from_text("") is None
    assert extractor._extract_period_from_text("abc") is None


# =============================================================================
# Cohort Label Parsing Tests (parse_cohort_label)
# =============================================================================


def test_parse_cohort_label_acquisition():
    """Parse acquisition cohort labels (year-based)."""
    extractor = ValueExtractor()

    cohort_type, normalized = extractor.parse_cohort_label("2021 Cohort")
    assert cohort_type == "acquisition"
    assert normalized == "2021"

    cohort_type, normalized = extractor.parse_cohort_label("2019 cohort")
    assert cohort_type == "acquisition"
    assert normalized == "2019"


def test_parse_cohort_label_tenure_months():
    """Parse tenure cohort labels in months."""
    extractor = ValueExtractor()

    cohort_type, normalized = extractor.parse_cohort_label("0-12 months")
    assert cohort_type == "tenure"
    assert normalized == "0-1y"

    cohort_type, normalized = extractor.parse_cohort_label("12-24 months")
    assert cohort_type == "tenure"
    assert normalized == "1-2y"


def test_parse_cohort_label_tenure_years():
    """Parse tenure cohort labels in years."""
    extractor = ValueExtractor()

    cohort_type, normalized = extractor.parse_cohort_label("0-1 years")
    assert cohort_type == "tenure"
    assert normalized == "0-1y"

    cohort_type, normalized = extractor.parse_cohort_label("3-5 years")
    assert cohort_type == "tenure"
    assert normalized == "3-5y"


def test_parse_cohort_label_tenure_plus():
    """Parse tenure cohort labels with plus (2+ years)."""
    extractor = ValueExtractor()

    cohort_type, normalized = extractor.parse_cohort_label("2+ years")
    assert cohort_type == "tenure"
    assert normalized == "2y+"

    cohort_type, normalized = extractor.parse_cohort_label("5+ years")
    assert cohort_type == "tenure"
    assert normalized == "5y+"


def test_parse_cohort_label_tenure_less_than():
    """Parse tenure cohort labels with less than."""
    extractor = ValueExtractor()

    cohort_type, normalized = extractor.parse_cohort_label("< 12 months")
    assert cohort_type == "tenure"
    assert normalized == "<1y"

    cohort_type, normalized = extractor.parse_cohort_label("< 2 years")
    assert cohort_type == "tenure"
    assert normalized == "<2y"


def test_parse_cohort_label_other():
    """Unknown cohort labels should return 'other'."""
    extractor = ValueExtractor()

    cohort_type, normalized = extractor.parse_cohort_label("Premium Tier")
    assert cohort_type == "other"
    assert normalized == "Premium Tier"


def test_parse_cohort_label_empty():
    """Empty cohort labels should return None."""
    extractor = ValueExtractor()

    assert extractor.parse_cohort_label("") == (None, None)
    assert extractor.parse_cohort_label(None) == (None, None)


# =============================================================================
# Unit Inference Tests (_infer_unit)
# =============================================================================


def test_infer_unit_currency():
    """Infer USD unit from currency symbols."""
    extractor = ValueExtractor()

    assert extractor._infer_unit("$1,234", "cm_revenue") == "usd"
    assert extractor._infer_unit("USD 500", "cm_cost") == "usd"


def test_infer_unit_percentage():
    """Infer percent unit from percentage symbols."""
    extractor = ValueExtractor()

    assert extractor._infer_unit("25%", "cm_churn_rate") == "percent"
    assert extractor._infer_unit("12.5 percent", "cm_retention_rate") == "percent"


def test_infer_unit_from_metric_id():
    """Infer unit from metric ID patterns."""
    extractor = ValueExtractor()

    assert extractor._infer_unit("1234", "cm_revenue_by_cohort") == "usd"
    assert extractor._infer_unit("500", "cm_churn_rate") == "percent"
    assert extractor._infer_unit("1000", "cm_daily_active_users") == "count"


def test_infer_unit_default_count():
    """Default to count for customer/user metrics."""
    extractor = ValueExtractor()

    assert extractor._infer_unit("1000", "cm_active_customers") == "count"
    assert extractor._infer_unit("5000", "cm_transactions_by_cohort") == "count"


# =============================================================================
# Column Identification Tests (_identify_columns)
# =============================================================================


def test_identify_columns_cohort():
    """Identify cohort columns from headers."""
    extractor = ValueExtractor()

    headers = ["Cohort", "Q1 2024", "Q2 2024"]
    column_info = extractor._identify_columns(headers)

    assert column_info[0]["type"] == "cohort"


def test_identify_columns_period():
    """Identify period columns from headers with dates."""
    extractor = ValueExtractor()

    headers = ["Metric", "Q1 2024", "Q2 2024", "FY 2023"]
    column_info = extractor._identify_columns(headers)

    assert column_info[1]["type"] == "value"
    assert column_info[1]["period_end"] == date(2024, 3, 31)
    assert column_info[2]["type"] == "value"
    assert column_info[2]["period_end"] == date(2024, 6, 30)


def test_identify_columns_default_value():
    """Default columns without special patterns to value type."""
    extractor = ValueExtractor()

    headers = ["Metric Name", "Amount", "Count"]
    column_info = extractor._identify_columns(headers)

    assert column_info[0]["type"] == "value"
    assert column_info[1]["type"] == "value"
    assert column_info[2]["type"] == "value"


# =============================================================================
# Metric Inference Tests (_infer_metric_from_context)
# =============================================================================


def test_infer_metric_single_candidate():
    """Use the only candidate metric if only one exists."""
    extractor = ValueExtractor()
    segment = build_segment(candidate_metric_ids=["cm_revenue_by_cohort"])

    metric_id = extractor._infer_metric_from_context(segment, [], 0)
    assert metric_id == "cm_revenue_by_cohort"


def test_infer_metric_from_header_revenue():
    """Infer revenue metric from header text."""
    extractor = ValueExtractor()
    segment = build_segment(
        candidate_metric_ids=["cm_revenue_by_cohort", "cm_transactions_by_cohort"]
    )
    headers = ["Cohort", "Revenue"]

    metric_id = extractor._infer_metric_from_context(segment, headers, 1)
    assert metric_id == "cm_revenue_by_cohort"


def test_infer_metric_from_header_transaction():
    """Infer transaction metric from header text."""
    extractor = ValueExtractor()
    segment = build_segment(
        candidate_metric_ids=["cm_revenue_by_cohort", "cm_transactions_by_cohort"]
    )
    headers = ["Cohort", "Transactions"]

    metric_id = extractor._infer_metric_from_context(segment, headers, 1)
    assert metric_id == "cm_transactions_by_cohort"


def test_infer_metric_from_header_customers():
    """Infer customer metric from header text."""
    extractor = ValueExtractor()
    segment = build_segment(
        candidate_metric_ids=[
            "cm_customers_period_end_by_tenure",
            "cm_revenue_by_cohort",
        ]
    )
    headers = ["Tenure", "Customers"]

    metric_id = extractor._infer_metric_from_context(segment, headers, 1)
    assert metric_id == "cm_customers_period_end_by_tenure"


def test_infer_metric_fallback_first():
    """Fall back to first candidate metric if no match."""
    extractor = ValueExtractor()
    segment = build_segment(
        candidate_metric_ids=["cm_revenue_by_cohort", "cm_transactions_by_cohort"]
    )
    headers = ["Unknown"]

    metric_id = extractor._infer_metric_from_context(segment, headers, 0)
    assert metric_id == "cm_revenue_by_cohort"


def test_infer_metric_no_candidates():
    """Return None if no candidate metrics."""
    extractor = ValueExtractor()
    segment = build_segment(candidate_metric_ids=[])

    metric_id = extractor._infer_metric_from_context(segment, [], 0)
    assert metric_id is None


# =============================================================================
# Text Cleaning Tests (_clean_text)
# =============================================================================


def test_clean_text_whitespace():
    """Clean multiple whitespace characters."""
    extractor = ValueExtractor()

    assert extractor._clean_text("  multiple   spaces  ") == "multiple spaces"
    assert extractor._clean_text("line\nbreak") == "line break"
    assert extractor._clean_text("tab\there") == "tab here"


# =============================================================================
# Table Extraction Tests (extract_from_table, _parse_table_row)
# =============================================================================


def test_extract_from_table_basic():
    """Extract values from a simple table."""
    html = """
    <table>
        <tr>
            <th>Cohort</th>
            <th>Q1 2024</th>
            <th>Q2 2024</th>
        </tr>
        <tr>
            <td>2021 Cohort</td>
            <td>$1,500,000</td>
            <td>$1,800,000</td>
        </tr>
    </table>
    """

    segment = build_segment(
        segment_type="table",
        raw_html=html,
        raw_text="Revenue by Cohort",
        candidate_metric_ids=["cm_revenue_by_cohort"],
        source_segment_id=123,
    )

    extractor = ValueExtractor()
    values = extractor.extract_from_table(segment, company_id=1)

    assert len(values) == 2  # Two values from two columns

    # First value (Q1 2024)
    assert values[0].value_numeric == Decimal("1500000")
    assert values[0].period_end == date(2024, 3, 31)
    assert values[0].cohort_type == "acquisition"
    assert values[0].cohort_bucket_normalized == "2021"
    assert values[0].extraction_method == "rule_table"

    # Second value (Q2 2024)
    assert values[1].value_numeric == Decimal("1800000")
    assert values[1].period_end == date(2024, 6, 30)


def test_extract_from_table_no_html():
    """Return empty list when no HTML provided."""
    segment = build_segment(
        segment_type="table",
        raw_html=None,
        candidate_metric_ids=["cm_revenue_by_cohort"],
    )

    extractor = ValueExtractor()
    values = extractor.extract_from_table(segment, company_id=1)

    assert values == []


def test_extract_from_table_no_table_tag():
    """Return empty list when HTML doesn't contain table."""
    html = "<div>Not a table</div>"

    segment = build_segment(
        segment_type="table",
        raw_html=html,
        candidate_metric_ids=["cm_revenue_by_cohort"],
    )

    extractor = ValueExtractor()
    values = extractor.extract_from_table(segment, company_id=1)

    assert values == []


def test_extract_from_table_only_header():
    """Return empty list for table with only header row."""
    html = """
    <table>
        <tr><th>Column 1</th><th>Column 2</th></tr>
    </table>
    """

    segment = build_segment(
        segment_type="table",
        raw_html=html,
        candidate_metric_ids=["cm_revenue_by_cohort"],
    )

    extractor = ValueExtractor()
    values = extractor.extract_from_table(segment, company_id=1)

    assert values == []


def test_extract_from_table_malformed_rows():
    """Skip rows with mismatched column count."""
    html = """
    <table>
        <tr>
            <th>Cohort</th>
            <th>Q1 2024</th>
            <th>Q2 2024</th>
        </tr>
        <tr>
            <td>2021 Cohort</td>
            <td>$1,500,000</td>
            <td>$1,800,000</td>
        </tr>
        <tr>
            <td>Bad Row</td>
            <!-- Missing columns -->
        </tr>
        <tr>
            <td>2022 Cohort</td>
            <td>$2,000,000</td>
            <td>$2,500,000</td>
        </tr>
    </table>
    """

    segment = build_segment(
        segment_type="table",
        raw_html=html,
        raw_text="Revenue by Cohort",
        candidate_metric_ids=["cm_revenue_by_cohort"],
    )

    extractor = ValueExtractor()
    values = extractor.extract_from_table(segment, company_id=1)

    # Should extract 4 values (2 from first valid row, 2 from third valid row)
    # and skip the malformed row
    assert len(values) == 4


def test_extract_from_table_tenure_cohorts():
    """Extract values with tenure cohort labels."""
    html = """
    <table>
        <tr>
            <th>Cohort</th>
            <th>Customers</th>
        </tr>
        <tr>
            <td>0-12 months</td>
            <td>1,500</td>
        </tr>
        <tr>
            <td>1-2 years</td>
            <td>800</td>
        </tr>
        <tr>
            <td>2+ years</td>
            <td>300</td>
        </tr>
    </table>
    """

    segment = build_segment(
        segment_type="table",
        raw_html=html,
        raw_text="Customers by Tenure",
        candidate_metric_ids=["cm_customers_period_end_by_tenure"],
    )

    extractor = ValueExtractor()
    values = extractor.extract_from_table(segment, company_id=1)

    assert len(values) == 3

    # First row (0-12 months)
    assert values[0].cohort_type == "tenure"
    assert values[0].cohort_bucket_normalized == "0-1y"
    assert values[0].value_numeric == Decimal("1500")

    # Second row (1-2 years)
    assert values[1].cohort_type == "tenure"
    assert values[1].cohort_bucket_normalized == "1-2y"

    # Third row (2+ years)
    assert values[2].cohort_type == "tenure"
    assert values[2].cohort_bucket_normalized == "2y+"


def test_extract_from_table_percentage_values():
    """Extract percentage values from table."""
    html = """
    <table>
        <tr>
            <th>Metric</th>
            <th>Value</th>
        </tr>
        <tr>
            <td>Churn Rate</td>
            <td>5.5%</td>
        </tr>
    </table>
    """

    segment = build_segment(
        segment_type="table",
        raw_html=html,
        candidate_metric_ids=["cm_churn_rate"],
    )

    extractor = ValueExtractor()
    values = extractor.extract_from_table(segment, company_id=1)

    assert len(values) == 1
    assert values[0].value_numeric == Decimal("5.5")
    assert values[0].unit == "percent"


def test_extract_from_table_skip_non_numeric_cells():
    """Skip table cells that don't contain numbers."""
    html = """
    <table>
        <tr>
            <th>Cohort</th>
            <th>Q1 2024</th>
            <th>Q2 2024</th>
        </tr>
        <tr>
            <td>2021 Cohort</td>
            <td>N/A</td>
            <td>$1,500,000</td>
        </tr>
    </table>
    """

    segment = build_segment(
        segment_type="table",
        raw_html=html,
        candidate_metric_ids=["cm_revenue_by_cohort"],
    )

    extractor = ValueExtractor()
    values = extractor.extract_from_table(segment, company_id=1)

    # Should only extract 1 value (Q2 2024), skip "N/A"
    assert len(values) == 1
    assert values[0].value_numeric == Decimal("1500000")
    assert values[0].period_end == date(2024, 6, 30)


def test_extract_from_segment_routes_to_table():
    """extract_from_segment should route table segments to extract_from_table."""
    html = """
    <table>
        <tr>
            <th>Metric</th>
            <th>Value</th>
        </tr>
        <tr>
            <td>Active Users</td>
            <td>1,500</td>
        </tr>
    </table>
    """

    segment = build_segment(
        segment_type="table",
        raw_html=html,
        candidate_metric_ids=["cm_active_users"],
    )

    extractor = ValueExtractor()
    values = extractor.extract_from_segment(segment, company_id=1)

    assert len(values) == 1
    assert values[0].extraction_method == "rule_table"
    assert values[0].source_type == "table"


def test_extract_from_segment_routes_to_text():
    """extract_from_segment should route non-table segments to extract_from_text."""
    segment = build_segment(
        segment_type="paragraph",
        raw_text="We had 1,500 active users.",
        candidate_metric_ids=["cm_active_users"],
    )

    extractor = ValueExtractor()
    values = extractor.extract_from_segment(segment, company_id=1)

    assert len(values) == 1
    assert values[0].extraction_method == "llm_text"
    assert values[0].source_type == "text"


# =============================================================================
# Convenience Function Tests
# =============================================================================


def test_convenience_function_extract_values():
    """Test the convenience function extract_values()."""
    from src.extraction.value_extractor import extract_values

    segment = build_segment(
        raw_text="We had 1,500 users.",
        candidate_metric_ids=["cm_active_users"],
    )

    values = extract_values(segment, company_id=42)

    assert len(values) == 1
    assert values[0].value_numeric == Decimal("1500")
    assert values[0].company_id == 42


# =============================================================================
# Quote Verification Tests
# =============================================================================


class TestNormalizeText:
    """Tests for _normalize_text helper function."""

    def test_html_entity_decoding(self):
        assert _normalize_text("Smith &amp; Co") == "Smith & Co"
        assert _normalize_text("100&nbsp;million") == "100 million"
        assert _normalize_text("It&#39;s working") == "It's working"

    def test_smart_quote_normalization(self):
        assert _normalize_text("\u201cquoted\u201d") == '"quoted"'
        assert _normalize_text("it\u2019s") == "it's"

    def test_whitespace_normalization(self):
        assert _normalize_text("hello   world") == "hello world"
        assert _normalize_text("hello\n\nworld") == "hello world"
        assert _normalize_text("  trimmed  ") == "trimmed"

    def test_empty_and_none(self):
        assert _normalize_text("") == ""
        assert _normalize_text(None) == ""


class TestVerifyQuoteInSource:
    """Tests for verify_quote_in_source function."""

    def test_exact_substring_match(self):
        quote = "We had 1.5 million users"
        source = "As of December 2023, we had 1.5 million users on our platform."
        assert verify_quote_in_source(quote, source) is True

    def test_short_quote_in_long_source(self):
        """Critical test: short quote should be found in very long source."""
        quote = "monthly active users"
        source = (
            "x" * 5000
            + " We define monthly active users as unique visitors. "
            + "y" * 5000
        )
        assert verify_quote_in_source(quote, source) is True

    def test_no_match_returns_false(self):
        quote = "Completely different text that doesn't exist anywhere"
        source = "We had 1.5 million users as of December 2023."
        assert verify_quote_in_source(quote, source) is False

    def test_fuzzy_match_minor_differences(self):
        # LLM might add/remove minor words
        quote = "We had approximately 1.5 million users"
        source = "We had 1.5 million users"
        # This should pass with 70% threshold (most words match)
        assert verify_quote_in_source(quote, source, threshold=0.7) is True

    def test_fuzzy_match_below_threshold(self):
        # Significantly different numbers should fail
        quote = "We had 10 million customers worldwide"
        source = "We had 1.5 million users"
        assert verify_quote_in_source(quote, source) is False

    def test_html_entities_in_source(self):
        """Source may have HTML entities that quote doesn't."""
        quote = "Smith & Co had 5 million users"
        source = "Smith &amp; Co had 5 million users as of 2023."
        assert verify_quote_in_source(quote, source) is True

    def test_smart_quotes_mismatch(self):
        """Quote may have straight quotes, source may have curly."""
        quote = '"Daily active users" means unique visitors'
        source = "\u201cDaily active users\u201d means unique visitors per day."
        assert verify_quote_in_source(quote, source) is True

    def test_newline_vs_space(self):
        """Source may have newlines where quote has spaces."""
        quote = "We define customers as paying subscribers"
        source = "We define customers\nas paying subscribers."
        assert verify_quote_in_source(quote, source) is True

    def test_empty_quote_returns_false(self):
        assert verify_quote_in_source("", "Some source text") is False

    def test_empty_source_returns_false(self):
        assert verify_quote_in_source("Some quote", "") is False

    def test_none_values_returns_false(self):
        assert verify_quote_in_source(None, "source") is False
        assert verify_quote_in_source("quote", None) is False

    def test_case_insensitive_matching(self):
        quote = "We Had 1.5 MILLION Users"
        source = "we had 1.5 million users"
        assert verify_quote_in_source(quote, source) is True

    def test_custom_threshold(self):
        quote = "We had many users"
        source = "We had some users"
        # Low threshold should pass
        assert verify_quote_in_source(quote, source, threshold=0.5) is True
        # High threshold should fail
        assert verify_quote_in_source(quote, source, threshold=0.95) is False

    def test_whitespace_only_after_normalization(self):
        """Edge case: text that becomes empty after normalization."""
        assert verify_quote_in_source("   ", "source") is False
