"""
Integration tests for context performance analysis (E1 multiplier optimization).

Tests verify that the PatternAnalyzer can analyze accept/reject rates
by context type and keyword direction to inform multiplier optimization.
"""

import pytest

from src.review.candidate_generator import CandidateGenerator
from src.review.config import CandidateGenerationConfig
from src.review.models import SegmentDict
from src.review.pattern_analyzer import PatternAnalyzer


@pytest.fixture
def db(clean_db):
    """Database adapter with clean test database (truncated before/after each test)."""
    return clean_db


@pytest.fixture
def generator():
    """Generator with context tracking enabled."""
    config = CandidateGenerationConfig(
        use_context_dependent_multipliers=True,
    )
    return CandidateGenerator(config=config)


@pytest.fixture
def analyzer(db):
    """Pattern analyzer for context performance analysis."""
    return PatternAnalyzer(db)


@pytest.fixture
def sample_candidates(db, generator):
    """
    Generate sample candidates with context types and insert decisions.

    Creates 3 filings with different context types and directions,
    then inserts review decisions (accept/reject).

    Returns:
        List of (filing_id, company_id, candidate_ids) tuples
    """
    filing_data = []

    # Create test companies and get their IDs
    company_id_1 = db.upsert_company(cik="0000002001", company_name="Test Company 1")
    company_id_2 = db.upsert_company(cik="0000002002", company_name="Test Company 2")
    company_id_3 = db.upsert_company(cik="0000002003", company_name="Test Company 3")

    # Insert filings
    filing_id_1 = db.upsert_filing(
        cik="0000002001",
        company_id=company_id_1,
        accession_number="0001234567-25-001001",
        form_type="S-1",
        filing_date="2025-01-01",
        sec_html_url="https://sec.gov/test1.html",
        is_post_combination=False,
        is_investment_vehicle=False,
        is_resource_extraction=False,
    )
    filing_id_2 = db.upsert_filing(
        cik="0000002002",
        company_id=company_id_2,
        accession_number="0001234567-25-001002",
        form_type="S-1",
        filing_date="2025-01-02",
        sec_html_url="https://sec.gov/test2.html",
        is_post_combination=False,
        is_investment_vehicle=False,
        is_resource_extraction=False,
    )
    filing_id_3 = db.upsert_filing(
        cik="0000002003",
        company_id=company_id_3,
        accession_number="0001234567-25-001003",
        form_type="S-1",
        filing_date="2025-01-03",
        sec_html_url="https://sec.gov/test3.html",
        is_post_combination=False,
        is_investment_vehicle=False,
        is_resource_extraction=False,
    )

    # Filing 1: Table context with "before" direction (high precision)
    segment_1: SegmentDict = {
        "segment_id": 1,
        "section_name": "Results",
        "segment_type": "table",
        "raw_text": "Net revenue retention 115% for the year",
        "raw_html": "<table><tr><td>Net revenue retention</td><td>115%</td></tr></table>",
        "start_char": 0,
        "end_char": 39,
    }

    candidates_1 = generator.generate_for_filing(
        filing_id=filing_id_1,
        company_id=company_id_1,
        segments=[segment_1],
        db=db,
    )

    # Insert candidates using bulk insert
    candidate_dicts_1 = [c.to_dict() for c in candidates_1]
    candidate_ids_1 = db.bulk_insert_review_candidates(candidate_dicts_1)

    # Mark as reviewed and accept all table candidates
    for candidate_id in candidate_ids_1:
        db.update_candidate_status(candidate_id, "reviewed")
        db.insert_review_decision(
            candidate_id=candidate_id,
            decision="accept",
            assigned_metric_id="cm_net_revenue_retention",
        )

    filing_data.append((filing_id_1, company_id_1, candidate_ids_1))

    # Filing 2: Parenthetical context with "after" direction (medium precision)
    # Include multiple values to generate multiple candidates for accept/reject split
    segment_2: SegmentDict = {
        "segment_id": 2,
        "section_name": "Overview",
        "segment_type": "paragraph",
        "raw_text": "We achieved (115% net revenue retention) and (120% net revenue retention) during the period",
        "raw_html": "<p>We achieved (115% net revenue retention) and (120% net revenue retention) during the period</p>",
        "start_char": 0,
        "end_char": 91,
    }

    candidates_2 = generator.generate_for_filing(
        filing_id=filing_id_2,
        company_id=company_id_2,
        segments=[segment_2],
        db=db,
    )

    # Insert candidates using bulk insert
    candidate_dicts_2 = [c.to_dict() for c in candidates_2]
    candidate_ids_2 = db.bulk_insert_review_candidates(candidate_dicts_2)

    # Mark as reviewed and accept half, reject half
    for i, candidate_id in enumerate(candidate_ids_2):
        db.update_candidate_status(candidate_id, "reviewed")
        decision = "accept" if i % 2 == 0 else "reject"
        db.insert_review_decision(
            candidate_id=candidate_id,
            decision=decision,
            assigned_metric_id="cm_net_revenue_retention" if decision == "accept" else None,
            rejection_category="not_a_metric" if decision == "reject" else None,
        )

    filing_data.append((filing_id_2, company_id_2, candidate_ids_2))

    # Filing 3: Default context with "before" direction (low precision)
    segment_3: SegmentDict = {
        "segment_id": 3,
        "section_name": "Narrative",
        "segment_type": "paragraph",
        "raw_text": "The company improved its net revenue retention measurement levels by reaching 115 percent",
        "raw_html": "<p>The company improved its net revenue retention measurement levels by reaching 115 percent</p>",
        "start_char": 0,
        "end_char": 89,
    }

    candidates_3 = generator.generate_for_filing(
        filing_id=filing_id_3,
        company_id=company_id_3,
        segments=[segment_3],
        db=db,
    )

    # Insert candidates using bulk insert
    candidate_dicts_3 = [c.to_dict() for c in candidates_3]
    candidate_ids_3 = db.bulk_insert_review_candidates(candidate_dicts_3)

    # Mark as reviewed and reject all default context candidates
    for candidate_id in candidate_ids_3:
        db.update_candidate_status(candidate_id, "reviewed")
        db.insert_review_decision(
            candidate_id=candidate_id,
            decision="reject",
            rejection_category="not_a_metric",
        )

    filing_data.append((filing_id_3, company_id_3, candidate_ids_3))

    yield filing_data

    # Teardown: clean up decisions and candidates to avoid cross-test contamination
    all_candidate_ids = [cid for _, _, cids in filing_data for cid in cids]
    if all_candidate_ids:
        with db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM review_decisions WHERE candidate_id = ANY(%s)",
                    (all_candidate_ids,),
                )
                cur.execute(
                    "DELETE FROM review_candidates WHERE candidate_id = ANY(%s)",
                    (all_candidate_ids,),
                )


