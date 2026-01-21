"""
Integration tests for DatabaseAdapter image review methods.

Tests CRUD operations on:
- image_review_candidates
- image_review_decisions

Requires:
- TEST_DATABASE_URL environment variable set
- Image review schema applied (sql/09_create_image_review_schema.sql)
"""

import pytest

from src.infra.validation import ValidationError
from tests.integration.conftest import (
    create_test_company_and_filing,
    create_test_image_candidate,
    create_test_image_decision,
)


# =============================================================================
# Candidate Query Tests
# =============================================================================


class TestGetFilingsWithImageCandidates:
    """Tests for get_filings_with_image_candidates method."""

    def test_returns_filing_with_counts(self, clean_db):
        """Test that method returns filing info with candidate counts."""
        company_id, filing_id = create_test_company_and_filing(clean_db)

        # Create 3 candidates: 2 pending, 1 reviewed
        for i in range(3):
            clean_db.insert_image_review_candidate(
                filing_id=filing_id,
                company_id=company_id,
                image_src=f"chart{i}.jpg",
                image_url=f"https://sec.gov/chart{i}.jpg",
                image_index=i + 1,
            )

        # Review one candidate
        candidates = clean_db.get_image_review_candidates_for_filing(filing_id)
        clean_db.insert_image_review_decision(
            image_candidate_id=candidates[0]["image_candidate_id"],
            decision="relevant",
            chart_type="cohort_table",
        )

        # Get filings
        filings = clean_db.get_filings_with_image_candidates()

        assert len(filings) == 1
        f = filings[0]
        assert f["filing_id"] == filing_id
        assert f["total_candidates"] == 3
        assert f["pending_count"] == 2
        assert f["reviewed_count"] == 1
        assert "company_name" in f
        assert "accession_number" in f

    def test_filters_by_status(self, clean_db):
        """Test filtering by candidate status."""
        company_id, filing_id = create_test_company_and_filing(clean_db)

        # Create candidate and review it
        clean_db.insert_image_review_candidate(
            filing_id=filing_id,
            company_id=company_id,
            image_src="chart.jpg",
            image_url="https://sec.gov/chart.jpg",
        )
        candidates = clean_db.get_image_review_candidates_for_filing(filing_id)
        clean_db.insert_image_review_decision(
            image_candidate_id=candidates[0]["image_candidate_id"],
            decision="relevant",
            chart_type="line_chart",
        )

        # Filter by pending - should return empty
        pending_filings = clean_db.get_filings_with_image_candidates(status="pending")
        assert len(pending_filings) == 0

        # Filter by reviewed - should return the filing
        reviewed_filings = clean_db.get_filings_with_image_candidates(status="reviewed")
        assert len(reviewed_filings) == 1

    def test_invalid_status_raises_error(self, clean_db):
        """Test that invalid status raises ValidationError."""
        with pytest.raises(ValidationError, match="review_status"):
            clean_db.get_filings_with_image_candidates(status="invalid_status")


class TestGetFilingsWithImageCandidatesCount:
    """Tests for get_filings_with_image_candidates_count method."""

    def test_returns_correct_count(self, clean_db):
        """Test that count method returns correct total."""
        # Create 3 filings with candidates
        for i in range(3):
            company_id, filing_id = create_test_company_and_filing(
                clean_db,
                cik=f"000123456{i}",
                accession_number=f"0001234567-24-00000{i}",
                company_name=f"Test Corp {i}",
            )
            clean_db.insert_image_review_candidate(
                filing_id=filing_id,
                company_id=company_id,
                image_src="chart.jpg",
                image_url="https://sec.gov/chart.jpg",
            )

        count = clean_db.get_filings_with_image_candidates_count()
        assert count == 3


