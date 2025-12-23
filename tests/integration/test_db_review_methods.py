"""
Integration tests for DatabaseAdapter review table methods.

Tests CRUD operations on:
- review_candidates
- review_decisions
- learned_patterns

Requires:
- TEST_DATABASE_URL environment variable set
- Review schema applied (sql/07_create_review_schema.sql)
"""

from decimal import Decimal

import pytest

from src.infra.validation import ValidationError
from tests.integration.conftest import (
    create_test_candidate,
    create_test_company_and_filing,
)


class TestReviewCandidatesMethods:
    """Tests for review_candidates table operations."""

    def test_insert_review_candidate_minimal(self, clean_db):
        """Test inserting a candidate with minimal required fields."""
        company_id, filing_id = create_test_company_and_filing(clean_db)

        candidate_id = clean_db.insert_review_candidate(
            filing_id=filing_id,
            company_id=company_id,
            char_position=100,
            context_text="We have approximately 10,000 active customers as of December 31, 2023.",
            raw_number_text="10,000",
            triggering_keyword="customers",
            keyword_distance=25,
            keyword_position="after",
        )

        assert candidate_id > 0

        # Verify retrieval
        candidate = clean_db.get_review_candidate(candidate_id)
        assert candidate is not None
        assert candidate["filing_id"] == filing_id
        assert candidate["company_id"] == company_id
        assert candidate["char_position"] == 100
        assert candidate["raw_number_text"] == "10,000"
        assert candidate["triggering_keyword"] == "customers"
        assert candidate["keyword_position"] == "after"
        assert candidate["review_status"] == "pending"

    def test_insert_review_candidate_full(self, clean_db):
        """Test inserting a candidate with all optional fields."""
        company_id, filing_id = create_test_company_and_filing(clean_db)

        features = {
            "keyword_distance": 25,
            "keyword_position": "after",
            "is_in_table": False,
            "is_in_risk_factors": False,
            "contains_definition_language": True,
            "has_period_mention": True,
            "number_format": "integer",
            "value_magnitude": 4.0,
        }

        candidate_id = clean_db.insert_review_candidate(
            filing_id=filing_id,
            company_id=company_id,
            char_position=100,
            context_text="We define active customers as those with at least one transaction. We have 10,000 active customers.",
            raw_number_text="10,000",
            triggering_keyword="active customers",
            keyword_distance=15,
            keyword_position="after",
            parsed_value=Decimal("10000"),
            parsed_unit="count",
            suggested_metric_id="cm_new_customers_acquired",
            suggestion_confidence=0.85,
            features=features,
            review_batch_id=1,
        )

        assert candidate_id > 0

        candidate = clean_db.get_review_candidate(candidate_id)
        assert candidate["parsed_value"] == Decimal("10000")
        assert candidate["parsed_unit"] == "count"
        assert candidate["suggested_metric_id"] == "cm_new_customers_acquired"
        assert float(candidate["suggestion_confidence"]) == 0.85
        assert candidate["features"]["is_in_table"] is False
        assert candidate["features"]["value_magnitude"] == 4.0
        assert candidate["review_batch_id"] == 1

    def test_get_review_candidates_for_filing(self, clean_db):
        """Test retrieving candidates for a specific filing."""
        company_id, filing_id = create_test_company_and_filing(clean_db)

        # Insert multiple candidates
        for i in range(5):
            clean_db.insert_review_candidate(
                filing_id=filing_id,
                company_id=company_id,
                char_position=i * 100,
                context_text=f"Context for candidate {i}",
                raw_number_text=str(i * 1000),
                triggering_keyword="customers",
                keyword_distance=10,
                keyword_position="before",
            )

        candidates = clean_db.get_review_candidates_for_filing(filing_id)
        assert len(candidates) == 5

        # Test with limit
        candidates_limited = clean_db.get_review_candidates_for_filing(
            filing_id, limit=3
        )
        assert len(candidates_limited) == 3

        # Verify ordering by char_position
        positions = [c["char_position"] for c in candidates]
        assert positions == sorted(positions)

    def test_get_review_candidates_for_filing_by_status(self, clean_db):
        """Test filtering candidates by status."""
        company_id, filing_id = create_test_company_and_filing(clean_db)

        # Insert 3 pending candidates
        candidate_ids = []
        for i in range(3):
            cid = clean_db.insert_review_candidate(
                filing_id=filing_id,
                company_id=company_id,
                char_position=i * 100,
                context_text=f"Context {i}",
                raw_number_text=str(i),
                triggering_keyword="test",
                keyword_distance=5,
                keyword_position="after",
            )
            candidate_ids.append(cid)

        # Update one to reviewed
        clean_db.update_candidate_status(candidate_ids[0], "reviewed")

        pending = clean_db.get_review_candidates_for_filing(filing_id, status="pending")
        assert len(pending) == 2

        reviewed = clean_db.get_review_candidates_for_filing(
            filing_id, status="reviewed"
        )
        assert len(reviewed) == 1

    def test_get_pending_candidates(self, clean_db):
        """Test getting all pending candidates."""
        company_id, filing_id = create_test_company_and_filing(clean_db)

        # Insert candidates
        for i in range(3):
            clean_db.insert_review_candidate(
                filing_id=filing_id,
                company_id=company_id,
                char_position=i * 100,
                context_text=f"Context {i}",
                raw_number_text=str(i),
                triggering_keyword="test",
                keyword_distance=5,
                keyword_position="after",
            )

        pending = clean_db.get_pending_candidates()
        assert len(pending) == 3

        # Verify join data is included
        assert pending[0]["accession_number"] == "0001234567-24-000001"
        assert pending[0]["company_name"] == "Test Corp"

    def test_update_candidate_status(self, clean_db):
        """Test updating a candidate's review status."""
        company_id, filing_id = create_test_company_and_filing(clean_db)

        candidate_id = clean_db.insert_review_candidate(
            filing_id=filing_id,
            company_id=company_id,
            char_position=0,
            context_text="Test context",
            raw_number_text="100",
            triggering_keyword="test",
            keyword_distance=5,
            keyword_position="before",
        )

        # Initially pending
        candidate = clean_db.get_review_candidate(candidate_id)
        assert candidate["review_status"] == "pending"

        # Update to in_progress
        result = clean_db.update_candidate_status(candidate_id, "in_progress")
        assert result is True

        candidate = clean_db.get_review_candidate(candidate_id)
        assert candidate["review_status"] == "in_progress"

        # Update to reviewed
        clean_db.update_candidate_status(candidate_id, "reviewed")
        candidate = clean_db.get_review_candidate(candidate_id)
        assert candidate["review_status"] == "reviewed"

    def test_update_candidate_status_nonexistent_returns_false(self, clean_db):
        """Updating a non-existent candidate should return False."""
        # Use an ID that doesn't exist
        result = clean_db.update_candidate_status(999999, "reviewed")
        assert result is False

    def test_bulk_insert_review_candidates(self, clean_db):
        """Test bulk inserting multiple candidates."""
        company_id, filing_id = create_test_company_and_filing(clean_db)

        candidates = [
            {
                "filing_id": filing_id,
                "company_id": company_id,
                "char_position": i * 100,
                "context_text": f"Bulk context {i}",
                "raw_number_text": str(i * 1000),
                "triggering_keyword": "customers",
                "keyword_distance": 10,
                "keyword_position": "after",
                "suggested_metric_id": ["cm_new_customers_acquired", "cm_customers_period_end_by_tenure", "cm_revenue_by_cohort", "cm_transactions_by_cohort", "cm_active_customers_total", "cm_revenue_per_customer", "cm_customer_acquisition_cost", "cm_new_customers_acquired", "cm_customers_period_end_by_tenure", "cm_revenue_by_cohort"][i],
            }
            for i in range(10)
        ]

        inserted_ids = clean_db.bulk_insert_review_candidates(candidates)
        assert len(inserted_ids) == 10
        assert all(cid > 0 for cid in inserted_ids)

        # Verify all were inserted
        all_candidates = clean_db.get_review_candidates_for_filing(filing_id)
        assert len(all_candidates) == 10

    def test_bulk_insert_empty_list(self, clean_db):
        """Test bulk insert with empty list returns empty list."""
        inserted_ids = clean_db.bulk_insert_review_candidates([])
        assert inserted_ids == []

    def test_bulk_update_candidate_status(self, clean_db):
        """Test bulk updating status for multiple candidates."""
        company_id, filing_id = create_test_company_and_filing(clean_db)

        # Insert multiple candidates
        candidate_ids = []
        for i in range(5):
            cid = clean_db.insert_review_candidate(
                filing_id=filing_id,
                company_id=company_id,
                char_position=i * 100,
                context_text=f"Context {i}",
                raw_number_text=str(i),
                triggering_keyword="test",
                keyword_distance=5,
                keyword_position="after",
            )
            candidate_ids.append(cid)

        # All should start as pending
        for cid in candidate_ids:
            candidate = clean_db.get_review_candidate(cid)
            assert candidate["review_status"] == "pending"

        # Bulk update first 3 to skipped
        rows_updated = clean_db.bulk_update_candidate_status(
            candidate_ids[:3], "skipped"
        )
        assert rows_updated == 3

        # Verify statuses
        for cid in candidate_ids[:3]:
            candidate = clean_db.get_review_candidate(cid)
            assert candidate["review_status"] == "skipped"

        for cid in candidate_ids[3:]:
            candidate = clean_db.get_review_candidate(cid)
            assert candidate["review_status"] == "pending"

    def test_bulk_update_candidate_status_empty_list(self, clean_db):
        """Test bulk update with empty list returns 0."""
        rows_updated = clean_db.bulk_update_candidate_status([], "reviewed")
        assert rows_updated == 0

    def test_bulk_update_candidate_status_nonexistent_ids(self, clean_db):
        """Test bulk update with non-existent IDs returns 0 updated."""
        # Use IDs that don't exist
        rows_updated = clean_db.bulk_update_candidate_status(
            [999998, 999999], "reviewed"
        )
        assert rows_updated == 0

    def test_bulk_update_candidate_status_partial_match(self, clean_db):
        """Test bulk update when some IDs exist and some don't."""
        company_id, filing_id = create_test_company_and_filing(clean_db)

        # Insert one candidate
        cid = clean_db.insert_review_candidate(
            filing_id=filing_id,
            company_id=company_id,
            char_position=100,
            context_text="Test",
            raw_number_text="100",
            triggering_keyword="test",
            keyword_distance=5,
            keyword_position="after",
        )

        # Update with one valid ID and one invalid
        rows_updated = clean_db.bulk_update_candidate_status(
            [cid, 999999], "in_progress"
        )
        assert rows_updated == 1

        # Verify the valid one was updated
        candidate = clean_db.get_review_candidate(cid)
        assert candidate["review_status"] == "in_progress"


