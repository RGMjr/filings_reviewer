"""
Integration tests for E2 RuleApplicator with CandidateGenerator.

Tests the end-to-end workflow of learned pattern filtering during
candidate generation.
"""

import pytest
from decimal import Decimal

from src.review.candidate_generator import CandidateGenerator


class TestE2CandidateFiltering:
    """Test E2 learned pattern filtering integration."""

    @pytest.fixture
    def sample_filing_data(self, clean_db):
        """Create test filing for E2 testing."""
        # Insert company
        company_id = clean_db.upsert_company(
            cik="0001234567",
            company_name="Test E2 Company",
        )

        # Insert filing
        filing_id = clean_db.upsert_filing(
            company_id=company_id,
            cik="0001234567",
            accession_number="0001234567-23-000001",
            filing_date="2023-06-15",
            form_type="S-1",
            sec_html_url="https://test.example.com",
            is_post_combination=False,
            is_investment_vehicle=False,
            is_resource_extraction=False,
        )

        # Create mock segments with text containing numbers and keywords
        segments = [
            {
                "source_segment_id": 1,
                "filing_id": filing_id,
                "segment_type": "paragraph",
                "raw_text": (
                    "Our annual recurring revenue (ARR) was $50.2 million "
                    "for the year ended December 31, 2022."
                ),
                "section_heading": "Business Overview",
                "section_path": "/Business Overview",
            },
            {
                "source_segment_id": 2,
                "filing_id": filing_id,
                "segment_type": "paragraph",
                "raw_text": (
                    "Risk Factors: The market size is estimated at $500 million. "
                    "We may face increased competition from the 1,234 existing competitors."
                ),
                "section_heading": "Risk Factors",
                "section_path": "/Risk Factors",
            },
            {
                "source_segment_id": 3,
                "filing_id": filing_id,
                "segment_type": "paragraph",
                "raw_text": (
                    "We had 12,500 active customers as of December 31, 2022, "
                    "representing a 45% increase from the prior year."
                ),
                "section_heading": "Our Customers",
                "section_path": "/Our Customers",
            },
        ]

        return {
            "filing_id": filing_id,
            "company_id": company_id,
            "segments": segments,
        }

    def test_baseline_without_learned_rules(self, clean_db, sample_filing_data):
        """Test candidate generation without learned rules (baseline)."""
        # Use segments from fixture
        segments = sample_filing_data["segments"]

        # Generate candidates with learned rules disabled
        generator = CandidateGenerator(apply_learned_rules=False)
        candidates = generator.generate_for_filing(
            filing_id=sample_filing_data["filing_id"],
            company_id=sample_filing_data["company_id"],
            segments=segments,
            db=clean_db,
        )

        # Should generate candidates from all segments
        assert len(candidates) > 0

    def test_improved_with_reject_rule(self, clean_db, sample_filing_data):
        """Test candidate generation with reject_rule pattern filters candidates."""
        # Insert a reject_rule pattern for risk factors
        pattern_id = clean_db.insert_learned_pattern(
            pattern_type="reject_rule",
            metric_id=None,  # Global pattern
            pattern_name="Test: Filter risk factors",
            pattern_definition={
                "conditions": [
                    {"field": "is_in_risk_factors", "op": "eq", "value": True}
                ]
            },
            precision_score=0.95,
            recall_score=0.80,
            sample_count=50,
        )

        # Approve the pattern (status='approved' is set by default on insert)
        # Note: Patterns are created with status='candidate' by default
        # We need to update to 'approved' for E2 to apply them
        clean_db.execute(
            "UPDATE learned_patterns SET status = 'approved' WHERE pattern_id = %(pattern_id)s",
            {"pattern_id": pattern_id}
        )

        # Use segments from fixture
        segments = sample_filing_data["segments"]

        # Generate candidates with learned rules enabled (default)
        generator = CandidateGenerator(apply_learned_rules=True)
        candidates, stats = generator.generate_for_filing(
            filing_id=sample_filing_data["filing_id"],
            company_id=sample_filing_data["company_id"],
            segments=segments,
            db=clean_db,
            return_stats=True,
        )

        # Verify filtering occurred
        # All candidates should NOT be in risk factors
        risk_factors_candidates = [
            c for c in candidates if c.features.is_in_risk_factors
        ]
        assert len(risk_factors_candidates) == 0, (
            "Expected all risk factors candidates to be filtered"
        )

        # Verify stats tracking
        assert stats.filtered_by_learned_rules >= 0

    def test_pattern_enable_disable_toggle(self, clean_db, sample_filing_data):
        """Test toggling learned rules on/off affects filtering."""
        # Insert reject pattern
        pattern_id = clean_db.insert_learned_pattern(
            pattern_type="reject_rule",
            metric_id=None,
            pattern_name="Test: Filter risk factors",
            pattern_definition={
                "conditions": [
                    {"field": "is_in_risk_factors", "op": "eq", "value": True}
                ]
            },
            precision_score=0.95,
            recall_score=0.80,
            sample_count=50,
        )

        # Approve the pattern
        clean_db.execute(
            "UPDATE learned_patterns SET status = 'approved' WHERE pattern_id = %(pattern_id)s",
            {"pattern_id": pattern_id}
        )

        # Use segments from fixture
        segments = sample_filing_data["segments"]

        # Generate with rules DISABLED
        generator_off = CandidateGenerator(apply_learned_rules=False)
        candidates_off = generator_off.generate_for_filing(
            filing_id=sample_filing_data["filing_id"],
            company_id=sample_filing_data["company_id"],
            segments=segments,
            db=clean_db,
        )

        # Generate with rules ENABLED
        generator_on = CandidateGenerator(apply_learned_rules=True)
        candidates_on = generator_on.generate_for_filing(
            filing_id=sample_filing_data["filing_id"],
            company_id=sample_filing_data["company_id"],
            segments=segments,
            db=clean_db,
        )

        # With rules enabled, should have fewer or equal candidates
        assert len(candidates_on) <= len(candidates_off)

        # Risk factors candidates should be filtered when enabled
        risk_on = [c for c in candidates_on if c.features.is_in_risk_factors]
        assert len(risk_on) == 0

    def test_no_db_provided_skips_filtering(self, clean_db, sample_filing_data):
        """Test that filtering is skipped if db=None."""
        # Insert pattern (should not be applied without db)
        pattern_id = clean_db.insert_learned_pattern(
            pattern_type="reject_rule",
            metric_id=None,
            pattern_name="Test: Should not apply",
            pattern_definition={
                "conditions": [
                    {"field": "is_in_risk_factors", "op": "eq", "value": True}
                ]
            },
            precision_score=0.95,
            recall_score=0.80,
            sample_count=50,
        )

        # Approve the pattern
        clean_db.execute(
            "UPDATE learned_patterns SET status = 'approved' WHERE pattern_id = %(pattern_id)s",
            {"pattern_id": pattern_id}
        )

        # Use segments from fixture
        segments = sample_filing_data["segments"]

        # Generate candidates WITHOUT passing db
        generator = CandidateGenerator(apply_learned_rules=True)
        candidates = generator.generate_for_filing(
            filing_id=sample_filing_data["filing_id"],
            company_id=sample_filing_data["company_id"],
            segments=segments,
            db=None,  # No database provided
        )

        # Filtering should be skipped (no assertion about content, just that it runs)
        assert isinstance(candidates, list)
