"""
Unit tests for the deduplicator module.

Tests the standalone deduplicate_candidates() function directly,
independent of CandidateGenerator.
"""

from decimal import Decimal

from src.review.deduplicator import deduplicate_candidates
from src.review.models import CandidateFeatures, ReviewCandidate


class TestDeduplicateCandidatesImport:
    """Test import paths for deduplicate_candidates."""

    def test_import_from_deduplicator_module(self):
        """Should be importable from src.review.deduplicator."""
        from src.review.deduplicator import deduplicate_candidates as fn
        assert callable(fn)

    def test_import_from_review_package(self):
        """Should be importable from src.review (public API)."""
        from src.review import deduplicate_candidates as fn
        assert callable(fn)


class TestDeduplicateCandidatesBasic:
    """Basic functionality tests for deduplicate_candidates."""

    @staticmethod
    def _make_candidate(
        parsed_value: Decimal,
        metric_id: str,
        confidence: float = None,
        features: CandidateFeatures = None,
    ) -> ReviewCandidate:
        """Helper to create test candidates."""
        return ReviewCandidate(
            filing_id=1,
            company_id=1,
            char_position=0,
            context_text="test context",
            raw_number_text=str(parsed_value) if parsed_value else "unknown",
            triggering_keyword="test",
            keyword_distance=10,
            keyword_position="before",
            parsed_value=parsed_value,
            suggested_metric_id=metric_id,
            suggestion_confidence=confidence,
            features=features,
        )

    def test_empty_list_returns_empty_tuple(self):
        """Empty input should return ([], 0)."""
        result, count = deduplicate_candidates([])

        assert result == []
        assert count == 0

    def test_single_candidate_unchanged(self):
        """Single candidate should be returned unchanged."""
        candidate = self._make_candidate(Decimal("100"), "cm_arr")

        result, count = deduplicate_candidates([candidate])

        assert len(result) == 1
        assert result[0] is candidate
        assert count == 0

    def test_unique_candidates_all_kept(self):
        """Candidates with different keys should all be kept."""
        candidates = [
            self._make_candidate(Decimal("100"), "cm_arr"),
            self._make_candidate(Decimal("200"), "cm_arr"),
            self._make_candidate(Decimal("100"), "cm_churn_rate"),
        ]

        result, count = deduplicate_candidates(candidates)

        assert len(result) == 3
        assert count == 0

    def test_exact_duplicates_removed(self):
        """Duplicate (value, metric) pairs should be deduplicated."""
        candidates = [
            self._make_candidate(Decimal("500"), "cm_arr", 0.8),
            self._make_candidate(Decimal("500"), "cm_arr", 0.6),
        ]

        result, count = deduplicate_candidates(candidates)

        assert len(result) == 1
        assert count == 1

    def test_highest_confidence_kept(self):
        """Among duplicates, highest confidence should be kept."""
        candidates = [
            self._make_candidate(Decimal("500"), "cm_arr", 0.5),
            self._make_candidate(Decimal("500"), "cm_arr", 0.9),
            self._make_candidate(Decimal("500"), "cm_arr", 0.7),
        ]

        result, count = deduplicate_candidates(candidates)

        assert len(result) == 1
        assert result[0].suggestion_confidence == 0.9
        assert count == 2

    def test_none_confidence_sorted_last(self):
        """Candidates with None confidence should be sorted after those with values."""
        candidates = [
            self._make_candidate(Decimal("100"), "cm_arr", None),
            self._make_candidate(Decimal("100"), "cm_arr", 0.3),
        ]

        result, count = deduplicate_candidates(candidates)

        assert len(result) == 1
        assert result[0].suggestion_confidence == 0.3
        assert count == 1

    def test_all_none_confidence_keeps_one(self):
        """When all duplicates have None confidence, one should be kept."""
        candidates = [
            self._make_candidate(Decimal("100"), "cm_arr", None),
            self._make_candidate(Decimal("100"), "cm_arr", None),
            self._make_candidate(Decimal("100"), "cm_arr", None),
        ]

        result, count = deduplicate_candidates(candidates)

        assert len(result) == 1
        assert count == 2