class TestReviewDecisionsMethods:
    """Tests for review_decisions table operations."""

    def test_insert_review_decision_accept(self, clean_db):
        """Test recording an accept decision."""
        company_id, filing_id, candidate_id = create_test_candidate(
            clean_db, suggested_metric_id="cm_new_customers_acquired"
        )

        decision_id = clean_db.insert_review_decision(
            candidate_id=candidate_id,
            decision="accept",
            assigned_metric_id="cm_new_customers_acquired",
            reviewer_notes="Clear customer count",
            review_time_seconds=15,
        )

        assert decision_id > 0

        # Verify decision was stored
        decision = clean_db.get_decision_for_candidate(candidate_id)
        assert decision is not None
        assert decision["decision"] == "accept"
        assert decision["assigned_metric_id"] == "cm_new_customers_acquired"
        assert decision["reviewer_notes"] == "Clear customer count"
        assert decision["review_time_seconds"] == 15

        # Verify candidate status was updated
        candidate = clean_db.get_review_candidate(candidate_id)
        assert candidate["review_status"] == "reviewed"

    def test_insert_review_decision_reject(self, clean_db):
        """Test recording a reject decision."""
        company_id, filing_id, candidate_id = create_test_candidate(clean_db)

        decision_id = clean_db.insert_review_decision(
            candidate_id=candidate_id,
            decision="reject",
            rejection_reason="This is revenue, not customers",
            rejection_category="wrong_metric",
            review_time_seconds=8,
        )

        assert decision_id > 0

        decision = clean_db.get_decision_for_candidate(candidate_id)
        assert decision["decision"] == "reject"
        assert decision["rejection_reason"] == "This is revenue, not customers"
        assert decision["rejection_category"] == "wrong_metric"

    def test_insert_review_decision_reclassify(self, clean_db):
        """Test recording a reclassify decision."""
        company_id, filing_id, candidate_id = create_test_candidate(clean_db)

        decision_id = clean_db.insert_review_decision(
            candidate_id=candidate_id,
            decision="reclassify",
            assigned_metric_id="cm_active_customers_total",  # Different from suggested
            reviewer_notes="Actually total, not active",
            review_time_seconds=20,
        )

        assert decision_id > 0

        decision = clean_db.get_decision_for_candidate(candidate_id)
        assert decision["decision"] == "reclassify"
        assert decision["assigned_metric_id"] == "cm_active_customers_total"

    def test_get_decisions_for_filing(self, clean_db):
        """Test getting all decisions for a filing."""
        company_id, filing_id, candidate_id = create_test_candidate(clean_db)

        # Create more candidates for this filing
        candidate_id2 = clean_db.insert_review_candidate(
            filing_id=filing_id,
            company_id=company_id,
            char_position=200,
            context_text="CAC is $150",
            raw_number_text="$150",
            triggering_keyword="CAC",
            keyword_distance=5,
            keyword_position="before",
        )

        # Record decisions
        clean_db.insert_review_decision(
            candidate_id=candidate_id,
            decision="accept",
            assigned_metric_id="cm_new_customers_acquired",
        )
        clean_db.insert_review_decision(
            candidate_id=candidate_id2,
            decision="reject",
            rejection_category="not_a_metric",
        )

        decisions = clean_db.get_decisions_for_filing(filing_id)
        assert len(decisions) == 2

        # Verify join data
        assert any(d["context_text"] == "We have 10,000 customers." for d in decisions)
        assert any(d["context_text"] == "CAC is $150" for d in decisions)

    def test_get_decision_statistics(self, clean_db):
        """Test getting decision statistics."""
        company_id, filing_id, _ = create_test_candidate(clean_db)

        # Create multiple candidates and decisions
        for i in range(6):
            cid = clean_db.insert_review_candidate(
                filing_id=filing_id,
                company_id=company_id,
                char_position=i * 100,
                context_text=f"Context {i}",
                raw_number_text=str(i),
                triggering_keyword="test",
                keyword_distance=5,
                keyword_position="after",
            )
            if i < 3:  # 3 accepts
                clean_db.insert_review_decision(
                    candidate_id=cid, decision="accept", assigned_metric_id="cm_revenue_per_customer"
                )
            elif i < 5:  # 2 rejects
                clean_db.insert_review_decision(
                    candidate_id=cid, decision="reject", rejection_category="other"
                )
            else:  # 1 reclassify
                clean_db.insert_review_decision(
                    candidate_id=cid, decision="reclassify", assigned_metric_id="cm_active_customers_total"
                )

        stats = clean_db.get_decision_statistics()
        assert stats["total_decisions"] == 6
        assert stats["accept_count"] == 3
        assert stats["reject_count"] == 2
        assert stats["reclassify_count"] == 1
        assert stats["accept_pct"] == 50.0

        # Test filtering by filing
        stats_filing = clean_db.get_decision_statistics(filing_id=filing_id)
        assert stats_filing["total_decisions"] == 6

    def test_get_decisions_by_reviewer(self, clean_db):
        """Test getting decisions filtered by reviewer_id."""
        company_id, filing_id, candidate_id = create_test_candidate(clean_db)

        # Create more candidates
        candidate_id2 = clean_db.insert_review_candidate(
            filing_id=filing_id,
            company_id=company_id,
            char_position=200,
            context_text="Second candidate",
            raw_number_text="200",
            triggering_keyword="test",
            keyword_distance=5,
            keyword_position="before",
        )
        candidate_id3 = clean_db.insert_review_candidate(
            filing_id=filing_id,
            company_id=company_id,
            char_position=300,
            context_text="Third candidate",
            raw_number_text="300",
            triggering_keyword="test",
            keyword_distance=5,
            keyword_position="after",
        )

        # Record decisions by different reviewers
        clean_db.insert_review_decision(
            candidate_id=candidate_id,
            decision="accept",
            assigned_metric_id="cm_new_customers_acquired",
            reviewer_id="alice@example.com",
        )
        clean_db.insert_review_decision(
            candidate_id=candidate_id2,
            decision="reject",
            rejection_category="not_a_metric",
            reviewer_id="alice@example.com",
        )
        clean_db.insert_review_decision(
            candidate_id=candidate_id3,
            decision="accept",
            assigned_metric_id="cm_active_customers_total",
            reviewer_id="bob@example.com",
        )

        # Get decisions by Alice
        alice_decisions = clean_db.get_decisions_by_reviewer("alice@example.com")
        assert len(alice_decisions) == 2
        assert all(d["reviewer_id"] == "alice@example.com" for d in alice_decisions)

        # Get decisions by Bob
        bob_decisions = clean_db.get_decisions_by_reviewer("bob@example.com")
        assert len(bob_decisions) == 1
        assert bob_decisions[0]["reviewer_id"] == "bob@example.com"

        # Verify join data is included
        assert alice_decisions[0]["company_name"] == "Test Corp"
        assert "accession_number" in alice_decisions[0]
        assert "context_text" in alice_decisions[0]

    def test_get_decisions_by_reviewer_filter_by_decision(self, clean_db):
        """Test filtering by decision type."""
        company_id, filing_id, candidate_id = create_test_candidate(clean_db)

        # Create more candidates
        candidate_id2 = clean_db.insert_review_candidate(
            filing_id=filing_id,
            company_id=company_id,
            char_position=200,
            context_text="Second",
            raw_number_text="200",
            triggering_keyword="test",
            keyword_distance=5,
            keyword_position="before",
        )

        # Same reviewer, different decisions
        clean_db.insert_review_decision(
            candidate_id=candidate_id,
            decision="accept",
            assigned_metric_id="cm_revenue_by_cohort",
            reviewer_id="reviewer@test.com",
        )
        clean_db.insert_review_decision(
            candidate_id=candidate_id2,
            decision="reject",
            rejection_category="other",
            reviewer_id="reviewer@test.com",
        )

        # Filter by accept
        accepts = clean_db.get_decisions_by_reviewer(
            "reviewer@test.com", decision="accept"
        )
        assert len(accepts) == 1
        assert accepts[0]["decision"] == "accept"

        # Filter by reject
        rejects = clean_db.get_decisions_by_reviewer(
            "reviewer@test.com", decision="reject"
        )
        assert len(rejects) == 1
        assert rejects[0]["decision"] == "reject"

    def test_get_decisions_by_reviewer_pagination(self, clean_db):
        """Test pagination with limit and offset."""
        company_id, filing_id, _ = create_test_candidate(clean_db)

        # Create multiple candidates and decisions by same reviewer
        for i in range(5):
            cid = clean_db.insert_review_candidate(
                filing_id=filing_id,
                company_id=company_id,
                char_position=i * 100,
                context_text=f"Context {i}",
                raw_number_text=str(i),
                triggering_keyword="test",
                keyword_distance=5,
                keyword_position="after",
            )
            clean_db.insert_review_decision(
                candidate_id=cid,
                decision="accept",
                assigned_metric_id=["cm_new_customers_acquired", "cm_customers_period_end_by_tenure", "cm_revenue_by_cohort", "cm_transactions_by_cohort", "cm_active_customers_total"][i],
                reviewer_id="paginated@test.com",
            )

        # Get all
        all_decisions = clean_db.get_decisions_by_reviewer("paginated@test.com")
        assert len(all_decisions) == 5

        # Get first 2
        page1 = clean_db.get_decisions_by_reviewer(
            "paginated@test.com", limit=2, offset=0
        )
        assert len(page1) == 2

        # Get next 2
        page2 = clean_db.get_decisions_by_reviewer(
            "paginated@test.com", limit=2, offset=2
        )
        assert len(page2) == 2

        # Verify pages are different (ordered by created_at DESC)
        page1_ids = [d["decision_id"] for d in page1]
        page2_ids = [d["decision_id"] for d in page2]
        assert not set(page1_ids).intersection(set(page2_ids))

    def test_get_decisions_by_reviewer_empty(self, clean_db):
        """Test with non-existent reviewer returns empty list."""
        decisions = clean_db.get_decisions_by_reviewer("nonexistent@test.com")
        assert decisions == []

    def test_get_decisions_by_reviewer_ordering(self, clean_db):
        """Test decisions are ordered by created_at descending."""
        company_id, filing_id, candidate_id = create_test_candidate(clean_db)

        candidate_id2 = clean_db.insert_review_candidate(
            filing_id=filing_id,
            company_id=company_id,
            char_position=200,
            context_text="Second",
            raw_number_text="200",
            triggering_keyword="test",
            keyword_distance=5,
            keyword_position="before",
        )

        # Insert decisions - first one should appear last in results
        first_decision_id = clean_db.insert_review_decision(
            candidate_id=candidate_id,
            decision="accept",
            assigned_metric_id="cm_transactions_by_cohort",
            reviewer_id="order@test.com",
        )
        second_decision_id = clean_db.insert_review_decision(
            candidate_id=candidate_id2,
            decision="accept",
            assigned_metric_id="cm_customers_period_end_by_tenure",
            reviewer_id="order@test.com",
        )

        decisions = clean_db.get_decisions_by_reviewer("order@test.com")
        assert len(decisions) == 2
        # Most recent first
        assert decisions[0]["decision_id"] == second_decision_id
        assert decisions[1]["decision_id"] == first_decision_id

    def test_get_decisions_by_reviewer_invalid_decision(self, clean_db):
        """Test that invalid decision filter raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            clean_db.get_decisions_by_reviewer("test@test.com", decision="invalid")
        assert "decision" in str(exc_info.value)

    def test_get_decisions_by_reviewer_invalid_limit(self, clean_db):
        """Test that invalid limit raises ValidationError."""
        # Zero limit
        with pytest.raises(ValidationError) as exc_info:
            clean_db.get_decisions_by_reviewer("test@test.com", limit=0)
        assert "limit must be > 0" in str(exc_info.value)

        # Negative limit
        with pytest.raises(ValidationError) as exc_info:
            clean_db.get_decisions_by_reviewer("test@test.com", limit=-5)
        assert "limit must be > 0" in str(exc_info.value)

    def test_get_decisions_by_reviewer_invalid_offset(self, clean_db):
        """Test that negative offset raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            clean_db.get_decisions_by_reviewer("test@test.com", offset=-1)
        assert "offset must be >= 0" in str(exc_info.value)

    def test_get_decisions_by_reviewer_include_total(self, clean_db):
        """Test include_total returns dict with results and total count."""
        company_id, filing_id, _ = create_test_candidate(clean_db)

        # Create multiple candidates and decisions
        for i in range(5):
            cid = clean_db.insert_review_candidate(
                filing_id=filing_id,
                company_id=company_id,
                char_position=i * 100,
                context_text=f"Context {i}",
                raw_number_text=str(i),
                triggering_keyword="test",
                keyword_distance=5,
                keyword_position="after",
            )
            clean_db.insert_review_decision(
                candidate_id=cid,
                decision="accept",
                assigned_metric_id=["cm_new_customers_acquired", "cm_customers_period_end_by_tenure", "cm_revenue_by_cohort", "cm_transactions_by_cohort", "cm_active_customers_total"][i],
                reviewer_id="total_test@test.com",
            )

        # Without include_total - returns list
        result_list = clean_db.get_decisions_by_reviewer("total_test@test.com")
        assert isinstance(result_list, list)
        assert len(result_list) == 5

        # With include_total - returns dict
        result_dict = clean_db.get_decisions_by_reviewer(
            "total_test@test.com", include_total=True
        )
        assert isinstance(result_dict, dict)
        assert "results" in result_dict
        assert "total" in result_dict
        assert len(result_dict["results"]) == 5
        assert result_dict["total"] == 5

        # With pagination + include_total
        paginated = clean_db.get_decisions_by_reviewer(
            "total_test@test.com", limit=2, offset=0, include_total=True
        )
        assert len(paginated["results"]) == 2
        assert paginated["total"] == 5  # Total ignores pagination


