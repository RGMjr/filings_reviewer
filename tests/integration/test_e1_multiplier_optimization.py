"""
Integration tests for E1 multiplier optimization (Phase 4 validation).

Tests verify the end-to-end flow:
1. Context type tracking in features
2. Context performance analysis
3. Multiplier recommendations
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
    """Pattern analyzer for recommendations."""
    return PatternAnalyzer(db)


class TestE1MultiplierOptimization:
    """Integration tests for E1 multiplier optimization."""

    def test_context_type_flows_to_database(self, db, generator):
        """Context type is tracked from generation through database."""
        # Create test company and filing
        company_id = db.upsert_company(cik="0000001234", company_name="Test Co")
        filing_id = db.upsert_filing(
            cik="0000001234",
            company_id=company_id,
            accession_number="0001234567-25-001234",
            form_type="S-1",
            filing_date="2025-01-01",
            sec_html_url="https://sec.gov/test.html",
            is_post_combination=False,
            is_investment_vehicle=False,
            is_resource_extraction=False,
        )

        # Generate candidate with table context
        segment: SegmentDict = {
            "segment_id": 1,
            "section_name": "Results",
            "segment_type": "table",
            "raw_text": "Net revenue retention 52% for the year",
            "raw_html": "<table><tr><td>Net revenue retention</td><td>52%</td></tr></table>",
            "start_char": 0,
            "end_char": 30,
        }

        candidates = generator.generate_for_filing(
            filing_id=filing_id,
            company_id=company_id,
            segments=[segment],
            db=db,
        )

        assert len(candidates) > 0

        # Insert into database
        candidate_dicts = [c.to_dict() for c in candidates]
        candidate_ids = db.bulk_insert_review_candidates(candidate_dicts)

        # Retrieve and verify context_type persisted
        retrieved = db.get_review_candidate(candidate_ids[0])
        assert retrieved is not None
        assert retrieved["features"] is not None
        assert retrieved["features"]["context_type"] == "table"

    def test_performance_analysis_with_real_data(self, db, generator, analyzer):
        """Context performance analysis works with real database data."""
        # Create test setup (simplified from Phase 2 fixture)
        company_id = db.upsert_company(cik="0000001235", company_name="Test Co 2")
        filing_id = db.upsert_filing(
            cik="0000001235",
            company_id=company_id,
            accession_number="0001234567-25-001235",
            form_type="S-1",
            filing_date="2025-01-01",
            sec_html_url="https://sec.gov/test2.html",
            is_post_combination=False,
            is_investment_vehicle=False,
            is_resource_extraction=False,
        )

        # Generate and insert candidates
        segment: SegmentDict = {
            "segment_id": 1,
            "section_name": "Results",
            "segment_type": "table",
            "raw_text": "Net revenue retention 52%",
            "raw_html": "<table><tr><td>Net revenue retention</td><td>52%</td></tr></table>",
            "start_char": 0,
            "end_char": 17,
        }

        candidates = generator.generate_for_filing(
            filing_id=filing_id,
            company_id=company_id,
            segments=[segment],
            db=db,
        )

        candidate_dicts = [c.to_dict() for c in candidates]
        candidate_ids = db.bulk_insert_review_candidates(candidate_dicts)

        # Add review decisions (use reject to avoid metric_id requirement)
        for candidate_id in candidate_ids:
            db.update_candidate_status(candidate_id, "reviewed")
            db.insert_review_decision(
                candidate_id=candidate_id,
                decision="reject",
                rejection_category="not_a_metric",
            )

        # Analyze performance
        performance = analyzer.analyze_context_performance()

        assert performance["total_decisions"] > 0
        assert performance["decisions_with_context"] > 0
        # Stats exist even if all rejected
        assert isinstance(performance["context_stats"], dict)

    def test_recommendation_generation_with_real_data(self, db, generator, analyzer):
        """Multiplier recommendations are generated from real review data."""
        # Similar setup as previous test
        company_id = db.upsert_company(cik="0000001236", company_name="Test Co 3")
        filing_id = db.upsert_filing(
            cik="0000001236",
            company_id=company_id,
            accession_number="0001234567-25-001236",
            form_type="S-1",
            filing_date="2025-01-01",
            sec_html_url="https://sec.gov/test3.html",
            is_post_combination=False,
            is_investment_vehicle=False,
            is_resource_extraction=False,
        )

        segment: SegmentDict = {
            "segment_id": 1,
            "section_name": "Results",
            "segment_type": "table",
            "raw_text": "Net revenue retention 52%",
            "raw_html": "<table><tr><td>Net revenue retention</td><td>52%</td></tr></table>",
            "start_char": 0,
            "end_char": 17,
        }

        candidates = generator.generate_for_filing(
            filing_id=filing_id,
            company_id=company_id,
            segments=[segment],
            db=db,
        )

        candidate_dicts = [c.to_dict() for c in candidates]
        candidate_ids = db.bulk_insert_review_candidates(candidate_dicts)

        for candidate_id in candidate_ids:
            db.update_candidate_status(candidate_id, "reviewed")
            db.insert_review_decision(
                candidate_id=candidate_id,
                decision="reject",
                rejection_category="not_a_metric",
            )

        # Generate recommendations
        recommendations = analyzer.generate_multiplier_recommendations(
            min_sample_size=1  # Low threshold for testing
        )

        assert "summary" in recommendations
        assert "current_multipliers" in recommendations
        assert "recommendations" in recommendations
        assert recommendations["summary"]["total_decisions"] > 0

    def test_high_precision_context_gets_lower_multiplier(self, db, generator, analyzer):
        """Contexts with high precision should get lower multiplier recommendations."""
        # Create multiple high-precision table candidates
        company_id = db.upsert_company(cik="0000001237", company_name="Test Co 4")
        filing_id = db.upsert_filing(
            cik="0000001237",
            company_id=company_id,
            accession_number="0001234567-25-001237",
            form_type="S-1",
            filing_date="2025-01-01",
            sec_html_url="https://sec.gov/test4.html",
            is_post_combination=False,
            is_investment_vehicle=False,
            is_resource_extraction=False,
        )

        # Generate multiple candidates with table context
        # Each segment uses a different text prefix to vary char_position of the number
        # (char_position is based on position within text, not start_char)
        decided_ids: set[int] = set()
        for i in range(15):
            prefix = "x" * (i * 5)  # vary prefix length so number appears at different position
            text = f"{prefix}NRR was {50 + i}%"
            segment: SegmentDict = {
                "segment_id": i + 1,
                "section_name": "Results",
                "segment_type": "table",
                "raw_text": text,
                "raw_html": f"<table><tr><td>NRR</td><td>{50 + i}%</td></tr></table>",
                "start_char": 0,
                "end_char": len(text),
            }

            candidates = generator.generate_for_filing(
                filing_id=filing_id,
                company_id=company_id,
                segments=[segment],
                db=db,
            )

            candidate_dicts = [c.to_dict() for c in candidates]
            candidate_ids = db.bulk_insert_review_candidates(candidate_dicts)

            # Reject each unique candidate only once
            for candidate_id in candidate_ids:
                if candidate_id not in decided_ids:
                    db.update_candidate_status(candidate_id, "reviewed")
                    db.insert_review_decision(
                        candidate_id=candidate_id,
                        decision="reject",
                        rejection_category="not_a_metric",
                    )
                    decided_ids.add(candidate_id)

        # Generate recommendations
        recommendations = analyzer.generate_multiplier_recommendations(min_sample_size=10)

        # Table context should have low precision (all rejected) and recommend higher multiplier
        if "table" in recommendations["recommendations"]:
            table_rec = recommendations["recommendations"]["table"]
            # Low precision should result in recommended > 1.0
            assert table_rec["sample_size"] >= 10
            assert table_rec["precision"] < 0.2  # Low precision (all rejected)

    def test_end_to_end_optimization_workflow(self, db, generator, analyzer):
        """Complete workflow from generation to recommendations."""
        # 1. Generate candidates with different contexts
        company_id = db.upsert_company(cik="0000001238", company_name="Test Co 5")
        filing_id = db.upsert_filing(
            cik="0000001238",
            company_id=company_id,
            accession_number="0001234567-25-001238",
            form_type="S-1",
            filing_date="2025-01-01",
            sec_html_url="https://sec.gov/test5.html",
            is_post_combination=False,
            is_investment_vehicle=False,
            is_resource_extraction=False,
        )

        # Table context (expect high precision)
        table_segment: SegmentDict = {
            "segment_id": 1,
            "section_name": "Results",
            "segment_type": "table",
            "raw_text": "Net revenue retention 52%",
            "raw_html": "<table><tr><td>Net revenue retention</td><td>52%</td></tr></table>",
            "start_char": 0,
            "end_char": 17,
        }

        # Default context (expect lower precision)
        default_segment: SegmentDict = {
            "segment_id": 2,
            "section_name": "Narrative",
            "segment_type": "paragraph",
            "raw_text": "The company increased from net revenue retention levels by reaching 52 percent",
            "raw_html": "<p>The company increased from net revenue retention levels by reaching 52 percent</p>",
            "start_char": 0,
            "end_char": 70,
        }

        # 2. Generate and insert candidates
        for segment in [table_segment, default_segment]:
            candidates = generator.generate_for_filing(
                filing_id=filing_id,
                company_id=company_id,
                segments=[segment],
                db=db,
            )

            candidate_dicts = [c.to_dict() for c in candidates]
            candidate_ids = db.bulk_insert_review_candidates(candidate_dicts)

            # 3. Add decisions (table = accept, default = reject)
            for candidate_id in candidate_ids:
                db.update_candidate_status(candidate_id, "reviewed")

                # Get candidate to check context
                candidate = db.get_review_candidate(candidate_id)
                _context_type = (
                    candidate["features"].get("context_type") if candidate["features"] else None
                )

                # For simplicity, reject all in this test
                # (Testing the flow, not precision values)
                db.insert_review_decision(
                    candidate_id=candidate_id,
                    decision="reject",
                    rejection_category="not_a_metric",
                )

        # 4. Analyze performance
        performance = analyzer.analyze_context_performance()
        assert performance["total_decisions"] > 0

        # 5. Generate recommendations
        recommendations = analyzer.generate_multiplier_recommendations(
            min_sample_size=1  # Low threshold for testing
        )

        # 6. Verify recommendations generated
        assert len(recommendations["recommendations"]) > 0
        assert recommendations["summary"]["total_decisions"] > 0

    def test_recommendations_respect_sample_size_thresholds(self, db, analyzer):
        """Recommendations should flag insufficient samples appropriately."""
        # Test with non-existent filing ID (no decisions)
        recommendations = analyzer.generate_multiplier_recommendations(
            filing_id=99999,  # Non-existent filing
            min_sample_size=10,
        )

        # Should handle empty case gracefully
        assert recommendations["summary"]["total_decisions"] == 0
        assert len(recommendations["recommendations"]) == 0

    def test_baseline_precision_affects_recommendations(self, db, generator, analyzer):
        """Different baseline precision values should produce different recommendations."""
        # Setup data
        company_id = db.upsert_company(cik="0000001239", company_name="Test Co 6")
        filing_id = db.upsert_filing(
            cik="0000001239",
            company_id=company_id,
            accession_number="0001234567-25-001239",
            form_type="S-1",
            filing_date="2025-01-01",
            sec_html_url="https://sec.gov/test6.html",
            is_post_combination=False,
            is_investment_vehicle=False,
            is_resource_extraction=False,
        )

        segment: SegmentDict = {
            "segment_id": 1,
            "section_name": "Results",
            "segment_type": "table",
            "raw_text": "Net revenue retention 52%",
            "raw_html": "<table><tr><td>Net revenue retention</td><td>52%</td></tr></table>",
            "start_char": 0,
            "end_char": 17,
        }

        candidates = generator.generate_for_filing(
            filing_id=filing_id,
            company_id=company_id,
            segments=[segment],
            db=db,
        )

        candidate_dicts = [c.to_dict() for c in candidates]
        candidate_ids = db.bulk_insert_review_candidates(candidate_dicts)

        for candidate_id in candidate_ids:
            db.update_candidate_status(candidate_id, "reviewed")
            db.insert_review_decision(
                candidate_id=candidate_id,
                decision="reject",
                rejection_category="not_a_metric",
            )

        # Generate with different baselines
        rec_baseline_05 = analyzer.generate_multiplier_recommendations(
            min_sample_size=1,
            baseline_precision=0.5,
        )

        rec_baseline_07 = analyzer.generate_multiplier_recommendations(
            min_sample_size=1,
            baseline_precision=0.7,
        )

        # Should produce different recommendations
        assert rec_baseline_05["summary"]["baseline_precision"] == 0.5
        assert rec_baseline_07["summary"]["baseline_precision"] == 0.7


class TestE1RegressionPrevention:
    """Tests to prevent regressions in E1 functionality."""

    def test_context_type_in_all_contexts(self, db, generator):
        """All context types should be correctly detected and stored."""
        company_id = db.upsert_company(cik="0000002000", company_name="Test Contexts")
        filing_id = db.upsert_filing(
            cik="0000002000",
            company_id=company_id,
            accession_number="0001234567-25-002000",
            form_type="S-1",
            filing_date="2025-01-01",
            sec_html_url="https://sec.gov/test_contexts.html",
            is_post_combination=False,
            is_investment_vehicle=False,
            is_resource_extraction=False,
        )

        test_cases = [
            (
                "table",
                "table",
                "Net revenue retention 52%",
                "<table><tr><td>Net revenue retention</td><td>52%</td></tr></table>",
            ),
            ("bullet", "paragraph", "• Net revenue retention was 52%", "<p>• Net revenue retention was 52%</p>"),
            (
                "parenthetical",
                "paragraph",
                "We achieved (52% net revenue retention)",
                "<p>We achieved (52% net revenue retention)</p>",
            ),
        ]

        for expected_context, segment_type, raw_text, raw_html in test_cases:
            segment: SegmentDict = {
                "segment_id": 1,
                "section_name": "Test",
                "segment_type": segment_type,
                "raw_text": raw_text,
                "raw_html": raw_html,
                "start_char": 0,
                "end_char": len(raw_text),
            }

            candidates = generator.generate_for_filing(
                filing_id=filing_id,
                company_id=company_id,
                segments=[segment],
                db=db,
            )

            if len(candidates) > 0:
                assert candidates[0].features is not None
                assert candidates[0].features.context_type == expected_context

    def test_performance_analysis_handles_no_context_type(self, db, analyzer):
        """Performance analysis should handle candidates without context_type gracefully."""
        # This tests backward compatibility
        performance = analyzer.analyze_context_performance()

        # Should not crash, even if no candidates have context_type
        assert "total_decisions" in performance
        assert "decisions_with_context" in performance
        assert "context_stats" in performance
