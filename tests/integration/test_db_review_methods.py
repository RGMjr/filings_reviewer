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

import pytest
from decimal import Decimal


class TestReviewCandidatesMethods:
    """Tests for review_candidates table operations."""

    def _create_test_company_and_filing(self, db):
        """Helper to create prerequisite company and filing."""
        company_id = db.upsert_company(
            cik="0001234567",
            company_name="Test Company Inc",
            ticker="TEST",
        )
        filing_id = db.upsert_filing(
            company_id=company_id,
            cik="0001234567",
            accession_number="0001234567-24-000001",
            form_type="S-1",
            filing_date="2024-01-15",
            sec_html_url="https://www.sec.gov/test",
            is_post_combination=False,
            is_investment_vehicle=False,
            is_resource_extraction=False,
        )
        return company_id, filing_id

    def test_insert_review_candidate_minimal(self, clean_db):
        """Test inserting a candidate with minimal required fields."""
        company_id, filing_id = self._create_test_company_and_filing(clean_db)

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
        company_id, filing_id = self._create_test_company_and_filing(clean_db)

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
            suggested_metric_id="active_customers",
            suggestion_confidence=0.85,
            features=features,
            review_batch_id=1,
        )

        assert candidate_id > 0

        candidate = clean_db.get_review_candidate(candidate_id)
        assert candidate["parsed_value"] == Decimal("10000")
        assert candidate["parsed_unit"] == "count"
        assert candidate["suggested_metric_id"] == "active_customers"
        assert float(candidate["suggestion_confidence"]) == 0.85
        assert candidate["features"]["is_in_table"] is False
        assert candidate["features"]["value_magnitude"] == 4.0
        assert candidate["review_batch_id"] == 1

    def test_get_review_candidates_for_filing(self, clean_db):
        """Test retrieving candidates for a specific filing."""
        company_id, filing_id = self._create_test_company_and_filing(clean_db)

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
        company_id, filing_id = self._create_test_company_and_filing(clean_db)

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
        company_id, filing_id = self._create_test_company_and_filing(clean_db)

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
        assert pending[0]["company_name"] == "Test Company Inc"

    def test_update_candidate_status(self, clean_db):
        """Test updating a candidate's review status."""
        company_id, filing_id = self._create_test_company_and_filing(clean_db)

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
        company_id, filing_id = self._create_test_company_and_filing(clean_db)

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
                "suggested_metric_id": f"metric_{i}",
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
        company_id, filing_id = self._create_test_company_and_filing(clean_db)

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
        company_id, filing_id = self._create_test_company_and_filing(clean_db)

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

    def _create_test_candidate(self, db):
        """Helper to create prerequisite company, filing, and candidate."""
        company_id = db.upsert_company(
            cik="0001234567",
            company_name="Test Company Inc",
        )
        filing_id = db.upsert_filing(
            company_id=company_id,
            cik="0001234567",
            accession_number="0001234567-24-000001",
            form_type="S-1",
            filing_date="2024-01-15",
            sec_html_url="https://www.sec.gov/test",
            is_post_combination=False,
            is_investment_vehicle=False,
            is_resource_extraction=False,
        )
        candidate_id = db.insert_review_candidate(
            filing_id=filing_id,
            company_id=company_id,
            char_position=100,
            context_text="We have 10,000 customers.",
            raw_number_text="10,000",
            triggering_keyword="customers",
            keyword_distance=15,
            keyword_position="after",
            suggested_metric_id="active_customers",
        )
        return company_id, filing_id, candidate_id

    def test_insert_review_decision_accept(self, clean_db):
        """Test recording an accept decision."""
        company_id, filing_id, candidate_id = self._create_test_candidate(clean_db)

        decision_id = clean_db.insert_review_decision(
            candidate_id=candidate_id,
            decision="accept",
            assigned_metric_id="active_customers",
            reviewer_notes="Clear customer count",
            review_time_seconds=15,
        )

        assert decision_id > 0

        # Verify decision was stored
        decision = clean_db.get_decision_for_candidate(candidate_id)
        assert decision is not None
        assert decision["decision"] == "accept"
        assert decision["assigned_metric_id"] == "active_customers"
        assert decision["reviewer_notes"] == "Clear customer count"
        assert decision["review_time_seconds"] == 15

        # Verify candidate status was updated
        candidate = clean_db.get_review_candidate(candidate_id)
        assert candidate["review_status"] == "reviewed"

    def test_insert_review_decision_reject(self, clean_db):
        """Test recording a reject decision."""
        company_id, filing_id, candidate_id = self._create_test_candidate(clean_db)

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
        company_id, filing_id, candidate_id = self._create_test_candidate(clean_db)

        decision_id = clean_db.insert_review_decision(
            candidate_id=candidate_id,
            decision="reclassify",
            assigned_metric_id="total_customers",  # Different from suggested
            reviewer_notes="Actually total, not active",
            review_time_seconds=20,
        )

        assert decision_id > 0

        decision = clean_db.get_decision_for_candidate(candidate_id)
        assert decision["decision"] == "reclassify"
        assert decision["assigned_metric_id"] == "total_customers"

    def test_get_decisions_for_filing(self, clean_db):
        """Test getting all decisions for a filing."""
        company_id, filing_id, candidate_id = self._create_test_candidate(clean_db)

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
            assigned_metric_id="active_customers",
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
        company_id, filing_id, _ = self._create_test_candidate(clean_db)

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
                    candidate_id=cid, decision="accept", assigned_metric_id="test"
                )
            elif i < 5:  # 2 rejects
                clean_db.insert_review_decision(
                    candidate_id=cid, decision="reject", rejection_category="other"
                )
            else:  # 1 reclassify
                clean_db.insert_review_decision(
                    candidate_id=cid, decision="reclassify", assigned_metric_id="other"
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
            metric_id="active_customers",
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
            metric_id="active_customers",
        )

        clean_db.update_pattern_status(global_id, "approved")
        clean_db.update_pattern_status(metric_id, "approved")

        # When filtering by metric, should get both global and metric-specific
        patterns = clean_db.get_approved_patterns(metric_id="active_customers")
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
            metric_id="active_customers",
        )
        # Different metric pattern
        other_metric_id = clean_db.insert_learned_pattern(
            pattern_type="accept_rule",
            pattern_name="Revenue pattern",
            pattern_definition={"conditions": []},
            metric_id="revenue",
        )

        # Should get global + metric-specific
        patterns = clean_db.get_candidate_patterns(metric_id="active_customers")
        assert len(patterns) == 2
        pattern_ids = [p["pattern_id"] for p in patterns]
        assert global_id in pattern_ids
        assert metric_id in pattern_ids
        assert other_metric_id not in pattern_ids

    def test_get_candidate_patterns_min_precision(self, clean_db):
        """Test filtering candidate patterns by minimum precision."""
        low_precision_id = clean_db.insert_learned_pattern(
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
        low_sample_id = clean_db.insert_learned_pattern(
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

    def _create_test_data(self, db):
        """Helper to create test company, filing, and candidates."""
        company_id = db.upsert_company(
            cik="0001234567",
            company_name="Test Company Inc",
        )
        filing_id = db.upsert_filing(
            company_id=company_id,
            cik="0001234567",
            accession_number="0001234567-24-000001",
            form_type="S-1",
            filing_date="2024-01-15",
            sec_html_url="https://www.sec.gov/test",
            is_post_combination=False,
            is_investment_vehicle=False,
            is_resource_extraction=False,
        )
        return company_id, filing_id

    def test_get_filings_with_candidates(self, clean_db):
        """Test getting filings with candidate counts."""
        company_id, filing_id = self._create_test_data(clean_db)

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
        assert filings[0]["company_name"] == "Test Company Inc"

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
        company_id, filing_id = self._create_test_data(clean_db)

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
        company_id, filing_id = self._create_test_data(clean_db)

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
        company_id, filing_id = self._create_test_data(clean_db)

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


class TestTransactionContext:
    """Tests for the transaction() context manager."""

    def _create_test_company_and_filing(self, db):
        """Helper to create prerequisite company and filing."""
        company_id = db.upsert_company(
            cik="0001234567",
            company_name="Test Company Inc",
            ticker="TEST",
        )
        filing_id = db.upsert_filing(
            company_id=company_id,
            cik="0001234567",
            accession_number="0001234567-24-000001",
            form_type="S-1",
            filing_date="2024-01-15",
            sec_html_url="https://www.sec.gov/test",
            is_post_combination=False,
            is_investment_vehicle=False,
            is_resource_extraction=False,
        )
        return company_id, filing_id

    def test_transaction_commits_on_success(self, clean_db):
        """Transaction should commit all operations on clean exit."""
        company_id, filing_id = self._create_test_company_and_filing(clean_db)

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
        company_id, filing_id = self._create_test_company_and_filing(clean_db)

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

    def _create_test_candidate(self, db):
        """Helper to create a test candidate."""
        company_id = db.upsert_company(
            cik="0001234567",
            company_name="Test Company Inc",
        )
        filing_id = db.upsert_filing(
            company_id=company_id,
            cik="0001234567",
            accession_number="0001234567-24-000001",
            form_type="S-1",
            filing_date="2024-01-15",
            sec_html_url="https://www.sec.gov/test",
            is_post_combination=False,
            is_investment_vehicle=False,
            is_resource_extraction=False,
        )
        candidate_id = db.insert_review_candidate(
            filing_id=filing_id,
            company_id=company_id,
            char_position=100,
            context_text="We have 10,000 customers",
            raw_number_text="10,000",
            triggering_keyword="customers",
            keyword_distance=15,
            keyword_position="after",
        )
        return company_id, filing_id, candidate_id

    def test_decision_and_status_update_atomic(self, clean_db):
        """Decision insert and status update should happen in same transaction."""
        company_id, filing_id, candidate_id = self._create_test_candidate(clean_db)

        # Verify initial state
        candidate = clean_db.get_review_candidate(candidate_id)
        assert candidate["review_status"] == "pending"

        # Insert decision (should atomically update status)
        decision_id = clean_db.insert_review_decision(
            candidate_id=candidate_id,
            decision="accept",
            assigned_metric_id="active_customers",
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
                assigned_metric_id="active_customers",
            )

        # Verify no decision was inserted
        decisions = clean_db.query(
            "SELECT * FROM review_decisions WHERE candidate_id = %(cid)s",
            {"cid": invalid_candidate_id},
        )
        assert len(decisions) == 0
