"""
Unit tests for review data models.

Tests validation, serialization, and business rules for:
- CandidateFeatures
- ReviewCandidate
- ReviewDecision
- LearnedPattern
"""

from decimal import Decimal
from datetime import datetime

import pytest

from src.review.models import (
    CandidateFeatures,
    ReviewCandidate,
    ReviewDecision,
    LearnedPattern,
    KEYWORD_POSITIONS,
    NUMBER_FORMATS,
    REVIEW_STATUSES,
    DECISION_TYPES,
    REJECTION_CATEGORIES,
    PATTERN_TYPES,
    PATTERN_STATUSES,
)


class TestCandidateFeatures:
    """Tests for CandidateFeatures dataclass."""

    def test_create_valid_features(self):
        """Should create features with valid values."""
        features = CandidateFeatures(
            keyword_distance=25,
            keyword_position="before",
            is_in_table=True,
            is_in_risk_factors=False,
            contains_definition_language=True,
            has_period_mention=True,
            number_format="integer",
            value_magnitude=4.5,
            surrounding_numbers_count=3,
        )

        assert features.keyword_distance == 25
        assert features.keyword_position == "before"
        assert features.is_in_table is True
        assert features.number_format == "integer"
        assert features.value_magnitude == 4.5

    def test_invalid_keyword_position_raises(self):
        """Should raise ValueError for invalid keyword_position."""
        with pytest.raises(ValueError, match="Invalid keyword_position"):
            CandidateFeatures(
                keyword_distance=10,
                keyword_position="invalid",
                is_in_table=False,
                is_in_risk_factors=False,
                contains_definition_language=False,
                has_period_mention=False,
                number_format="integer",
            )

    def test_invalid_number_format_raises(self):
        """Should raise ValueError for invalid number_format."""
        with pytest.raises(ValueError, match="Invalid number_format"):
            CandidateFeatures(
                keyword_distance=10,
                keyword_position="after",
                is_in_table=False,
                is_in_risk_factors=False,
                contains_definition_language=False,
                has_period_mention=False,
                number_format="invalid_format",
            )

    def test_to_dict(self):
        """Should convert to dictionary for JSONB storage."""
        features = CandidateFeatures(
            keyword_distance=25,
            keyword_position="after",
            is_in_table=True,
            is_in_risk_factors=False,
            contains_definition_language=True,
            has_period_mention=False,
            number_format="currency",
            value_magnitude=6.0,
            surrounding_numbers_count=2,
            section_name="Use of Proceeds",
            context_word_count=45,
        )

        d = features.to_dict()

        assert d["keyword_distance"] == 25
        assert d["keyword_position"] == "after"
        assert d["is_in_table"] is True
        assert d["number_format"] == "currency"
        assert d["section_name"] == "Use of Proceeds"
        assert d["context_word_count"] == 45

    def test_from_dict(self):
        """Should create from dictionary (JSONB)."""
        data = {
            "keyword_distance": 15,
            "keyword_position": "before",
            "is_in_table": False,
            "is_in_risk_factors": True,
            "contains_definition_language": False,
            "has_period_mention": True,
            "number_format": "percentage",
            "value_magnitude": 2.0,
            "surrounding_numbers_count": 5,
        }

        features = CandidateFeatures.from_dict(data)

        assert features.keyword_distance == 15
        assert features.keyword_position == "before"
        assert features.is_in_risk_factors is True
        assert features.number_format == "percentage"

    def test_from_dict_with_defaults(self):
        """Should use defaults for missing optional fields."""
        data = {
            "keyword_distance": 10,
            "keyword_position": "after",
        }

        features = CandidateFeatures.from_dict(data)

        assert features.keyword_distance == 10
        assert features.is_in_table is False  # default
        assert features.number_format == "integer"  # default
        assert features.value_magnitude is None  # default
        assert features.surrounding_numbers_count == 0  # default

    def test_from_dict_empty_uses_all_defaults(self):
        """Should handle empty dict by using all defaults."""
        features = CandidateFeatures.from_dict({})

        assert features.keyword_distance == 0
        assert features.keyword_position == "after"
        assert features.number_format == "integer"


