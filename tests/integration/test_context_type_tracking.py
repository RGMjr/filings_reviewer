"""
Unit tests for context_type tracking (E1 multiplier optimization).

These tests verify that the context_type field is correctly populated
in CandidateFeatures based on the textual context where the keyword-number
pair appears.
"""

import pytest

from src.infra.db import DatabaseAdapter
from src.review.candidate_generator import CandidateGenerator
from src.review.config import CandidateGenerationConfig
from src.review.models import SegmentDict


@pytest.fixture
def db(test_db_url):
    """Database adapter with test database."""
    return DatabaseAdapter(test_db_url)


@pytest.fixture
def generator():
    """Generator with context-dependent multipliers enabled."""
    config = CandidateGenerationConfig(
        use_context_dependent_multipliers=True,
    )
    return CandidateGenerator(config=config)


class TestContextTypeTracking:
    """Verify context_type is tracked in features."""

    def test_table_context_type(self, db, generator):
        """Table segments should have context_type='table'."""
        text = "Gross margin was 52% for the year."
        segment: SegmentDict = {
            "segment_id": 1,
            "section_name": "Results",
            "segment_type": "table",  # Table segment
            "raw_text": text,
            "raw_html": f"<table><tr><td>{text}</td></tr></table>",
            "start_char": 0,
            "end_char": len(text),
        }

        candidates = generator.generate_for_filing(
            filing_id=1,
            company_id=1,
            segments=[segment],
            db=db,
        )

        assert len(candidates) > 0, "Expected at least one candidate"
        # Check first candidate has table context
        assert candidates[0].features is not None
        assert candidates[0].features.context_type == "table"

    def test_bullet_context_type(self, db, generator):
        """Bullet points should have context_type='bullet'."""
        text = "• Gross margin was 52% for the year"
        segment: SegmentDict = {
            "segment_id": 1,
            "section_name": "Results",
            "segment_type": "paragraph",
            "raw_text": text,
            "raw_html": f"<p>{text}</p>",
            "start_char": 0,
            "end_char": len(text),
        }

        candidates = generator.generate_for_filing(
            filing_id=1,
            company_id=1,
            segments=[segment],
            db=db,
        )

        assert len(candidates) > 0, "Expected at least one candidate"
        # Check first candidate has bullet context
        assert candidates[0].features is not None
        assert candidates[0].features.context_type == "bullet"

    def test_parenthetical_context_type(self, db, generator):
        """Parenthetical text (NUMBER in parentheses) should have context_type='parenthetical'."""
        # Note: Parenthetical detection checks if NUMBER is inside parentheses
        text = "The company achieved (52% gross margin) improvement"
        segment: SegmentDict = {
            "segment_id": 1,
            "section_name": "Results",
            "segment_type": "paragraph",
            "raw_text": text,
            "raw_html": f"<p>{text}</p>",
            "start_char": 0,
            "end_char": len(text),
        }

        candidates = generator.generate_for_filing(
            filing_id=1,
            company_id=1,
            segments=[segment],
            db=db,
        )

        assert len(candidates) > 0, "Expected at least one candidate"
        # Check first candidate has parenthetical context
        assert candidates[0].features is not None
        assert candidates[0].features.context_type == "parenthetical"

    def test_copula_context_type(self, db, generator):
        """Copula verb pattern should have context_type='copula'."""
        text = "Gross margin was 52% in the quarter"
        segment: SegmentDict = {
            "segment_id": 1,
            "section_name": "Results",
            "segment_type": "paragraph",
            "raw_text": text,
            "raw_html": f"<p>{text}</p>",
            "start_char": 0,
            "end_char": len(text),
        }

        candidates = generator.generate_for_filing(
            filing_id=1,
            company_id=1,
            segments=[segment],
            db=db,
        )

        assert len(candidates) > 0, "Expected at least one candidate"
        # Check first candidate has copula context
        assert candidates[0].features is not None
        assert candidates[0].features.context_type == "copula"

    def test_default_context_type(self, db, generator):
        """No special context should have context_type='default'."""
        text = "The company increased from gross margin measurement levels by reaching 52 percent"
        segment: SegmentDict = {
            "segment_id": 1,
            "section_name": "Results",
            "segment_type": "paragraph",
            "raw_text": text,
            "raw_html": f"<p>{text}</p>",
            "start_char": 0,
            "end_char": len(text),
        }

        candidates = generator.generate_for_filing(
            filing_id=1,
            company_id=1,
            segments=[segment],
            db=db,
        )

        assert len(candidates) > 0, "Expected at least one candidate"
        # Check first candidate has default context
        assert candidates[0].features is not None
        assert candidates[0].features.context_type == "default"

    def test_context_type_serialization(self, db, generator):
        """Context type should survive serialization round-trip."""
        text = "• Gross margin was 52%"
        segment: SegmentDict = {
            "segment_id": 1,
            "section_name": "Results",
            "segment_type": "paragraph",
            "raw_text": text,
            "raw_html": f"<p>{text}</p>",
            "start_char": 0,
            "end_char": len(text),
        }

        candidates = generator.generate_for_filing(
            filing_id=1,
            company_id=1,
            segments=[segment],
            db=db,
        )

        assert len(candidates) > 0
        candidate = candidates[0]
        assert candidate.features is not None
        assert candidate.features.context_type == "bullet"

        # Serialize to dict and back
        features_dict = candidate.features.to_dict()
        assert "context_type" in features_dict
        assert features_dict["context_type"] == "bullet"

        # Deserialize from dict
        from src.review.models import CandidateFeatures

        features_restored = CandidateFeatures.from_dict(features_dict)
        assert features_restored.context_type == "bullet"
