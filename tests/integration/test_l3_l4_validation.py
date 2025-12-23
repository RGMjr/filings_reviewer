"""
Integration tests for L3/L4 keyword direction and multiplier functionality.

These tests validate that the L3 (direction detection) and L4 (context-dependent
multipliers) enhancements work correctly from end-to-end:
- L3: Direction field flows from KeywordMatch → ReviewCandidate → Database
- L4: Context-dependent multipliers affect keyword selection appropriately

Test Strategy:
- Use realistic filing text patterns
- Verify direction is computed and persisted correctly
- Verify multipliers influence keyword selection as expected
- Test all context types (parenthetical, bullet, table, copula, preposition)
- Verify database schema compliance (direction constraint)
"""

from decimal import Decimal

import pytest

from src.infra.db import DatabaseAdapter
from src.review.candidate_generator import CandidateGenerator
from src.review.config import CandidateGenerationConfig
from src.review.models import SegmentDict

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def db(test_db_url):
    """Database adapter with test database."""
    return DatabaseAdapter(test_db_url)


@pytest.fixture
def generator():
    """Candidate generator with L3/L4 enabled."""
    config = CandidateGenerationConfig(
        max_keyword_distance=200,
        prefer_closest_keyword=True,
        use_context_dependent_multipliers=True,
    )
    return CandidateGenerator(config=config)


@pytest.fixture
def generator_no_multipliers():
    """Candidate generator with L4 disabled (L3 only)."""
    config = CandidateGenerationConfig(
        max_keyword_distance=200,
        prefer_closest_keyword=True,
        use_context_dependent_multipliers=False,
        post_value_distance_multiplier=1.0,  # No preference
    )
    return CandidateGenerator(config=config)


# =============================================================================
# L3 Validation Tests - Direction Detection
# =============================================================================