class TestReviewCandidate:
    """Tests for ReviewCandidate dataclass."""

    def test_create_minimal_candidate(self):
        """Should create candidate with required fields only."""
        candidate = ReviewCandidate(
            filing_id=1,
            company_id=2,
            char_position=100,
            context_text="We have 10,000 active customers.",
            raw_number_text="10,000",
            triggering_keyword="customers",
            keyword_distance=20,
            keyword_position="after",
        )

        assert candidate.filing_id == 1
        assert candidate.company_id == 2
        assert candidate.char_position == 100
        assert candidate.review_status == "pending"  # default
        assert candidate.candidate_id is None  # not yet in DB

    def test_create_full_candidate(self):
        """Should create candidate with all optional fields."""
        features = CandidateFeatures(
            keyword_distance=20,
            keyword_position="after",
            is_in_table=False,
            is_in_risk_factors=False,
            contains_definition_language=True,
            has_period_mention=True,
            number_format="integer",
        )

        candidate = ReviewCandidate(
            filing_id=1,
            company_id=2,
            char_position=100,
            context_text="We have 10,000 active customers.",
            raw_number_text="10,000",
            triggering_keyword="customers",
            keyword_distance=20,
            keyword_position="after",
            source_segment_id=5,
            parsed_value=Decimal("10000"),
            parsed_unit="count",
            suggested_metric_id="active_customers",
            suggestion_confidence=0.85,
            features=features,
            review_batch_id=1,
        )

        assert candidate.parsed_value == Decimal("10000")
        assert candidate.suggestion_confidence == 0.85
        assert candidate.features.contains_definition_language is True

    def test_invalid_keyword_position_raises(self):
        """Should raise ValueError for invalid keyword_position."""
        with pytest.raises(ValueError, match="Invalid keyword_position"):
            ReviewCandidate(
                filing_id=1,
                company_id=2,
                char_position=100,
                context_text="Test",
                raw_number_text="100",
                triggering_keyword="test",
                keyword_distance=10,
                keyword_position="invalid",
            )

    def test_invalid_review_status_raises(self):
        """Should raise ValueError for invalid review_status."""
        with pytest.raises(ValueError, match="Invalid review_status"):
            ReviewCandidate(
                filing_id=1,
                company_id=2,
                char_position=100,
                context_text="Test",
                raw_number_text="100",
                triggering_keyword="test",
                keyword_distance=10,
                keyword_position="after",
                review_status="invalid_status",
            )

    def test_invalid_confidence_raises(self):
        """Should raise ValueError for confidence outside 0-1."""
        with pytest.raises(ValueError, match="suggestion_confidence must be between"):
            ReviewCandidate(
                filing_id=1,
                company_id=2,
                char_position=100,
                context_text="Test",
                raw_number_text="100",
                triggering_keyword="test",
                keyword_distance=10,
                keyword_position="after",
                suggestion_confidence=1.5,
            )

    def test_confidence_boundary_values(self):
        """Should accept confidence at boundaries (0 and 1)."""
        candidate_zero = ReviewCandidate(
            filing_id=1,
            company_id=2,
            char_position=100,
            context_text="Test",
            raw_number_text="100",
            triggering_keyword="test",
            keyword_distance=10,
            keyword_position="after",
            suggestion_confidence=0.0,
        )
        assert candidate_zero.suggestion_confidence == 0.0

        candidate_one = ReviewCandidate(
            filing_id=1,
            company_id=2,
            char_position=100,
            context_text="Test",
            raw_number_text="100",
            triggering_keyword="test",
            keyword_distance=10,
            keyword_position="after",
            suggestion_confidence=1.0,
        )
        assert candidate_one.suggestion_confidence == 1.0

    def test_to_dict(self):
        """Should convert to dictionary for database insertion."""
        candidate = ReviewCandidate(
            filing_id=1,
            company_id=2,
            char_position=100,
            context_text="Test context",
            raw_number_text="100",
            triggering_keyword="test",
            keyword_distance=10,
            keyword_position="before",
            parsed_value=Decimal("100"),
            suggested_metric_id="test_metric",
        )

        d = candidate.to_dict()

        assert d["filing_id"] == 1
        assert d["company_id"] == 2
        assert d["char_position"] == 100
        assert d["keyword_position"] == "before"
        assert d["parsed_value"] == Decimal("100")
        assert d["features"] is None  # not set

    def test_to_dict_with_features(self):
        """Should serialize features to dict."""
        features = CandidateFeatures(
            keyword_distance=10,
            keyword_position="after",
            is_in_table=True,
            is_in_risk_factors=False,
            contains_definition_language=False,
            has_period_mention=False,
            number_format="integer",
        )

        candidate = ReviewCandidate(
            filing_id=1,
            company_id=2,
            char_position=100,
            context_text="Test",
            raw_number_text="100",
            triggering_keyword="test",
            keyword_distance=10,
            keyword_position="after",
            features=features,
        )

        d = candidate.to_dict()
        assert d["features"]["is_in_table"] is True

    def test_from_row(self):
        """Should create from database row."""
        row = {
            "candidate_id": 1,
            "filing_id": 10,
            "company_id": 20,
            "source_segment_id": 5,
            "char_position": 100,
            "context_text": "Test context",
            "raw_number_text": "1000",
            "parsed_value": Decimal("1000"),
            "parsed_unit": "count",
            "triggering_keyword": "customers",
            "keyword_distance": 15,
            "keyword_position": "after",
            "suggested_metric_id": "active_customers",
            "suggestion_confidence": Decimal("0.9"),
            "features": {"is_in_table": True, "keyword_distance": 15},
            "review_status": "reviewed",
            "review_batch_id": 1,
            "created_at": datetime(2024, 1, 15),
            "updated_at": datetime(2024, 1, 16),
        }

        candidate = ReviewCandidate.from_row(row)

        assert candidate.candidate_id == 1
        assert candidate.filing_id == 10
        assert candidate.parsed_value == Decimal("1000")
        assert candidate.features.is_in_table is True
        assert candidate.review_status == "reviewed"
        assert candidate.created_at == datetime(2024, 1, 15)

    def test_from_row_without_features(self):
        """Should handle row without features."""
        row = {
            "filing_id": 10,
            "company_id": 20,
            "char_position": 100,
            "context_text": "Test",
            "raw_number_text": "100",
            "triggering_keyword": "test",
            "keyword_distance": 10,
            "keyword_position": "after",
            "features": None,
        }

        candidate = ReviewCandidate.from_row(row)
        assert candidate.features is None