class TestLearnedPatternsMethods:
    """Tests for learned_patterns table operations."""

    def test_insert_learned_pattern(self, clean_db):
        """Test inserting a learned pattern."""
        pattern_definition = {
            "conditions": [
                {"field": "is_in_risk_factors", "op": "eq", "value": True},
                {"field": "keyword_distance", "op": "gt", "value": 50},
            ],
            "logic": "and",
        }

        pattern_id = clean_db.insert_learned_pattern(
            pattern_type="reject_rule",
            pattern_name="Risk factors far keyword",
            pattern_definition=pattern_definition,
            pattern_description="Numbers in risk factors far from keywords are usually not metrics",
            precision_score=0.92,
            recall_score=0.45,
            f1_score=0.60,
            sample_count=100,
        )

        assert pattern_id > 0

        pattern = clean_db.get_learned_pattern(pattern_id)
        assert pattern is not None
        assert pattern["pattern_type"] == "reject_rule"
        assert pattern["pattern_name"] == "Risk factors far keyword"
        assert pattern["status"] == "candidate"
        assert float(pattern["precision_score"]) == 0.92
        assert pattern["pattern_definition"]["logic"] == "and"

    def test_get_approved_patterns(self, clean_db):
        """Test getting approved patterns."""
        # Create candidate pattern
        pattern_id = clean_db.insert_learned_pattern(
            pattern_type="accept_rule",
            pattern_name="Close keyword definition",
            pattern_definition={"conditions": [], "logic": "and"},
            metric_id="cm_new_customers_acquired",
            precision_score=0.95,
        )

        # Initially no approved patterns
        approved = clean_db.get_approved_patterns()
        assert len(approved) == 0

        # Approve the pattern
        clean_db.update_pattern_status(pattern_id, "approved", approved_by="test_user")

        approved = clean_db.get_approved_patterns()
        assert len(approved) == 1
        assert approved[0]["pattern_id"] == pattern_id
        assert approved[0]["approved_by"] == "test_user"
        assert approved[0]["approved_at"] is not None

    def test_get_approved_patterns_by_type(self, clean_db):
        """Test filtering approved patterns by type."""
        # Create and approve patterns of different types
        accept_id = clean_db.insert_learned_pattern(
            pattern_type="accept_rule",
            pattern_name="Accept pattern",
            pattern_definition={"conditions": []},
        )
        reject_id = clean_db.insert_learned_pattern(
            pattern_type="reject_rule",
            pattern_name="Reject pattern",
            pattern_definition={"conditions": []},
        )

        clean_db.update_pattern_status(accept_id, "approved")
        clean_db.update_pattern_status(reject_id, "approved")

        accept_patterns = clean_db.get_approved_patterns(pattern_type="accept_rule")
        assert len(accept_patterns) == 1
        assert accept_patterns[0]["pattern_type"] == "accept_rule"

        reject_patterns = clean_db.get_approved_patterns(pattern_type="reject_rule")
        assert len(reject_patterns) == 1

    def test_get_approved_patterns_by_metric(self, clean_db):
        """Test filtering approved patterns by metric."""
        # Global pattern (no metric)
        global_id = clean_db.insert_learned_pattern(
            pattern_type="accept_rule",
            pattern_name="Global pattern",
            pattern_definition={"conditions": []},
            metric_id=None,
        )
        # Metric-specific pattern
        metric_id = clean_db.insert_learned_pattern(
            pattern_type="accept_rule",
            pattern_name="Customer pattern",
            pattern_definition={"conditions": []},
            metric_id="cm_new_customers_acquired",
        )

        clean_db.update_pattern_status(global_id, "approved")
        clean_db.update_pattern_status(metric_id, "approved")

        # When filtering by metric, should get both global and metric-specific
        patterns = clean_db.get_approved_patterns(metric_id="cm_new_customers_acquired")
        assert len(patterns) == 2

    def test_update_pattern_status(self, clean_db):
        """Test updating pattern status through lifecycle."""
        pattern_id = clean_db.insert_learned_pattern(
            pattern_type="accept_rule",
            pattern_name="Test pattern",
            pattern_definition={"conditions": []},
        )

        # Initially candidate
        pattern = clean_db.get_learned_pattern(pattern_id)
        assert pattern["status"] == "candidate"

        # Reject it
        result = clean_db.update_pattern_status(pattern_id, "rejected")
        assert result is True
        pattern = clean_db.get_learned_pattern(pattern_id)
        assert pattern["status"] == "rejected"

        # Approve it (could happen after modification)
        result = clean_db.update_pattern_status(pattern_id, "approved", approved_by="admin")
        assert result is True
        pattern = clean_db.get_learned_pattern(pattern_id)
        assert pattern["status"] == "approved"
        assert pattern["approved_by"] == "admin"

        # Deprecate it
        result = clean_db.update_pattern_status(pattern_id, "deprecated")
        assert result is True
        pattern = clean_db.get_learned_pattern(pattern_id)
        assert pattern["status"] == "deprecated"

    def test_update_pattern_status_nonexistent_returns_false(self, clean_db):
        """Updating a non-existent pattern should return False."""
        # Use an ID that doesn't exist
        result = clean_db.update_pattern_status(999999, "approved")
        assert result is False

    def test_get_candidate_patterns_basic(self, clean_db):
        """Test getting candidate patterns (status='candidate')."""
        # Insert patterns with different statuses
        candidate_id = clean_db.insert_learned_pattern(
            pattern_type="accept_rule",
            pattern_name="Candidate pattern",
            pattern_definition={"conditions": []},
            precision_score=0.85,
        )
        approved_id = clean_db.insert_learned_pattern(
            pattern_type="reject_rule",
            pattern_name="Approved pattern",
            pattern_definition={"conditions": []},
            precision_score=0.90,
        )
        clean_db.update_pattern_status(approved_id, "approved")

        # Should only get the candidate one
        patterns = clean_db.get_candidate_patterns()
        assert len(patterns) == 1
        assert patterns[0]["pattern_id"] == candidate_id
        assert patterns[0]["status"] == "candidate"

    def test_get_candidate_patterns_by_type(self, clean_db):
        """Test filtering candidate patterns by type."""
        accept_id = clean_db.insert_learned_pattern(
            pattern_type="accept_rule",
            pattern_name="Accept candidate",
            pattern_definition={"conditions": []},
        )
        reject_id = clean_db.insert_learned_pattern(
            pattern_type="reject_rule",
            pattern_name="Reject candidate",
            pattern_definition={"conditions": []},
        )

        accept_patterns = clean_db.get_candidate_patterns(pattern_type="accept_rule")
        assert len(accept_patterns) == 1
        assert accept_patterns[0]["pattern_id"] == accept_id

        reject_patterns = clean_db.get_candidate_patterns(pattern_type="reject_rule")
        assert len(reject_patterns) == 1
        assert reject_patterns[0]["pattern_id"] == reject_id

    def test_get_candidate_patterns_by_metric(self, clean_db):
        """Test filtering candidate patterns by metric."""
        # Global pattern
        global_id = clean_db.insert_learned_pattern(
            pattern_type="accept_rule",
            pattern_name="Global pattern",
            pattern_definition={"conditions": []},
            metric_id=None,
        )
        # Metric-specific pattern
        metric_id = clean_db.insert_learned_pattern(
            pattern_type="accept_rule",
            pattern_name="Customer pattern",
            pattern_definition={"conditions": []},
            metric_id="cm_new_customers_acquired",
        )
        # Different metric pattern
        other_metric_id = clean_db.insert_learned_pattern(
            pattern_type="accept_rule",
            pattern_name="Revenue pattern",
            pattern_definition={"conditions": []},
            metric_id="revenue",
        )

        # Should get global + metric-specific
        patterns = clean_db.get_candidate_patterns(metric_id="cm_new_customers_acquired")
        assert len(patterns) == 2
        pattern_ids = [p["pattern_id"] for p in patterns]
        assert global_id in pattern_ids
        assert metric_id in pattern_ids
        assert other_metric_id not in pattern_ids

    def test_get_candidate_patterns_min_precision(self, clean_db):
        """Test filtering candidate patterns by minimum precision."""
        _low_precision_id = clean_db.insert_learned_pattern(
            pattern_type="accept_rule",
            pattern_name="Low precision",
            pattern_definition={"conditions": []},
            precision_score=0.50,
        )
        high_precision_id = clean_db.insert_learned_pattern(
            pattern_type="accept_rule",
            pattern_name="High precision",
            pattern_definition={"conditions": []},
            precision_score=0.95,
        )

        # Filter for high precision
        patterns = clean_db.get_candidate_patterns(min_precision=0.80)
        assert len(patterns) == 1
        assert patterns[0]["pattern_id"] == high_precision_id

        # Lower threshold gets both
        patterns = clean_db.get_candidate_patterns(min_precision=0.40)
        assert len(patterns) == 2

    def test_get_candidate_patterns_min_sample_count(self, clean_db):
        """Test filtering candidate patterns by minimum sample count."""
        _low_sample_id = clean_db.insert_learned_pattern(
            pattern_type="accept_rule",
            pattern_name="Low samples",
            pattern_definition={"conditions": []},
            sample_count=10,
        )
        high_sample_id = clean_db.insert_learned_pattern(
            pattern_type="accept_rule",
            pattern_name="High samples",
            pattern_definition={"conditions": []},
            sample_count=100,
        )

        # Filter for high sample count
        patterns = clean_db.get_candidate_patterns(min_sample_count=50)
        assert len(patterns) == 1
        assert patterns[0]["pattern_id"] == high_sample_id

    def test_get_candidate_patterns_ordering(self, clean_db):
        """Test that patterns are ordered by precision desc, then created_at desc."""
        # Insert in order: low precision, high precision
        low_id = clean_db.insert_learned_pattern(
            pattern_type="accept_rule",
            pattern_name="Low precision",
            pattern_definition={"conditions": []},
            precision_score=0.60,
        )
        high_id = clean_db.insert_learned_pattern(
            pattern_type="accept_rule",
            pattern_name="High precision",
            pattern_definition={"conditions": []},
            precision_score=0.95,
        )

        patterns = clean_db.get_candidate_patterns()
        assert len(patterns) == 2
        # High precision should come first
        assert patterns[0]["pattern_id"] == high_id
        assert patterns[1]["pattern_id"] == low_id

    def test_get_candidate_patterns_empty(self, clean_db):
        """Test when no candidate patterns exist."""
        patterns = clean_db.get_candidate_patterns()
        assert patterns == []


