"""
Unit tests for bulk_insert_review_candidates upsert logic with conflict resolution.

Tests the two-phase algorithm:
1. Conflict Detection: Pre-fetch existing candidates, resolve by confidence
2. Runner-Up Capture: Log best alternative metric at each position

Task: DUP-2
"""

import pytest

from tests.integration.conftest import (
    create_test_company_and_filing,
)


def make_candidate(
    filing_id: int,
    company_id: int,
    char_position: int = 100,
    suggested_metric_id: str | None = "cm_arr",
    suggestion_confidence: float | None = 0.8,
    source_segment_id: int | None = None,
    context_text: str = "Test context",
    raw_number_text: str = "1000",
    triggering_keyword: str = "customers",
    keyword_distance: int = 10,
    keyword_position: str = "after",
) -> dict:
    """Create a test candidate dict."""
    return {
        "filing_id": filing_id,
        "company_id": company_id,
        "source_segment_id": source_segment_id,
        "char_position": char_position,
        "context_text": context_text,
        "raw_number_text": raw_number_text,
        "triggering_keyword": triggering_keyword,
        "keyword_distance": keyword_distance,
        "keyword_position": keyword_position,
        "suggested_metric_id": suggested_metric_id,
        "suggestion_confidence": suggestion_confidence,
    }


class TestBasicInsert:
    """Tests for basic insert scenarios without conflicts."""

    def test_insert_single_new(self, clean_db):
        """Inserting a single new candidate returns its ID."""
        company_id, filing_id = create_test_company_and_filing(clean_db)

        candidates = [make_candidate(filing_id, company_id)]
        result = clean_db.bulk_insert_review_candidates(candidates)

        assert len(result) == 1
        assert result[0] > 0

        # Verify in DB
        candidate = clean_db.get_review_candidate(result[0])
        assert candidate["suggested_metric_id"] == "cm_arr"

    def test_insert_multiple_new(self, clean_db):
        """Inserting multiple non-conflicting candidates returns all IDs."""
        company_id, filing_id = create_test_company_and_filing(clean_db)

        candidates = [
            make_candidate(filing_id, company_id, char_position=100),
            make_candidate(filing_id, company_id, char_position=200),
            make_candidate(filing_id, company_id, char_position=300),
        ]
        result = clean_db.bulk_insert_review_candidates(candidates)

        assert len(result) == 3
        assert len(set(result)) == 3  # All unique IDs
        assert all(cid > 0 for cid in result)

    def test_insert_empty_list(self, clean_db):
        """Inserting empty list returns empty list."""
        result = clean_db.bulk_insert_review_candidates([])
        assert result == []

    def test_insert_empty_list_with_log_suppressed(self, clean_db):
        """Inserting empty list with log_suppressed returns empty tuple."""
        result = clean_db.bulk_insert_review_candidates([], log_suppressed=True)
        assert result == ([], [])


class TestConflictNewLoses:
    """Tests where new candidate loses to existing."""

    def test_conflict_new_lower_confidence(self, clean_db):
        """New candidate with lower confidence loses to existing."""
        company_id, filing_id = create_test_company_and_filing(clean_db)

        # Insert existing candidate
        existing = make_candidate(
            filing_id, company_id, suggestion_confidence=0.8
        )
        [existing_id] = clean_db.bulk_insert_review_candidates([existing])

        # Try to insert new with lower confidence
        new_candidate = make_candidate(
            filing_id, company_id, suggestion_confidence=0.5
        )
        result = clean_db.bulk_insert_review_candidates([new_candidate])

        # Should return existing ID
        assert result == [existing_id]

        # DB should still have original
        candidate = clean_db.get_review_candidate(existing_id)
        assert float(candidate["suggestion_confidence"]) == pytest.approx(0.8)

    def test_conflict_new_equal_confidence(self, clean_db):
        """New candidate with equal confidence loses (existing wins ties)."""
        company_id, filing_id = create_test_company_and_filing(clean_db)

        # Insert existing
        existing = make_candidate(
            filing_id, company_id,
            suggestion_confidence=0.8,
            context_text="Original context",
        )
        [existing_id] = clean_db.bulk_insert_review_candidates([existing])

        # Try with equal confidence
        new_candidate = make_candidate(
            filing_id, company_id,
            suggestion_confidence=0.8,
            context_text="New context",
        )
        result = clean_db.bulk_insert_review_candidates([new_candidate])

        assert result == [existing_id]

        # DB should still have original context
        candidate = clean_db.get_review_candidate(existing_id)
        assert candidate["context_text"] == "Original context"

    def test_conflict_multiple_losers(self, clean_db):
        """Multiple new candidates all lose to existing."""
        company_id, filing_id = create_test_company_and_filing(clean_db)

        # Insert 3 existing with high confidence
        existing = [
            make_candidate(
                filing_id, company_id,
                char_position=i * 100,
                suggestion_confidence=0.9,
            )
            for i in range(3)
        ]
        existing_ids = clean_db.bulk_insert_review_candidates(existing)

        # Try to insert 3 new with lower confidence
        new_candidates = [
            make_candidate(
                filing_id, company_id,
                char_position=i * 100,
                suggestion_confidence=0.5,
            )
            for i in range(3)
        ]
        result = clean_db.bulk_insert_review_candidates(new_candidates)

        assert result == existing_ids