class TestReviewDecision:
    """Tests for ReviewDecision dataclass."""

    def test_create_accept_decision(self):
        """Should create accept decision with required metric."""
        decision = ReviewDecision(
            candidate_id=1,
            decision="accept",
            assigned_metric_id="active_customers",
        )

        assert decision.decision == "accept"
        assert decision.assigned_metric_id == "active_customers"

    def test_create_reject_decision(self):
        """Should create reject decision with reason."""
        decision = ReviewDecision(
            candidate_id=1,
            decision="reject",
            rejection_reason="This is revenue, not customers",
            rejection_category="wrong_metric",
        )

        assert decision.decision == "reject"
        assert decision.rejection_category == "wrong_metric"

    def test_create_reclassify_decision(self):
        """Should create reclassify decision with new metric."""
        decision = ReviewDecision(
            candidate_id=1,
            decision="reclassify",
            assigned_metric_id="total_customers",
            reviewer_notes="Actually total, not active",
        )

        assert decision.decision == "reclassify"
        assert decision.assigned_metric_id == "total_customers"

    def test_invalid_decision_raises(self):
        """Should raise ValueError for invalid decision type."""
        with pytest.raises(ValueError, match="Invalid decision"):
            ReviewDecision(
                candidate_id=1,
                decision="invalid_decision",
            )

    def test_invalid_rejection_category_raises(self):
        """Should raise ValueError for invalid rejection category."""
        with pytest.raises(ValueError, match="Invalid rejection_category"):
            ReviewDecision(
                candidate_id=1,
                decision="reject",
                rejection_category="invalid_category",
            )

    def test_accept_without_metric_raises(self):
        """Should raise ValueError when accept has no metric."""
        with pytest.raises(ValueError, match="requires assigned_metric_id"):
            ReviewDecision(
                candidate_id=1,
                decision="accept",
                # missing assigned_metric_id
            )

    def test_reclassify_without_metric_raises(self):
        """Should raise ValueError when reclassify has no metric."""
        with pytest.raises(ValueError, match="requires assigned_metric_id"):
            ReviewDecision(
                candidate_id=1,
                decision="reclassify",
                # missing assigned_metric_id
            )

    def test_rejection_category_on_non_reject_raises(self):
        """Should raise ValueError when rejection_category on non-reject."""
        with pytest.raises(ValueError, match="rejection_category should only be set"):
            ReviewDecision(
                candidate_id=1,
                decision="accept",
                assigned_metric_id="test",
                rejection_category="wrong_metric",
            )

    def test_reject_allows_no_category(self):
        """Should allow reject without category (optional)."""
        decision = ReviewDecision(
            candidate_id=1,
            decision="reject",
            rejection_reason="Just wrong",
            # rejection_category is optional
        )

        assert decision.rejection_category is None

    def test_to_dict(self):
        """Should convert to dictionary for database insertion."""
        decision = ReviewDecision(
            candidate_id=1,
            decision="accept",
            assigned_metric_id="active_customers",
            reviewer_notes="Clear match",
            review_time_seconds=12,
        )

        d = decision.to_dict()

        assert d["candidate_id"] == 1
        assert d["decision"] == "accept"
        assert d["assigned_metric_id"] == "active_customers"
        assert d["review_time_seconds"] == 12

    def test_from_row(self):
        """Should create from database row."""
        row = {
            "decision_id": 1,
            "candidate_id": 10,
            "decision": "reject",
            "assigned_metric_id": None,
            "rejection_reason": "Not a metric",
            "rejection_category": "not_a_metric",
            "reviewer_notes": None,
            "review_time_seconds": 5,
            "created_at": datetime(2024, 1, 15),
        }

        decision = ReviewDecision.from_row(row)

        assert decision.decision_id == 1
        assert decision.candidate_id == 10
        assert decision.decision == "reject"
        assert decision.rejection_category == "not_a_metric"