class TestDeduplicateCandidatesEdgeCases:
    """Edge case tests for deduplicate_candidates."""

    @staticmethod
    def _make_candidate(
        parsed_value: Decimal,
        metric_id: str,
        confidence: float = None,
        features: CandidateFeatures = None,
    ) -> ReviewCandidate:
        """Helper to create test candidates."""
        return ReviewCandidate(
            filing_id=1,
            company_id=1,
            char_position=0,
            context_text="test context",
            raw_number_text=str(parsed_value) if parsed_value else "unknown",
            triggering_keyword="test",
            keyword_distance=10,
            keyword_position="before",
            parsed_value=parsed_value,
            suggested_metric_id=metric_id,
            suggestion_confidence=confidence,
            features=features,
        )

    def test_none_parsed_value_handled(self):
        """Candidates with None parsed_value should be groupable."""
        candidates = [
            ReviewCandidate(
                filing_id=1,
                company_id=1,
                char_position=0,
                context_text="test",
                raw_number_text="unknown",
                triggering_keyword="test",
                keyword_distance=10,
                keyword_position="before",
                parsed_value=None,
                suggested_metric_id="cm_arr",
                suggestion_confidence=0.5,
            ),
            ReviewCandidate(
                filing_id=1,
                company_id=1,
                char_position=100,
                context_text="test2",
                raw_number_text="unknown2",
                triggering_keyword="test",
                keyword_distance=10,
                keyword_position="before",
                parsed_value=None,
                suggested_metric_id="cm_arr",
                suggestion_confidence=0.8,
            ),
        ]

        result, count = deduplicate_candidates(candidates)

        assert len(result) == 1
        assert result[0].suggestion_confidence == 0.8
        assert count == 1

    def test_none_metric_id_handled(self):
        """Candidates with None metric_id should be groupable."""
        candidates = [
            self._make_candidate(Decimal("100"), None, 0.5),
            self._make_candidate(Decimal("100"), None, 0.9),
        ]

        result, count = deduplicate_candidates(candidates)

        assert len(result) == 1
        assert result[0].suggestion_confidence == 0.9
        assert count == 1

    def test_mixed_none_and_real_metric_ids(self):
        """None metric_id and real metric_id should be separate groups."""
        candidates = [
            self._make_candidate(Decimal("100"), None, 0.5),
            self._make_candidate(Decimal("100"), "cm_arr", 0.9),
        ]

        result, count = deduplicate_candidates(candidates)

        assert len(result) == 2
        assert count == 0

    def test_multiple_groups_with_duplicates(self):
        """Multiple groups with different duplicate counts."""
        candidates = [
            # Group 1: (100, cm_arr) - 3 duplicates
            self._make_candidate(Decimal("100"), "cm_arr", 0.9),
            self._make_candidate(Decimal("100"), "cm_arr", 0.7),
            self._make_candidate(Decimal("100"), "cm_arr", 0.5),
            # Group 2: (200, cm_arr) - 2 duplicates
            self._make_candidate(Decimal("200"), "cm_arr", 0.8),
            self._make_candidate(Decimal("200"), "cm_arr", 0.6),
            # Group 3: (100, cm_churn) - 1 (no duplicate)
            self._make_candidate(Decimal("100"), "cm_churn_rate", 0.4),
        ]

        result, count = deduplicate_candidates(candidates)

        assert len(result) == 3
        assert count == 3  # 2 from group 1, 1 from group 2

    def test_decimal_precision_preserved(self):
        """Decimal precision should be preserved in grouping."""
        candidates = [
            self._make_candidate(Decimal("100.50"), "cm_arr", 0.9),
            self._make_candidate(Decimal("100.5"), "cm_arr", 0.7),  # Same value, different repr
        ]

        result, count = deduplicate_candidates(candidates)

        # "100.50" and "100.5" have different string representations
        # so they may or may not be deduplicated depending on normalization
        # Current impl uses str(), so these are different keys
        # This test documents the current behavior
        assert len(result) == 2
        assert count == 0


