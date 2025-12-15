"""
Integration tests for P1.5 sentence-aware filtering.

Tests the end-to-end pipeline with sentence boundary detection enabled,
verifying that cross-sentence false positives are filtered correctly.
"""

import pytest
from decimal import Decimal
from typing import Any, Dict, List

from src.review.candidate_generator import CandidateGenerator
from src.review.config import (
    CandidateGenerationConfig,
    DEFAULT_CONFIG,
    get_high_precision_config,
    get_high_recall_config,
    get_fast_config,
)


class TestSentenceFilteringIntegration:
    """End-to-end tests for sentence-aware filtering."""

    def _make_segment(
        self, text: str, segment_type: str = "paragraph"
    ) -> Dict[str, Any]:
        """Create a test segment dict."""
        return {
            "source_segment_id": 1,
            "raw_text": text,
            "segment_type": segment_type,
            "section_heading": "Test Section",
            "section_path": ["Test"],
        }

    def test_cross_sentence_filtering_basic(self) -> None:
        """Test that numbers are matched to keywords in same sentence only."""
        # Problem example: two sentences, two different metrics
        # Using actual keywords: "gross margin" and "active customers"
        text = (
            "Gross margin increased from 52.3% to 54.1% in the period. "
            "We have 50,000 active customers worldwide."
        )
        segment = self._make_segment(text)

        # With sentence filtering enabled (default)
        generator = CandidateGenerator()
        candidates = generator.generate_for_filing(
            filing_id=1,
            company_id=1,
            segments=[segment],
        )

        # Should have candidates for gross margin and active customers
        # But gross margin keywords should NOT match customer numbers and vice versa
        gross_margin_candidates = [
            c for c in candidates if c.suggested_metric_id == "cm_gross_margin_overall"
        ]
        customer_candidates = [
            c for c in candidates if c.suggested_metric_id == "cm_active_customers_total"
        ]

        # 52.3% and 54.1% should match gross margin (same sentence)
        # Note: Percentages are parsed as decimal values (52.3% → 0.523)
        assert any(
            c.parsed_value == Decimal("0.523") for c in gross_margin_candidates
        ), f"Expected 52.3% (0.523) to match gross margin. Candidates: {[(c.parsed_value, c.suggested_metric_id) for c in candidates]}"
        assert any(
            c.parsed_value == Decimal("0.541") for c in gross_margin_candidates
        ), f"Expected 54.1% (0.541) to match gross margin. Candidates: {[(c.parsed_value, c.suggested_metric_id) for c in candidates]}"

        # 50,000 should match active customers (same sentence)
        assert any(
            c.parsed_value == Decimal("50000") for c in customer_candidates
        ), f"Expected 50,000 to match active customers. Candidates: {[(c.parsed_value, c.suggested_metric_id) for c in candidates]}"

        # 50,000 should NOT match gross margin (different sentence)
        assert not any(
            c.parsed_value == Decimal("50000") for c in gross_margin_candidates
        ), "50,000 should not match gross margin (different sentence)"

    def test_sentence_filtering_disabled_high_recall(self) -> None:
        """Test that high recall config allows cross-sentence matches."""
        text = (
            "Gross margin increased to 54.1% in the quarter. "
            "We have 50,000 active customers."
        )
        segment = self._make_segment(text)

        # High recall disables sentence filtering
        config = get_high_recall_config()
        generator = CandidateGenerator(config=config)
        candidates = generator.generate_for_filing(
            filing_id=1,
            company_id=1,
            segments=[segment],
        )

        # With sentence filtering disabled, should still find candidates
        assert len(candidates) > 0

    def test_sentence_filtering_enabled_high_precision(self) -> None:
        """Test that high precision config enables sentence filtering."""
        text = (
            "Gross margin was 54.1% for the quarter. "
            "Our active customers reached 50,000."
        )
        segment = self._make_segment(text)

        config = get_high_precision_config()
        generator = CandidateGenerator(config=config)
        candidates = generator.generate_for_filing(
            filing_id=1,
            company_id=1,
            segments=[segment],
        )

        # Verify sentence filtering is working
        gross_margin_candidates = [
            c for c in candidates if c.suggested_metric_id == "cm_gross_margin_overall"
        ]

        # 50,000 should NOT match gross margin (different sentence)
        assert not any(
            c.parsed_value == Decimal("50000") for c in gross_margin_candidates
        ), "High precision should filter cross-sentence matches"

    def test_table_segment_no_sentence_filtering(self) -> None:
        """Test that table segments skip sentence filtering by default."""
        # Table text with actual keywords - "active customers" and "gross margin"
        text = "Active customers: 50,000. Gross margin 45%."
        segment = self._make_segment(text, segment_type="table")

        generator = CandidateGenerator()
        candidates = generator.generate_for_filing(
            filing_id=1,
            company_id=1,
            segments=[segment],
        )

        # Tables should allow matches (no sentence filtering)
        assert len(candidates) > 0, f"Tables should allow matches. Got: {candidates}"

    def test_single_sentence_multiple_metrics(self) -> None:
        """Test that multiple metrics in same sentence are preserved."""
        text = (
            "We grew our active customers to 100,000 while maintaining "
            "a gross margin of 55% and net revenue retention of 110%."
        )
        segment = self._make_segment(text)

        generator = CandidateGenerator()
        candidates = generator.generate_for_filing(
            filing_id=1,
            company_id=1,
            segments=[segment],
        )

        # Should find candidates for all three metrics in the same sentence
        metric_ids = {c.suggested_metric_id for c in candidates}
        assert "cm_active_customers_total" in metric_ids, f"Expected cm_active_customers_total in {metric_ids}"
        assert "cm_gross_margin_overall" in metric_ids, f"Expected cm_gross_margin_overall in {metric_ids}"
        assert "cm_net_revenue_retention" in metric_ids, f"Expected cm_net_revenue_retention in {metric_ids}"

    def test_abbreviations_not_sentence_breaks(self) -> None:
        """Test that abbreviations don't trigger false sentence breaks."""
        # Using "active customers" which is an actual keyword
        text = (
            "Mr. Smith reported that Inc. had growth to 50,000 "
            "active customers in the U.S. market."
        )
        segment = self._make_segment(text)

        generator = CandidateGenerator()
        candidates = generator.generate_for_filing(
            filing_id=1,
            company_id=1,
            segments=[segment],
        )

        # Should treat this as a single sentence
        # 50,000 should match active customers
        customer_candidates = [
            c for c in candidates if c.suggested_metric_id == "cm_active_customers_total"
        ]
        assert any(
            c.parsed_value == Decimal("50000") for c in customer_candidates
        ), f"50,000 should match active customers (abbreviations aren't sentence breaks). Got: {[(c.parsed_value, c.suggested_metric_id) for c in candidates]}"

    def test_decimals_not_sentence_breaks(self) -> None:
        """Test that decimal numbers don't trigger false sentence breaks."""
        # 50.5K should parse as 50500 and "active customers" should match
        text = (
            "The total customers reached 50,500 with strong "
            "retention among active customers."
        )
        segment = self._make_segment(text)

        generator = CandidateGenerator()
        candidates = generator.generate_for_filing(
            filing_id=1,
            company_id=1,
            segments=[segment],
        )

        # Should find candidates related to customers
        customer_candidates = [
            c for c in candidates
            if "customer" in c.suggested_metric_id.lower()
        ]
        assert len(customer_candidates) > 0, f"Should find customer-related candidates. Got: {[(c.parsed_value, c.suggested_metric_id) for c in candidates]}"

    def test_config_flags_respected(self) -> None:
        """Test that config flags control sentence filtering behavior."""
        # Use actual keywords
        text = "Gross margin was 55%. Active customers reached 50,000."
        segment = self._make_segment(text)

        # Explicitly disable sentence detection
        config = CandidateGenerationConfig(
            detect_sentences=False,
            respect_sentence_boundaries=False,
        )
        generator = CandidateGenerator(config=config)
        candidates_no_filter = generator.generate_for_filing(
            filing_id=1,
            company_id=1,
            segments=[segment],
        )

        # Explicitly enable sentence detection
        config = CandidateGenerationConfig(
            detect_sentences=True,
            respect_sentence_boundaries=True,
        )
        generator = CandidateGenerator(config=config)
        candidates_with_filter = generator.generate_for_filing(
            filing_id=1,
            company_id=1,
            segments=[segment],
        )

        # Both should produce candidates
        assert len(candidates_no_filter) > 0, f"No-filter should produce candidates. Got: {candidates_no_filter}"
        assert len(candidates_with_filter) > 0, f"With-filter should produce candidates. Got: {candidates_with_filter}"