class TestHelperMethods:
    """Tests for Flask route helper methods."""

    def test_get_filings_with_candidates(self, clean_db):
        """Test getting filings with candidate counts."""
        company_id, filing_id = create_test_company_and_filing(clean_db)

        # Add candidates
        for i in range(5):
            clean_db.insert_review_candidate(
                filing_id=filing_id,
                company_id=company_id,
                char_position=i * 100,
                context_text=f"Context {i}",
                raw_number_text=str(i),
                triggering_keyword="test",
                keyword_distance=5,
                keyword_position="after",
            )

        filings = clean_db.get_filings_with_candidates()
        assert len(filings) == 1
        assert filings[0]["filing_id"] == filing_id
        assert filings[0]["total_candidates"] == 5
        assert filings[0]["pending_count"] == 5
        assert filings[0]["reviewed_count"] == 0
        assert filings[0]["company_name"] == "Test Corp"

    def test_get_filings_with_candidates_multiple_filings(self, clean_db):
        """Test with multiple filings, sorted by pending count."""
        company_id = clean_db.upsert_company(
            cik="0001234567", company_name="Test Company"
        )

        # Filing 1: 2 candidates
        filing_id1 = clean_db.upsert_filing(
            company_id=company_id,
            cik="0001234567",
            accession_number="0001234567-24-000001",
            form_type="S-1",
            filing_date="2024-01-15",
            sec_html_url="https://test1",
            is_post_combination=False,
            is_investment_vehicle=False,
            is_resource_extraction=False,
        )
        for i in range(2):
            clean_db.insert_review_candidate(
                filing_id=filing_id1,
                company_id=company_id,
                char_position=i,
                context_text=f"C{i}",
                raw_number_text="1",
                triggering_keyword="t",
                keyword_distance=1,
                keyword_position="after",
            )

        # Filing 2: 5 candidates
        filing_id2 = clean_db.upsert_filing(
            company_id=company_id,
            cik="0001234567",
            accession_number="0001234567-24-000002",
            form_type="S-1/A",
            filing_date="2024-02-15",
            sec_html_url="https://test2",
            is_post_combination=False,
            is_investment_vehicle=False,
            is_resource_extraction=False,
        )
        for i in range(5):
            clean_db.insert_review_candidate(
                filing_id=filing_id2,
                company_id=company_id,
                char_position=i,
                context_text=f"C{i}",
                raw_number_text="1",
                triggering_keyword="t",
                keyword_distance=1,
                keyword_position="after",
            )

        filings = clean_db.get_filings_with_candidates()
        assert len(filings) == 2
        # Filing 2 should be first (more pending)
        assert filings[0]["filing_id"] == filing_id2
        assert filings[0]["pending_count"] == 5

    def test_get_review_progress(self, clean_db):
        """Test getting overall review progress."""
        company_id, filing_id = create_test_company_and_filing(clean_db)

        # Add candidates with different statuses
        candidate_ids = []
        for i in range(6):
            cid = clean_db.insert_review_candidate(
                filing_id=filing_id,
                company_id=company_id,
                char_position=i * 100,
                context_text=f"Context {i}",
                raw_number_text=str(i),
                triggering_keyword="test",
                keyword_distance=5,
                keyword_position="after",
            )
            candidate_ids.append(cid)

        # Update some statuses
        clean_db.update_candidate_status(candidate_ids[0], "reviewed")
        clean_db.update_candidate_status(candidate_ids[1], "reviewed")
        clean_db.update_candidate_status(candidate_ids[2], "skipped")

        progress = clean_db.get_review_progress()
        assert progress["total_candidates"] == 6
        assert progress["pending_count"] == 3
        assert progress["reviewed_count"] == 2
        assert progress["skipped_count"] == 1
        assert progress["total_filings"] == 1
        assert abs(progress["review_pct"] - 33.33) < 0.1

    def test_get_review_progress_empty(self, clean_db):
        """Test review progress with no candidates."""
        progress = clean_db.get_review_progress()
        assert progress["total_candidates"] == 0
        assert progress["review_pct"] == 0

    def test_get_next_candidate_for_review(self, clean_db):
        """Test getting next pending candidate."""
        company_id, filing_id = create_test_company_and_filing(clean_db)

        # Add candidates
        for i in range(3):
            clean_db.insert_review_candidate(
                filing_id=filing_id,
                company_id=company_id,
                char_position=(i + 1) * 100,  # 100, 200, 300
                context_text=f"Context {i}",
                raw_number_text=str(i),
                triggering_keyword="test",
                keyword_distance=5,
                keyword_position="after",
            )

        # Get next - should be first by char_position
        next_candidate = clean_db.get_next_candidate_for_review()
        assert next_candidate is not None
        assert next_candidate["char_position"] == 100

        # Review first one
        clean_db.update_candidate_status(next_candidate["candidate_id"], "reviewed")

        # Get next - should be second
        next_candidate = clean_db.get_next_candidate_for_review()
        assert next_candidate["char_position"] == 200

    def test_get_next_candidate_for_review_by_filing(self, clean_db):
        """Test getting next candidate filtered by filing."""
        company_id = clean_db.upsert_company(
            cik="0001234567", company_name="Test Company"
        )

        filing_id1 = clean_db.upsert_filing(
            company_id=company_id,
            cik="0001234567",
            accession_number="0001234567-24-000001",
            form_type="S-1",
            filing_date="2024-01-15",
            sec_html_url="https://test1",
            is_post_combination=False,
            is_investment_vehicle=False,
            is_resource_extraction=False,
        )
        filing_id2 = clean_db.upsert_filing(
            company_id=company_id,
            cik="0001234567",
            accession_number="0001234567-24-000002",
            form_type="S-1/A",
            filing_date="2024-02-15",
            sec_html_url="https://test2",
            is_post_combination=False,
            is_investment_vehicle=False,
            is_resource_extraction=False,
        )

        # Add candidate to each filing
        clean_db.insert_review_candidate(
            filing_id=filing_id1,
            company_id=company_id,
            char_position=100,
            context_text="Filing 1 context",
            raw_number_text="100",
            triggering_keyword="test",
            keyword_distance=5,
            keyword_position="after",
        )
        clean_db.insert_review_candidate(
            filing_id=filing_id2,
            company_id=company_id,
            char_position=200,
            context_text="Filing 2 context",
            raw_number_text="200",
            triggering_keyword="test",
            keyword_distance=5,
            keyword_position="after",
        )

        # Get next for filing 2 specifically
        next_candidate = clean_db.get_next_candidate_for_review(filing_id=filing_id2)
        assert next_candidate is not None
        assert next_candidate["filing_id"] == filing_id2
        assert next_candidate["context_text"] == "Filing 2 context"

    def test_get_next_candidate_for_review_none_pending(self, clean_db):
        """Test when no pending candidates exist."""
        company_id, filing_id = create_test_company_and_filing(clean_db)

        cid = clean_db.insert_review_candidate(
            filing_id=filing_id,
            company_id=company_id,
            char_position=100,
            context_text="Test",
            raw_number_text="100",
            triggering_keyword="test",
            keyword_distance=5,
            keyword_position="after",
        )

        # Mark as reviewed
        clean_db.update_candidate_status(cid, "reviewed")

        next_candidate = clean_db.get_next_candidate_for_review()
        assert next_candidate is None

    def test_get_review_candidates_with_decisions_no_decisions(self, clean_db):
        """Test fetching candidates with decisions when no decisions exist."""
        company_id, filing_id = create_test_company_and_filing(clean_db)

        # Insert candidates without decisions
        for i in range(3):
            clean_db.insert_review_candidate(
                filing_id=filing_id,
                company_id=company_id,
                char_position=i * 100,
                context_text=f"Context {i}",
                raw_number_text=str(i * 1000),
                triggering_keyword="customers",
                keyword_distance=10 + i,
                keyword_position="after",
            )

        candidates = clean_db.get_review_candidates_with_decisions(filing_id)
        assert len(candidates) == 3

        # All should have NULL decision fields
        for candidate in candidates:
            assert candidate["decision_id"] is None
            assert candidate["decision"] is None
            assert candidate["assigned_metric_id"] is None
            assert candidate["rejection_category"] is None
            assert candidate["reviewer_notes"] is None

    def test_get_review_candidates_with_decisions_with_decisions(self, clean_db):
        """Test fetching candidates with decisions when decisions exist."""
        company_id, filing_id = create_test_company_and_filing(clean_db)

        # Insert 3 candidates
        candidate_ids = []
        for i in range(3):
            cid = clean_db.insert_review_candidate(
                filing_id=filing_id,
                company_id=company_id,
                char_position=i * 100,
                context_text=f"Context {i}",
                raw_number_text=str(i * 1000),
                triggering_keyword="customers",
                keyword_distance=10,
                keyword_position="after",
                suggested_metric_id="cm_new_customers_acquired",
            )
            candidate_ids.append(cid)

        # Add decisions to first two candidates
        decision_id1 = clean_db.insert_review_decision(
            candidate_id=candidate_ids[0],
            decision="accept",
            assigned_metric_id="cm_new_customers_acquired",
            reviewer_notes="Looks good",
            review_time_seconds=10,
        )
        decision_id2 = clean_db.insert_review_decision(
            candidate_id=candidate_ids[1],
            decision="reject",
            rejection_category="wrong_metric",
            rejection_reason="Not a customer metric",
            review_time_seconds=15,
        )

        # Fetch candidates with decisions
        candidates = clean_db.get_review_candidates_with_decisions(filing_id)
        assert len(candidates) == 3

        # Verify first candidate has accept decision
        cand0 = next(c for c in candidates if c["candidate_id"] == candidate_ids[0])
        assert cand0["decision_id"] == decision_id1
        assert cand0["decision"] == "accept"
        assert cand0["reviewer_notes"] == "Looks good"
        assert cand0["review_status"] == "reviewed"

        # Verify second candidate has reject decision
        cand1 = next(c for c in candidates if c["candidate_id"] == candidate_ids[1])
        assert cand1["decision_id"] == decision_id2
        assert cand1["decision"] == "reject"
        assert cand1["rejection_category"] == "wrong_metric"

        # Verify third candidate has no decision
        cand2 = next(c for c in candidates if c["candidate_id"] == candidate_ids[2])
        assert cand2["decision_id"] is None
        assert cand2["decision"] is None

    # REMOVED: test_get_review_candidates_with_decisions_latest_decision
    # This test tried to insert multiple decisions for the same candidate, which violates
    # the UNIQUE constraint on candidate_id in review_decisions table. The current schema
    # enforces one decision per candidate, so "latest decision" logic is not needed.

    def test_get_review_candidates_with_decisions_filters_by_status(self, clean_db):
        """Test filtering candidates by status works with decisions."""
        company_id, filing_id = create_test_company_and_filing(clean_db)

        # Insert 3 candidates
        candidate_ids = []
        for i in range(3):
            cid = clean_db.insert_review_candidate(
                filing_id=filing_id,
                company_id=company_id,
                char_position=i * 100,
                context_text=f"Context {i}",
                raw_number_text=str(i),
                triggering_keyword="test",
                keyword_distance=5,
                keyword_position="after",
            )
            candidate_ids.append(cid)

        # Review first two
        clean_db.insert_review_decision(
            candidate_id=candidate_ids[0],
            decision="accept",
            assigned_metric_id="cm_new_customers_acquired",
        )
        clean_db.insert_review_decision(
            candidate_id=candidate_ids[1],
            decision="reject",
            rejection_category="not_a_metric",
        )

        # Filter by pending status
        pending = clean_db.get_review_candidates_with_decisions(
            filing_id, status="pending"
        )
        assert len(pending) == 1
        assert pending[0]["candidate_id"] == candidate_ids[2]
        assert pending[0]["decision_id"] is None

        # Filter by reviewed status
        reviewed = clean_db.get_review_candidates_with_decisions(
            filing_id, status="reviewed"
        )
        assert len(reviewed) == 2
        # Both should have decisions
        assert all(c["decision_id"] is not None for c in reviewed)

    def test_get_filings_with_candidates_offset_pagination(self, clean_db):
        """Test pagination with offset for get_filings_with_candidates."""
        # Create 5 filings with candidates
        filing_ids = []
        for i in range(5):
            company_id, filing_id = create_test_company_and_filing(
                clean_db,
                cik=f"000123456{i}",
                accession_number=f"000123456{i}-24-000001",
            )
            clean_db.insert_review_candidate(
                filing_id=filing_id,
                company_id=company_id,
                char_position=100,
                context_text="We have 10000 customers.",
                raw_number_text="10,000",
                triggering_keyword="customers",
                keyword_distance=5,
                keyword_position="after",
            )
            filing_ids.append(filing_id)

        # Test page 1 (offset=0, limit=2)
        page1 = clean_db.get_filings_with_candidates(limit=2, offset=0)
        assert len(page1) == 2

        # Test page 2 (offset=2, limit=2)
        page2 = clean_db.get_filings_with_candidates(limit=2, offset=2)
        assert len(page2) == 2

        # Test page 3 (offset=4, limit=2)
        page3 = clean_db.get_filings_with_candidates(limit=2, offset=4)
        assert len(page3) == 1

        # Verify no overlap between pages
        page1_ids = {f["filing_id"] for f in page1}
        page2_ids = {f["filing_id"] for f in page2}
        page3_ids = {f["filing_id"] for f in page3}
        assert len(page1_ids & page2_ids) == 0
        assert len(page2_ids & page3_ids) == 0
        assert len(page1_ids & page3_ids) == 0

    def test_get_filings_with_candidates_count(self, clean_db):
        """Test counting filings with candidates."""
        # Initially should be 0
        count = clean_db.get_filings_with_candidates_count()
        assert count == 0

        # Create 3 filings with candidates
        for i in range(3):
            company_id, filing_id = create_test_company_and_filing(
                clean_db,
                cik=f"0001234{i:02d}",
                accession_number=f"0001234{i:02d}-24-000001",
            )
            clean_db.insert_review_candidate(
                filing_id=filing_id,
                company_id=company_id,
                char_position=100,
                context_text="We have 10000 customers.",
                raw_number_text="10,000",
                triggering_keyword="customers",
                keyword_distance=5,
                keyword_position="after",
            )

        # Should now be 3
        count = clean_db.get_filings_with_candidates_count()
        assert count == 3

        # Mark first filing's candidate as reviewed
        filings = clean_db.get_filings_with_candidates()
        first_filing_id = filings[0]["filing_id"]
        candidates = clean_db.get_review_candidates_for_filing(first_filing_id)
        clean_db.update_candidate_status(candidates[0]["candidate_id"], "reviewed")

        # Count with status filter
        pending_count = clean_db.get_filings_with_candidates_count(status="pending")
        reviewed_count = clean_db.get_filings_with_candidates_count(status="reviewed")
        assert pending_count == 2  # 2 filings with pending candidates
        assert reviewed_count == 1  # 1 filing with reviewed candidates


