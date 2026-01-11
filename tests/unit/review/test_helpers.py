"""
Tests for src/review/helpers.py

Tests the generate_candidates_for_filing() convenience function.
"""

from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from src.review.candidate_generator import CandidateGenerator
from src.review.helpers import generate_candidates_for_filing


class TestGenerateCandidatesForFiling:
    """Tests for the generate_candidates_for_filing convenience function."""

    @pytest.fixture
    def mock_db(self):
        """Create a mock database adapter."""
        db = MagicMock()
        return db

    def test_generates_candidates_for_valid_filing(self, mock_db):
        """Generate candidates when filing and segments exist."""
        # Setup mock
        mock_db.get_filing_with_company.return_value = {
            "filing_id": 1,
            "company_id": 100,
            "accession_number": "0001234567-24-000001",
            "form_type": "S-1",
            "company_name": "Test Company",
        }
        mock_db.get_source_segments_for_filing.return_value = [
            {
                "source_segment_id": 1,
                "raw_text": "We have 50,000 active customers as of year end.",
            }
        ]

        # Execute
        candidates = generate_candidates_for_filing(mock_db, filing_id=1)

        # Verify
        assert len(candidates) >= 1
        assert candidates[0].filing_id == 1
        assert candidates[0].company_id == 100
        assert candidates[0].suggested_metric_id == "cm_active_customers_total"

        # Verify DB calls
        mock_db.get_filing_with_company.assert_called_once_with(1)
        mock_db.get_source_segments_for_filing.assert_called_once_with(1)

    def test_raises_value_error_when_filing_not_found(self, mock_db):
        """Raise ValueError when filing doesn't exist."""
        mock_db.get_filing_with_company.return_value = None

        with pytest.raises(ValueError, match="Filing not found: 999"):
            generate_candidates_for_filing(mock_db, filing_id=999)

        # Should not call get_source_segments_for_filing
        mock_db.get_source_segments_for_filing.assert_not_called()

    def test_returns_empty_list_when_no_segments(self, mock_db):
        """Return empty list when filing has no segments."""
        mock_db.get_filing_with_company.return_value = {
            "filing_id": 1,
            "company_id": 100,
        }
        mock_db.get_source_segments_for_filing.return_value = []

        candidates = generate_candidates_for_filing(mock_db, filing_id=1)

        assert candidates == []

    def test_returns_empty_list_when_segments_is_none(self, mock_db):
        """Return empty list when get_source_segments_for_filing returns None."""
        mock_db.get_filing_with_company.return_value = {
            "filing_id": 1,
            "company_id": 100,
        }
        mock_db.get_source_segments_for_filing.return_value = None

        candidates = generate_candidates_for_filing(mock_db, filing_id=1)

        assert candidates == []

    def test_uses_custom_generator_when_provided(self, mock_db):
        """Use custom generator when provided."""
        mock_db.get_filing_with_company.return_value = {
            "filing_id": 1,
            "company_id": 100,
        }
        mock_db.get_source_segments_for_filing.return_value = [
            {
                "source_segment_id": 1,
                "raw_text": "We have 50,000 active customers.",
            }
        ]

        # Create custom generator with different settings
        custom_generator = CandidateGenerator(
            max_keyword_distance=50,  # Shorter distance
            context_words=20,
        )

        candidates = generate_candidates_for_filing(
            mock_db, filing_id=1, generator=custom_generator
        )

        # Should still find candidates (keyword is close enough)
        assert len(candidates) >= 1

    def test_generates_multiple_candidates_from_multiple_segments(self, mock_db):
        """Generate candidates from multiple segments."""
        mock_db.get_filing_with_company.return_value = {
            "filing_id": 1,
            "company_id": 100,
        }
        mock_db.get_source_segments_for_filing.return_value = [
            {
                "source_segment_id": 1,
                "raw_text": "We have 50,000 active customers.",
            },
            {
                "source_segment_id": 2,
                "raw_text": "Our retention rate is 95%.",
            },
        ]

        candidates = generate_candidates_for_filing(mock_db, filing_id=1)

        # Should have candidates from both segments
        assert len(candidates) >= 2

        segment_ids = {c.source_segment_id for c in candidates}
        assert 1 in segment_ids
        assert 2 in segment_ids

    def test_no_candidates_when_no_metric_keywords(self, mock_db):
        """Return empty list when segments have no metric keywords near numbers."""
        mock_db.get_filing_with_company.return_value = {
            "filing_id": 1,
            "company_id": 100,
        }
        mock_db.get_source_segments_for_filing.return_value = [
            {
                "source_segment_id": 1,
                "raw_text": "The weather was 75 degrees in summer.",
            }
        ]

        candidates = generate_candidates_for_filing(mock_db, filing_id=1)

        assert candidates == []

    def test_candidate_has_correct_context(self, mock_db):
        """Verify candidate context contains the number and surrounding text."""
        mock_db.get_filing_with_company.return_value = {
            "filing_id": 1,
            "company_id": 100,
        }
        mock_db.get_source_segments_for_filing.return_value = [
            {
                "source_segment_id": 1,
                "raw_text": "As of December 31, 2023, we had 10,000 active customers worldwide.",
            }
        ]

        candidates = generate_candidates_for_filing(mock_db, filing_id=1)

        assert len(candidates) >= 1
        # Context should include the number
        assert "10,000" in candidates[0].context_text
        # Context should include surrounding text
        assert "active customers" in candidates[0].context_text

    def test_candidate_parsed_value_is_correct(self, mock_db):
        """Verify parsed numeric value is correct."""
        mock_db.get_filing_with_company.return_value = {
            "filing_id": 1,
            "company_id": 100,
        }
        mock_db.get_source_segments_for_filing.return_value = [
            {
                "source_segment_id": 1,
                "raw_text": "We acquired 5 million new customers.",
            }
        ]

        candidates = generate_candidates_for_filing(mock_db, filing_id=1)

        assert len(candidates) >= 1
        # Should parse "5 million" as 5000000
        assert candidates[0].parsed_value == Decimal("5000000")

    def test_saves_candidates_when_save_true(self, mock_db):
        """Save candidates to database when save=True."""
        mock_db.get_filing_with_company.return_value = {
            "filing_id": 1,
            "company_id": 100,
        }
        mock_db.get_source_segments_for_filing.return_value = [
            {
                "source_segment_id": 1,
                "raw_text": "We have 50,000 active customers.",
            }
        ]
        # Mock bulk insert returns candidate IDs
        mock_db.bulk_insert_review_candidates.return_value = [101]

        candidates = generate_candidates_for_filing(mock_db, filing_id=1, save=True)

        # Verify bulk insert was called
        mock_db.bulk_insert_review_candidates.assert_called_once()

        # Verify candidate has ID set
        assert len(candidates) >= 1
        assert candidates[0].candidate_id == 101

    def test_does_not_save_when_save_false(self, mock_db):
        """Do not save candidates when save=False (default)."""
        mock_db.get_filing_with_company.return_value = {
            "filing_id": 1,
            "company_id": 100,
        }
        mock_db.get_source_segments_for_filing.return_value = [
            {
                "source_segment_id": 1,
                "raw_text": "We have 50,000 active customers.",
            }
        ]

        candidates = generate_candidates_for_filing(mock_db, filing_id=1, save=False)

        # Verify bulk insert was NOT called
        mock_db.bulk_insert_review_candidates.assert_not_called()

        # Candidate should not have an ID
        assert len(candidates) >= 1
        assert candidates[0].candidate_id is None

    def test_assigns_batch_id_when_provided(self, mock_db):
        """Assign batch_id to candidates when saving."""
        mock_db.get_filing_with_company.return_value = {
            "filing_id": 1,
            "company_id": 100,
        }
        mock_db.get_source_segments_for_filing.return_value = [
            {
                "source_segment_id": 1,
                "raw_text": "We have 50,000 active customers.",
            }
        ]
        mock_db.bulk_insert_review_candidates.return_value = [101]

        generate_candidates_for_filing(mock_db, filing_id=1, save=True, batch_id=42)

        # Get the call args for bulk_insert
        call_args = mock_db.bulk_insert_review_candidates.call_args
        candidate_dicts = call_args[0][0]

        # Verify batch_id was set
        assert candidate_dicts[0]["review_batch_id"] == 42

    def test_does_not_save_when_no_candidates(self, mock_db):
        """Do not call save when there are no candidates."""
        mock_db.get_filing_with_company.return_value = {
            "filing_id": 1,
            "company_id": 100,
        }
        mock_db.get_source_segments_for_filing.return_value = [
            {
                "source_segment_id": 1,
                "raw_text": "No metrics here, just text.",
            }
        ]

        candidates = generate_candidates_for_filing(mock_db, filing_id=1, save=True)

        # No candidates, so bulk insert should not be called
        assert candidates == []
        mock_db.bulk_insert_review_candidates.assert_not_called()