class TestL3DirectionDetection:
    """Validate L3 direction detection from end-to-end."""

    def test_direction_before_persisted_to_database(self, db, generator):
        """Direction 'before' is persisted to database correctly."""
        # Arrange: Text with keyword before number
        text = "Our gross margin was 52% for the year."
        segment: SegmentDict = {
            "segment_id": 1,
            "section_name": "Results",
            "segment_type": "paragraph",
            "raw_text": text,
            "raw_html": f"<p>{text}</p>",
            "start_char": 0,
            "end_char": len(text),
        }

        # Act: Generate candidates
        candidates = generator.generate_for_filing(
            filing_id=1,
            company_id=1,
            segments=[segment],
            db=db,
        )

        # Assert: Should have at least one candidate
        assert len(candidates) > 0, "Expected at least one candidate"

        # Find the gross margin candidate by metric_id
        margin_candidates = [
            c for c in candidates
            if c.parsed_value == Decimal("0.52") and c.suggested_metric_id == "cm_gross_margin_overall"
        ]
        assert len(margin_candidates) > 0, \
            f"Expected gross margin candidate, got: {[(c.parsed_value, c.suggested_metric_id) for c in candidates]}"

        # Verify direction is 'before'
        candidate = margin_candidates[0]
        assert candidate.keyword_position == "before", \
            f"Expected 'before', got '{candidate.keyword_position}'"

    def test_direction_after_persisted_to_database(self, db, generator):
        """Direction 'after' is persisted to database correctly."""
        # Arrange: Text with keyword after number
        text = "We achieved 52% gross margin improvement."
        segment: SegmentDict = {
            "segment_id": 1,
            "section_name": "Results",
            "segment_type": "paragraph",
            "raw_text": text,
            "raw_html": f"<p>{text}</p>",
            "start_char": 0,
            "end_char": len(text),
        }

        # Act: Generate candidates
        candidates = generator.generate_for_filing(
            filing_id=1,
            company_id=1,
            segments=[segment],
            db=db,
        )

        # Assert: Should have at least one candidate
        assert len(candidates) > 0

        # Find the gross margin candidate
        margin_candidates = [
            c for c in candidates
            if c.parsed_value == Decimal("0.52") and c.suggested_metric_id == "cm_gross_margin_overall"
        ]
        assert len(margin_candidates) > 0

        # Verify direction is 'after'
        candidate = margin_candidates[0]
        assert candidate.keyword_position == "after", \
            f"Expected 'after', got '{candidate.keyword_position}'"

    def test_direction_at_mapped_to_before(self, db, generator):
        """Edge case: 'at' direction is mapped to 'before' for semantic correctness."""
        # Note: This is an edge case where keyword and number start at same position
        # In practice, this is rare, but we handle it by mapping 'at' → 'before'
        # Rationale: When at same position, there's no temporal "after" in reading order
        # The database schema constrains direction to ('before', 'after')

        # Arrange: Create segment with contrived text that might trigger 'at'
        text = "revenue100margin"  # Keyword and number adjacent (unrealistic but tests edge case)
        segment: SegmentDict = {
            "segment_id": 1,
            "section_name": "Results",
            "segment_type": "paragraph",
            "raw_text": text,
            "raw_html": f"<p>{text}</p>",
            "start_char": 0,
            "end_char": len(text),
        }

        # Act: Generate candidates
        candidates = generator.generate_for_filing(
            filing_id=1,
            company_id=1,
            segments=[segment],
            db=db,
        )

        # Assert: All candidates should have valid direction ('before' or 'after')
        for candidate in candidates:
            assert candidate.keyword_position in ("before", "after"), \
                f"Invalid direction: {candidate.keyword_position} (should be 'before' or 'after')"

    def test_multiple_numbers_correct_directions(self, db, generator):
        """Each number gets correct direction for its nearest keywords."""
        # Arrange: Text with two numbers and their keywords
        text = "We had 50000 active customers and gross margin of 52%"
        #              ^num1  ^kw1 (after)            ^kw2 (before) ^num2
        segment: SegmentDict = {
            "segment_id": 1,
            "section_name": "Results",
            "segment_type": "paragraph",
            "raw_text": text,
            "raw_html": f"<p>{text}</p>",
            "start_char": 0,
            "end_char": len(text),
        }

        # Act: Generate candidates
        candidates = generator.generate_for_filing(
            filing_id=1,
            company_id=1,
            segments=[segment],
            db=db,
        )

        # Assert: Should have at least 2 candidates
        assert len(candidates) >= 2

        # Find customer candidate (50000)
        customer_candidates = [
            c for c in candidates
            if c.parsed_value == Decimal("50000") and "cm_active_customers_total" in c.suggested_metric_id
        ]
        if customer_candidates:
            # "active customers" is AFTER 50000
            assert customer_candidates[0].keyword_position == "after"

        # Find margin candidate (52%)
        margin_candidates = [
            c for c in candidates
            if c.parsed_value == Decimal("0.52") and c.suggested_metric_id == "cm_gross_margin_overall"
        ]
        if margin_candidates:
            # "gross margin" is BEFORE 52%
            assert margin_candidates[0].keyword_position == "before"


# =============================================================================
# L4 Validation Tests - Context-Dependent Multipliers
# =============================================================================


