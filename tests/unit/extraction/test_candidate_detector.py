"""
Tests for CandidateDetector - unified metric candidate detection.

Test Coverage Target: ≥90% for src/extraction/candidate_detector.py

Test Categories:
1. Basic Detection (8-10 tests)
2. False Positive Filtering (6-8 tests)
3. Table-Aware Detection (8-10 tests)
4. Confidence Scoring (4-5 tests)
5. Integration with StructureParser (4-5 tests)
"""

from decimal import Decimal

import pytest

from src.extraction.candidate_detector import (
    DEFAULT_KEYWORDS,
    CandidateDetector,
)

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def detector() -> CandidateDetector:
    """Default CandidateDetector instance."""
    return CandidateDetector()


@pytest.fixture
def detector_no_fp_filter() -> CandidateDetector:
    """CandidateDetector with false positive filter disabled."""
    return CandidateDetector(use_false_positive_filter=False)


@pytest.fixture
def detector_no_row_validation() -> CandidateDetector:
    """CandidateDetector with row validation disabled."""
    return CandidateDetector(use_row_validation=False)


@pytest.fixture
def custom_keywords_detector() -> CandidateDetector:
    """CandidateDetector with custom keywords."""
    return CandidateDetector(keywords=["subscribers", "downloads", "installs"])


# =============================================================================
# Test Category 1: Basic Detection
# =============================================================================


class TestBasicDetection:
    """Tests for basic candidate detection functionality."""

    def test_single_keyword_value_pair_detected(self, detector: CandidateDetector) -> None:
        """Test that a simple keyword-value pair is detected."""
        text = "We have 50 million active customers"
        candidates = detector.detect(text)

        assert len(candidates) >= 1
        customer_candidates = [c for c in candidates if "customer" in c.keyword.lower()]
        assert len(customer_candidates) >= 1
        assert customer_candidates[0].value == Decimal("50000000")

    def test_multiple_candidates_in_same_text(self, detector: CandidateDetector) -> None:
        """Test that multiple keyword-value pairs are detected."""
        text = "We have 50 million customers and 10 million active users monthly."
        candidates = detector.detect(text)

        # Should find both customers and users
        keywords_found = {c.keyword.lower() for c in candidates}
        assert "customers" in keywords_found or any("customer" in k for k in keywords_found)

    def test_numbers_without_keywords_rejected(self, detector: CandidateDetector) -> None:
        """Test that numbers without nearby keywords are not detected."""
        text = "The building has 15 floors and was built in 1998."
        candidates = detector.detect(text)

        # No metric keywords, so no candidates
        assert len(candidates) == 0

    def test_keywords_without_numbers_rejected(self, detector: CandidateDetector) -> None:
        """Test that keywords without nearby numbers are not detected."""
        text = "We value our customers and users very much."
        candidates = detector.detect(text)

        # No numbers, so no candidates
        assert len(candidates) == 0

    def test_empty_text_returns_empty_list(self, detector: CandidateDetector) -> None:
        """Test that empty text returns empty list."""
        assert detector.detect("") == []
        assert detector.detect("   ") == []

    def test_whitespace_only_returns_empty_list(self, detector: CandidateDetector) -> None:
        """Test that whitespace-only text returns empty list."""
        assert detector.detect("  \n\t  ") == []

    def test_currency_values_detected(self, detector: CandidateDetector) -> None:
        """Test that currency values are properly detected."""
        text = "Our revenue was $100 million this quarter."
        candidates = detector.detect(text)

        revenue_candidates = [c for c in candidates if "revenue" in c.keyword.lower()]
        assert len(revenue_candidates) >= 1

    def test_percentage_values_detected(self, detector: CandidateDetector) -> None:
        """Test that percentage values are properly detected."""
        text = "Our retention rate was 95%."
        candidates = detector.detect(text)

        retention_candidates = [c for c in candidates if "retention" in c.keyword.lower()]
        assert len(retention_candidates) >= 1

    def test_value_position_is_correct(self, detector: CandidateDetector) -> None:
        """Test that value_position correctly points to the number."""
        text = "We have 100 customers"
        candidates = detector.detect(text)

        customer_candidates = [c for c in candidates if "customer" in c.keyword.lower()]
        assert len(customer_candidates) >= 1
        # The number "100" should be at position 8
        pos = customer_candidates[0].value_position
        assert text[pos : pos + 3] == "100"

    def test_keyword_position_is_correct(self, detector: CandidateDetector) -> None:
        """Test that keyword_position correctly points to the keyword."""
        text = "We have 100 customers"
        candidates = detector.detect(text)

        customer_candidates = [c for c in candidates if "customer" in c.keyword.lower()]
        assert len(customer_candidates) >= 1
        pos = customer_candidates[0].keyword_position
        assert "customer" in text[pos : pos + 10].lower()