class TestDeduplicateCandidatesL1Enhancement:
    """Tests for L1 respectively pattern period handling."""

    @staticmethod
    def _make_candidate_with_period(
        parsed_value: Decimal,
        metric_id: str,
        confidence: float = None,
        detected_period: str = None,
        respectively_confidence: float = None,
    ) -> ReviewCandidate:
        """Helper to create test candidates with period features."""
        features = None
        if detected_period is not None or respectively_confidence is not None:
            features = CandidateFeatures(
                keyword_distance=10,
                keyword_position="before",
                is_in_table=False,
                is_in_risk_factors=False,
                contains_definition_language=False,
                has_period_mention=True,
                number_format="decimal",
                detected_period=detected_period,
                respectively_confidence=respectively_confidence,
            )

        return ReviewCandidate(
            filing_id=1,
            company_id=1,
            char_position=0,
            context_text="test context",
            raw_number_text=str(parsed_value),
            triggering_keyword="test",
            keyword_distance=10,
            keyword_position="before",
            parsed_value=parsed_value,
            suggested_metric_id=metric_id,
            suggestion_confidence=confidence,
            features=features,
        )

    def test_different_periods_kept_separate(self):
        """Same value/metric with different periods should be kept separate."""
        candidates = [
            self._make_candidate_with_period(Decimal("33"), "cm_customer_churn_rate", 0.8, "2015"),
            self._make_candidate_with_period(Decimal("33"), "cm_customer_churn_rate", 0.8, "2016"),
            self._make_candidate_with_period(Decimal("33"), "cm_customer_churn_rate", 0.8, "2017"),
        ]

        result, count = deduplicate_candidates(candidates)

        assert len(result) == 3
        assert count == 0

    def test_same_period_deduplicated(self):
        """Same value/metric/period should be deduplicated."""
        candidates = [
            self._make_candidate_with_period(Decimal("33"), "cm_customer_churn_rate", 0.9, "2015"),
            self._make_candidate_with_period(Decimal("33"), "cm_customer_churn_rate", 0.7, "2015"),
        ]

        result, count = deduplicate_candidates(candidates)

        assert len(result) == 1
        assert result[0].suggestion_confidence == 0.9
        assert count == 1

    def test_none_period_grouped_together(self):
        """Candidates with None period should be grouped together."""
        candidates = [
            self._make_candidate_with_period(Decimal("100"), "cm_arr", 0.8, None),
            self._make_candidate_with_period(Decimal("100"), "cm_arr", 0.6, None),
        ]

        result, count = deduplicate_candidates(candidates)

        assert len(result) == 1
        assert count == 1

    def test_none_period_separate_from_real_period(self):
        """None period and real period should be separate groups."""
        candidates = [
            self._make_candidate_with_period(Decimal("100"), "cm_arr", 0.8, None),
            self._make_candidate_with_period(Decimal("100"), "cm_arr", 0.6, "2015"),
        ]

        result, count = deduplicate_candidates(candidates)

        assert len(result) == 2
        assert count == 0

    def test_respectively_confidence_as_secondary_sort(self):
        """When suggestion_confidence is equal, respectively_confidence should break tie."""
        candidates = [
            self._make_candidate_with_period(
                Decimal("33"), "cm_customer_churn_rate", 0.8, "2015", respectively_confidence=0.7
            ),
            self._make_candidate_with_period(
                Decimal("33"), "cm_customer_churn_rate", 0.8, "2015", respectively_confidence=0.95
            ),
        ]

        result, count = deduplicate_candidates(candidates)

        assert len(result) == 1
        # Should keep the one with higher respectively_confidence
        assert result[0].features.respectively_confidence == 0.95
        assert count == 1

    def test_no_features_treated_as_none_period(self):
        """Candidates without features should be treated as period=None."""
        candidates = [
            ReviewCandidate(
                filing_id=1,
                company_id=1,
                char_position=0,
                context_text="test",
                raw_number_text="100",
                triggering_keyword="test",
                keyword_distance=10,
                keyword_position="before",
                parsed_value=Decimal("100"),
                suggested_metric_id="cm_arr",
                suggestion_confidence=0.8,
                features=None,  # No features
            ),
            ReviewCandidate(
                filing_id=1,
                company_id=1,
                char_position=100,
                context_text="test2",
                raw_number_text="100",
                triggering_keyword="test",
                keyword_distance=10,
                keyword_position="before",
                parsed_value=Decimal("100"),
                suggested_metric_id="cm_arr",
                suggestion_confidence=0.6,
                features=None,  # No features
            ),
        ]

        result, count = deduplicate_candidates(candidates)

        assert len(result) == 1
        assert result[0].suggestion_confidence == 0.8
        assert count == 1

    def test_features_without_period_treated_as_none(self):
        """Features with detected_period=None should group together."""
        candidates = [
            self._make_candidate_with_period(Decimal("100"), "cm_arr", 0.8, None),
            ReviewCandidate(
                filing_id=1,
                company_id=1,
                char_position=0,
                context_text="test",
                raw_number_text="100",
                triggering_keyword="test",
                keyword_distance=10,
                keyword_position="before",
                parsed_value=Decimal("100"),
                suggested_metric_id="cm_arr",
                suggestion_confidence=0.6,
                features=CandidateFeatures(
                    keyword_distance=10,
                    keyword_position="before",
                    is_in_table=False,
                    is_in_risk_factors=False,
                    contains_definition_language=False,
                    has_period_mention=False,
                    number_format="decimal",
                ),  # Features present but period=None
            ),
        ]

        result, count = deduplicate_candidates(candidates)

        assert len(result) == 1
        assert count == 1