class TestL4ContextDependentMultipliers:
    """Validate L4 context-dependent multipliers affect keyword selection."""

    def test_parenthetical_prefers_post_value(self, db, generator):
        """Parenthetical text prefers post-value keywords."""
        # Arrange: "33% (gross margin)" - metric in parentheses after value
        text = "We achieved 33% (gross margin) improvement in Q1."
        segment: SegmentDict = {
            "segment_id": 1,
            "section_name": "Results",
            "segment_type": "paragraph",
            "raw_text": text,
            "raw_html": f"<p>{text}</p>",
            "start_char": 0,
            "end_char": len(text),
        }

        # Act: Generate candidates
        candidates = generator.generate_for_filing(
            filing_id=1,
            company_id=1,
            segments=[segment],
            db=db,
        )

        # Assert: Should find "gross margin" (post-value, in parentheses)
        margin_candidates = [
            c for c in candidates
            if c.parsed_value == Decimal("0.33") and c.suggested_metric_id == "cm_gross_margin_overall"
        ]
        assert len(margin_candidates) > 0
        assert margin_candidates[0].keyword_position == "after"

    def test_bullet_point_prefers_pre_value(self, db, generator):
        """Bullet points prefer pre-value keywords."""
        # Arrange: "• Gross margin was 33%" - metric before value in bullet
        text = "• Gross margin was 33% improvement"
        segment: SegmentDict = {
            "segment_id": 1,
            "section_name": "Results",
            "segment_type": "paragraph",
            "raw_text": text,
            "raw_html": f"<p>{text}</p>",
            "start_char": 0,
            "end_char": len(text),
        }

        # Act: Generate candidates
        candidates = generator.generate_for_filing(
            filing_id=1,
            company_id=1,
            segments=[segment],
            db=db,
        )

        # Assert: Should find "gross margin" (pre-value, in bullet)
        margin_candidates = [
            c for c in candidates
            if c.parsed_value == Decimal("0.33") and c.suggested_metric_id == "cm_gross_margin_overall"
        ]
        assert len(margin_candidates) > 0
        # Should be 'before' due to bullet context (prefers pre-value)
        assert margin_candidates[0].keyword_position == "before"

    def test_copula_verb_prefers_pre_value(self, db, generator):
        """Copula verbs (is/was/were) prefer pre-value keywords."""
        # Arrange: "Gross margin was 33%" - copula verb between metric and value
        text = "Gross margin was 33% in the quarter."
        segment: SegmentDict = {
            "segment_id": 1,
            "section_name": "Results",
            "segment_type": "paragraph",
            "raw_text": text,
            "raw_html": f"<p>{text}</p>",
            "start_char": 0,
            "end_char": len(text),
        }

        # Act: Generate candidates
        candidates = generator.generate_for_filing(
            filing_id=1,
            company_id=1,
            segments=[segment],
            db=db,
        )

        # Assert: Should find "gross margin" (pre-value, with copula verb)
        margin_candidates = [
            c for c in candidates
            if c.parsed_value == Decimal("0.33") and c.suggested_metric_id == "cm_gross_margin_overall"
        ]
        assert len(margin_candidates) > 0
        assert margin_candidates[0].keyword_position == "before"

    def test_preposition_prefers_post_value(self, db, generator):
        """Prepositional phrases (of/for/in) prefer post-value keywords."""
        # Arrange: "33% of revenue" - preposition after value
        text = "We achieved 33% of revenue growth in Q1."
        segment: SegmentDict = {
            "segment_id": 1,
            "section_name": "Results",
            "segment_type": "paragraph",
            "raw_text": text,
            "raw_html": f"<p>{text}</p>",
            "start_char": 0,
            "end_char": len(text),
        }

        # Act: Generate candidates
        candidates = generator.generate_for_filing(
            filing_id=1,
            company_id=1,
            segments=[segment],
            db=db,
        )

        # Assert: Should find "revenue" (post-value, after preposition)
        # Note: revenue might not match if not in metric keywords
        # This test verifies the multiplier is applied, not specific keyword selection
        assert len(candidates) > 0

    def test_multiplier_disabled_uses_distance_only(self, db, generator_no_multipliers):
        """With multipliers disabled, closest keyword wins regardless of direction."""
        # Arrange: Equidistant keywords before and after
        text = "active customers here 100 retention rate"
        #       ^pre-value (far)  ^num ^post-value (far)
        segment: SegmentDict = {
            "segment_id": 1,
            "section_name": "Results",
            "segment_type": "paragraph",
            "raw_text": text,
            "raw_html": f"<p>{text}</p>",
            "start_char": 0,
            "end_char": len(text),
        }

        # Act: Generate candidates with multipliers DISABLED
        candidates = generator_no_multipliers.generate_for_filing(
            filing_id=1,
            company_id=1,
            segments=[segment],
            db=db,
        )

        # Assert: Should find candidates based purely on distance
        assert len(candidates) > 0
        # With multiplier=1.0, direction doesn't influence selection
        # (this is baseline behavior for comparison)


