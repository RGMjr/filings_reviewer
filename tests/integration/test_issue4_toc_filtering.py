"""
Integration test for Issue 4 - Standalone TOC pattern filtering.

Verifies end-to-end that standalone page numbers before "Table of Contents"
are filtered during candidate generation.
"""

from decimal import Decimal
from typing import Any

from src.review.candidate_generator import CandidateGenerator


class TestIssue4StandaloneTOCFiltering:
    """Integration tests for Issue 4 standalone TOC pattern filtering."""

    def _make_segment(
        self, text: str, segment_type: str = "paragraph"
    ) -> dict[str, Any]:
        """Create a test segment dict."""
        return {
            "source_segment_id": 1,
            "raw_text": text,
            "segment_type": segment_type,
            "section_heading": "Test Section",
            "section_path": ["Test"],
        }

    def test_issue4_standalone_toc_numbers_filtered(self) -> None:
        """Test that standalone TOC page numbers don't create candidates."""
        # Realistic context from filing with TOC pattern
        text = "was 43.0%, respectively.\n73 Table of Contents\nLifetime Value"
        segment = self._make_segment(text)

        # Generate candidates
        generator = CandidateGenerator()
        candidates = generator.generate_for_filing(
            filing_id=9999,
            company_id=456,
            segments=[segment],
        )

        # Should NOT create candidate for "73" (TOC page number)
        values = [c.parsed_value for c in candidates]
        assert Decimal("73") not in values, (
            f"Standalone TOC number should be filtered. "
            f"Got candidates: {[(c.parsed_value, c.suggested_metric_id) for c in candidates]}"
        )

        # Should create candidate for "43.0%" (valid metric)
        # Note: Percentages are parsed as decimals (43.0% → 0.43)
        assert Decimal("0.43") in values, (
            f"Valid metric should not be filtered. "
            f"Got candidates: {[(c.parsed_value, c.suggested_metric_id) for c in candidates]}"
        )

    def test_toc_abbreviation_filtered(self) -> None:
        """Test that TOC abbreviation pattern is filtered."""
        # Use recognized metric keyword "net revenue retention"
        text = "Net revenue retention was 25% year-over-year.\n73 TOC\nCustomer Metrics"
        segment = self._make_segment(text)

        generator = CandidateGenerator()
        candidates = generator.generate_for_filing(
            filing_id=9999,
            company_id=456,
            segments=[segment],
        )

        # Should NOT create candidate for "73" (TOC abbreviation)
        values = [c.parsed_value for c in candidates]
        assert Decimal("73") not in values, (
            f"TOC abbreviation should be filtered. "
            f"Got candidates: {[(c.parsed_value, c.suggested_metric_id) for c in candidates]}"
        )

        # Should create candidate for "25%" (net revenue retention - valid metric)
        assert Decimal("0.25") in values, (
            f"Valid metric should not be filtered. "
            f"Got candidates: {[(c.parsed_value, c.suggested_metric_id) for c in candidates]}"
        )

    def test_case_insensitive_toc_filtering(self) -> None:
        """Test that TOC filtering works regardless of case."""
        test_cases = [
            "Margin was 50%.\n73 Table of Contents\nNext section",
            "Margin was 50%.\n73 TABLE OF CONTENTS\nNext section",
            "Margin was 50%.\n73 table of contents\nNext section",
        ]

        for text in test_cases:
            segment = self._make_segment(text)
            generator = CandidateGenerator()
            candidates = generator.generate_for_filing(
                filing_id=9999,
                company_id=456,
                segments=[segment],
            )

            # Should NOT create candidate for "73" (regardless of case)
            values = [c.parsed_value for c in candidates]
            assert Decimal("73") not in values, (
                f"TOC pattern should be filtered (case: {text}). "
                f"Got candidates: {[(c.parsed_value, c.suggested_metric_id) for c in candidates]}"
            )

    def test_contents_in_different_context_not_filtered(self) -> None:
        """Test that 'contents' in non-TOC context is not filtered."""
        # Use "net revenue retention" as a recognized metric
        text = "The report showed net revenue retention of 110% with strong growth."
        segment = self._make_segment(text)

        generator = CandidateGenerator()
        candidates = generator.generate_for_filing(
            filing_id=9999,
            company_id=456,
            segments=[segment],
        )

        # "110%" should create a candidate (net revenue retention - valid metric)
        values = [c.parsed_value for c in candidates]
        assert Decimal("1.10") in values, (
            f"110% net revenue retention should not be filtered. "
            f"Got candidates: {[(c.parsed_value, c.suggested_metric_id) for c in candidates]}"
        )

    def test_multiple_metrics_with_toc_pattern(self) -> None:
        """Test that valid metrics are preserved when TOC pattern is present."""
        text = (
            "Customer acquisition cost was 45 dollars and gross margin was 52.3%, "
            "respectively.\n73 Table of Contents\nOur active customers reached 50,000."
        )
        segment = self._make_segment(text)

        generator = CandidateGenerator()
        candidates = generator.generate_for_filing(
            filing_id=9999,
            company_id=456,
            segments=[segment],
        )

        values = [c.parsed_value for c in candidates]

        # Should filter TOC page number
        assert Decimal("73") not in values, (
            "TOC page number should be filtered"
        )

        # Should keep valid metrics
        # 45 dollars (CAC), 52.3% gross margin, 50,000 customers
        assert Decimal("45") in values or Decimal("0.523") in values or Decimal("50000") in values, (
            f"Valid metrics should not be filtered. "
            f"Got candidates: {[(c.parsed_value, c.suggested_metric_id) for c in candidates]}"
        )

    def test_toc_pattern_with_whitespace_variations(self) -> None:
        """Test TOC pattern filtering with different whitespace."""
        test_cases = [
            "was 50%.\n73 Table of Contents\nNext",  # newline
            "was 50%. 73 Table of Contents. Next",    # spaces
            "was 50%.\n73  Table of Contents\nNext",  # multiple spaces
        ]

        for text in test_cases:
            segment = self._make_segment(text)
            generator = CandidateGenerator()
            candidates = generator.generate_for_filing(
                filing_id=9999,
                company_id=456,
                segments=[segment],
            )

            # Should filter "73" in all cases
            values = [c.parsed_value for c in candidates]
            assert Decimal("73") not in values, (
                f"TOC pattern should be filtered (whitespace test: {text!r}). "
                f"Got candidates: {[(c.parsed_value, c.suggested_metric_id) for c in candidates]}"
            )