class TestConflictNewWins:
    """Tests where new candidate wins over existing."""

    def test_conflict_new_higher_confidence(self, clean_db):
        """New candidate with higher confidence wins."""
        company_id, filing_id = create_test_company_and_filing(clean_db)

        # Insert existing with low confidence
        existing = make_candidate(
            filing_id, company_id,
            suggestion_confidence=0.5,
            context_text="Old context",
        )
        [existing_id] = clean_db.bulk_insert_review_candidates([existing])

        # Insert new with higher confidence
        new_candidate = make_candidate(
            filing_id, company_id,
            suggestion_confidence=0.9,
            context_text="New context",
        )
        result = clean_db.bulk_insert_review_candidates([new_candidate])

        # Should still return same ID (update, not insert)
        assert result == [existing_id]

        # DB should have new values
        candidate = clean_db.get_review_candidate(existing_id)
        assert candidate["context_text"] == "New context"
        assert float(candidate["suggestion_confidence"]) == pytest.approx(0.9)

    def test_conflict_winner_replaces_existing(self, clean_db):
        """Verify UPDATE actually happened."""
        company_id, filing_id = create_test_company_and_filing(clean_db)

        # Insert existing
        existing = make_candidate(
            filing_id, company_id,
            suggestion_confidence=0.3,
            raw_number_text="old_number",
            triggering_keyword="old_keyword",
        )
        [existing_id] = clean_db.bulk_insert_review_candidates([existing])

        # Insert winner
        winner = make_candidate(
            filing_id, company_id,
            suggestion_confidence=0.9,
            raw_number_text="new_number",
            triggering_keyword="new_keyword",
        )
        clean_db.bulk_insert_review_candidates([winner])

        # Verify all fields updated
        candidate = clean_db.get_review_candidate(existing_id)
        assert candidate["raw_number_text"] == "new_number"
        assert candidate["triggering_keyword"] == "new_keyword"
        assert float(candidate["suggestion_confidence"]) == pytest.approx(0.9)

    def test_conflict_old_values_captured(self, clean_db):
        """Old values captured in suppression log when new wins."""
        company_id, filing_id = create_test_company_and_filing(clean_db)

        # Insert existing
        existing = make_candidate(
            filing_id, company_id,
            suggestion_confidence=0.3,
            suggested_metric_id="cm_old",
        )
        [existing_id] = clean_db.bulk_insert_review_candidates([existing])

        # Insert winner with log_suppressed
        winner = make_candidate(
            filing_id, company_id,
            suggestion_confidence=0.9,
            suggested_metric_id="cm_old",  # Same metric, different confidence
        )
        result_ids, logs = clean_db.bulk_insert_review_candidates(
            [winner], log_suppressed=True
        )

        assert len(result_ids) == 1
        assert len(logs) == 1

        log = logs[0]
        assert log["suppression_reason"] == "lower_confidence"
        assert float(log["suggestion_confidence"]) == pytest.approx(0.3)  # OLD confidence
        assert float(log["winner_confidence"]) == pytest.approx(0.9)  # NEW confidence
        assert log["winner_candidate_id"] == existing_id