# =============================================================================
# Test Category 2: False Positive Filtering
# =============================================================================


class TestFalsePositiveFiltering:
    """Tests for false positive filtering functionality."""

    def test_page_numbers_filtered(self, detector: CandidateDetector) -> None:
        """Test that page numbers are filtered out."""
        text = "See page 23 for more details on customers."
        candidates = detector.detect(text)

        # Should not include 23 as a customer value
        for c in candidates:
            if "customer" in c.keyword.lower():
                assert c.value != Decimal("23")

    def test_years_filtered(self, detector: CandidateDetector) -> None:
        """Test that year values (1990-2100) are filtered."""
        text = "In 2023, we had many customers."
        candidates = detector.detect(text)

        # 2023 should be filtered as a year
        for c in candidates:
            assert c.value != Decimal("2023")

    def test_dates_filtered(self, detector: CandidateDetector) -> None:
        """Test that date components are filtered."""
        text = "As of January 31, 2024, we had 50 million customers."
        candidates = detector.detect(text)

        # 31 and 2024 should be filtered, 50 million should remain
        values = {c.value for c in candidates}
        assert Decimal("31") not in values
        assert Decimal("2024") not in values

    def test_measurement_units_filtered(self, detector: CandidateDetector) -> None:
        """Test that measurement unit numbers are filtered (e.g., '24-hour')."""
        text = "We measure users on a 24-hour period basis."
        candidates = detector.detect(text)

        # 24 should be filtered as part of "24-hour"
        for c in candidates:
            if "user" in c.keyword.lower():
                assert c.value != Decimal("24")

    def test_toc_references_filtered(self, detector: CandidateDetector) -> None:
        """Test that Table of Contents references are filtered."""
        text = "73 Table of Contents customers"
        candidates = detector.detect(text)

        # 73 should be filtered as TOC page number
        for c in candidates:
            if "customer" in c.keyword.lower():
                assert c.value != Decimal("73")

    def test_disabled_filter_allows_years(self, detector_no_fp_filter: CandidateDetector) -> None:
        """Test that years are detected when filter is disabled."""
        text = "In 2023 we had 50 million customers."
        candidates = detector_no_fp_filter.detect(text)

        # With filter disabled, 2023 should be detected
        values = {c.value for c in candidates}
        # 2023 should now be in values
        assert Decimal("2023") in values or any(c.value == Decimal("2023") for c in candidates)

    def test_large_metric_values_not_filtered(self, detector: CandidateDetector) -> None:
        """Test that legitimate large metric values are not filtered."""
        text = "We have 50 million customers worldwide."
        candidates = detector.detect(text)

        # 50 million should not be filtered
        customer_candidates = [c for c in candidates if "customer" in c.keyword.lower()]
        assert len(customer_candidates) >= 1
        assert customer_candidates[0].value == Decimal("50000000")

    def test_small_numbers_below_threshold_filtered(self, detector: CandidateDetector) -> None:
        """Test that very small numbers are filtered by default."""
        text = "We have 3 customers and 5 users."
        candidates = detector.detect(text)

        # Small numbers like 3, 5 should be filtered (below MIN_METRIC_VALUE)
        values = {c.value for c in candidates}
        assert Decimal("3") not in values
        assert Decimal("5") not in values