class TestSuppressionLogging:
    """Tests for DUP-3 suppression logging feature."""

    @pytest.fixture
    def mock_db(self):
        """Create a mock database adapter."""
        db = MagicMock()
        return db

    def test_log_suppressed_false_by_default(self, mock_db):
        """Default behavior: log_suppressed=False, returns list of IDs."""
        mock_db.get_filing_with_company.return_value = {
            "filing_id": 1,
            "company_id": 100,
        }
        mock_db.get_source_segments_for_filing.return_value = [
            {
                "source_segment_id": 1,
                "raw_text": "We have 50,000 active customers.",
            }
        ]
        # Default return type when log_suppressed=False
        mock_db.bulk_insert_review_candidates.return_value = [101]

        candidates = generate_candidates_for_filing(mock_db, filing_id=1, save=True)

        # Should call without log_suppressed kwarg (defaults to False)
        mock_db.bulk_insert_review_candidates.assert_called_once()
        call_kwargs = mock_db.bulk_insert_review_candidates.call_args.kwargs
        assert "log_suppressed" not in call_kwargs or call_kwargs.get("log_suppressed") is False

        assert len(candidates) >= 1
        assert candidates[0].candidate_id == 101

    def test_log_suppressed_true_passes_to_db(self, mock_db):
        """When log_suppressed=True, pass to bulk_insert_review_candidates."""
        mock_db.get_filing_with_company.return_value = {
            "filing_id": 1,
            "company_id": 100,
        }
        mock_db.get_source_segments_for_filing.return_value = [
            {
                "source_segment_id": 1,
                "raw_text": "We have 50,000 active customers.",
            }
        ]
        # Return type when log_suppressed=True: (ids, suppression_entries)
        mock_db.bulk_insert_review_candidates.return_value = ([101], [])

        candidates = generate_candidates_for_filing(
            mock_db, filing_id=1, save=True, log_suppressed=True
        )

        # Should call with log_suppressed=True
        mock_db.bulk_insert_review_candidates.assert_called_once()
        call_kwargs = mock_db.bulk_insert_review_candidates.call_args.kwargs
        assert call_kwargs.get("log_suppressed") is True

        assert len(candidates) >= 1
        assert candidates[0].candidate_id == 101

    def test_log_suppressed_with_suppression_entries(self, mock_db):
        """Handle suppression entries returned from database."""
        mock_db.get_filing_with_company.return_value = {
            "filing_id": 1,
            "company_id": 100,
        }
        mock_db.get_source_segments_for_filing.return_value = [
            {
                "source_segment_id": 1,
                "raw_text": "We have 50,000 active customers.",
            }
        ]
        # Simulate suppression entries
        suppression_entries = [
            {"suppression_reason": "lower_confidence", "suppressed_id": 201},
            {"suppression_reason": "runner_up", "suppressed_id": 202},
            {"suppression_reason": "lower_confidence", "suppressed_id": 203},
        ]
        mock_db.bulk_insert_review_candidates.return_value = ([101], suppression_entries)

        candidates = generate_candidates_for_filing(
            mock_db, filing_id=1, save=True, log_suppressed=True
        )

        # Function should complete without error
        assert len(candidates) >= 1
        assert candidates[0].candidate_id == 101

    def test_log_suppressed_ignored_when_save_false(self, mock_db):
        """log_suppressed has no effect when save=False."""
        mock_db.get_filing_with_company.return_value = {
            "filing_id": 1,
            "company_id": 100,
        }
        mock_db.get_source_segments_for_filing.return_value = [
            {
                "source_segment_id": 1,
                "raw_text": "We have 50,000 active customers.",
            }
        ]

        # log_suppressed=True but save=False
        candidates = generate_candidates_for_filing(
            mock_db, filing_id=1, save=False, log_suppressed=True
        )

        # bulk_insert should not be called
        mock_db.bulk_insert_review_candidates.assert_not_called()

        # Candidates generated but without IDs
        assert len(candidates) >= 1
        assert candidates[0].candidate_id is None

    def test_log_suppressed_with_no_candidates(self, mock_db):
        """No error when log_suppressed=True but no candidates generated."""
        mock_db.get_filing_with_company.return_value = {
            "filing_id": 1,
            "company_id": 100,
        }
        mock_db.get_source_segments_for_filing.return_value = [
            {
                "source_segment_id": 1,
                "raw_text": "No metrics here, just regular text.",
            }
        ]

        # log_suppressed=True with no candidates
        candidates = generate_candidates_for_filing(
            mock_db, filing_id=1, save=True, log_suppressed=True
        )

        # No candidates, no insert call
        assert candidates == []
        mock_db.bulk_insert_review_candidates.assert_not_called()

    def test_log_suppressed_with_batch_id(self, mock_db):
        """log_suppressed works together with batch_id."""
        mock_db.get_filing_with_company.return_value = {
            "filing_id": 1,
            "company_id": 100,
        }
        mock_db.get_source_segments_for_filing.return_value = [
            {
                "source_segment_id": 1,
                "raw_text": "We have 50,000 active customers.",
            }
        ]
        mock_db.bulk_insert_review_candidates.return_value = ([101], [])

        candidates = generate_candidates_for_filing(
            mock_db, filing_id=1, save=True, batch_id=42, log_suppressed=True
        )

        # Verify both batch_id and log_suppressed work
        call_args = mock_db.bulk_insert_review_candidates.call_args
        candidate_dicts = call_args[0][0]
        call_kwargs = call_args.kwargs

        assert candidate_dicts[0]["review_batch_id"] == 42
        assert call_kwargs.get("log_suppressed") is True
        assert candidates[0].candidate_id == 101