class TestContextPerformanceAnalysis:
    """Test context performance analysis for E1 multiplier optimization."""

    def test_analyze_context_performance_basic(self, db, analyzer, sample_candidates):
        """Basic context performance analysis returns expected structure."""
        results = analyzer.analyze_context_performance()

        # Check structure
        assert "total_decisions" in results
        assert "decisions_with_context" in results
        assert "context_stats" in results

        # Should have processed some decisions
        assert results["total_decisions"] > 0
        assert results["decisions_with_context"] > 0

        # Context stats should be dict of contexts
        assert isinstance(results["context_stats"], dict)

    def test_context_stats_structure(self, db, analyzer, sample_candidates):
        """Each context in stats has expected fields."""
        results = analyzer.analyze_context_performance()
        context_stats = results["context_stats"]

        # Check at least one context exists
        assert len(context_stats) > 0

        # Check structure of first context
        for _context_type, stats in context_stats.items():
            assert "total" in stats
            assert "accepted" in stats
            assert "rejected" in stats
            assert "precision" in stats
            assert "by_direction" in stats

            # Check direction breakdown
            by_direction = stats["by_direction"]
            for direction in ["before", "after", "unknown"]:
                assert direction in by_direction
                assert "total" in by_direction[direction]
                assert "accepted" in by_direction[direction]
                assert "precision" in by_direction[direction]

    def test_precision_calculation(self, db, analyzer, sample_candidates):
        """Precision is calculated correctly (accepted / total)."""
        results = analyzer.analyze_context_performance()
        context_stats = results["context_stats"]

        for context_type, stats in context_stats.items():
            total = stats["total"]
            accepted = stats["accepted"]
            rejected = stats["rejected"]
            precision = stats["precision"]

            # Total should equal accepted + rejected
            assert total == accepted + rejected, (
                f"Context {context_type}: total != accepted + rejected"
            )

            # Precision should be correct
            if total > 0:
                expected_precision = accepted / total
                assert abs(precision - expected_precision) < 0.001, (
                    f"Context {context_type}: precision mismatch"
                )

    def test_direction_breakdown(self, db, analyzer, sample_candidates):
        """Direction breakdown sums to total for each context."""
        results = analyzer.analyze_context_performance()
        context_stats = results["context_stats"]

        for context_type, stats in context_stats.items():
            total = stats["total"]
            by_direction = stats["by_direction"]

            # Sum of direction totals should equal context total
            direction_total = sum(by_direction[d]["total"] for d in ["before", "after", "unknown"])
            assert direction_total == total, (
                f"Context {context_type}: direction totals don't sum to context total"
            )

            # Sum of direction accepts should equal context accepts
            direction_accepts = sum(
                by_direction[d]["accepted"] for d in ["before", "after", "unknown"]
            )
            assert direction_accepts == stats["accepted"], (
                f"Context {context_type}: direction accepts don't sum to context accepts"
            )

    def test_table_context_high_precision(self, db, analyzer, sample_candidates):
        """Table context should show high precision (all accepted)."""
        results = analyzer.analyze_context_performance()
        context_stats = results["context_stats"]

        # Table context should exist and have high precision
        if "table" in context_stats:
            table_stats = context_stats["table"]
            assert table_stats["precision"] == 1.0, "Table context should have 100% precision"
            assert table_stats["rejected"] == 0, "Table context should have no rejections"

    def test_default_context_low_precision(self, db, analyzer, sample_candidates):
        """Default context should show low precision (all rejected)."""
        results = analyzer.analyze_context_performance()
        context_stats = results["context_stats"]

        # Default context should exist and have low precision
        if "default" in context_stats:
            default_stats = context_stats["default"]
            assert default_stats["precision"] == 0.0, "Default context should have 0% precision"
            assert default_stats["accepted"] == 0, "Default context should have no accepts"

    def test_parenthetical_context_medium_precision(self, db, analyzer, sample_candidates):
        """Parenthetical context should show medium precision (mixed decisions)."""
        results = analyzer.analyze_context_performance()
        context_stats = results["context_stats"]

        # Parenthetical context should exist and have some mix of accept/reject
        if "parenthetical" in context_stats:
            paren_stats = context_stats["parenthetical"]
            # Should be neither 0% nor 100% (has both accepts and rejects)
            # Note: aggregate precision may vary due to other test data in database
            assert 0.0 < paren_stats["precision"] < 1.0, (
                "Parenthetical context should have mixed precision (not 0% or 100%)"
            )

    def test_filter_by_filing_id(self, db, analyzer, sample_candidates):
        """Filtering by filing_id returns only decisions for that filing."""
        filing_id = sample_candidates[0][0]

        results = analyzer.analyze_context_performance(filing_id=filing_id)

        # Should have decisions
        assert results["total_decisions"] > 0

        # Should be fewer than analyzing all filings
        all_results = analyzer.analyze_context_performance()
        assert results["total_decisions"] <= all_results["total_decisions"]

    def test_filter_by_metric_id(self, db, analyzer, sample_candidates):
        """Filtering by metric_id returns only decisions for that metric."""
        # Use a common metric like 'cm_net_revenue_retention'
        results = analyzer.analyze_context_performance(metric_id="cm_net_revenue_retention")

        # Should have some decisions (all our test cases use net revenue retention)
        assert results["total_decisions"] > 0

        # Should be fewer or equal to all filings
        all_results = analyzer.analyze_context_performance()
        assert results["total_decisions"] <= all_results["total_decisions"]

    def test_empty_results(self, db, analyzer):
        """Returns empty structure when no decisions exist."""
        # Use non-existent filing_id
        results = analyzer.analyze_context_performance(filing_id=99999)

        assert results["total_decisions"] == 0
        assert results["decisions_with_context"] == 0
        assert results["context_stats"] == {}