class TestGetImageReviewCandidatesForFiling:
    """Tests for get_image_review_candidates_for_filing method."""

    def test_sorts_by_tier_priority(self, clean_db):
        """Test that candidates are sorted by detection tier priority."""
        company_id, filing_id = create_test_company_and_filing(clean_db)

        # Insert candidates in reverse priority order
        tiers = ["tier_3_all", "tier_2_large", "tier_1_cohort", "seed_list"]
        for i, tier in enumerate(tiers):
            clean_db.insert_image_review_candidate(
                filing_id=filing_id,
                company_id=company_id,
                image_src=f"chart_{tier}.jpg",
                image_url=f"https://sec.gov/chart_{tier}.jpg",
                detection_tier=tier,
                image_index=i + 1,
            )

        candidates = clean_db.get_image_review_candidates_for_filing(
            filing_id, sort_by="tier"
        )

        # Should be in priority order: seed_list, tier_1, tier_2, tier_3
        assert candidates[0]["detection_tier"] == "seed_list"
        assert candidates[1]["detection_tier"] == "tier_1_cohort"
        assert candidates[2]["detection_tier"] == "tier_2_large"
        assert candidates[3]["detection_tier"] == "tier_3_all"

    def test_sorts_by_confidence(self, clean_db):
        """Test sorting by cohort_confidence."""
        company_id, filing_id = create_test_company_and_filing(clean_db)

        confidences = [0.3, 0.9, 0.5, 0.7]
        for i, conf in enumerate(confidences):
            clean_db.insert_image_review_candidate(
                filing_id=filing_id,
                company_id=company_id,
                image_src=f"chart{i}.jpg",
                image_url=f"https://sec.gov/chart{i}.jpg",
                cohort_confidence=conf,
                image_index=i + 1,
            )

        candidates = clean_db.get_image_review_candidates_for_filing(
            filing_id, sort_by="confidence"
        )

        # Should be descending by confidence
        assert float(candidates[0]["cohort_confidence"]) == 0.9
        assert float(candidates[1]["cohort_confidence"]) == 0.7
        assert float(candidates[2]["cohort_confidence"]) == 0.5
        assert float(candidates[3]["cohort_confidence"]) == 0.3

    def test_sorts_by_position(self, clean_db):
        """Test sorting by image_index (position)."""
        company_id, filing_id = create_test_company_and_filing(clean_db)

        # Insert in scrambled order
        for idx in [3, 1, 4, 2]:
            clean_db.insert_image_review_candidate(
                filing_id=filing_id,
                company_id=company_id,
                image_src=f"chart{idx}.jpg",
                image_url=f"https://sec.gov/chart{idx}.jpg",
                image_index=idx,
            )

        candidates = clean_db.get_image_review_candidates_for_filing(
            filing_id, sort_by="position"
        )

        # Should be in image_index order
        indices = [c["image_index"] for c in candidates]
        assert indices == [1, 2, 3, 4]

    def test_includes_decision_data(self, clean_db):
        """Test that decision data is included via LEFT JOIN."""
        company_id, filing_id, candidate_id = create_test_image_candidate(clean_db)

        # Make a decision
        clean_db.insert_image_review_decision(
            image_candidate_id=candidate_id,
            decision="relevant",
            chart_type="cohort_heatmap",
            reviewer_notes="Good chart",
        )

        candidates = clean_db.get_image_review_candidates_for_filing(filing_id)

        assert len(candidates) == 1
        c = candidates[0]
        assert c["decision"] == "relevant"
        assert c["chart_type"] == "cohort_heatmap"
        assert c["decision_notes"] == "Good chart"

    def test_invalid_sort_by_raises_error(self, clean_db):
        """Test that invalid sort_by raises ValidationError."""
        company_id, filing_id = create_test_company_and_filing(clean_db)

        with pytest.raises(ValidationError, match="sort_by"):
            clean_db.get_image_review_candidates_for_filing(filing_id, sort_by="invalid")