class TestDeduplicateCandidatesLogging:
    """Test logging behavior of deduplicate_candidates."""

    def test_logs_when_duplicates_removed(self, caplog):
        """Should log debug message when duplicates are removed."""
        import logging

        candidates = [
            ReviewCandidate(
                filing_id=1,
                company_id=1,
                char_position=0,
                context_text="test",
                raw_number_text="100",
                triggering_keyword="test",
                keyword_distance=10,
                keyword_position="before",
                parsed_value=Decimal("100"),
                suggested_metric_id="cm_arr",
                suggestion_confidence=0.8,
            ),
            ReviewCandidate(
                filing_id=1,
                company_id=1,
                char_position=100,
                context_text="test2",
                raw_number_text="100",
                triggering_keyword="test",
                keyword_distance=10,
                keyword_position="before",
                parsed_value=Decimal("100"),
                suggested_metric_id="cm_arr",
                suggestion_confidence=0.6,
            ),
        ]

        with caplog.at_level(logging.DEBUG, logger="src.review.deduplicator"):
            result, count = deduplicate_candidates(candidates)

        assert count == 1
        assert "Deduplication removed 1 candidates" in caplog.text
        assert "(2 -> 1)" in caplog.text

    def test_no_log_when_no_duplicates(self, caplog):
        """Should not log when no duplicates are removed."""
        import logging

        candidates = [
            ReviewCandidate(
                filing_id=1,
                company_id=1,
                char_position=0,
                context_text="test",
                raw_number_text="100",
                triggering_keyword="test",
                keyword_distance=10,
                keyword_position="before",
                parsed_value=Decimal("100"),
                suggested_metric_id="cm_arr",
            ),
        ]

        with caplog.at_level(logging.DEBUG, logger="src.review.deduplicator"):
            result, count = deduplicate_candidates(candidates)

        assert count == 0
        assert "Deduplication removed" not in caplog.text