class TestRunnerUpCapture:
    """Tests for runner-up detection and logging."""

    def test_runner_up_captured(self, clean_db):
        """Runner-up with different metric is captured."""
        company_id, filing_id = create_test_company_and_filing(clean_db)

        # Two candidates at same position, different metrics
        candidates = [
            make_candidate(
                filing_id, company_id,
                char_position=100,
                suggested_metric_id="cm_arr",
                suggestion_confidence=0.9,
            ),
            make_candidate(
                filing_id, company_id,
                char_position=100,
                suggested_metric_id="cm_mrr",
                suggestion_confidence=0.7,
            ),
        ]

        result_ids, logs = clean_db.bulk_insert_review_candidates(
            candidates, log_suppressed=True
        )

        # Both should be inserted (different metrics)
        assert len(result_ids) == 2
        assert len(set(result_ids)) == 2

        # Runner-up should be logged
        runner_up_logs = [l for l in logs if l["suppression_reason"] == "runner_up"]
        assert len(runner_up_logs) == 1

        log = runner_up_logs[0]
        assert log["suggested_metric_id"] == "cm_mrr"  # The runner-up metric
        assert float(log["suggestion_confidence"]) == pytest.approx(0.7)

    def test_runner_up_different_metric_only(self, clean_db):
        """Same position+metric produces lower_confidence, not runner_up."""
        company_id, filing_id = create_test_company_and_filing(clean_db)

        # Two candidates at same position, SAME metric
        candidates = [
            make_candidate(
                filing_id, company_id,
                char_position=100,
                suggested_metric_id="cm_arr",
                suggestion_confidence=0.9,
            ),
            make_candidate(
                filing_id, company_id,
                char_position=100,
                suggested_metric_id="cm_arr",
                suggestion_confidence=0.7,
            ),
        ]

        result_ids, logs = clean_db.bulk_insert_review_candidates(
            candidates, log_suppressed=True
        )

        # Same ID for both (dedup within batch)
        assert result_ids[0] == result_ids[1]

        # Should be lower_confidence, NOT runner_up
        assert len(logs) == 1
        assert logs[0]["suppression_reason"] == "lower_confidence"

    def test_runner_up_highest_alternative(self, clean_db):
        """Runner-up is highest confidence alternative metric."""
        company_id, filing_id = create_test_company_and_filing(clean_db)

        # 3 metrics at same position
        candidates = [
            make_candidate(
                filing_id, company_id,
                char_position=100,
                suggested_metric_id="cm_arr",
                suggestion_confidence=0.9,
            ),
            make_candidate(
                filing_id, company_id,
                char_position=100,
                suggested_metric_id="cm_mrr",
                suggestion_confidence=0.5,
            ),
            make_candidate(
                filing_id, company_id,
                char_position=100,
                suggested_metric_id="cm_customers",
                suggestion_confidence=0.7,
            ),
        ]

        result_ids, logs = clean_db.bulk_insert_review_candidates(
            candidates, log_suppressed=True
        )

        runner_up_logs = [l for l in logs if l["suppression_reason"] == "runner_up"]
        assert len(runner_up_logs) == 1

        # cm_customers (0.7) is runner-up, not cm_mrr (0.5)
        assert runner_up_logs[0]["suggested_metric_id"] == "cm_customers"

    def test_runner_up_linked_to_winner(self, clean_db):
        """Runner-up's winner_candidate_id points to the winner."""
        company_id, filing_id = create_test_company_and_filing(clean_db)

        candidates = [
            make_candidate(
                filing_id, company_id,
                char_position=100,
                suggested_metric_id="cm_arr",
                suggestion_confidence=0.9,
            ),
            make_candidate(
                filing_id, company_id,
                char_position=100,
                suggested_metric_id="cm_mrr",
                suggestion_confidence=0.7,
            ),
        ]

        result_ids, logs = clean_db.bulk_insert_review_candidates(
            candidates, log_suppressed=True
        )

        # Find which ID is cm_arr (the winner)
        arr_id = result_ids[0]  # First one is cm_arr

        runner_up_logs = [l for l in logs if l["suppression_reason"] == "runner_up"]
        assert len(runner_up_logs) == 1
        assert runner_up_logs[0]["winner_candidate_id"] == arr_id