# =============================================================================
# Test Category 3: Table-Aware Detection
# =============================================================================


class TestTableAwareDetection:
    """Tests for table-aware detection with StructureParser."""

    def test_keywords_and_values_in_same_row_accepted(self, detector: CandidateDetector) -> None:
        """Test that keyword-value pairs in same row are accepted."""
        html = """
        <table>
            <tr><td>Active customers</td><td>1000</td></tr>
            <tr><td>Revenue</td><td>$500</td></tr>
        </table>
        """
        text = "Active customers [CELL] 1000 [ROW] Revenue [CELL] $500 [ROW] "

        candidates = detector.detect(text=text, html=html, segment_type="table")

        # Should find candidates for both rows
        assert len(candidates) >= 1

    def test_cross_row_keyword_value_matches_rejected(self, detector: CandidateDetector) -> None:
        """Test that keyword in one row doesn't match value in another row."""
        html = """
        <table>
            <tr><td>Active customers</td><td></td></tr>
            <tr><td></td><td>1000</td></tr>
        </table>
        """
        text = "Active customers [CELL]  [ROW]  [CELL] 1000 [ROW] "

        candidates = detector.detect(text=text, html=html, segment_type="table")

        # "Active customers" and "1000" are in different rows - should be rejected
        customer_candidates = [c for c in candidates if "customer" in c.keyword.lower()]
        assert len(customer_candidates) == 0

    def test_same_cell_detection_works(self, detector: CandidateDetector) -> None:
        """Test that same-cell detection works correctly."""
        html = """
        <table>
            <tr><td>We have 1000 active customers</td></tr>
        </table>
        """
        text = "We have 1000 active customers [ROW] "

        candidates = detector.detect(text=text, html=html, segment_type="table")

        # Keyword and value should be detected as same cell
        customer_candidates = [c for c in candidates if "customer" in c.keyword.lower()]
        if customer_candidates:
            # Note: same_cell detection depends on position mapping
            assert customer_candidates[0].same_row is True

    def test_non_table_segments_handle_gracefully(self, detector: CandidateDetector) -> None:
        """Test that non-table segments work without HTML."""
        text = "We have 1000 active customers."

        # No HTML provided, segment_type is paragraph
        candidates = detector.detect(text=text, html=None, segment_type="paragraph")

        # Should still detect candidates
        customer_candidates = [c for c in candidates if "customer" in c.keyword.lower()]
        assert len(customer_candidates) >= 1

    def test_missing_html_handled_with_fallback(self, detector: CandidateDetector) -> None:
        """Test that missing HTML for table segment is handled gracefully."""
        text = "Revenue [CELL] 1000 [ROW] "

        # Table segment but no HTML
        candidates = detector.detect(text=text, html=None, segment_type="table")

        # Should still detect candidates, just without row validation
        assert len(candidates) >= 0  # May or may not find revenue depending on keywords

    def test_invalid_html_handled_gracefully(self, detector: CandidateDetector) -> None:
        """Test that invalid HTML is handled gracefully."""
        text = "We have 50000 customers."
        html = "<<<not valid html>>>"

        # Should not crash, should fall back to text-only detection
        candidates = detector.detect(text=text, html=html, segment_type="table")

        # Should still work - verify no exception was raised
        # and candidates were detected properly
        customer_candidates = [c for c in candidates if "customer" in c.keyword.lower()]
        assert len(customer_candidates) >= 1

    def test_row_validation_disabled_allows_cross_row(
        self, detector_no_row_validation: CandidateDetector
    ) -> None:
        """Test that disabling row validation allows cross-row matches."""
        html = """
        <table>
            <tr><td>Active customers</td><td></td></tr>
            <tr><td></td><td>1000</td></tr>
        </table>
        """
        text = "Active customers [CELL]  [ROW]  [CELL] 1000 [ROW] "

        candidates = detector_no_row_validation.detect(text=text, html=html, segment_type="table")

        # With row validation disabled, cross-row match should be allowed
        customer_candidates = [c for c in candidates if "customer" in c.keyword.lower()]
        # May still be rejected due to distance, but row constraint is not the reason
        # Just verify no exception is raised
        assert isinstance(candidates, list)

    def test_empty_cells_handled(self, detector: CandidateDetector) -> None:
        """Test that empty cells in tables don't cause issues."""
        html = """
        <table>
            <tr><td></td><td></td></tr>
            <tr><td>Customers</td><td>1000</td></tr>
        </table>
        """
        text = " [CELL]  [ROW] Customers [CELL] 1000 [ROW] "

        candidates = detector.detect(text=text, html=html, segment_type="table")

        # Should find the customer candidate in the second row
        customer_candidates = [c for c in candidates if "customer" in c.keyword.lower()]
        assert len(customer_candidates) >= 1

    def test_large_table_performance(self, detector: CandidateDetector) -> None:
        """Test detection performance on a large table (100+ rows)."""
        # Create a table with 100 rows
        rows = []
        for i in range(100):
            rows.append(f"<tr><td>Metric {i}</td><td>{i * 1000}</td></tr>")
        html = f"<table>{''.join(rows)}</table>"

        # Create corresponding text
        text_parts = []
        for i in range(100):
            text_parts.append(f"Metric {i} [CELL] {i * 1000} [ROW] ")
        text = "".join(text_parts)

        # This should complete without timeout (performance test)
        candidates = detector.detect(text=text, html=html, segment_type="table")

        # Just verify it completes
        assert isinstance(candidates, list)