class TestAnalysisViewMethods:
    """Tests for analysis view query methods."""

    def _create_test_data_with_decisions(self, db):
        """Helper to create test data with candidates and decisions."""
        company_id, filing_id = create_test_company_and_filing(db)

        # Create candidates with different suggested metrics
        candidates = []

        # 3 active_customers candidates
        for i in range(3):
            _, _, cid = create_test_candidate(
                db,
                filing_id=filing_id,
                company_id=company_id,
                char_position=i * 100,
                context_text=f"Active customers context {i}",
                raw_number_text=str(1000 + i),
                triggering_keyword="customers",
                keyword_distance=20 + i * 10,
                keyword_position="after",
                suggested_metric_id="cm_new_customers_acquired",
            )
            candidates.append(("cm_new_customers_acquired", cid))

        # 2 arr candidates
        for i in range(2):
            _, _, cid = create_test_candidate(
                db,
                filing_id=filing_id,
                company_id=company_id,
                char_position=300 + i * 100,
                context_text=f"ARR context {i}",
                raw_number_text=str(500 + i),
                triggering_keyword="ARR",
                keyword_distance=15 + i * 5,
                keyword_position="before",
                suggested_metric_id="cm_revenue_by_cohort",
            )
            candidates.append(("cm_revenue_by_cohort", cid))

        return company_id, filing_id, candidates

    def test_get_decision_stats_by_metric_empty(self, clean_db):
        """Test with no decisions - should return empty list."""
        stats = clean_db.get_decision_stats_by_metric()
        assert stats == []

    def test_get_decision_stats_by_metric_with_data(self, clean_db):
        """Test decision stats aggregation."""
        company_id, filing_id, candidates = self._create_test_data_with_decisions(
            clean_db
        )

        # Add decisions: 2 accept, 1 reject for active_customers
        clean_db.insert_review_decision(
            candidate_id=candidates[0][1],  # active_customers
            decision="accept",
            assigned_metric_id="cm_new_customers_acquired",
        )
        clean_db.insert_review_decision(
            candidate_id=candidates[1][1],  # active_customers
            decision="accept",
            assigned_metric_id="cm_new_customers_acquired",
        )
        clean_db.insert_review_decision(
            candidate_id=candidates[2][1],  # active_customers
            decision="reject",
            rejection_reason="Wrong metric",
            rejection_category="wrong_metric",
        )

        # 1 accept, 1 reclassify for arr
        clean_db.insert_review_decision(
            candidate_id=candidates[3][1],  # arr
            decision="accept",
            assigned_metric_id="cm_revenue_by_cohort",
        )
        clean_db.insert_review_decision(
            candidate_id=candidates[4][1],  # arr
            decision="reclassify",
            assigned_metric_id="cm_revenue_per_customer",  # Valid metric ID
        )

        stats = clean_db.get_decision_stats_by_metric()

        # Should have entries for active_customers and arr
        assert len(stats) >= 4  # At least 2 metrics * 2 decision types each

        # Check active_customers stats
        ac_stats = [s for s in stats if s["suggested_metric"] == "cm_new_customers_acquired"]
        assert len(ac_stats) == 2  # accept and reject
        ac_accept = next(s for s in ac_stats if s["decision"] == "accept")
        ac_reject = next(s for s in ac_stats if s["decision"] == "reject")
        assert ac_accept["decision_count"] == 2
        assert ac_reject["decision_count"] == 1

        # Check arr stats
        arr_stats = [s for s in stats if s["suggested_metric"] == "cm_revenue_by_cohort"]
        assert len(arr_stats) == 2  # accept and reclassify

    def test_get_decision_stats_by_metric_filtered(self, clean_db):
        """Test filtering by specific metric."""
        company_id, filing_id, candidates = self._create_test_data_with_decisions(
            clean_db
        )

        # Add one decision for each metric
        clean_db.insert_review_decision(
            candidate_id=candidates[0][1],
            decision="accept",
            assigned_metric_id="cm_new_customers_acquired",
        )
        clean_db.insert_review_decision(
            candidate_id=candidates[3][1],
            decision="accept",
            assigned_metric_id="cm_revenue_by_cohort",
        )

        # Filter to only active_customers
        stats = clean_db.get_decision_stats_by_metric(metric_id="cm_new_customers_acquired")
        assert all(s["suggested_metric"] == "cm_new_customers_acquired" for s in stats)
        assert len(stats) == 1  # Only accept for active_customers

    def test_get_rejection_reasons_empty(self, clean_db):
        """Test with no rejections - should return empty list."""
        reasons = clean_db.get_rejection_reasons()
        assert reasons == []

    def test_get_rejection_reasons_with_data(self, clean_db):
        """Test rejection reason aggregation."""
        company_id, filing_id, candidates = self._create_test_data_with_decisions(
            clean_db
        )

        # Add rejections with different categories
        clean_db.insert_review_decision(
            candidate_id=candidates[0][1],
            decision="reject",
            rejection_reason="Not a real metric",
            rejection_category="not_a_metric",
        )
        clean_db.insert_review_decision(
            candidate_id=candidates[1][1],
            decision="reject",
            rejection_reason="Wrong metric type",
            rejection_category="wrong_metric",
        )
        clean_db.insert_review_decision(
            candidate_id=candidates[2][1],
            decision="reject",
            rejection_reason="Also not a metric",
            rejection_category="not_a_metric",
        )

        reasons = clean_db.get_rejection_reasons()

        # Should have 2 categories for active_customers
        assert len(reasons) == 2
        ac_reasons = [r for r in reasons if r["suggested_metric"] == "cm_new_customers_acquired"]
        assert len(ac_reasons) == 2

        # not_a_metric should have count 2
        not_metric = next(
            r for r in ac_reasons if r["rejection_category"] == "not_a_metric"
        )
        assert not_metric["rejection_count"] == 2
        assert not_metric["avg_keyword_distance"] is not None

        # wrong_metric should have count 1
        wrong_metric = next(
            r for r in ac_reasons if r["rejection_category"] == "wrong_metric"
        )
        assert wrong_metric["rejection_count"] == 1

    def test_get_rejection_reasons_filtered(self, clean_db):
        """Test filtering by specific metric."""
        company_id, filing_id, candidates = self._create_test_data_with_decisions(
            clean_db
        )

        # Add rejections to both metrics
        clean_db.insert_review_decision(
            candidate_id=candidates[0][1],
            decision="reject",
            rejection_category="wrong_metric",
        )
        clean_db.insert_review_decision(
            candidate_id=candidates[3][1],
            decision="reject",
            rejection_category="not_a_metric",
        )

        # Filter to only arr
        reasons = clean_db.get_rejection_reasons(metric_id="cm_revenue_by_cohort")
        assert all(r["suggested_metric"] == "cm_revenue_by_cohort" for r in reasons)
        assert len(reasons) == 1

    def test_get_rejection_reasons_includes_keyword_stats(self, clean_db):
        """Test that keyword distance and position stats are included."""
        company_id, filing_id, candidates = self._create_test_data_with_decisions(
            clean_db
        )

        # Add a rejection
        clean_db.insert_review_decision(
            candidate_id=candidates[0][1],
            decision="reject",
            rejection_category="wrong_metric",
        )

        reasons = clean_db.get_rejection_reasons()
        assert len(reasons) == 1
        reason = reasons[0]

        # Should have keyword stats from the view
        assert "avg_keyword_distance" in reason
        assert "common_keyword_position" in reason
        assert reason["common_keyword_position"] == "after"  # Matches candidate