class TestLearnedPattern:
    """Tests for LearnedPattern dataclass."""

    def test_create_accept_rule(self):
        """Should create accept rule pattern."""
        pattern = LearnedPattern(
            pattern_type="accept_rule",
            pattern_name="Close keyword with definition",
            pattern_definition={
                "conditions": [
                    {"field": "keyword_distance", "op": "lt", "value": 30},
                    {"field": "contains_definition_language", "op": "eq", "value": True},
                ],
                "logic": "and",
            },
            precision_score=0.95,
            recall_score=0.60,
        )

        assert pattern.pattern_type == "accept_rule"
        assert pattern.status == "candidate"  # default
        assert pattern.precision_score == 0.95

    def test_create_reject_rule(self):
        """Should create reject rule pattern."""
        pattern = LearnedPattern(
            pattern_type="reject_rule",
            pattern_name="Risk factors far keyword",
            pattern_definition={
                "conditions": [
                    {"field": "is_in_risk_factors", "op": "eq", "value": True},
                    {"field": "keyword_distance", "op": "gt", "value": 50},
                ],
                "logic": "and",
            },
            metric_id=None,  # global pattern
        )

        assert pattern.pattern_type == "reject_rule"
        assert pattern.metric_id is None

    def test_invalid_pattern_type_raises(self):
        """Should raise ValueError for invalid pattern type."""
        with pytest.raises(ValueError, match="Invalid pattern_type"):
            LearnedPattern(
                pattern_type="invalid_type",
                pattern_name="Test",
                pattern_definition={},
            )

    def test_invalid_status_raises(self):
        """Should raise ValueError for invalid status."""
        with pytest.raises(ValueError, match="Invalid status"):
            LearnedPattern(
                pattern_type="accept_rule",
                pattern_name="Test",
                pattern_definition={},
                status="invalid_status",
            )

    def test_invalid_precision_raises(self):
        """Should raise ValueError for precision outside 0-1."""
        with pytest.raises(ValueError, match="precision_score must be between"):
            LearnedPattern(
                pattern_type="accept_rule",
                pattern_name="Test",
                pattern_definition={},
                precision_score=1.5,
            )

    def test_invalid_recall_raises(self):
        """Should raise ValueError for recall outside 0-1."""
        with pytest.raises(ValueError, match="recall_score must be between"):
            LearnedPattern(
                pattern_type="accept_rule",
                pattern_name="Test",
                pattern_definition={},
                recall_score=-0.1,
            )

    def test_score_boundary_values(self):
        """Should accept scores at boundaries."""
        pattern = LearnedPattern(
            pattern_type="accept_rule",
            pattern_name="Test",
            pattern_definition={},
            precision_score=0.0,
            recall_score=1.0,
            f1_score=0.5,
        )

        assert pattern.precision_score == 0.0
        assert pattern.recall_score == 1.0

    def test_to_dict(self):
        """Should convert to dictionary for database insertion."""
        pattern = LearnedPattern(
            pattern_type="reject_rule",
            pattern_name="Test pattern",
            pattern_definition={"conditions": [], "logic": "and"},
            metric_id="active_customers",
            precision_score=0.90,
            sample_count=50,
        )

        d = pattern.to_dict()

        assert d["pattern_type"] == "reject_rule"
        assert d["pattern_name"] == "Test pattern"
        assert d["metric_id"] == "active_customers"
        assert d["precision_score"] == 0.90

    def test_from_row(self):
        """Should create from database row."""
        row = {
            "pattern_id": 1,
            "pattern_type": "accept_rule",
            "metric_id": "active_customers",
            "pattern_name": "Test pattern",
            "pattern_description": "A test pattern",
            "pattern_definition": {"conditions": [], "logic": "and"},
            "precision_score": Decimal("0.95"),
            "recall_score": Decimal("0.80"),
            "f1_score": Decimal("0.87"),
            "sample_count": 100,
            "status": "approved",
            "approved_at": datetime(2024, 1, 15),
            "approved_by": "admin",
            "created_at": datetime(2024, 1, 10),
            "updated_at": datetime(2024, 1, 15),
        }

        pattern = LearnedPattern.from_row(row)

        assert pattern.pattern_id == 1
        assert pattern.status == "approved"
        assert pattern.approved_by == "admin"


