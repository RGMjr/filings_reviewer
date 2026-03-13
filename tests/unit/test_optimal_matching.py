"""
Test optimal matching in validation script.

Verifies that two-pass optimal matching assigns best matches by score,
rather than first-come-first-served.
"""
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from scripts.validate_against_gold_standard import (
    GoldStandardEntry,
    validate_filing,
)


def test_optimal_matching_prefers_higher_scores():
    """
    Test that optimal matching assigns better matches over worse matches.

    Scenario:
    - Gold Entry 1: metric=cm_arr, value=1000000
    - Candidate A: metric=cm_arr, value=1000001 (close value match, score=4.5)
    - Candidate B: metric=cm_arr, value=2000000 (metric match only, score=2)

    With first-come-first-served, if B is processed first, it would take Entry 1.
    With optimal matching, A should take Entry 1 (higher score).
    """
    gold_entries = [
        GoldStandardEntry(
            document_url="https://example.com/filing",
            company="Test Company",
            metric_id="cm_arr",
            is_new_metric=False,
            text_variant="ARR",
            raw_value="1000000",
            scaled_value="",
            scale_unit="",
            period="FY2023",
            definition="Annual Recurring Revenue",
            source_quote="ARR was 1000000",
            line_number=1,
            is_definition_only=False,
        )
    ]

    # Candidate B: weaker match (metric only)
    candidate_b = {
        'candidate_id': 2,
        'suggested_metric_id': 'cm_arr',
        'parsed_value': 2000000.0,
        'raw_number_text': '2 million',
        'triggering_keyword': 'arr',
        'context_text': 'ARR was 2 million',
    }

    # Candidate A: stronger match (metric + close value)
    candidate_a = {
        'candidate_id': 1,
        'suggested_metric_id': 'cm_arr',
        'parsed_value': 1000001.0,  # Within 1% of gold value
        'raw_number_text': '1,000,001',
        'triggering_keyword': 'arr',
        'context_text': 'ARR reached 1,000,001',
    }

    # Pass candidates in "bad" order (B first)
    candidates = [candidate_b, candidate_a]

    # Mock database (not used since we pass candidates_override)
    class MockDB:
        def get_review_candidates_for_filing(self, filing_id):
            return []

    result = validate_filing(
        db=MockDB(),
        filing_id=None,
        company_name="Test Company",
        gold_entries=gold_entries,
        verbose=False,
        candidates_override=candidates,
    )

    # With optimal matching, Candidate A should match Entry 1
    # Candidate B should be a false positive
    assert result.true_positives == 1
    assert result.false_positives == 1
    assert result.false_negatives == 0

    # Verify that the matched candidate is A (stronger match)
    matched_candidate_id = result.tp_matches[0].candidate_id
    assert matched_candidate_id == 1, f"Expected candidate 1 (A) to match, got {matched_candidate_id}"


def test_optimal_matching_handles_overlapping_candidates():
    """
    Test optimal matching with multiple candidates competing for same gold entry.

    Scenario:
    - Gold Entry 1: metric=cm_arr, value=5000000
    - Candidate A: metric=cm_arr, value=5000000 (exact match, score=5)
    - Candidate B: metric=cm_arr, value=4950000 (close match, score=4.5)
    - Candidate C: metric=cm_mrr, value=5000000 (value only, score=3)

    Expected: A takes Entry 1, B and C are FP
    """
    gold_entries = [
        GoldStandardEntry(
            document_url="https://example.com/filing",
            company="Test Company",
            metric_id="cm_arr",
            is_new_metric=False,
            text_variant="ARR",
            raw_value="5000000",
            scaled_value="",
            scale_unit="",
            period="FY2023",
            definition="Annual Recurring Revenue",
            source_quote="ARR reached 5000000",
            line_number=1,
            is_definition_only=False,
        )
    ]

    candidates = [
        {
            'candidate_id': 3,
            'suggested_metric_id': 'cm_mrr',
            'parsed_value': 5000000.0,
            'raw_number_text': '5M',
            'triggering_keyword': 'mrr',
            'context_text': 'MRR of 5M',
        },
        {
            'candidate_id': 2,
            'suggested_metric_id': 'cm_arr',
            'parsed_value': 4950000.0,
            'raw_number_text': '4.95M',
            'triggering_keyword': 'arr',
            'context_text': 'ARR 4.95M',
        },
        {
            'candidate_id': 1,
            'suggested_metric_id': 'cm_arr',
            'parsed_value': 5000000.0,
            'raw_number_text': '5M',
            'triggering_keyword': 'arr',
            'context_text': 'ARR 5M',
        },
    ]

    class MockDB:
        def get_review_candidates_for_filing(self, filing_id):
            return []

    result = validate_filing(
        db=MockDB(),
        filing_id=None,
        company_name="Test Company",
        gold_entries=gold_entries,
        verbose=False,
        candidates_override=candidates,
    )

    # Only one should match
    assert result.true_positives == 1
    assert result.false_positives == 2
    assert result.false_negatives == 0

    # The best match (exact value + metric) should win
    matched_candidate_id = result.tp_matches[0].candidate_id
    assert matched_candidate_id == 1, f"Expected candidate 1 (exact match) to win, got {matched_candidate_id}"