class TestDailyDecisionCounts:
    """Tests for get_daily_decision_counts() method."""

    def test_get_daily_decision_counts_empty(self, clean_db):
        """Test with no decisions - should return 7 days with count 0."""
        daily_counts = clean_db.get_daily_decision_counts(days=7)

        assert len(daily_counts) == 7
        # All days should have count 0
        assert all(row["count"] == 0 for row in daily_counts)
        # Should be ordered by date ascending
        dates = [row["date"] for row in daily_counts]
        assert dates == sorted(dates)

    def test_get_daily_decision_counts_with_data(self, clean_db):
        """Test with decisions made over several days."""
        from datetime import date, timedelta

        company_id, filing_id = create_test_company_and_filing(clean_db)

        # Create candidates
        candidate_ids = []
        for i in range(5):
            _, _, cid = create_test_candidate(
                clean_db,
                filing_id=filing_id,
                company_id=company_id,
                char_position=i * 100,
                context_text=f"Test context {i}",
                raw_number_text=str(1000 + i),
            )
            candidate_ids.append(cid)

        # Define dates
        today = date.today()
        two_days_ago = today - timedelta(days=2)
        five_days_ago = today - timedelta(days=5)

        # Add decisions using the standard method
        # Insert 3 decisions "today"
        for i in range(3):
            clean_db.insert_review_decision(
                candidate_id=candidate_ids[i],
                decision="accept",
                assigned_metric_id="cm_new_customers_acquired",
            )

        # Manually backdate two decisions for testing
        clean_db.insert_review_decision(
            candidate_id=candidate_ids[3],
            decision="accept",
            assigned_metric_id="cm_new_customers_acquired",
        )
        clean_db.insert_review_decision(
            candidate_id=candidate_ids[4],
            decision="reject",
            rejection_category="not_a_metric",
        )

        # Backdate the last two using raw SQL
        with clean_db.get_connection() as conn:
            with conn.cursor() as cur:
                # Find the last two decision IDs
                cur.execute(
                    """
                    SELECT decision_id FROM review_decisions
                    WHERE candidate_id IN (%s, %s)
                    ORDER BY created_at DESC
                    """,
                    (candidate_ids[3], candidate_ids[4])
                )
                decision_ids = [row["decision_id"] for row in cur.fetchall()]

                # Backdate them
                if len(decision_ids) >= 2:
                    cur.execute(
                        "UPDATE review_decisions SET created_at = %s WHERE decision_id = %s",
                        (two_days_ago, decision_ids[0])
                    )
                    cur.execute(
                        "UPDATE review_decisions SET created_at = %s WHERE decision_id = %s",
                        (five_days_ago, decision_ids[1])
                    )

        # Query daily counts
        daily_counts = clean_db.get_daily_decision_counts(days=7)

        # Basic structure check
        assert len(daily_counts) == 7
        assert all("date" in row and "count" in row for row in daily_counts)

        # Verify total decisions = 5
        total = sum(r["count"] for r in daily_counts)
        assert total == 5, f"Expected 5 total decisions, got {total}"

        # Find specific dates - they should exist
        counts_by_date = {row["date"]: row["count"] for row in daily_counts}
        assert today in counts_by_date
        assert two_days_ago in counts_by_date
        assert five_days_ago in counts_by_date

    def test_get_daily_decision_counts_fills_gaps(self, clean_db):
        """Test that days with no decisions are included with count 0."""

        company_id, filing_id = create_test_company_and_filing(clean_db)
        _, _, candidate_id = create_test_candidate(
            clean_db,
            filing_id=filing_id,
            company_id=company_id,
        )

        # Add one decision today using standard method
        clean_db.insert_review_decision(
            candidate_id=candidate_id,
            decision="accept",
            assigned_metric_id="cm_new_customers_acquired",
        )

        # Query 7 days
        daily_counts = clean_db.get_daily_decision_counts(days=7)

        # Should have exactly 7 entries
        assert len(daily_counts) == 7

        # Total should be 1
        total = sum(r["count"] for r in daily_counts)
        assert total == 1, f"Expected 1 total decision, got {total}"

        # All dates should be present and consecutive
        counts_by_date = {row["date"]: row["count"] for row in daily_counts}
        actual_dates = sorted(counts_by_date.keys())

        # Check we have 7 consecutive dates
        assert len(actual_dates) == 7
        for i in range(1, 7):
            # Each date should be exactly 1 day after the previous
            assert (actual_dates[i] - actual_dates[i-1]).days == 1


class TestTransactionContext:
    """Tests for the transaction() context manager."""

    def test_transaction_commits_on_success(self, clean_db):
        """Transaction should commit all operations on clean exit."""
        company_id, filing_id = create_test_company_and_filing(clean_db)

        # Use transaction for multiple operations
        with clean_db.transaction() as conn:
            with conn.cursor() as cur:
                # Insert candidate
                cur.execute(
                    """
                    INSERT INTO review_candidates (
                        filing_id, company_id, char_position, context_text,
                        raw_number_text, triggering_keyword, keyword_distance,
                        keyword_position
                    )
                    VALUES (%(filing_id)s, %(company_id)s, 100, 'Test context',
                            '1000', 'customers', 10, 'after')
                    RETURNING candidate_id
                    """,
                    {"filing_id": filing_id, "company_id": company_id},
                )
                result = cur.fetchone()
                candidate_id = result["candidate_id"]

                # Update status in same transaction
                cur.execute(
                    """
                    UPDATE review_candidates
                    SET review_status = 'in_progress'
                    WHERE candidate_id = %(candidate_id)s
                    """,
                    {"candidate_id": candidate_id},
                )

        # Verify both operations committed
        candidate = clean_db.get_review_candidate(candidate_id)
        assert candidate is not None
        assert candidate["review_status"] == "in_progress"

    def test_transaction_rolls_back_on_exception(self, clean_db):
        """Transaction should roll back all operations on exception."""
        company_id, filing_id = create_test_company_and_filing(clean_db)

        # Get initial candidate count
        initial_count = len(clean_db.get_review_candidates_for_filing(filing_id))

        with pytest.raises(ValueError):
            with clean_db.transaction() as conn:
                with conn.cursor() as cur:
                    # Insert candidate (would succeed)
                    cur.execute(
                        """
                        INSERT INTO review_candidates (
                            filing_id, company_id, char_position, context_text,
                            raw_number_text, triggering_keyword, keyword_distance,
                            keyword_position
                        )
                        VALUES (%(filing_id)s, %(company_id)s, 100, 'Test context',
                                '1000', 'customers', 10, 'after')
                        RETURNING candidate_id
                        """,
                        {"filing_id": filing_id, "company_id": company_id},
                    )
                    # Raise exception before commit
                    raise ValueError("Simulated failure")

        # Verify insert was rolled back
        final_count = len(clean_db.get_review_candidates_for_filing(filing_id))
        assert final_count == initial_count


class TestAtomicReviewDecision:
    """Tests that insert_review_decision is atomic."""

    def test_decision_and_status_update_atomic(self, clean_db):
        """Decision insert and status update should happen in same transaction."""
        company_id, filing_id, candidate_id = create_test_candidate(clean_db)

        # Verify initial state
        candidate = clean_db.get_review_candidate(candidate_id)
        assert candidate["review_status"] == "pending"

        # Insert decision (should atomically update status)
        decision_id = clean_db.insert_review_decision(
            candidate_id=candidate_id,
            decision="accept",
            assigned_metric_id="cm_new_customers_acquired",
        )

        # Verify both happened
        decision = clean_db.get_decision_for_candidate(candidate_id)
        assert decision is not None
        assert decision["decision_id"] == decision_id

        candidate = clean_db.get_review_candidate(candidate_id)
        assert candidate["review_status"] == "reviewed"

    def test_decision_with_invalid_candidate_rolls_back(self, clean_db):
        """If decision insert fails, nothing should be committed."""
        # Use a non-existent candidate_id
        invalid_candidate_id = 999999

        with pytest.raises(Exception):  # Foreign key violation
            clean_db.insert_review_decision(
                candidate_id=invalid_candidate_id,
                decision="accept",
                assigned_metric_id="cm_new_customers_acquired",
            )

        # Verify no decision was inserted
        decisions = clean_db.query(
            "SELECT * FROM review_decisions WHERE candidate_id = %(cid)s",
            {"cid": invalid_candidate_id},
        )
        assert len(decisions) == 0