class TestNullSegmentHandling:
    """Tests for NULL source_segment_id handling."""

    def test_null_segment_conflict(self, clean_db):
        """Two candidates with NULL segment_id conflict correctly."""
        company_id, filing_id = create_test_company_and_filing(clean_db)

        # Insert existing with NULL segment
        existing = make_candidate(
            filing_id, company_id,
            source_segment_id=None,
            suggestion_confidence=0.8,
        )
        [existing_id] = clean_db.bulk_insert_review_candidates([existing])

        # Try lower confidence
        new_candidate = make_candidate(
            filing_id, company_id,
            source_segment_id=None,
            suggestion_confidence=0.5,
        )
        result = clean_db.bulk_insert_review_candidates([new_candidate])

        assert result == [existing_id]

    def test_mixed_null_and_not_null(self, clean_db):
        """Batch with both NULL and non-NULL segments processed correctly."""
        company_id, filing_id = create_test_company_and_filing(clean_db)

        # Create a segment
        with clean_db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO source_segments (filing_id, segment_type, raw_text, sequence_index)
                    VALUES (%(filing_id)s, 'paragraph', 'Test text', 0)
                    RETURNING source_segment_id
                """, {"filing_id": filing_id})
                segment_id = cur.fetchone()["source_segment_id"]

        candidates = [
            make_candidate(
                filing_id, company_id,
                char_position=100,
                source_segment_id=segment_id,
            ),
            make_candidate(
                filing_id, company_id,
                char_position=200,
                source_segment_id=None,
            ),
        ]

        result = clean_db.bulk_insert_review_candidates(candidates)

        assert len(result) == 2
        assert len(set(result)) == 2

    def test_null_segment_runner_up(self, clean_db):
        """Runner-up with NULL segment captured correctly."""
        company_id, filing_id = create_test_company_and_filing(clean_db)

        candidates = [
            make_candidate(
                filing_id, company_id,
                char_position=100,
                source_segment_id=None,
                suggested_metric_id="cm_arr",
                suggestion_confidence=0.9,
            ),
            make_candidate(
                filing_id, company_id,
                char_position=100,
                source_segment_id=None,
                suggested_metric_id="cm_mrr",
                suggestion_confidence=0.7,
            ),
        ]

        result_ids, logs = clean_db.bulk_insert_review_candidates(
            candidates, log_suppressed=True
        )

        runner_up_logs = [l for l in logs if l["suppression_reason"] == "runner_up"]
        assert len(runner_up_logs) == 1
        assert runner_up_logs[0]["source_segment_id"] is None


class TestReturnContract:
    """Tests for return value guarantees."""

    def test_return_length_matches_input(self, clean_db):
        """Return length always equals input length."""
        company_id, filing_id = create_test_company_and_filing(clean_db)

        # Mix of new, conflict-wins, conflict-loses
        existing = make_candidate(
            filing_id, company_id,
            char_position=100,
            suggestion_confidence=0.5,
        )
        [existing_id] = clean_db.bulk_insert_review_candidates([existing])

        candidates = [
            # Conflict: loses to existing
            make_candidate(
                filing_id, company_id,
                char_position=100,
                suggestion_confidence=0.3,
            ),
            # New
            make_candidate(
                filing_id, company_id,
                char_position=200,
            ),
            # Conflict: wins over existing
            make_candidate(
                filing_id, company_id,
                char_position=100,
                suggestion_confidence=0.9,
            ),
        ]

        result = clean_db.bulk_insert_review_candidates(candidates)

        assert len(result) == len(candidates)

    def test_return_order_preserved(self, clean_db):
        """zip(input, output, strict=True) is safe."""
        company_id, filing_id = create_test_company_and_filing(clean_db)

        candidates = [
            make_candidate(
                filing_id, company_id,
                char_position=300,
                suggested_metric_id="cm_third",
            ),
            make_candidate(
                filing_id, company_id,
                char_position=100,
                suggested_metric_id="cm_first",
            ),
            make_candidate(
                filing_id, company_id,
                char_position=200,
                suggested_metric_id="cm_second",
            ),
        ]

        result = clean_db.bulk_insert_review_candidates(candidates)

        # Verify order by checking metrics match
        for candidate, cid in zip(candidates, result, strict=True):
            db_candidate = clean_db.get_review_candidate(cid)
            assert db_candidate["suggested_metric_id"] == candidate["suggested_metric_id"]


class TestWithinBatchDedup:
    """Tests for within-batch deduplication."""

    def test_batch_dedup_higher_confidence_wins(self, clean_db):
        """Within batch, higher confidence wins."""
        company_id, filing_id = create_test_company_and_filing(clean_db)

        # Same uniqueness key, different confidence
        candidates = [
            make_candidate(
                filing_id, company_id,
                char_position=100,
                suggested_metric_id="cm_arr",
                suggestion_confidence=0.5,
            ),
            make_candidate(
                filing_id, company_id,
                char_position=100,
                suggested_metric_id="cm_arr",
                suggestion_confidence=0.9,
                context_text="Winner context",
            ),
        ]

        result = clean_db.bulk_insert_review_candidates(candidates)

        # Both should have same ID (deduped)
        assert result[0] == result[1]

        # Winner's values should be in DB
        candidate = clean_db.get_review_candidate(result[0])
        assert float(candidate["suggestion_confidence"]) == pytest.approx(0.9)
        assert candidate["context_text"] == "Winner context"

    def test_batch_dedup_first_wins_ties(self, clean_db):
        """Within batch with equal confidence, first wins."""
        company_id, filing_id = create_test_company_and_filing(clean_db)

        candidates = [
            make_candidate(
                filing_id, company_id,
                char_position=100,
                suggested_metric_id="cm_arr",
                suggestion_confidence=0.8,
                context_text="First context",
            ),
            make_candidate(
                filing_id, company_id,
                char_position=100,
                suggested_metric_id="cm_arr",
                suggestion_confidence=0.8,
                context_text="Second context",
            ),
        ]

        result = clean_db.bulk_insert_review_candidates(candidates)

        candidate = clean_db.get_review_candidate(result[0])
        assert candidate["context_text"] == "First context"

    def test_batch_dedup_suppression_logged(self, clean_db):
        """Within-batch loser logged as suppressed."""
        company_id, filing_id = create_test_company_and_filing(clean_db)

        candidates = [
            make_candidate(
                filing_id, company_id,
                char_position=100,
                suggested_metric_id="cm_arr",
                suggestion_confidence=0.5,
            ),
            make_candidate(
                filing_id, company_id,
                char_position=100,
                suggested_metric_id="cm_arr",
                suggestion_confidence=0.9,
            ),
        ]

        result_ids, logs = clean_db.bulk_insert_review_candidates(
            candidates, log_suppressed=True
        )

        # One suppression for the loser
        assert len(logs) == 1
        assert logs[0]["suppression_reason"] == "lower_confidence"
        assert float(logs[0]["suggestion_confidence"]) == pytest.approx(0.5)
        assert logs[0]["input_index"] == 0  # First candidate was the loser


class TestBackwardCompatibility:
    """Tests for backward compatibility."""

    def test_default_returns_list(self, clean_db):
        """Default behavior returns list[int]."""
        company_id, filing_id = create_test_company_and_filing(clean_db)

        candidates = [make_candidate(filing_id, company_id)]
        result = clean_db.bulk_insert_review_candidates(candidates)

        assert isinstance(result, list)
        assert all(isinstance(x, int) for x in result)

    def test_log_suppressed_returns_tuple(self, clean_db):
        """log_suppressed=True returns tuple."""
        company_id, filing_id = create_test_company_and_filing(clean_db)

        candidates = [make_candidate(filing_id, company_id)]
        result = clean_db.bulk_insert_review_candidates(
            candidates, log_suppressed=True
        )

        assert isinstance(result, tuple)
        assert len(result) == 2
        ids, logs = result
        assert isinstance(ids, list)
        assert isinstance(logs, list)

    def test_existing_caller_works(self, clean_db):
        """Existing callers using zip(candidates, ids, strict=True) work."""
        company_id, filing_id = create_test_company_and_filing(clean_db)

        candidates = [
            make_candidate(filing_id, company_id, char_position=i * 100)
            for i in range(5)
        ]

        result = clean_db.bulk_insert_review_candidates(candidates)

        # This is what helpers.py does - should not raise
        for candidate, cid in zip(candidates, result, strict=True):
            assert cid > 0