class TestDeduplicateCandidatesP16SameSentencePreference:
    """Tests for P1.6 same-sentence preference enhancement."""

    @staticmethod
    def _make_candidate_with_sentence(
        parsed_value: Decimal,
        metric_id: str,
        confidence: float = None,
        is_same_sentence: bool = True,
    ) -> ReviewCandidate:
        """Helper to create test candidates with is_same_sentence field."""
        features = CandidateFeatures(
            keyword_distance=10,
            keyword_position="before",
            is_in_table=False,
            is_in_risk_factors=False,
            contains_definition_language=False,
            has_period_mention=False,
            number_format="decimal",
            is_same_sentence=is_same_sentence,
        )

        return ReviewCandidate(
            filing_id=1,
            company_id=1,
            char_position=0,
            context_text="test context",
            raw_number_text=str(parsed_value),
            triggering_keyword="test",
            keyword_distance=10,
            keyword_position="before",
            parsed_value=parsed_value,
            suggested_metric_id=metric_id,
            suggestion_confidence=confidence,
            features=features,
        )

    def test_same_sentence_preferred_over_higher_confidence_cross_sentence(self):
        """Same-sentence candidate should win over higher-confidence cross-sentence."""
        candidates = [
            self._make_candidate_with_sentence(
                Decimal("100"), "cm_arr", confidence=0.7, is_same_sentence=True
            ),
            self._make_candidate_with_sentence(
                Decimal("100"), "cm_arr", confidence=0.9, is_same_sentence=False
            ),
        ]

        result, count = deduplicate_candidates(candidates, prefer_same_sentence=True)

        assert len(result) == 1
        assert result[0].suggestion_confidence == 0.7  # Same-sentence wins
        assert result[0].features.is_same_sentence is True
        assert count == 1

    def test_same_sentence_preference_disabled(self):
        """When prefer_same_sentence=False, highest confidence wins."""
        candidates = [
            self._make_candidate_with_sentence(
                Decimal("100"), "cm_arr", confidence=0.7, is_same_sentence=True
            ),
            self._make_candidate_with_sentence(
                Decimal("100"), "cm_arr", confidence=0.9, is_same_sentence=False
            ),
        ]

        result, count = deduplicate_candidates(candidates, prefer_same_sentence=False)

        assert len(result) == 1
        assert result[0].suggestion_confidence == 0.9  # Highest confidence wins
        assert result[0].features.is_same_sentence is False
        assert count == 1

    def test_highest_confidence_among_same_sentence_selected(self):
        """Among same-sentence candidates, highest confidence should win."""
        candidates = [
            self._make_candidate_with_sentence(
                Decimal("100"), "cm_arr", confidence=0.6, is_same_sentence=True
            ),
            self._make_candidate_with_sentence(
                Decimal("100"), "cm_arr", confidence=0.8, is_same_sentence=True
            ),
            self._make_candidate_with_sentence(
                Decimal("100"), "cm_arr", confidence=0.95, is_same_sentence=False
            ),
        ]

        result, count = deduplicate_candidates(candidates, prefer_same_sentence=True)

        assert len(result) == 1
        assert result[0].suggestion_confidence == 0.8  # Highest same-sentence wins
        assert count == 2

    def test_fallback_to_all_when_no_same_sentence(self):
        """When no same-sentence candidates exist, use all candidates."""
        candidates = [
            self._make_candidate_with_sentence(
                Decimal("100"), "cm_arr", confidence=0.7, is_same_sentence=False
            ),
            self._make_candidate_with_sentence(
                Decimal("100"), "cm_arr", confidence=0.9, is_same_sentence=False
            ),
        ]

        result, count = deduplicate_candidates(candidates, prefer_same_sentence=True)

        assert len(result) == 1
        assert result[0].suggestion_confidence == 0.9  # Highest confidence among all
        assert count == 1

    def test_fallback_when_features_none(self):
        """Candidates without features should be considered in fallback."""
        candidates = [
            ReviewCandidate(
                filing_id=1,
                company_id=1,
                char_position=0,
                context_text="test",
                raw_number_text="100",
                triggering_keyword="test",
                keyword_distance=10,
                keyword_position="before",
                parsed_value=Decimal("100"),
                suggested_metric_id="cm_arr",
                suggestion_confidence=0.8,
                features=None,  # No features = can't determine same-sentence
            ),
            ReviewCandidate(
                filing_id=1,
                company_id=1,
                char_position=100,
                context_text="test2",
                raw_number_text="100",
                triggering_keyword="test",
                keyword_distance=10,
                keyword_position="before",
                parsed_value=Decimal("100"),
                suggested_metric_id="cm_arr",
                suggestion_confidence=0.6,
                features=None,
            ),
        ]

        result, count = deduplicate_candidates(candidates, prefer_same_sentence=True)

        assert len(result) == 1
        assert result[0].suggestion_confidence == 0.8  # Highest confidence
        assert count == 1

    def test_mixed_features_and_no_features(self):
        """Candidate with is_same_sentence=True should win over no features."""
        same_sentence_candidate = self._make_candidate_with_sentence(
            Decimal("100"), "cm_arr", confidence=0.7, is_same_sentence=True
        )
        no_features_candidate = ReviewCandidate(
            filing_id=1,
            company_id=1,
            char_position=100,
            context_text="test2",
            raw_number_text="100",
            triggering_keyword="test",
            keyword_distance=10,
            keyword_position="before",
            parsed_value=Decimal("100"),
            suggested_metric_id="cm_arr",
            suggestion_confidence=0.9,
            features=None,
        )

        result, count = deduplicate_candidates(
            [same_sentence_candidate, no_features_candidate],
            prefer_same_sentence=True,
        )

        assert len(result) == 1
        assert result[0].suggestion_confidence == 0.7  # Same-sentence wins
        assert count == 1

    def test_default_prefer_same_sentence_is_true(self):
        """Default value for prefer_same_sentence should be True."""
        candidates = [
            self._make_candidate_with_sentence(
                Decimal("100"), "cm_arr", confidence=0.7, is_same_sentence=True
            ),
            self._make_candidate_with_sentence(
                Decimal("100"), "cm_arr", confidence=0.9, is_same_sentence=False
            ),
        ]

        # Call without prefer_same_sentence argument - should default to True
        result, count = deduplicate_candidates(candidates)

        assert len(result) == 1
        assert result[0].suggestion_confidence == 0.7  # Same-sentence wins
        assert result[0].features.is_same_sentence is True

    def test_independent_groups_each_prefer_same_sentence(self):
        """Each independent group should apply same-sentence preference."""
        candidates = [
            # Group 1: (100, cm_arr)
            self._make_candidate_with_sentence(
                Decimal("100"), "cm_arr", confidence=0.7, is_same_sentence=True
            ),
            self._make_candidate_with_sentence(
                Decimal("100"), "cm_arr", confidence=0.9, is_same_sentence=False
            ),
            # Group 2: (200, cm_arr) - only cross-sentence
            self._make_candidate_with_sentence(
                Decimal("200"), "cm_arr", confidence=0.6, is_same_sentence=False
            ),
            self._make_candidate_with_sentence(
                Decimal("200"), "cm_arr", confidence=0.8, is_same_sentence=False
            ),
        ]

        result, count = deduplicate_candidates(candidates, prefer_same_sentence=True)

        assert len(result) == 2
        assert count == 2

        # Find the results by value
        group1 = [c for c in result if c.parsed_value == Decimal("100")][0]
        group2 = [c for c in result if c.parsed_value == Decimal("200")][0]

        # Group 1: same-sentence (0.7) wins over cross-sentence (0.9)
        assert group1.suggestion_confidence == 0.7
        assert group1.features.is_same_sentence is True

        # Group 2: highest confidence (0.8) wins (no same-sentence available)
        assert group2.suggestion_confidence == 0.8