class TestGetNextPendingImageCandidate:
    """Tests for get_next_pending_image_candidate method."""

    def test_returns_first_pending_when_no_current(self, clean_db):
        """Test getting first pending candidate."""
        company_id, filing_id = create_test_company_and_filing(clean_db)

        for i in range(3):
            clean_db.insert_image_review_candidate(
                filing_id=filing_id,
                company_id=company_id,
                image_src=f"chart{i}.jpg",
                image_url=f"https://sec.gov/chart{i}.jpg",
                image_index=i + 1,
            )

        next_candidate = clean_db.get_next_pending_image_candidate(filing_id)

        assert next_candidate is not None
        assert next_candidate["image_index"] == 1

    def test_returns_none_when_all_reviewed(self, clean_db):
        """Test returns None when no pending candidates."""
        company_id, filing_id, candidate_id = create_test_image_candidate(clean_db)

        # Review the candidate
        clean_db.insert_image_review_decision(
            image_candidate_id=candidate_id,
            decision="relevant",
            chart_type="bar_chart",
        )

        next_candidate = clean_db.get_next_pending_image_candidate(filing_id)
        assert next_candidate is None

    def test_skips_reviewed_candidates(self, clean_db):
        """Test that reviewed candidates are skipped."""
        company_id, filing_id = create_test_company_and_filing(clean_db)

        # Create 3 candidates
        candidate_ids = []
        for i in range(3):
            cid = clean_db.insert_image_review_candidate(
                filing_id=filing_id,
                company_id=company_id,
                image_src=f"chart{i}.jpg",
                image_url=f"https://sec.gov/chart{i}.jpg",
                image_index=i + 1,
            )
            candidate_ids.append(cid)

        # Review first two
        for cid in candidate_ids[:2]:
            clean_db.insert_image_review_decision(
                image_candidate_id=cid,
                decision="not_relevant",
                rejection_reason="decorative",
            )

        next_candidate = clean_db.get_next_pending_image_candidate(filing_id)

        assert next_candidate is not None
        assert next_candidate["image_candidate_id"] == candidate_ids[2]

    def test_returns_next_after_current_candidate(self, clean_db):
        """Test that passing current_candidate_id returns the NEXT pending candidate.

        This is the key navigation test - when reviewing candidate N, calling
        get_next_pending_image_candidate(filing_id, N) should return candidate N+1.
        """
        company_id, filing_id = create_test_company_and_filing(clean_db)

        # Create 5 pending candidates
        candidate_ids = []
        for i in range(5):
            cid = clean_db.insert_image_review_candidate(
                filing_id=filing_id,
                company_id=company_id,
                image_src=f"chart{i}.jpg",
                image_url=f"https://sec.gov/chart{i}.jpg",
                image_index=i + 1,
            )
            candidate_ids.append(cid)

        # Get next after first candidate - should return second
        next_after_first = clean_db.get_next_pending_image_candidate(
            filing_id, current_candidate_id=candidate_ids[0]
        )
        assert next_after_first is not None
        assert next_after_first["image_candidate_id"] == candidate_ids[1]

        # Get next after second candidate - should return third
        next_after_second = clean_db.get_next_pending_image_candidate(
            filing_id, current_candidate_id=candidate_ids[1]
        )
        assert next_after_second is not None
        assert next_after_second["image_candidate_id"] == candidate_ids[2]

        # Get next after last candidate - should return None
        next_after_last = clean_db.get_next_pending_image_candidate(
            filing_id, current_candidate_id=candidate_ids[4]
        )
        assert next_after_last is None

    def test_next_candidate_skips_reviewed_in_middle(self, clean_db):
        """Test navigation skips reviewed candidates in the middle of the list.

        Scenario: 5 candidates, #2 and #3 are reviewed. After #1, should get #4.
        """
        company_id, filing_id = create_test_company_and_filing(clean_db)

        # Create 5 candidates
        candidate_ids = []
        for i in range(5):
            cid = clean_db.insert_image_review_candidate(
                filing_id=filing_id,
                company_id=company_id,
                image_src=f"chart{i}.jpg",
                image_url=f"https://sec.gov/chart{i}.jpg",
                image_index=i + 1,
            )
            candidate_ids.append(cid)

        # Review candidates 1 and 2 (indices 1, 2 - the middle ones)
        clean_db.insert_image_review_decision(
            image_candidate_id=candidate_ids[1],
            decision="relevant",
            chart_type="line_chart",
        )
        clean_db.insert_image_review_decision(
            image_candidate_id=candidate_ids[2],
            decision="not_relevant",
            rejection_reason="decorative",
        )

        # Get next after first pending (candidate_ids[0]) - should skip reviewed ones
        next_candidate = clean_db.get_next_pending_image_candidate(
            filing_id, current_candidate_id=candidate_ids[0]
        )

        assert next_candidate is not None
        # Should return candidate_ids[3] since [1] and [2] are reviewed
        assert next_candidate["image_candidate_id"] == candidate_ids[3]