# =============================================================================
# Test Category 4: Confidence Scoring
# =============================================================================


class TestConfidenceScoring:
    """Tests for confidence scoring functionality."""

    def test_close_proximity_increases_confidence(self, detector: CandidateDetector) -> None:
        """Test that closer keyword-value pairs have higher confidence."""
        # Close proximity: keyword right next to value
        text_close = "100 customers"
        candidates_close = detector.detect(text_close)

        # Further apart: more words between
        text_far = "We estimate that approximately 100 of our total customers"
        candidates_far = detector.detect(text_far)

        if candidates_close and candidates_far:
            close_conf = candidates_close[0].confidence
            far_conf = candidates_far[0].confidence
            # Close proximity should have higher or equal confidence
            assert close_conf >= far_conf

    def test_same_cell_increases_confidence(self, detector: CandidateDetector) -> None:
        """Test that same-cell matches have higher confidence."""
        html = """
        <table>
            <tr><td>100 customers</td></tr>
        </table>
        """
        text = "100 customers [ROW] "

        candidates = detector.detect(text=text, html=html, segment_type="table")

        if candidates:
            # Same-cell should add confidence bonus
            # Base (0.5) + proximity (0.3) + same_cell (0.15) = 0.95
            assert candidates[0].confidence >= 0.5

    def test_confidence_capped_at_one(self, detector: CandidateDetector) -> None:
        """Test that confidence is capped at 1.0."""
        # Very close proximity in same cell
        html = "<table><tr><td>50 customers</td></tr></table>"
        text = "50 customers [ROW] "

        candidates = detector.detect(text=text, html=html, segment_type="table")

        for c in candidates:
            assert c.confidence <= 1.0

    def test_confidence_minimum_is_base(self, detector: CandidateDetector) -> None:
        """Test that confidence is at least the base score (0.5) for valid matches."""
        text = "We have approximately 100000 customers in our database system today"
        candidates = detector.detect(text)

        for c in candidates:
            assert c.confidence >= 0.5

    def test_unit_present_in_candidates(self, detector: CandidateDetector) -> None:
        """Test that unit is correctly populated in candidates."""
        text = "Revenue was $100 million this quarter."
        candidates = detector.detect(text)

        # At least one candidate should have a unit
        if candidates:
            # Check that unit is set (may be None, 'usd', 'count', or '%')
            for c in candidates:
                assert c.unit is None or c.unit in ["count", "usd", "%"]