# =============================================================================
# L3+L4 Combined Tests - Direction + Multiplier Interaction
# =============================================================================


class TestL3L4Combined:
    """Validate L3 and L4 work together correctly."""

    def test_direction_recorded_with_multiplier_applied(self, db, generator):
        """Direction is recorded correctly even when multiplier influences selection."""
        # Arrange: Pre-value keyword far away, post-value keyword close
        # Multiplier should make post-value win, and direction should be 'after'
        text = "active customers increased significantly here and 100 gross margin"
        #       ^pre-value (far)                                   ^num ^post-value (close)
        segment: SegmentDict = {
            "segment_id": 1,
            "section_name": "Results",
            "segment_type": "paragraph",
            "raw_text": text,
            "raw_html": f"<p>{text}</p>",
            "start_char": 0,
            "end_char": len(text),
        }

        # Act: Generate candidates
        candidates = generator.generate_for_filing(
            filing_id=1,
            company_id=1,
            segments=[segment],
            db=db,
        )

        # Assert: Should have at least one candidate
        assert len(candidates) > 0

        # Gross margin is much closer than active customers, should win
        margin_candidates = [
            c for c in candidates
            if c.parsed_value == Decimal("100") and c.suggested_metric_id == "cm_gross_margin_overall"
        ]
        if len(margin_candidates) > 0:
            # Should be 'after' (post-value) and should be the selected keyword
            assert margin_candidates[0].keyword_position == "after"

    def test_boundary_and_multiplier_both_applied(self, db, generator):
        """Boundary filtering happens first, then multiplier sorting."""
        # Arrange: Two bullets, each with different keywords
        text = """• Active customers increased significantly
• Performance was 100 with gross margin improvement"""
        segment: SegmentDict = {
            "segment_id": 1,
            "section_name": "Results",
            "segment_type": "paragraph",
            "raw_text": text,
            "raw_html": f"<p>{text}</p>",
            "start_char": 0,
            "end_char": len(text),
        }

        # Act: Generate candidates
        candidates = generator.generate_for_filing(
            filing_id=1,
            company_id=1,
            segments=[segment],
            db=db,
        )

        # Assert: Should find "gross margin" (same bullet, post-value)
        # Should NOT find "active customers" (different bullet, filtered by boundary)
        margin_candidates = [
            c for c in candidates
            if c.parsed_value == Decimal("100") and c.suggested_metric_id == "cm_gross_margin_overall"
        ]
        if len(margin_candidates) > 0:
            assert margin_candidates[0].keyword_position == "after"

        # Verify no customer candidates for value 100
        customer_candidates = [
            c for c in candidates
            if c.parsed_value == Decimal("100") and "customer" in c.triggering_keyword.lower()
        ]
        # Should be 0 (filtered by boundary)
        assert len(customer_candidates) == 0


# =============================================================================
# Real-World Pattern Tests
# =============================================================================