# =============================================================================
# Decision CRUD Tests
# =============================================================================


class TestInsertImageReviewCandidate:
    """Tests for insert_image_review_candidate method."""

    def test_creates_record_with_all_fields(self, clean_db):
        """Test creating a candidate with all fields."""
        company_id, filing_id = create_test_company_and_filing(clean_db)

        candidate_id = clean_db.insert_image_review_candidate(
            filing_id=filing_id,
            company_id=company_id,
            image_src="detailed_chart.png",
            image_url="https://sec.gov/detailed_chart.png",
            image_width=800,
            image_height=600,
            image_alt="Revenue cohort analysis",
            preceding_text="As shown in the chart below...",
            detected_keywords=["cohort", "revenue", "retention"],
            cohort_keyword_nearby=True,
            image_index=5,
            cohort_confidence=0.92,
            is_decorative=False,
            detection_tier="tier_1_cohort",
        )

        assert candidate_id > 0

        # Verify retrieval
        candidate = clean_db.get_image_review_candidate(candidate_id)
        assert candidate is not None
        assert candidate["image_src"] == "detailed_chart.png"
        assert candidate["image_width"] == 800
        assert candidate["image_height"] == 600
        assert candidate["image_alt"] == "Revenue cohort analysis"
        assert float(candidate["cohort_confidence"]) == 0.92
        assert candidate["detection_tier"] == "tier_1_cohort"
        assert candidate["review_status"] == "pending"

    def test_upsert_returns_existing_on_duplicate(self, clean_db):
        """Test that duplicate insert returns existing candidate_id."""
        company_id, filing_id = create_test_company_and_filing(clean_db)

        # First insert
        first_id = clean_db.insert_image_review_candidate(
            filing_id=filing_id,
            company_id=company_id,
            image_src="chart.jpg",
            image_url="https://sec.gov/chart.jpg",
        )

        # Second insert with same filing_id + image_src
        second_id = clean_db.insert_image_review_candidate(
            filing_id=filing_id,
            company_id=company_id,
            image_src="chart.jpg",
            image_url="https://sec.gov/chart_different.jpg",  # Different URL
        )

        assert first_id == second_id

    def test_validates_cohort_confidence_range(self, clean_db):
        """Test that cohort_confidence outside 0-1 raises error."""
        company_id, filing_id = create_test_company_and_filing(clean_db)

        with pytest.raises(ValidationError, match="cohort_confidence"):
            clean_db.insert_image_review_candidate(
                filing_id=filing_id,
                company_id=company_id,
                image_src="chart.jpg",
                image_url="https://sec.gov/chart.jpg",
                cohort_confidence=1.5,  # Invalid
            )

    def test_validates_detection_tier(self, clean_db):
        """Test that invalid detection_tier raises error."""
        company_id, filing_id = create_test_company_and_filing(clean_db)

        with pytest.raises(ValidationError, match="detection_tier"):
            clean_db.insert_image_review_candidate(
                filing_id=filing_id,
                company_id=company_id,
                image_src="chart.jpg",
                image_url="https://sec.gov/chart.jpg",
                detection_tier="invalid_tier",
            )