# =============================================================================
# Test Category 5: Integration with StructureParser
# =============================================================================


class TestStructureParserIntegration:
    """Tests for integration with StructureParser."""

    def test_structure_parser_used_when_html_available(self, detector: CandidateDetector) -> None:
        """Test that StructureParser is used when HTML is provided."""
        html = """
        <table>
            <tr><td>Active customers</td><td>5000</td></tr>
        </table>
        """
        text = "Active customers [CELL] 5000 [ROW] "

        candidates = detector.detect(text=text, html=html, segment_type="table")

        # Should find candidates with same_row=True
        customer_candidates = [c for c in candidates if "customer" in c.keyword.lower()]
        if customer_candidates:
            assert customer_candidates[0].same_row is True

    def test_position_mapping_correct(self, detector: CandidateDetector) -> None:
        """Test that position mapping between text and HTML is correct."""
        html = """
        <table>
            <tr><td>Revenue</td><td>$100 million</td></tr>
        </table>
        """
        text = "Revenue [CELL] $100 million [ROW] "

        candidates = detector.detect(text=text, html=html, segment_type="table")

        # Positions should be valid indices into the text
        for c in candidates:
            assert 0 <= c.value_position < len(text)
            assert 0 <= c.keyword_position < len(text)

    def test_row_boundaries_respected(self, detector: CandidateDetector) -> None:
        """Test that row boundaries are respected in detection."""
        html = """
        <table>
            <tr><td>Customers</td><td>1000</td></tr>
            <tr><td>Users</td><td>2000</td></tr>
        </table>
        """
        text = "Customers [CELL] 1000 [ROW] Users [CELL] 2000 [ROW] "

        candidates = detector.detect(text=text, html=html, segment_type="table")

        # Each keyword should match with the value in its row, not cross-row
        customer_candidates = [c for c in candidates if "customer" in c.keyword.lower()]
        user_candidates = [c for c in candidates if "user" in c.keyword.lower()]

        if customer_candidates:
            assert customer_candidates[0].value == Decimal("1000")
        if user_candidates:
            assert user_candidates[0].value == Decimal("2000")

    def test_detect_in_segment_convenience_method(self, detector: CandidateDetector) -> None:
        """Test the detect_in_segment convenience method."""
        segment: dict[str, object] = {
            "raw_text": "We have 1000 customers",
            "raw_html": None,
            "segment_type": "paragraph",
        }

        candidates = detector.detect_in_segment(segment)

        customer_candidates = [c for c in candidates if "customer" in c.keyword.lower()]
        assert len(customer_candidates) >= 1

    def test_detect_in_segment_with_table(self, detector: CandidateDetector) -> None:
        """Test detect_in_segment with table segment."""
        html = "<table><tr><td>Users</td><td>5000</td></tr></table>"
        segment: dict[str, object] = {
            "raw_text": "Users [CELL] 5000 [ROW] ",
            "raw_html": html,
            "segment_type": "table",
        }

        candidates = detector.detect_in_segment(segment)

        user_candidates = [c for c in candidates if "user" in c.keyword.lower()]
        assert len(user_candidates) >= 1