class TestValidationErrors:
    """Tests for validation error conditions in review methods."""

    # =========================================================================
    # insert_review_candidate validation
    # =========================================================================

    def test_insert_candidate_invalid_keyword_position(self, clean_db):
        """Invalid keyword_position should raise ValidationError."""
        company_id, filing_id = create_test_company_and_filing(clean_db)

        with pytest.raises(ValidationError) as exc_info:
            clean_db.insert_review_candidate(
                filing_id=filing_id,
                company_id=company_id,
                char_position=100,
                context_text="Test context",
                raw_number_text="1000",
                triggering_keyword="customers",
                keyword_distance=10,
                keyword_position="invalid",  # Not 'before' or 'after'
            )
        assert "keyword_position" in str(exc_info.value)

    def test_insert_candidate_confidence_too_high(self, clean_db):
        """suggestion_confidence > 1 should raise ValidationError."""
        company_id, filing_id = create_test_company_and_filing(clean_db)

        with pytest.raises(ValidationError) as exc_info:
            clean_db.insert_review_candidate(
                filing_id=filing_id,
                company_id=company_id,
                char_position=100,
                context_text="Test context",
                raw_number_text="1000",
                triggering_keyword="customers",
                keyword_distance=10,
                keyword_position="after",
                suggestion_confidence=1.5,  # Must be <= 1
            )
        assert "suggestion_confidence" in str(exc_info.value)

    def test_insert_candidate_confidence_negative(self, clean_db):
        """suggestion_confidence < 0 should raise ValidationError."""
        company_id, filing_id = create_test_company_and_filing(clean_db)

        with pytest.raises(ValidationError) as exc_info:
            clean_db.insert_review_candidate(
                filing_id=filing_id,
                company_id=company_id,
                char_position=100,
                context_text="Test context",
                raw_number_text="1000",
                triggering_keyword="customers",
                keyword_distance=10,
                keyword_position="before",
                suggestion_confidence=-0.1,  # Must be >= 0
            )
        assert "suggestion_confidence" in str(exc_info.value)

    # =========================================================================
    # bulk_insert_review_candidates validation
    # =========================================================================

    def test_bulk_insert_invalid_keyword_position(self, clean_db):
        """Invalid keyword_position in any candidate should raise ValidationError."""
        company_id, filing_id = create_test_company_and_filing(clean_db)

        candidates = [
            {
                "filing_id": filing_id,
                "company_id": company_id,
                "char_position": 100,
                "context_text": "Valid candidate",
                "raw_number_text": "1000",
                "triggering_keyword": "customers",
                "keyword_distance": 10,
                "keyword_position": "after",  # Valid
            },
            {
                "filing_id": filing_id,
                "company_id": company_id,
                "char_position": 200,
                "context_text": "Invalid candidate",
                "raw_number_text": "2000",
                "triggering_keyword": "users",
                "keyword_distance": 15,
                "keyword_position": "beside",  # Invalid
            },
        ]

        with pytest.raises(ValidationError) as exc_info:
            clean_db.bulk_insert_review_candidates(candidates)
        assert "keyword_position" in str(exc_info.value)
        assert "candidate 1" in str(exc_info.value)

    def test_bulk_insert_invalid_confidence(self, clean_db):
        """Invalid suggestion_confidence in any candidate should raise ValidationError."""
        company_id, filing_id = create_test_company_and_filing(clean_db)

        candidates = [
            {
                "filing_id": filing_id,
                "company_id": company_id,
                "char_position": 100,
                "context_text": "Valid candidate",
                "raw_number_text": "1000",
                "triggering_keyword": "customers",
                "keyword_distance": 10,
                "keyword_position": "after",
                "suggestion_confidence": 0.8,  # Valid
            },
            {
                "filing_id": filing_id,
                "company_id": company_id,
                "char_position": 200,
                "context_text": "Invalid candidate",
                "raw_number_text": "2000",
                "triggering_keyword": "users",
                "keyword_distance": 15,
                "keyword_position": "before",
                "suggestion_confidence": 2.0,  # Invalid - too high
            },
        ]

        with pytest.raises(ValidationError) as exc_info:
            clean_db.bulk_insert_review_candidates(candidates)
        assert "suggestion_confidence" in str(exc_info.value)
        assert "candidate 1" in str(exc_info.value)

    def test_bulk_insert_fails_fast_no_partial_insert(self, clean_db):
        """Validation failure should prevent any candidates from being inserted."""
        company_id, filing_id = create_test_company_and_filing(clean_db)

        # Get initial count
        initial_count = len(clean_db.get_review_candidates_for_filing(filing_id))

        candidates = [
            {
                "filing_id": filing_id,
                "company_id": company_id,
                "char_position": 100,
                "context_text": "Valid candidate",
                "raw_number_text": "1000",
                "triggering_keyword": "customers",
                "keyword_distance": 10,
                "keyword_position": "after",
            },
            {
                "filing_id": filing_id,
                "company_id": company_id,
                "char_position": 200,
                "context_text": "Invalid candidate",
                "raw_number_text": "2000",
                "triggering_keyword": "users",
                "keyword_distance": 15,
                "keyword_position": "invalid",  # Will cause failure
            },
        ]

        with pytest.raises(ValidationError):
            clean_db.bulk_insert_review_candidates(candidates)

        # Verify nothing was inserted
        final_count = len(clean_db.get_review_candidates_for_filing(filing_id))
        assert final_count == initial_count

    # =========================================================================
    # insert_review_decision validation
    # =========================================================================

    def test_insert_decision_invalid_type(self, clean_db):
        """Invalid decision type should raise ValidationError."""
        company_id, filing_id, candidate_id = create_test_candidate(clean_db)

        with pytest.raises(ValidationError) as exc_info:
            clean_db.insert_review_decision(
                candidate_id=candidate_id,
                decision="approve",  # Invalid - should be 'accept'
            )
        assert "decision" in str(exc_info.value)

    def test_insert_decision_accept_without_metric_id(self, clean_db):
        """Accept decision without assigned_metric_id should raise ValidationError."""
        company_id, filing_id, candidate_id = create_test_candidate(clean_db)

        with pytest.raises(ValidationError) as exc_info:
            clean_db.insert_review_decision(
                candidate_id=candidate_id,
                decision="accept",
                assigned_metric_id=None,  # Required for accept
            )
        assert "assigned_metric_id" in str(exc_info.value)

    def test_insert_decision_reclassify_without_metric_id(self, clean_db):
        """Reclassify decision without assigned_metric_id should raise ValidationError."""
        company_id, filing_id, candidate_id = create_test_candidate(clean_db)

        with pytest.raises(ValidationError) as exc_info:
            clean_db.insert_review_decision(
                candidate_id=candidate_id,
                decision="reclassify",
                assigned_metric_id=None,  # Required for reclassify
            )
        assert "assigned_metric_id" in str(exc_info.value)

    def test_insert_decision_rejection_category_on_accept(self, clean_db):
        """rejection_category on non-reject decision should raise ValidationError."""
        company_id, filing_id, candidate_id = create_test_candidate(clean_db)

        with pytest.raises(ValidationError) as exc_info:
            clean_db.insert_review_decision(
                candidate_id=candidate_id,
                decision="accept",
                assigned_metric_id="cm_new_customers_acquired",
                rejection_category="wrong_metric",  # Only valid for reject
            )
        assert "rejection_category" in str(exc_info.value)

    def test_insert_decision_invalid_rejection_category(self, clean_db):
        """Invalid rejection_category should raise ValidationError."""
        company_id, filing_id, candidate_id = create_test_candidate(clean_db)

        with pytest.raises(ValidationError) as exc_info:
            clean_db.insert_review_decision(
                candidate_id=candidate_id,
                decision="reject",
                rejection_category="invalid_category",  # Not in allowed list
            )
        assert "rejection_category" in str(exc_info.value)

    # =========================================================================
    # update_candidate_status validation
    # =========================================================================

    def test_update_candidate_status_invalid(self, clean_db):
        """Invalid status should raise ValidationError."""
        company_id, filing_id, candidate_id = create_test_candidate(clean_db)

        with pytest.raises(ValidationError) as exc_info:
            clean_db.update_candidate_status(candidate_id, "completed")  # Invalid
        assert "review_status" in str(exc_info.value)

    # =========================================================================
    # bulk_update_candidate_status validation
    # =========================================================================

    def test_bulk_update_candidate_status_invalid(self, clean_db):
        """Invalid status in bulk update should raise ValidationError."""
        company_id, filing_id, candidate_id = create_test_candidate(clean_db)

        with pytest.raises(ValidationError) as exc_info:
            clean_db.bulk_update_candidate_status([candidate_id], "done")  # Invalid
        assert "review_status" in str(exc_info.value)

    def test_bulk_update_no_partial_update_on_validation_error(self, clean_db):
        """Validation error should prevent any status updates."""
        company_id, filing_id = create_test_company_and_filing(clean_db)

        # Create multiple candidates
        candidate_ids = []
        for i in range(3):
            cid = clean_db.insert_review_candidate(
                filing_id=filing_id,
                company_id=company_id,
                char_position=i * 100,
                context_text=f"Context {i}",
                raw_number_text=str(i),
                triggering_keyword="test",
                keyword_distance=5,
                keyword_position="after",
            )
            candidate_ids.append(cid)

        # Attempt bulk update with invalid status
        with pytest.raises(ValidationError):
            clean_db.bulk_update_candidate_status(candidate_ids, "invalid_status")

        # Verify all candidates still have original status
        for cid in candidate_ids:
            candidate = clean_db.get_review_candidate(cid)
            assert candidate["review_status"] == "pending"

    # =========================================================================
    # insert_learned_pattern validation
    # =========================================================================

    def test_insert_pattern_invalid_type(self, clean_db):
        """Invalid pattern_type should raise ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            clean_db.insert_learned_pattern(
                pattern_type="invalid_type",  # Not 'accept_rule', 'reject_rule', or 'feature_weight'
                pattern_name="Test pattern",
                pattern_definition={"conditions": []},
            )
        assert "pattern_type" in str(exc_info.value)

    def test_insert_pattern_precision_too_high(self, clean_db):
        """precision_score > 1 should raise ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            clean_db.insert_learned_pattern(
                pattern_type="accept_rule",
                pattern_name="Test pattern",
                pattern_definition={"conditions": []},
                precision_score=1.5,  # Must be <= 1
            )
        assert "precision_score" in str(exc_info.value)

    def test_insert_pattern_precision_negative(self, clean_db):
        """precision_score < 0 should raise ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            clean_db.insert_learned_pattern(
                pattern_type="accept_rule",
                pattern_name="Test pattern",
                pattern_definition={"conditions": []},
                precision_score=-0.1,  # Must be >= 0
            )
        assert "precision_score" in str(exc_info.value)

    def test_insert_pattern_recall_too_high(self, clean_db):
        """recall_score > 1 should raise ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            clean_db.insert_learned_pattern(
                pattern_type="reject_rule",
                pattern_name="Test pattern",
                pattern_definition={"conditions": []},
                recall_score=2.0,  # Must be <= 1
            )
        assert "recall_score" in str(exc_info.value)

    def test_insert_pattern_f1_negative(self, clean_db):
        """f1_score < 0 should raise ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            clean_db.insert_learned_pattern(
                pattern_type="feature_weight",
                pattern_name="Test pattern",
                pattern_definition={"conditions": []},
                f1_score=-0.5,  # Must be >= 0
            )
        assert "f1_score" in str(exc_info.value)

    def test_insert_pattern_boundary_scores_valid(self, clean_db):
        """Boundary values 0 and 1 should be valid."""
        # Score of exactly 0 should work
        pattern_id = clean_db.insert_learned_pattern(
            pattern_type="accept_rule",
            pattern_name="Zero score pattern",
            pattern_definition={"conditions": []},
            precision_score=0.0,
            recall_score=0.0,
            f1_score=0.0,
        )
        assert pattern_id > 0

        # Score of exactly 1 should work
        pattern_id = clean_db.insert_learned_pattern(
            pattern_type="reject_rule",
            pattern_name="Perfect score pattern",
            pattern_definition={"conditions": []},
            precision_score=1.0,
            recall_score=1.0,
            f1_score=1.0,
        )
        assert pattern_id > 0

    # =========================================================================
    # update_pattern_status validation
    # =========================================================================

    def test_update_pattern_status_invalid(self, clean_db):
        """Invalid status should raise ValidationError."""
        # First create a valid pattern
        pattern_id = clean_db.insert_learned_pattern(
            pattern_type="accept_rule",
            pattern_name="Test pattern",
            pattern_definition={"conditions": []},
        )

        with pytest.raises(ValidationError) as exc_info:
            clean_db.update_pattern_status(pattern_id, "invalid_status")
        assert "pattern_status" in str(exc_info.value)

    def test_update_pattern_status_empty(self, clean_db):
        """Empty status should raise ValidationError."""
        pattern_id = clean_db.insert_learned_pattern(
            pattern_type="accept_rule",
            pattern_name="Test pattern",
            pattern_definition={"conditions": []},
        )

        with pytest.raises(ValidationError) as exc_info:
            clean_db.update_pattern_status(pattern_id, "")
        assert "pattern_status" in str(exc_info.value)


class TestGetAllReviewedCandidatesWithDecisions:
    """Tests for get_all_reviewed_candidates_with_decisions() (Phase 4 - E1)."""

    def test_get_all_reviewed_empty_database(self, clean_db):
        """Test with no candidates in database."""
        candidates = clean_db.get_all_reviewed_candidates_with_decisions()
        assert len(candidates) == 0

    def test_get_all_reviewed_only_pending_candidates(self, clean_db):
        """Test that pending (unreviewed) candidates are not returned."""
        company_id, filing_id = create_test_company_and_filing(clean_db)

        # Insert 3 pending candidates (no decisions)
        for i in range(3):
            clean_db.insert_review_candidate(
                filing_id=filing_id,
                company_id=company_id,
                char_position=i * 100,
                context_text=f"Context {i}",
                raw_number_text=str(i * 1000),
                triggering_keyword="customers",
                keyword_distance=10,
                keyword_position="after",
            )

        # Should return 0 since no decisions exist
        candidates = clean_db.get_all_reviewed_candidates_with_decisions()
        assert len(candidates) == 0

    def test_get_all_reviewed_single_filing(self, clean_db):
        """Test with reviewed candidates from a single filing."""
        company_id, filing_id = create_test_company_and_filing(clean_db)

        # Insert 2 candidates with decisions
        cand1 = clean_db.insert_review_candidate(
            filing_id=filing_id,
            company_id=company_id,
            char_position=100,
            context_text="We have 1,000 customers",
            raw_number_text="1,000",
            triggering_keyword="customers",
            keyword_distance=10,
            keyword_position="after",
            suggested_metric_id="cm_new_customers_acquired",
        )

        cand2 = clean_db.insert_review_candidate(
            filing_id=filing_id,
            company_id=company_id,
            char_position=200,
            context_text="Revenue was $5M",
            raw_number_text="$5M",
            triggering_keyword="revenue",
            keyword_distance=15,
            keyword_position="after",
            suggested_metric_id="annual_recurring_revenue",
        )

        # Add decisions
        clean_db.insert_review_decision(
            candidate_id=cand1,
            decision="accept",
            assigned_metric_id="cm_new_customers_acquired",  # Valid metric from seed
            reviewer_notes="Good match",
        )

        clean_db.insert_review_decision(
            candidate_id=cand2,
            decision="reject",
            rejection_category="wrong_metric",
            rejection_reason="Not ARR",
        )

        # Fetch all reviewed
        candidates = clean_db.get_all_reviewed_candidates_with_decisions()
        assert len(candidates) == 2

        # Verify both have decisions
        for candidate in candidates:
            assert candidate["decision"] is not None
            assert candidate["decision_id"] is not None

        # Verify specific decisions
        cand1_result = next(c for c in candidates if c["candidate_id"] == cand1)
        assert cand1_result["decision"] == "accept"
        assert cand1_result["reviewer_notes"] == "Good match"

        cand2_result = next(c for c in candidates if c["candidate_id"] == cand2)
        assert cand2_result["decision"] == "reject"
        assert cand2_result["rejection_category"] == "wrong_metric"

    def test_get_all_reviewed_multiple_filings(self, clean_db):
        """Test with reviewed candidates across multiple filings."""
        # Create two companies and filings
        company1_id, filing1_id = create_test_company_and_filing(clean_db)
        company2_id, filing2_id = create_test_company_and_filing(
            clean_db, cik="0000654321"
        )

        # Insert candidate in filing 1
        cand1 = clean_db.insert_review_candidate(
            filing_id=filing1_id,
            company_id=company1_id,
            char_position=100,
            context_text="Filing 1 candidate",
            raw_number_text="1,000",
            triggering_keyword="customers",
            keyword_distance=10,
            keyword_position="after",
            suggested_metric_id="cm_new_customers_acquired",
        )

        # Insert candidate in filing 2
        cand2 = clean_db.insert_review_candidate(
            filing_id=filing2_id,
            company_id=company2_id,
            char_position=200,
            context_text="Filing 2 candidate",
            raw_number_text="2,000",
            triggering_keyword="customers",
            keyword_distance=15,
            keyword_position="after",
            suggested_metric_id="cm_new_customers_acquired",
        )

        # Add decisions to both
        clean_db.insert_review_decision(
            candidate_id=cand1, decision="accept", assigned_metric_id="cm_new_customers_acquired"
        )
        clean_db.insert_review_decision(
            candidate_id=cand2,
            decision="reject",
            rejection_category="not_a_metric",
        )

        # Fetch all reviewed - should get both
        candidates = clean_db.get_all_reviewed_candidates_with_decisions()
        assert len(candidates) == 2

        # Verify from different filings
        filing_ids = {c["filing_id"] for c in candidates}
        assert filing1_id in filing_ids
        assert filing2_id in filing_ids

    def test_get_all_reviewed_filters_by_metric_id(self, clean_db):
        """Test filtering by metric_id."""
        company_id, filing_id = create_test_company_and_filing(clean_db)

        # Insert 3 candidates with different metric IDs
        cand1 = clean_db.insert_review_candidate(
            filing_id=filing_id,
            company_id=company_id,
            char_position=100,
            context_text="ARR candidate",
            raw_number_text="$5M",
            triggering_keyword="revenue",
            keyword_distance=10,
            keyword_position="after",
            suggested_metric_id="annual_recurring_revenue",
        )

        cand2 = clean_db.insert_review_candidate(
            filing_id=filing_id,
            company_id=company_id,
            char_position=200,
            context_text="Customer candidate",
            raw_number_text="1,000",
            triggering_keyword="customers",
            keyword_distance=10,
            keyword_position="after",
            suggested_metric_id="cm_new_customers_acquired",
        )

        cand3 = clean_db.insert_review_candidate(
            filing_id=filing_id,
            company_id=company_id,
            char_position=300,
            context_text="Another ARR candidate",
            raw_number_text="$10M",
            triggering_keyword="revenue",
            keyword_distance=15,
            keyword_position="after",
            suggested_metric_id="annual_recurring_revenue",
        )

        # Add decisions to all
        for cand_id in [cand1, cand2, cand3]:
            clean_db.insert_review_decision(
                candidate_id=cand_id,
                decision="accept",
                assigned_metric_id="cm_new_customers_acquired",
            )

        # Filter by ARR
        arr_candidates = clean_db.get_all_reviewed_candidates_with_decisions(
            metric_id="annual_recurring_revenue"
        )
        assert len(arr_candidates) == 2
        for c in arr_candidates:
            assert c["suggested_metric_id"] == "annual_recurring_revenue"

        # Filter by active_customers
        customer_candidates = clean_db.get_all_reviewed_candidates_with_decisions(
            metric_id="cm_new_customers_acquired"
        )
        assert len(customer_candidates) == 1
        assert customer_candidates[0]["suggested_metric_id"] == "cm_new_customers_acquired"

        # No filter - get all
        all_candidates = clean_db.get_all_reviewed_candidates_with_decisions()
        assert len(all_candidates) == 3

    def test_get_all_reviewed_pagination(self, clean_db):
        """Test pagination with limit and offset."""
        company_id, filing_id = create_test_company_and_filing(clean_db)

        # Insert 10 candidates with decisions
        candidate_ids = []
        for i in range(10):
            cand_id = clean_db.insert_review_candidate(
                filing_id=filing_id,
                company_id=company_id,
                char_position=i * 100,
                context_text=f"Candidate {i}",
                raw_number_text=str(i * 1000),
                triggering_keyword="customers",
                keyword_distance=10,
                keyword_position="after",
            )
            candidate_ids.append(cand_id)

            # Add decision
            clean_db.insert_review_decision(
                candidate_id=cand_id,
                decision="accept" if i % 2 == 0 else "reject",
                assigned_metric_id="cm_new_customers_acquired" if i % 2 == 0 else None,
                rejection_category="not_a_metric" if i % 2 == 1 else None,
            )

        # Test limit
        batch1 = clean_db.get_all_reviewed_candidates_with_decisions(limit=3)
        assert len(batch1) == 3

        # Test limit + offset
        batch2 = clean_db.get_all_reviewed_candidates_with_decisions(
            limit=3, offset=3
        )
        assert len(batch2) == 3

        # Batches should be different
        batch1_ids = {c["candidate_id"] for c in batch1}
        batch2_ids = {c["candidate_id"] for c in batch2}
        assert batch1_ids.isdisjoint(batch2_ids)

        # Test offset beyond data
        batch_empty = clean_db.get_all_reviewed_candidates_with_decisions(
            limit=5, offset=100
        )
        assert len(batch_empty) == 0

    # REMOVED: test_get_all_reviewed_latest_decision_only
    # This test tried to insert multiple decisions for the same candidate, which violates
    # the UNIQUE constraint on candidate_id in review_decisions table. The current schema
    # enforces one decision per candidate, so "latest decision" logic is not needed.

    def test_get_all_reviewed_mixed_reviewed_and_pending(self, clean_db):
        """Test that only reviewed candidates are returned, pending are excluded."""
        company_id, filing_id = create_test_company_and_filing(clean_db)

        # Insert 2 reviewed candidates
        cand1 = clean_db.insert_review_candidate(
            filing_id=filing_id,
            company_id=company_id,
            char_position=100,
            context_text="Reviewed 1",
            raw_number_text="1,000",
            triggering_keyword="customers",
            keyword_distance=10,
            keyword_position="after",
        )
        clean_db.insert_review_decision(
            candidate_id=cand1, decision="accept", assigned_metric_id="cm_new_customers_acquired"
        )

        cand2 = clean_db.insert_review_candidate(
            filing_id=filing_id,
            company_id=company_id,
            char_position=200,
            context_text="Reviewed 2",
            raw_number_text="2,000",
            triggering_keyword="customers",
            keyword_distance=10,
            keyword_position="after",
        )
        clean_db.insert_review_decision(
            candidate_id=cand2,
            decision="reject",
            rejection_category="not_a_metric",
        )

        # Insert 3 pending candidates (no decisions)
        for i in range(3):
            clean_db.insert_review_candidate(
                filing_id=filing_id,
                company_id=company_id,
                char_position=(i + 3) * 100,
                context_text=f"Pending {i}",
                raw_number_text=str((i + 3) * 1000),
                triggering_keyword="customers",
                keyword_distance=10,
                keyword_position="after",
            )

        # Should only get the 2 reviewed candidates
        candidates = clean_db.get_all_reviewed_candidates_with_decisions()
        assert len(candidates) == 2

        # All returned should have decisions
        for candidate in candidates:
            assert candidate["decision"] is not None
            assert candidate["decision_id"] is not None