class TestLearnedPatternMatches:
    """Tests for LearnedPattern.matches() method."""

    def test_matches_eq_operator(self):
        """Should match equality condition."""
        pattern = LearnedPattern(
            pattern_type="reject_rule",
            pattern_name="In risk factors",
            pattern_definition={
                "conditions": [
                    {"field": "is_in_risk_factors", "op": "eq", "value": True},
                ],
                "logic": "and",
            },
        )

        features_match = CandidateFeatures(
            keyword_distance=10,
            keyword_position="after",
            is_in_table=False,
            is_in_risk_factors=True,
            contains_definition_language=False,
            has_period_mention=False,
            number_format="integer",
        )

        features_no_match = CandidateFeatures(
            keyword_distance=10,
            keyword_position="after",
            is_in_table=False,
            is_in_risk_factors=False,
            contains_definition_language=False,
            has_period_mention=False,
            number_format="integer",
        )

        assert pattern.matches(features_match) is True
        assert pattern.matches(features_no_match) is False

    def test_matches_gt_operator(self):
        """Should match greater-than condition."""
        pattern = LearnedPattern(
            pattern_type="reject_rule",
            pattern_name="Far keyword",
            pattern_definition={
                "conditions": [
                    {"field": "keyword_distance", "op": "gt", "value": 50},
                ],
                "logic": "and",
            },
        )

        features_far = CandidateFeatures(
            keyword_distance=60,
            keyword_position="after",
            is_in_table=False,
            is_in_risk_factors=False,
            contains_definition_language=False,
            has_period_mention=False,
            number_format="integer",
        )

        features_close = CandidateFeatures(
            keyword_distance=30,
            keyword_position="after",
            is_in_table=False,
            is_in_risk_factors=False,
            contains_definition_language=False,
            has_period_mention=False,
            number_format="integer",
        )

        assert pattern.matches(features_far) is True
        assert pattern.matches(features_close) is False

    def test_matches_and_logic(self):
        """Should require all conditions with AND logic."""
        pattern = LearnedPattern(
            pattern_type="reject_rule",
            pattern_name="Risk + far",
            pattern_definition={
                "conditions": [
                    {"field": "is_in_risk_factors", "op": "eq", "value": True},
                    {"field": "keyword_distance", "op": "gt", "value": 50},
                ],
                "logic": "and",
            },
        )

        # Both conditions true
        features_both = CandidateFeatures(
            keyword_distance=60,
            keyword_position="after",
            is_in_table=False,
            is_in_risk_factors=True,
            contains_definition_language=False,
            has_period_mention=False,
            number_format="integer",
        )

        # Only one condition true
        features_one = CandidateFeatures(
            keyword_distance=60,
            keyword_position="after",
            is_in_table=False,
            is_in_risk_factors=False,
            contains_definition_language=False,
            has_period_mention=False,
            number_format="integer",
        )

        assert pattern.matches(features_both) is True
        assert pattern.matches(features_one) is False

    def test_matches_or_logic(self):
        """Should require any condition with OR logic."""
        pattern = LearnedPattern(
            pattern_type="accept_rule",
            pattern_name="Definition or table",
            pattern_definition={
                "conditions": [
                    {"field": "contains_definition_language", "op": "eq", "value": True},
                    {"field": "is_in_table", "op": "eq", "value": True},
                ],
                "logic": "or",
            },
        )

        # One condition true
        features_def = CandidateFeatures(
            keyword_distance=10,
            keyword_position="after",
            is_in_table=False,
            is_in_risk_factors=False,
            contains_definition_language=True,
            has_period_mention=False,
            number_format="integer",
        )

        # Neither condition true
        features_neither = CandidateFeatures(
            keyword_distance=10,
            keyword_position="after",
            is_in_table=False,
            is_in_risk_factors=False,
            contains_definition_language=False,
            has_period_mention=False,
            number_format="integer",
        )

        assert pattern.matches(features_def) is True
        assert pattern.matches(features_neither) is False

    def test_matches_in_operator(self):
        """Should match value in list."""
        pattern = LearnedPattern(
            pattern_type="accept_rule",
            pattern_name="Number or currency",
            pattern_definition={
                "conditions": [
                    {"field": "number_format", "op": "in", "value": ["integer", "currency"]},
                ],
                "logic": "and",
            },
        )

        features_int = CandidateFeatures(
            keyword_distance=10,
            keyword_position="after",
            is_in_table=False,
            is_in_risk_factors=False,
            contains_definition_language=False,
            has_period_mention=False,
            number_format="integer",
        )

        features_pct = CandidateFeatures(
            keyword_distance=10,
            keyword_position="after",
            is_in_table=False,
            is_in_risk_factors=False,
            contains_definition_language=False,
            has_period_mention=False,
            number_format="percentage",
        )

        assert pattern.matches(features_int) is True
        assert pattern.matches(features_pct) is False

    def test_matches_empty_conditions_returns_false(self):
        """Should return False for empty conditions."""
        pattern = LearnedPattern(
            pattern_type="accept_rule",
            pattern_name="Empty",
            pattern_definition={"conditions": [], "logic": "and"},
        )

        features = CandidateFeatures(
            keyword_distance=10,
            keyword_position="after",
            is_in_table=False,
            is_in_risk_factors=False,
            contains_definition_language=False,
            has_period_mention=False,
            number_format="integer",
        )

        assert pattern.matches(features) is False

    def test_matches_lte_operator(self):
        """Should match less-than-or-equal condition."""
        pattern = LearnedPattern(
            pattern_type="accept_rule",
            pattern_name="Close keyword",
            pattern_definition={
                "conditions": [
                    {"field": "keyword_distance", "op": "lte", "value": 20},
                ],
                "logic": "and",
            },
        )

        features_exact = CandidateFeatures(
            keyword_distance=20,
            keyword_position="after",
            is_in_table=False,
            is_in_risk_factors=False,
            contains_definition_language=False,
            has_period_mention=False,
            number_format="integer",
        )

        features_over = CandidateFeatures(
            keyword_distance=21,
            keyword_position="after",
            is_in_table=False,
            is_in_risk_factors=False,
            contains_definition_language=False,
            has_period_mention=False,
            number_format="integer",
        )

        assert pattern.matches(features_exact) is True
        assert pattern.matches(features_over) is False