class TestInsertImageReviewDecision:
    """Tests for insert_image_review_decision method."""

    def test_creates_decision_and_updates_status(self, clean_db):
        """Test creating a decision updates candidate status."""
        company_id, filing_id, candidate_id = create_test_image_candidate(clean_db)

        # Verify candidate is pending
        candidate = clean_db.get_image_review_candidate(candidate_id)
        assert candidate["review_status"] == "pending"

        # Make decision
        decision_id = clean_db.insert_image_review_decision(
            image_candidate_id=candidate_id,
            decision="relevant",
            chart_type="cohort_table",
            reviewer_id="test_user",
            review_time_seconds=45,
        )

        assert decision_id > 0

        # Verify status updated
        candidate = clean_db.get_image_review_candidate(candidate_id)
        assert candidate["review_status"] == "reviewed"
        assert candidate["decision"] == "relevant"
        assert candidate["chart_type"] == "cohort_table"

    def test_relevant_requires_chart_type(self, clean_db):
        """Test that 'relevant' decision requires chart_type."""
        company_id, filing_id, candidate_id = create_test_image_candidate(clean_db)

        with pytest.raises(ValidationError, match="chart_type"):
            clean_db.insert_image_review_decision(
                image_candidate_id=candidate_id,
                decision="relevant",
                chart_type=None,  # Missing
            )

    def test_not_relevant_requires_rejection_reason(self, clean_db):
        """Test that 'not_relevant' decision requires rejection_reason."""
        company_id, filing_id, candidate_id = create_test_image_candidate(clean_db)

        with pytest.raises(ValidationError, match="rejection_reason"):
            clean_db.insert_image_review_decision(
                image_candidate_id=candidate_id,
                decision="not_relevant",
                rejection_reason=None,  # Missing
            )

    def test_validates_decision_type(self, clean_db):
        """Test that invalid decision raises error."""
        company_id, filing_id, candidate_id = create_test_image_candidate(clean_db)

        with pytest.raises(ValidationError, match="decision"):
            clean_db.insert_image_review_decision(
                image_candidate_id=candidate_id,
                decision="invalid_decision",
            )

    def test_validates_chart_type(self, clean_db):
        """Test that invalid chart_type raises error."""
        company_id, filing_id, candidate_id = create_test_image_candidate(clean_db)

        with pytest.raises(ValidationError, match="chart_type"):
            clean_db.insert_image_review_decision(
                image_candidate_id=candidate_id,
                decision="relevant",
                chart_type="invalid_chart_type",
            )

    def test_validates_rejection_reason(self, clean_db):
        """Test that invalid rejection_reason raises error."""
        company_id, filing_id, candidate_id = create_test_image_candidate(clean_db)

        with pytest.raises(ValidationError, match="rejection_reason"):
            clean_db.insert_image_review_decision(
                image_candidate_id=candidate_id,
                decision="not_relevant",
                rejection_reason="invalid_reason",
            )


class TestDeleteImageReviewDecision:
    """Tests for delete_image_review_decision method."""

    def test_deletes_and_resets_status(self, clean_db):
        """Test deleting decision resets candidate to pending."""
        company_id, filing_id, candidate_id, decision_id = create_test_image_decision(
            clean_db
        )

        # Verify reviewed status
        candidate = clean_db.get_image_review_candidate(candidate_id)
        assert candidate["review_status"] == "reviewed"

        # Delete decision
        result = clean_db.delete_image_review_decision(decision_id)
        assert result is True

        # Verify status reset
        candidate = clean_db.get_image_review_candidate(candidate_id)
        assert candidate["review_status"] == "pending"
        assert candidate["decision"] is None

    def test_returns_false_for_nonexistent(self, clean_db):
        """Test returns False when decision doesn't exist."""
        result = clean_db.delete_image_review_decision(999999)
        assert result is False