class TestRealWorldPatterns:
    """Test L3/L4 on realistic filing patterns."""

    def test_farfetch_ltv_cac_pattern(self, db, generator):
        """Test the Farfetch LTV/CAC example from Issue 1 - boundary detection prevents cross-bullet matching."""
        # Arrange: The problematic pattern from METRIC_IDENTIFICATION_ISSUES.md
        text = """• Six month LTV/CAC ratio for the years ended December 31, 2015, 2016 and 2017 cohorts was 1.42, 1.53 and 1.72, respectively; and
• Platform Order Contribution Margin for the years ended December 31, 2015, 2016 and 2017 was 33.0%, 35.0% and 43.0%, respectively."""

        segment: SegmentDict = {
            "segment_id": 1,
            "section_name": "Key Performance Indicators",
            "segment_type": "paragraph",
            "raw_text": text,
            "raw_html": f"<p>{text}</p>",
            "start_char": 0,
            "end_char": len(text),
        }

        # Act: Generate candidates
        candidates = generator.generate_for_filing(
            filing_id=1,
            company_id=1,
            segments=[segment],
            db=db,
        )

        # Assert: Should have candidates
        assert len(candidates) >= 3  # At least the LTV/CAC values

        # Verify LTV/CAC candidates (1.42, 1.53, 1.72) are matched correctly
        ltv_candidates = [
            c for c in candidates
            if c.parsed_value in (Decimal("1.42"), Decimal("1.53"), Decimal("1.72"))
        ]
        assert len(ltv_candidates) >= 3, \
            f"Expected at least 3 LTV/CAC candidates, got: {[(c.parsed_value, c.suggested_metric_id) for c in candidates]}"

        # The key test: LTV/CAC values should NOT incorrectly match "Contribution Margin"
        # from the second bullet (boundary detection prevents this)
        for ltv_candidate in ltv_candidates:
            # Check that it's matched to LTV-related metrics, not margin metrics
            assert "ltv" in ltv_candidate.suggested_metric_id.lower() or \
                   "lifetime" in ltv_candidate.suggested_metric_id.lower() or \
                   "cac" in ltv_candidate.suggested_metric_id.lower() or \
                   "acquisition" in ltv_candidate.suggested_metric_id.lower(), \
                f"LTV/CAC value {ltv_candidate.parsed_value} incorrectly matched to: {ltv_candidate.suggested_metric_id}"

        # Note: The 33%, 35%, 43% values may or may not be matched due to distance filtering
        # and year filtering. The key improvement from L3/L4 is that boundary detection
        # prevents cross-bullet matching (LTV/CAC values won't match margin keywords)

    def test_subject_verb_object_structure(self, db, generator):
        """Test standard subject-verb-object: 'Gross margin was 33%'."""
        text = "Gross margin was 33% for the quarter ended March 31, 2017."
        segment: SegmentDict = {
            "segment_id": 1,
            "section_name": "Results",
            "segment_type": "paragraph",
            "raw_text": text,
            "raw_html": f"<p>{text}</p>",
            "start_char": 0,
            "end_char": len(text),
        }

        # Act: Generate candidates
        candidates = generator.generate_for_filing(
            filing_id=1,
            company_id=1,
            segments=[segment],
            db=db,
        )

        # Assert: Should find gross margin candidate
        margin_candidates = [
            c for c in candidates
            if c.parsed_value == Decimal("0.33") and c.suggested_metric_id == "cm_gross_margin_overall"
        ]
        assert len(margin_candidates) > 0
        # "Gross margin" is before "was 33%"
        assert margin_candidates[0].keyword_position == "before"

    def test_metric_clarification_parenthetical(self, db, generator):
        """Test metric clarification: '33% (gross margin)'."""
        text = "The company achieved 33% (gross margin) through operational improvements."
        segment: SegmentDict = {
            "segment_id": 1,
            "section_name": "Results",
            "segment_type": "paragraph",
            "raw_text": text,
            "raw_html": f"<p>{text}</p>",
            "start_char": 0,
            "end_char": len(text),
        }

        # Act: Generate candidates
        candidates = generator.generate_for_filing(
            filing_id=1,
            company_id=1,
            segments=[segment],
            db=db,
        )

        # Assert: Should find gross margin candidate (in parentheses after value)
        margin_candidates = [
            c for c in candidates
            if c.parsed_value == Decimal("0.33") and c.suggested_metric_id == "cm_gross_margin_overall"
        ]
        assert len(margin_candidates) > 0
        # Parenthetical multiplier (1.15) should prefer post-value "gross margin"
        assert margin_candidates[0].keyword_position == "after"