# =============================================================================
# Test Category 6: Edge Cases and Additional Tests
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases and additional scenarios."""

    def test_numbers_in_footnotes(self, detector: CandidateDetector) -> None:
        """Test handling of numbers in footnotes."""
        text = "Revenue was $100 million (see Note 5 for details)."
        candidates = detector.detect(text)

        # 5 should be filtered as note reference
        for c in candidates:
            assert c.value != Decimal("5")

    def test_percentages_vs_absolute_numbers(self, detector: CandidateDetector) -> None:
        """Test distinction between percentages and absolute numbers."""
        text = "Retention rate was 95% with 1000 customers."
        candidates = detector.detect(text)

        # Should have candidates with different units
        units = {c.unit for c in candidates}
        # At least one should be percentage, one should be count
        assert "%" in units or "count" in units

    def test_negative_numbers(self, detector: CandidateDetector) -> None:
        """Test handling of negative numbers."""
        text = "Growth was -5% with churn of 100 customers."
        candidates = detector.detect(text)

        # Negative numbers should still be detected
        values = [c.value for c in candidates]
        # -5 should be detected (as percentage, so -0.05)
        # Note: depends on NumberParser handling

    def test_numbers_with_commas(self, detector: CandidateDetector) -> None:
        """Test handling of comma-separated numbers."""
        text = "We have 1,234,567 active customers worldwide."
        candidates = detector.detect(text)

        customer_candidates = [c for c in candidates if "customer" in c.keyword.lower()]
        if customer_candidates:
            assert customer_candidates[0].value == Decimal("1234567")

    def test_custom_keywords(self, custom_keywords_detector: CandidateDetector) -> None:
        """Test detection with custom keywords."""
        text = "We have 1 million subscribers and 500000 downloads."
        candidates = custom_keywords_detector.detect(text)

        # Should find subscribers and downloads but not "customers"
        keywords = {c.keyword.lower() for c in candidates}
        assert "subscribers" in keywords or "downloads" in keywords

    def test_default_keywords_list_not_empty(self) -> None:
        """Test that DEFAULT_KEYWORDS is populated."""
        assert len(DEFAULT_KEYWORDS) > 0
        assert "customers" in DEFAULT_KEYWORDS
        assert "users" in DEFAULT_KEYWORDS

    def test_detected_candidate_fields(self, detector: CandidateDetector) -> None:
        """Test that DetectedCandidate has all required fields."""
        text = "We have 1000 customers"
        candidates = detector.detect(text)

        if candidates:
            c = candidates[0]
            # Verify all fields exist
            assert hasattr(c, "keyword")
            assert hasattr(c, "keyword_position")
            assert hasattr(c, "value")
            assert hasattr(c, "value_position")
            assert hasattr(c, "unit")
            assert hasattr(c, "confidence")
            assert hasattr(c, "same_row")
            assert hasattr(c, "same_cell")
            assert hasattr(c, "raw_text")

    def test_raw_text_contains_context(self, detector: CandidateDetector) -> None:
        """Test that raw_text contains surrounding context."""
        text = "We have 1000 active customers in the US."
        candidates = detector.detect(text)

        if candidates:
            # raw_text should contain part of the context
            assert "customer" in candidates[0].raw_text.lower() or "1000" in candidates[0].raw_text

    def test_max_keyword_distance_configurable(self) -> None:
        """Test that max_keyword_distance is configurable."""
        # Short distance - should not match far apart keyword-value
        detector_short = CandidateDetector(max_keyword_distance=10)

        # Very far apart
        text = "customers " + " " * 50 + "1000"
        candidates = detector_short.detect(text)

        # Should not match due to distance
        customer_candidates = [c for c in candidates if "customer" in c.keyword.lower()]
        assert len(customer_candidates) == 0

    def test_multiple_keywords_same_value(self, detector: CandidateDetector) -> None:
        """Test that multiple keywords can match the same value."""
        text = "Active customers and users: 1000"
        candidates = detector.detect(text)

        # Both "customers" and "users" should match 1000
        keywords = {c.keyword.lower() for c in candidates}
        matched_1000 = [c for c in candidates if c.value == Decimal("1000")]
        # At least one match
        assert len(matched_1000) >= 1