class TestGetImageDecisionById:
    """Tests for get_image_decision_by_id method."""

    def test_returns_decision_with_filing_id(self, clean_db):
        """Test that method returns decision details including filing_id."""
        company_id, filing_id, candidate_id, decision_id = create_test_image_decision(
            clean_db
        )

        result = clean_db.get_image_decision_by_id(decision_id)

        assert result is not None
        assert result["image_decision_id"] == decision_id
        assert result["image_candidate_id"] == candidate_id
        assert result["filing_id"] == filing_id
        assert result["decision"] == "relevant"
        assert result["chart_type"] == "cohort_table"
        assert "created_at" in result

    def test_returns_none_for_nonexistent(self, clean_db):
        """Test returns None when decision doesn't exist."""
        result = clean_db.get_image_decision_by_id(999999)
        assert result is None


class TestUpdateImageCandidateStatus:
    """Tests for update_image_candidate_status method."""

    def test_updates_to_skipped(self, clean_db):
        """Test updating status to skipped."""
        company_id, filing_id, candidate_id = create_test_image_candidate(clean_db)

        result = clean_db.update_image_candidate_status(candidate_id, "skipped")
        assert result is True

        candidate = clean_db.get_image_review_candidate(candidate_id)
        assert candidate["review_status"] == "skipped"

    def test_validates_status(self, clean_db):
        """Test that invalid status raises error."""
        company_id, filing_id, candidate_id = create_test_image_candidate(clean_db)

        with pytest.raises(ValidationError, match="review_status"):
            clean_db.update_image_candidate_status(candidate_id, "invalid_status")

    def test_returns_false_for_nonexistent(self, clean_db):
        """Test returns False when candidate doesn't exist."""
        result = clean_db.update_image_candidate_status(999999, "skipped")
        assert result is False


# =============================================================================
# Statistics Tests
# =============================================================================


class TestGetImageReviewProgress:
    """Tests for get_image_review_progress method."""

    def test_returns_correct_totals(self, clean_db):
        """Test progress stats with mixed statuses."""
        company_id, filing_id = create_test_company_and_filing(clean_db)

        # Create 5 candidates
        candidate_ids = []
        for i in range(5):
            cid = clean_db.insert_image_review_candidate(
                filing_id=filing_id,
                company_id=company_id,
                image_src=f"chart{i}.jpg",
                image_url=f"https://sec.gov/chart{i}.jpg",
                detection_tier="tier_1_cohort",
            )
            candidate_ids.append(cid)

        # Review 2, skip 1
        clean_db.insert_image_review_decision(
            image_candidate_id=candidate_ids[0],
            decision="relevant",
            chart_type="cohort_table",
        )
        clean_db.insert_image_review_decision(
            image_candidate_id=candidate_ids[1],
            decision="not_relevant",
            rejection_reason="decorative",
        )
        clean_db.update_image_candidate_status(candidate_ids[2], "skipped")

        progress = clean_db.get_image_review_progress()

        assert progress["total_candidates"] == 5
        assert progress["reviewed_count"] == 2
        assert progress["pending_count"] == 2
        assert progress["skipped_count"] == 1
        assert progress["review_pct"] == 40.0
        assert progress["total_filings"] == 1

    def test_includes_tier_breakdown(self, clean_db):
        """Test that progress includes by-tier breakdown."""
        company_id, filing_id = create_test_company_and_filing(clean_db)

        # Create candidates in different tiers
        clean_db.insert_image_review_candidate(
            filing_id=filing_id,
            company_id=company_id,
            image_src="chart1.jpg",
            image_url="https://sec.gov/chart1.jpg",
            detection_tier="tier_1_cohort",
        )
        clean_db.insert_image_review_candidate(
            filing_id=filing_id,
            company_id=company_id,
            image_src="chart2.jpg",
            image_url="https://sec.gov/chart2.jpg",
            detection_tier="tier_2_large",
        )

        progress = clean_db.get_image_review_progress()

        assert "by_tier" in progress
        assert "tier_1_cohort" in progress["by_tier"]
        assert "tier_2_large" in progress["by_tier"]
        assert progress["by_tier"]["tier_1_cohort"]["total"] == 1
        assert progress["by_tier"]["tier_2_large"]["total"] == 1

    def test_handles_empty_table(self, clean_db):
        """Test progress with no candidates."""
        progress = clean_db.get_image_review_progress()

        assert progress["total_candidates"] == 0
        assert progress["pending_count"] == 0
        assert progress["review_pct"] == 0.0
        assert progress["by_tier"] == {}