class TestEnumerationConstants:
    """Tests for enumeration constants alignment with schema."""

    def test_keyword_positions(self):
        """Should have valid keyword positions."""
        assert "before" in KEYWORD_POSITIONS
        assert "after" in KEYWORD_POSITIONS
        assert len(KEYWORD_POSITIONS) == 2

    def test_number_formats(self):
        """Should have valid number formats."""
        assert "integer" in NUMBER_FORMATS
        assert "decimal" in NUMBER_FORMATS
        assert "percentage" in NUMBER_FORMATS
        assert "currency" in NUMBER_FORMATS

    def test_review_statuses(self):
        """Should match SQL CHECK constraint."""
        assert "pending" in REVIEW_STATUSES
        assert "in_progress" in REVIEW_STATUSES
        assert "reviewed" in REVIEW_STATUSES
        assert "skipped" in REVIEW_STATUSES

    def test_decision_types(self):
        """Should match SQL CHECK constraint."""
        assert "accept" in DECISION_TYPES
        assert "reject" in DECISION_TYPES
        assert "reclassify" in DECISION_TYPES

    def test_rejection_categories(self):
        """Should match SQL CHECK constraint."""
        assert "wrong_metric" in REJECTION_CATEGORIES
        assert "not_a_metric" in REJECTION_CATEGORIES
        assert "wrong_value" in REJECTION_CATEGORIES
        assert "wrong_period" in REJECTION_CATEGORIES
        assert "duplicate" in REJECTION_CATEGORIES
        assert "other" in REJECTION_CATEGORIES

    def test_pattern_types(self):
        """Should match SQL CHECK constraint."""
        assert "accept_rule" in PATTERN_TYPES
        assert "reject_rule" in PATTERN_TYPES
        assert "feature_weight" in PATTERN_TYPES

    def test_pattern_statuses(self):
        """Should match SQL CHECK constraint."""
        assert "candidate" in PATTERN_STATUSES
        assert "approved" in PATTERN_STATUSES
        assert "rejected" in PATTERN_STATUSES
        assert "deprecated" in PATTERN_STATUSES
