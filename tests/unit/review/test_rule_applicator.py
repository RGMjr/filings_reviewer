"""
Unit tests for E2 Rule Applicator.

Tests pattern loading, caching, filtering logic, and metric precedence.
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, MagicMock

from src.review.rule_applicator import RuleApplicator
from src.review.models import CandidateFeatures, LearnedPattern, ReviewCandidate


class TestRuleApplicatorInit:
    """Tests for RuleApplicator initialization."""

    @patch("src.review.rule_applicator.logger")
    def test_init_loads_patterns(self, mock_logger):
        """Test initialization loads patterns from database."""
        mock_db = Mock()
        mock_db.get_learned_patterns.return_value = [
            {
                "pattern_id": 1,
                "pattern_type": "reject_rule",
                "metric_id": None,
                "pattern_name": "Test Pattern",
                "pattern_description": "Description",
                "pattern_definition": {"conditions": [{"field": "test", "op": "eq", "value": True}]},
                "precision_score": 0.95,
                "recall_score": 0.80,
                "f1_score": 0.87,
                "sample_count": 50,
                "status": "approved",
                "approved_at": datetime.now(),
                "approved_by": "tester",
                "created_at": datetime.now(),
                "updated_at": datetime.now(),
            }
        ]

        applicator = RuleApplicator(mock_db)

        assert len(applicator._patterns) == 1
        assert applicator._last_reload is not None
        mock_db.get_learned_patterns.assert_called_once_with(status="approved")

    def test_init_with_custom_reload_interval(self):
        """Test initialization with custom reload interval."""
        mock_db = Mock()
        mock_db.get_learned_patterns.return_value = []

        applicator = RuleApplicator(mock_db, reload_interval_seconds=600)

        assert applicator.reload_interval == 600

    def test_init_with_invalid_reload_interval(self):
        """Test initialization fails with invalid reload interval."""
        mock_db = Mock()

        with pytest.raises(ValueError, match="reload_interval_seconds must be at least 1"):
            RuleApplicator(mock_db, reload_interval_seconds=0)

    @patch("src.review.rule_applicator.logger")
    def test_init_handles_db_error_gracefully(self, mock_logger):
        """Test initialization handles database errors gracefully."""
        mock_db = Mock()
        mock_db.get_learned_patterns.side_effect = Exception("Database connection failed")

        # Should not raise - just log warning and start with empty patterns
        applicator = RuleApplicator(mock_db)

        assert applicator._patterns == []
        assert applicator._last_reload is not None
        assert mock_logger.warning.called


class TestPatternLoading:
    """Tests for pattern loading and caching."""

    @patch("src.review.rule_applicator.logger")
    def test_reload_patterns_loads_from_db(self, mock_logger):
        """Test _reload_patterns loads patterns from database."""
        mock_db = Mock()
        pattern_data = {
            "pattern_id": 1,
            "pattern_type": "reject_rule",
            "metric_id": "annual_recurring_revenue",
            "pattern_name": "ARR: Exclude risk factors",
            "pattern_description": "Filter ARR in risk factors section",
            "pattern_definition": {"conditions": [{"field": "is_in_risk_factors", "op": "eq", "value": True}]},
            "precision_score": 0.92,
            "recall_score": 0.15,
            "f1_score": 0.26,
            "sample_count": 30,
            "status": "approved",
            "approved_at": datetime.now(),
            "approved_by": "human_reviewer",
            "created_at": datetime.now(),
            "updated_at": datetime.now(),
        }
        mock_db.get_learned_patterns.return_value = [pattern_data]

        applicator = RuleApplicator(mock_db)

        assert len(applicator._patterns) == 1
        pattern = applicator._patterns[0]
        assert pattern.pattern_name == "ARR: Exclude risk factors"
        assert pattern.metric_id == "annual_recurring_revenue"

    @patch("src.review.rule_applicator.logger")
    def test_reload_patterns_updates_timestamp(self, mock_logger):
        """Test _reload_patterns updates last_reload timestamp."""
        mock_db = Mock()
        mock_db.get_learned_patterns.return_value = []

        before = datetime.now()
        applicator = RuleApplicator(mock_db)
        after = datetime.now()

        assert applicator._last_reload is not None
        assert before <= applicator._last_reload <= after

    @patch("src.review.rule_applicator.logger")
    def test_reload_patterns_preserves_existing_on_error(self, mock_logger):
        """Test _reload_patterns keeps existing patterns if reload fails."""
        mock_db = Mock()
        pattern_data = {
            "pattern_id": 1,
            "pattern_type": "reject_rule",
            "metric_id": None,
            "pattern_name": "Existing Pattern",
            "pattern_description": None,
            "pattern_definition": {"conditions": []},
            "precision_score": 0.90,
            "recall_score": None,
            "f1_score": None,
            "sample_count": 10,
            "status": "approved",
            "approved_at": datetime.now(),
            "approved_by": None,
            "created_at": datetime.now(),
            "updated_at": datetime.now(),
        }
        mock_db.get_learned_patterns.return_value = [pattern_data]

        applicator = RuleApplicator(mock_db)
        assert len(applicator._patterns) == 1

        # Simulate database error on second call
        mock_db.get_learned_patterns.side_effect = Exception("Connection lost")

        # Force reload should not crash, should keep existing patterns
        applicator.force_reload()

        assert len(applicator._patterns) == 1  # Preserved
        assert applicator._patterns[0].pattern_name == "Existing Pattern"


class TestCacheManagement:
    """Tests for pattern cache expiration and reload."""

    @patch("src.review.rule_applicator.logger")
    def test_check_reload_reloads_if_expired(self, mock_logger):
        """Test _check_reload reloads patterns after cache expires."""
        mock_db = Mock()
        mock_db.get_learned_patterns.return_value = []

        applicator = RuleApplicator(mock_db, reload_interval_seconds=1)

        # Initial load
        assert mock_db.get_learned_patterns.call_count == 1

        # Simulate cache expiration by backdating last_reload
        applicator._last_reload = datetime.now() - timedelta(seconds=2)

        # Trigger check_reload
        applicator._check_reload()

        # Should have reloaded
        assert mock_db.get_learned_patterns.call_count == 2

    @patch("src.review.rule_applicator.logger")
    def test_check_reload_does_not_reload_if_fresh(self, mock_logger):
        """Test _check_reload does not reload if cache is fresh."""
        mock_db = Mock()
        mock_db.get_learned_patterns.return_value = []

        applicator = RuleApplicator(mock_db, reload_interval_seconds=300)

        # Initial load
        assert mock_db.get_learned_patterns.call_count == 1

        # Trigger check_reload immediately (cache is fresh)
        applicator._check_reload()

        # Should NOT have reloaded
        assert mock_db.get_learned_patterns.call_count == 1

    @patch("src.review.rule_applicator.logger")
    def test_force_reload_bypasses_cache(self, mock_logger):
        """Test force_reload bypasses cache expiration check."""
        mock_db = Mock()
        mock_db.get_learned_patterns.return_value = []

        applicator = RuleApplicator(mock_db)

        # Initial load
        assert mock_db.get_learned_patterns.call_count == 1

        # Force reload even though cache is fresh
        applicator.force_reload()

        # Should have reloaded
        assert mock_db.get_learned_patterns.call_count == 2


class TestShouldFilter:
    """Tests for candidate filtering logic."""

    @patch("src.review.rule_applicator.logger")
    def test_should_filter_matching_reject_pattern(self, mock_logger):
        """Test should_filter returns True for matching reject pattern."""
        mock_db = Mock()
        pattern_data = {
            "pattern_id": 1,
            "pattern_type": "reject_rule",
            "metric_id": None,
            "pattern_name": "Reject risk factors",
            "pattern_description": None,
            "pattern_definition": {"conditions": [{"field": "is_in_risk_factors", "op": "eq", "value": True}]},
            "precision_score": 0.95,
            "recall_score": None,
            "f1_score": None,
            "sample_count": 20,
            "status": "approved",
            "approved_at": datetime.now(),
            "approved_by": None,
            "created_at": datetime.now(),
            "updated_at": datetime.now(),
        }
        mock_db.get_learned_patterns.return_value = [pattern_data]

        applicator = RuleApplicator(mock_db)

        # Create candidate with features matching the pattern
        candidate = ReviewCandidate(
            candidate_id=1,
            filing_id=100,
            company_id=1,
            source_segment_id=500,
            char_position=1000,
            context_text="Risk Factors section...",
            raw_number_text="$1.2M",
            parsed_value=1200000,
            parsed_unit="dollars",
            triggering_keyword="revenue",
            keyword_distance=10,
            keyword_position="before",
            suggested_metric_id=None,
        )
        features = CandidateFeatures(
            keyword_distance=10,
            keyword_position="before",
            is_in_table=False,
            is_in_risk_factors=True,  # Matches pattern
            contains_definition_language=False,
            has_period_mention=False,
            number_format="currency",
        )

        should_filter, reason = applicator.should_filter(candidate, features)

        assert should_filter is True
        assert "Reject risk factors" in reason

    @patch("src.review.rule_applicator.logger")
    def test_should_not_filter_non_matching_pattern(self, mock_logger):
        """Test should_filter returns False for non-matching pattern."""
        mock_db = Mock()
        pattern_data = {
            "pattern_id": 1,
            "pattern_type": "reject_rule",
            "metric_id": None,
            "pattern_name": "Reject risk factors",
            "pattern_description": None,
            "pattern_definition": {"conditions": [{"field": "is_in_risk_factors", "op": "eq", "value": True}]},
            "precision_score": 0.95,
            "recall_score": None,
            "f1_score": None,
            "sample_count": 20,
            "status": "approved",
            "approved_at": datetime.now(),
            "approved_by": None,
            "created_at": datetime.now(),
            "updated_at": datetime.now(),
        }
        mock_db.get_learned_patterns.return_value = [pattern_data]

        applicator = RuleApplicator(mock_db)

        candidate = ReviewCandidate(
            candidate_id=1,
            filing_id=100,
            company_id=1,
            source_segment_id=500,
            char_position=1000,
            context_text="Business Overview section...",
            raw_number_text="$1.2M",
            parsed_value=1200000,
            parsed_unit="dollars",
            triggering_keyword="revenue",
            keyword_distance=10,
            keyword_position="before",
            suggested_metric_id=None,
        )
        features = CandidateFeatures(
            keyword_distance=10,
            keyword_position="before",
            is_in_table=False,
            is_in_risk_factors=False,  # Does NOT match pattern
            contains_definition_language=False,
            has_period_mention=False,
            number_format="currency",
        )

        should_filter, reason = applicator.should_filter(candidate, features)

        assert should_filter is False
        assert reason is None

    @patch("src.review.rule_applicator.logger")
    def test_should_filter_metric_specific_precedence(self, mock_logger):
        """Test metric-specific patterns checked before global patterns."""
        mock_db = Mock()
        # Create two patterns: one metric-specific, one global
        metric_pattern = {
            "pattern_id": 1,
            "pattern_type": "reject_rule",
            "metric_id": "annual_recurring_revenue",  # Metric-specific
            "pattern_name": "ARR specific rule",
            "pattern_description": None,
            "pattern_definition": {"conditions": [{"field": "keyword_distance", "op": "gt", "value": 50}]},
            "precision_score": 0.90,
            "recall_score": None,
            "f1_score": None,
            "sample_count": 10,
            "status": "approved",
            "approved_at": datetime.now(),
            "approved_by": None,
            "created_at": datetime.now(),
            "updated_at": datetime.now(),
        }
        global_pattern = {
            "pattern_id": 2,
            "pattern_type": "reject_rule",
            "metric_id": None,  # Global pattern
            "pattern_name": "Global rule",
            "pattern_description": None,
            "pattern_definition": {"conditions": [{"field": "is_in_risk_factors", "op": "eq", "value": True}]},
            "precision_score": 0.85,
            "recall_score": None,
            "f1_score": None,
            "sample_count": 20,
            "status": "approved",
            "approved_at": datetime.now(),
            "approved_by": None,
            "created_at": datetime.now(),
            "updated_at": datetime.now(),
        }
        mock_db.get_learned_patterns.return_value = [global_pattern, metric_pattern]

        applicator = RuleApplicator(mock_db)

        candidate = ReviewCandidate(
            candidate_id=1,
            filing_id=100,
            company_id=1,
            source_segment_id=500,
            char_position=1000,
            context_text="Context...",
            raw_number_text="$1.2M",
            parsed_value=1200000,
            parsed_unit="dollars",
            triggering_keyword="revenue",
            keyword_distance=60,  # Matches metric-specific rule
            keyword_position="before",
            suggested_metric_id="annual_recurring_revenue",
        )
        features = CandidateFeatures(
            keyword_distance=60,
            keyword_position="before",
            is_in_table=False,
            is_in_risk_factors=False,
            contains_definition_language=False,
            has_period_mention=False,
            number_format="currency",
        )

        should_filter, reason = applicator.should_filter(candidate, features)

        # Should match metric-specific rule, not global rule
        assert should_filter is True
        assert "ARR specific rule" in reason

    @patch("src.review.rule_applicator.logger")
    def test_should_filter_ignores_accept_patterns(self, mock_logger):
        """Test should_filter ignores accept_rule patterns (only uses reject_rule)."""
        mock_db = Mock()
        pattern_data = {
            "pattern_id": 1,
            "pattern_type": "accept_rule",  # Accept pattern, not reject
            "metric_id": None,
            "pattern_name": "Accept rule",
            "pattern_description": None,
            "pattern_definition": {"conditions": [{"field": "is_in_risk_factors", "op": "eq", "value": True}]},
            "precision_score": 0.95,
            "recall_score": None,
            "f1_score": None,
            "sample_count": 20,
            "status": "approved",
            "approved_at": datetime.now(),
            "approved_by": None,
            "created_at": datetime.now(),
            "updated_at": datetime.now(),
        }
        mock_db.get_learned_patterns.return_value = [pattern_data]

        applicator = RuleApplicator(mock_db)

        candidate = ReviewCandidate(
            candidate_id=1,
            filing_id=100,
            company_id=1,
            source_segment_id=500,
            char_position=1000,
            context_text="Context...",
            raw_number_text="$1.2M",
            parsed_value=1200000,
            parsed_unit="dollars",
            triggering_keyword="revenue",
            keyword_distance=10,
            keyword_position="before",
            suggested_metric_id=None,
        )
        features = CandidateFeatures(
            keyword_distance=10,
            keyword_position="before",
            is_in_table=False,
            is_in_risk_factors=True,  # Matches accept pattern
            contains_definition_language=False,
            has_period_mention=False,
            number_format="currency",
        )

        should_filter, reason = applicator.should_filter(candidate, features)

        # Should NOT filter (accept patterns not applied in should_filter)
        assert should_filter is False
        assert reason is None

    @patch("src.review.rule_applicator.logger")
    def test_should_filter_with_no_patterns(self, mock_logger):
        """Test should_filter returns False when no patterns loaded."""
        mock_db = Mock()
        mock_db.get_learned_patterns.return_value = []

        applicator = RuleApplicator(mock_db)

        candidate = ReviewCandidate(
            candidate_id=1,
            filing_id=100,
            company_id=1,
            source_segment_id=500,
            char_position=1000,
            context_text="Context...",
            raw_number_text="$1.2M",
            parsed_value=1200000,
            parsed_unit="dollars",
            triggering_keyword="revenue",
            keyword_distance=10,
            keyword_position="before",
            suggested_metric_id=None,
        )
        features = CandidateFeatures(
            keyword_distance=10,
            keyword_position="before",
            is_in_table=False,
            is_in_risk_factors=False,
            contains_definition_language=False,
            has_period_mention=False,
            number_format="currency",
        )

        should_filter, reason = applicator.should_filter(candidate, features)

        assert should_filter is False
        assert reason is None


class TestGetStats:
    """Tests for statistics reporting."""

    @patch("src.review.rule_applicator.logger")
    def test_get_stats_returns_pattern_counts(self, mock_logger):
        """Test get_stats returns correct pattern type counts."""
        mock_db = Mock()
        patterns = [
            {
                "pattern_id": 1,
                "pattern_type": "reject_rule",
                "metric_id": None,
                "pattern_name": "Reject 1",
                "pattern_description": None,
                "pattern_definition": {"conditions": []},
                "precision_score": 0.90,
                "recall_score": None,
                "f1_score": None,
                "sample_count": 10,
                "status": "approved",
                "approved_at": datetime.now(),
                "approved_by": None,
                "created_at": datetime.now(),
                "updated_at": datetime.now(),
            },
            {
                "pattern_id": 2,
                "pattern_type": "reject_rule",
                "metric_id": None,
                "pattern_name": "Reject 2",
                "pattern_description": None,
                "pattern_definition": {"conditions": []},
                "precision_score": 0.85,
                "recall_score": None,
                "f1_score": None,
                "sample_count": 15,
                "status": "approved",
                "approved_at": datetime.now(),
                "approved_by": None,
                "created_at": datetime.now(),
                "updated_at": datetime.now(),
            },
            {
                "pattern_id": 3,
                "pattern_type": "accept_rule",
                "metric_id": None,
                "pattern_name": "Accept 1",
                "pattern_description": None,
                "pattern_definition": {"conditions": []},
                "precision_score": 0.92,
                "recall_score": None,
                "f1_score": None,
                "sample_count": 8,
                "status": "approved",
                "approved_at": datetime.now(),
                "approved_by": None,
                "created_at": datetime.now(),
                "updated_at": datetime.now(),
            },
            {
                "pattern_id": 4,
                "pattern_type": "feature_weight",
                "metric_id": None,
                "pattern_name": "Weight 1",
                "pattern_description": None,
                "pattern_definition": {"weights": {}},
                "precision_score": None,
                "recall_score": None,
                "f1_score": None,
                "sample_count": 50,
                "status": "approved",
                "approved_at": datetime.now(),
                "approved_by": None,
                "created_at": datetime.now(),
                "updated_at": datetime.now(),
            },
        ]
        mock_db.get_learned_patterns.return_value = patterns

        applicator = RuleApplicator(mock_db)
        stats = applicator.get_stats()

        assert stats["total_patterns"] == 4
        assert stats["reject_patterns"] == 2
        assert stats["accept_patterns"] == 1
        assert stats["feature_weight_patterns"] == 1
        assert stats["last_reload"] is not None
        assert stats["cache_age_seconds"] is not None
        assert stats["cache_age_seconds"] >= 0

    @patch("src.review.rule_applicator.logger")
    def test_get_stats_with_no_patterns(self, mock_logger):
        """Test get_stats with no patterns loaded."""
        mock_db = Mock()
        mock_db.get_learned_patterns.return_value = []

        applicator = RuleApplicator(mock_db)
        stats = applicator.get_stats()

        assert stats["total_patterns"] == 0
        assert stats["reject_patterns"] == 0
        assert stats["accept_patterns"] == 0
        assert stats["feature_weight_patterns"] == 0

    @patch("src.review.rule_applicator.logger")
    def test_get_stats_triggers_cache_check(self, mock_logger):
        """Test get_stats triggers cache expiration check."""
        mock_db = Mock()
        mock_db.get_learned_patterns.return_value = []

        applicator = RuleApplicator(mock_db, reload_interval_seconds=1)

        # Initial load
        assert mock_db.get_learned_patterns.call_count == 1

        # Simulate cache expiration
        applicator._last_reload = datetime.now() - timedelta(seconds=2)

        # get_stats should trigger reload
        stats = applicator.get_stats()

        # Should have reloaded
        assert mock_db.get_learned_patterns.call_count == 2