class TestGetImageDecisionStatistics:
    """Tests for get_image_decision_statistics method."""

    def test_groups_by_tier(self, clean_db):
        """Test statistics grouped by detection tier."""
        company_id, filing_id = create_test_company_and_filing(clean_db)

        # Create candidates in tier_1 and tier_2
        tier1_id = clean_db.insert_image_review_candidate(
            filing_id=filing_id,
            company_id=company_id,
            image_src="t1.jpg",
            image_url="https://sec.gov/t1.jpg",
            detection_tier="tier_1_cohort",
        )
        tier2_id = clean_db.insert_image_review_candidate(
            filing_id=filing_id,
            company_id=company_id,
            image_src="t2.jpg",
            image_url="https://sec.gov/t2.jpg",
            detection_tier="tier_2_large",
        )

        # Make decisions
        clean_db.insert_image_review_decision(
            image_candidate_id=tier1_id,
            decision="relevant",
            chart_type="cohort_table",
        )
        clean_db.insert_image_review_decision(
            image_candidate_id=tier2_id,
            decision="not_relevant",
            rejection_reason="not_a_chart",
        )

        stats = clean_db.get_image_decision_statistics()

        assert len(stats) == 2

        tier1_stats = next(s for s in stats if s["detection_tier"] == "tier_1_cohort")
        assert tier1_stats["relevant_count"] == 1
        assert tier1_stats["not_relevant_count"] == 0
        assert float(tier1_stats["precision_pct"]) == 100.0

        tier2_stats = next(s for s in stats if s["detection_tier"] == "tier_2_large")
        assert tier2_stats["relevant_count"] == 0
        assert tier2_stats["not_relevant_count"] == 1
        assert float(tier2_stats["precision_pct"]) == 0.0

    def test_handles_no_decisions(self, clean_db):
        """Test statistics with no decisions."""
        stats = clean_db.get_image_decision_statistics()
        assert stats == []


# =============================================================================
# Edge Case Tests
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_filing_with_no_candidates(self, clean_db):
        """Test that filings without candidates don't appear."""
        company_id, filing_id = create_test_company_and_filing(clean_db)

        # No candidates created
        filings = clean_db.get_filings_with_image_candidates()
        assert len(filings) == 0

    def test_candidate_with_null_detection_tier(self, clean_db):
        """Test handling candidates with NULL detection_tier."""
        company_id, filing_id = create_test_company_and_filing(clean_db)

        candidate_id = clean_db.insert_image_review_candidate(
            filing_id=filing_id,
            company_id=company_id,
            image_src="chart.jpg",
            image_url="https://sec.gov/chart.jpg",
            detection_tier=None,  # NULL
        )

        # Should still be retrievable
        candidate = clean_db.get_image_review_candidate(candidate_id)
        assert candidate is not None
        assert candidate["detection_tier"] is None

        # Should appear in progress stats under 'unknown'
        progress = clean_db.get_image_review_progress()
        assert progress["total_candidates"] == 1

    def test_pagination_offset_and_limit(self, clean_db):
        """Test pagination with offset and limit."""
        company_id, filing_id = create_test_company_and_filing(clean_db)

        # Create 10 candidates
        for i in range(10):
            clean_db.insert_image_review_candidate(
                filing_id=filing_id,
                company_id=company_id,
                image_src=f"chart{i}.jpg",
                image_url=f"https://sec.gov/chart{i}.jpg",
                image_index=i + 1,
            )

        # Get page 2 (offset 3, limit 3)
        candidates = clean_db.get_image_review_candidates_for_filing(
            filing_id, sort_by="position", limit=3, offset=3
        )

        assert len(candidates) == 3
        assert candidates[0]["image_index"] == 4
        assert candidates[1]["image_index"] == 5
        assert candidates[2]["image_index"] == 6
