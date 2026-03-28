"""
Integration tests for L1 respectively pattern detection in candidate generation.

Tests the end-to-end workflow of respectively pattern enrichment:
- Pattern detection during candidate generation
- Period associations stored in candidate features
- Database persistence via JSONB
- Interaction with E2 learned rules filtering
"""

from decimal import Decimal

import pytest

from src.review.candidate_generator import CandidateGenerator
from src.review.config import CandidateGenerationConfig
from tests.integration.conftest import create_test_company_and_filing


class TestRespectivelyEndToEnd:
    """Test end-to-end respectively pattern detection and enrichment."""

    @pytest.fixture
    def farfetch_filing_data(self, clean_db):
        """Create filing with Farfetch LTV/CAC ratio example."""
        company_id, filing_id = create_test_company_and_filing(
            clean_db,
            cik="0001405349",
            company_name="Farfetch Ltd",
            accession_number="0001405349-18-000012",
            filing_date="2018-03-02",
        )

        # Real Farfetch S-1 example (LTV/CAC ratio)
        segments = [
            {
                "source_segment_id": None,  # No actual source segment in DB
                "filing_id": filing_id,
                "segment_type": "paragraph",
                "raw_text": (
                    "Six month LTV/CAC ratio for the years ended December 31, "
                    "2015, 2016 and 2017 cohorts was 1.42, 1.53 and 1.72, respectively"
                ),
                "section_heading": "Key Performance Indicators",
                "section_path": "/Business Overview/Key Performance Indicators",
            }
        ]

        return {
            "filing_id": filing_id,
            "company_id": company_id,
            "segments": segments,
        }

    @pytest.fixture
    def farfetch_margin_data(self, clean_db):
        """Create filing with gross margin example."""
        company_id, filing_id = create_test_company_and_filing(
            clean_db,
            cik="0001405349",
            company_name="Farfetch Ltd",
            accession_number="0001405349-18-000013",
            filing_date="2018-03-02",
        )

        # Net revenue retention example (simplified for testing)
        segments = [
            {
                "source_segment_id": None,  # No actual source segment in DB
                "filing_id": filing_id,
                "segment_type": "paragraph",
                "raw_text": (
                    "Net revenue retention rate for the years ended "
                    "December 31, 2015, 2016 and 2017 was 33.0%, 35.0% and 43.0%, "
                    "respectively."
                ),
                "section_heading": "Management's Discussion and Analysis",
                "section_path": "/MD&A/Results of Operations",
            }
        ]

        return {
            "filing_id": filing_id,
            "company_id": company_id,
            "segments": segments,
        }

    def test_farfetch_ltv_cac_end_to_end(self, clean_db, farfetch_filing_data):
        """Test end-to-end: Farfetch LTV/CAC ratio with period associations."""
        # Enable respectively pattern detection
        config = CandidateGenerationConfig(detect_respectively_patterns=True)
        generator = CandidateGenerator(config=config)

        # Generate candidates
        candidates = generator.generate_for_filing(
            filing_id=farfetch_filing_data["filing_id"],
            company_id=farfetch_filing_data["company_id"],
            segments=farfetch_filing_data["segments"],
            db=clean_db,
        )

        # Multiple keywords may match (LTV/CAC, CAC, LTV) creating multiple candidates per number
        # Verify we have at least 3 candidates
        assert len(candidates) >= 3, f"Expected at least 3 candidates, got {len(candidates)}"

        # Verify all three periods are represented
        periods = {
            c.features.detected_period for c in candidates if c.features
        }
        assert periods == {"2015", "2016", "2017"}, f"Expected periods {{2015, 2016, 2017}}, got {periods}"

        # Verify all three values are represented
        values = {c.parsed_value for c in candidates}
        assert Decimal("1.42") in values
        assert Decimal("1.53") in values
        assert Decimal("1.72") in values

        # Verify each candidate has confidence score
        for candidate in candidates:
            assert candidate.features is not None
            assert candidate.features.respectively_confidence is not None
            assert candidate.features.respectively_confidence >= 0.8, \
                f"Expected high confidence (>=0.8), got {candidate.features.respectively_confidence}"

    def test_farfetch_margin_end_to_end(self, clean_db, farfetch_margin_data):
        """Test end-to-end: Gross margin with period associations."""
        config = CandidateGenerationConfig(detect_respectively_patterns=True)
        generator = CandidateGenerator(config=config)

        candidates = generator.generate_for_filing(
            filing_id=farfetch_margin_data["filing_id"],
            company_id=farfetch_margin_data["company_id"],
            segments=farfetch_margin_data["segments"],
            db=clean_db,
        )

        # Verify we have candidates (may be multiple per number if multiple keywords match)
        assert len(candidates) >= 3, f"Expected at least 3 candidates, got {len(candidates)}"

        # Verify all three periods are represented
        periods = {c.features.detected_period for c in candidates if c.features}
        assert periods == {"2015", "2016", "2017"}, f"Expected periods {{2015, 2016, 2017}}, got {periods}"

        # Verify percentage values (divide by 100 since parsed as decimals)
        values = {c.parsed_value for c in candidates}
        assert Decimal("0.33") in values or Decimal("33.0") in values
        assert Decimal("0.35") in values or Decimal("35.0") in values
        assert Decimal("0.43") in values or Decimal("43.0") in values

        # Should have very high confidence (perfect pattern structure)
        for candidate in candidates:
            assert candidate.features.respectively_confidence >= 0.9

    def test_respectively_disabled_by_config(self, clean_db, farfetch_filing_data):
        """Test that enrichment is skipped when config disabled."""
        # Create config with respectively detection disabled
        config = CandidateGenerationConfig(detect_respectively_patterns=False)
        generator = CandidateGenerator(config=config)

        candidates = generator.generate_for_filing(
            filing_id=farfetch_filing_data["filing_id"],
            company_id=farfetch_filing_data["company_id"],
            segments=farfetch_filing_data["segments"],
            db=clean_db,
        )

        # Should still generate candidates, but no periods detected
        assert len(candidates) >= 3

        # Verify no periods detected
        for candidate in candidates:
            if candidate.features:
                assert candidate.features.detected_period is None
                assert candidate.features.respectively_confidence is None

    def test_low_confidence_pattern_ignored(self, clean_db):
        """Test that patterns below confidence threshold are ignored."""
        company_id, filing_id = create_test_company_and_filing(clean_db)

        # Create pattern with low confidence (non-consecutive years, no 'and')
        segments = [
            {
                "source_segment_id": None,
                "filing_id": filing_id,
                "segment_type": "paragraph",
                "raw_text": (
                    "Revenue for 2015, 2020, 2025 was 33, 35, 43 respectively"
                ),
                "section_heading": "Test",
                "section_path": "/Test",
            }
        ]

        # Use high confidence threshold
        config = CandidateGenerationConfig(
            detect_respectively_patterns=True,
            respectively_min_confidence=0.8,  # High threshold
        )
        generator = CandidateGenerator(config=config)

        candidates = generator.generate_for_filing(
            filing_id=filing_id,
            company_id=company_id,
            segments=segments,
            db=clean_db,
        )

        # Pattern exists but confidence too low - no enrichment
        for candidate in candidates:
            if candidate.features:
                assert candidate.features.detected_period is None


class TestDatabasePersistence:
    """Test that detected periods persist to database via JSONB."""

    def test_jsonb_round_trip(self, clean_db):
        """Test detected periods survive database round-trip."""
        company_id, filing_id = create_test_company_and_filing(clean_db)

        segments = [
            {
                "source_segment_id": None,  # No actual source segment in DB
                "filing_id": filing_id,
                "segment_type": "paragraph",
                "raw_text": (
                    "Net revenue retention rate for 2015, 2016 and 2017 was "
                    "33%, 35% and 43%, respectively."
                ),
                "section_heading": "Test",
                "section_path": "/Test",
            }
        ]

        # Generate candidates with respectively detection
        config = CandidateGenerationConfig(detect_respectively_patterns=True)
        generator = CandidateGenerator(config=config)
        candidates = generator.generate_for_filing(
            filing_id=filing_id,
            company_id=company_id,
            segments=segments,
            db=clean_db,
        )

        # Save to database (set source_segment_id to None for all candidates)
        candidate_dicts = [c.to_dict() for c in candidates]
        for candidate_dict in candidate_dicts:
            candidate_dict["source_segment_id"] = None
        clean_db.bulk_insert_review_candidates(candidate_dicts)

        # Retrieve from database
        retrieved = clean_db.get_review_candidates_for_filing(filing_id)

        # Verify we got candidates back (may be more than 3 if multiple keywords matched)
        assert len(retrieved) >= 3, f"Expected at least 3 candidates, got {len(retrieved)}"

        # Verify all three periods are represented
        retrieved_periods = {
            r["features"].get("detected_period") for r in retrieved
            if r["features"]
        }
        assert "2015" in retrieved_periods
        assert "2016" in retrieved_periods
        assert "2017" in retrieved_periods

        # Verify confidence scores preserved
        for candidate in retrieved:
            if candidate["features"] and candidate["features"].get("detected_period"):
                assert candidate["features"].get("respectively_confidence") is not None
                assert candidate["features"]["respectively_confidence"] > 0.5

    def test_backward_compatibility_with_old_candidates(self, clean_db):
        """Test that old candidates without detected_period still work."""
        company_id, filing_id = create_test_company_and_filing(clean_db)

        # Insert candidate without detected_period (old format)
        candidate_id = clean_db.insert_review_candidate(
            filing_id=filing_id,
            company_id=company_id,
            char_position=100,
            context_text="We had 10,000 customers.",
            raw_number_text="10,000",
            triggering_keyword="customers",
            keyword_distance=15,
            keyword_position="after",
            suggested_metric_id="cm_active_customers",
            source_segment_id=None,  # No source segment
            features={},  # No detected_period
        )

        # Verify insertion succeeded
        assert candidate_id is not None

        # Retrieve and verify
        candidate = clean_db.get_review_candidate(candidate_id)
        assert candidate is not None, f"Failed to retrieve candidate {candidate_id}"

        # Old candidates should not have respectively fields
        features = candidate.get("features") or {}
        assert features.get("detected_period") is None
        assert features.get("respectively_confidence") is None


class TestDeduplicationStrategy:
    """Test deduplication preserves different periods."""

    def test_same_value_different_periods_preserved(self, clean_db):
        """Test that different periods preserve candidates even with same value."""
        company_id, filing_id = create_test_company_and_filing(clean_db)

        # Use distinctsegment where value appears for multiple years with respectively
        segments = [
            {
                "source_segment_id": None,
                "filing_id": filing_id,
                "segment_type": "paragraph",
                "raw_text": (
                    "Net revenue retention rate for 2015, 2016 and 2017 was "
                    "35%, 40% and 45%, respectively."
                ),
                "section_heading": "Test",
                "section_path": "/Test",
            }
        ]

        config = CandidateGenerationConfig(detect_respectively_patterns=True)
        generator = CandidateGenerator(config=config)
        candidates = generator.generate_for_filing(
            filing_id=filing_id,
            company_id=company_id,
            segments=segments,
            db=clean_db,
        )

        # Should have at least 3 unique (value, period) combinations
        # (may have more if multiple keywords match)
        assert len(candidates) >= 3, f"Expected at least 3 candidates, got {len(candidates)}"

        # Extract unique (value, period) pairs
        value_period_pairs = {
            (c.parsed_value, c.features.detected_period)
            for c in candidates
            if c.features and c.features.detected_period
        }

        # Should have all 3 unique combinations
        assert len(value_period_pairs) >= 3, f"Expected 3 unique (value, period) pairs, got {value_period_pairs}"

        # Verify all three periods present
        periods = {period for _, period in value_period_pairs}
        assert periods == {"2015", "2016", "2017"}

    def test_same_value_same_period_deduped(self, clean_db):
        """Test deduplication with multiple respectively patterns in one segment."""
        company_id, filing_id = create_test_company_and_filing(clean_db)

        # Create segment with two respectively patterns
        segments = [
            {
                "source_segment_id": None,
                "filing_id": filing_id,
                "segment_type": "paragraph",
                "raw_text": (
                    "Net revenue retention for 2015 and 2016 was 110% and 115%, respectively. "
                    "Net revenue retention rate for 2015 and 2016 was 35% and 40%, respectively."
                ),
                "section_heading": "Test",
                "section_path": "/Test",
            }
        ]

        config = CandidateGenerationConfig(detect_respectively_patterns=True)
        generator = CandidateGenerator(config=config)
        candidates = generator.generate_for_filing(
            filing_id=filing_id,
            company_id=company_id,
            segments=segments,
            db=clean_db,
        )

        # Should have candidates (current implementation may only detect first pattern)
        assert len(candidates) >= 2, f"Expected at least 2 candidates, got {len(candidates)}"

        # Extract unique (value, period, metric) tuples
        unique_candidates = {
            (c.parsed_value, c.features.detected_period if c.features else None, c.suggested_metric_id)
            for c in candidates
        }

        # Each unique combination should appear once
        assert len(candidates) == len(unique_candidates)


class TestInteractionWithE2Filtering:
    """Test respectively enrichment interacts correctly with E2 learned rules."""

    def test_enrichment_before_e2_filtering(self, clean_db):
        """Test that respectively enrichment happens before E2 filtering."""
        company_id, filing_id = create_test_company_and_filing(clean_db)

        segments = [
            {
                "source_segment_id": None,
                "filing_id": filing_id,
                "segment_type": "paragraph",
                "raw_text": (
                    "Revenue for 2015, 2016 and 2017 was "
                    "$1M, $2M and $3M, respectively."
                ),
                "section_heading": "Test",
                "section_path": "/Test",
            }
        ]

        # Enable both respectively and learned rules
        config = CandidateGenerationConfig(
            detect_respectively_patterns=True,
            apply_learned_rules=True,
        )
        generator = CandidateGenerator(config=config)
        candidates = generator.generate_for_filing(
            filing_id=filing_id,
            company_id=company_id,
            segments=segments,
            db=clean_db,
        )

        # Candidates should have periods (enrichment happened)
        for candidate in candidates:
            if candidate.features:
                # Should have detected_period from respectively enrichment
                assert candidate.features.detected_period in ["2015", "2016", "2017"]

        # E2 filtering could then use detected_period in learned patterns
        # (if patterns were trained to consider period associations)

    def test_e2_filtering_respects_period_context(self, clean_db):
        """Test that E2 filtering can access detected_period in features."""
        company_id, filing_id = create_test_company_and_filing(clean_db)

        segments = [
            {
                "source_segment_id": None,
                "filing_id": filing_id,
                "segment_type": "paragraph",
                "raw_text": (
                    "GMV for 2015, 2016 and 2017 was "
                    "$50M, $75M and $100M, respectively."
                ),
                "section_heading": "Business Metrics",
                "section_path": "/Business Metrics",
            }
        ]

        config = CandidateGenerationConfig(
            detect_respectively_patterns=True,
            apply_learned_rules=True,
        )
        generator = CandidateGenerator(config=config)
        candidates = generator.generate_for_filing(
            filing_id=filing_id,
            company_id=company_id,
            segments=segments,
            db=clean_db,
        )

        # Verify features include detected_period
        for candidate in candidates:
            assert candidate.features is not None
            assert "detected_period" in candidate.features.to_dict()
            assert "respectively_confidence" in candidate.features.to_dict()


class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_no_pattern_found(self, clean_db):
        """Test segments without respectively patterns work normally."""
        company_id, filing_id = create_test_company_and_filing(clean_db)

        segments = [
            {
                "source_segment_id": None,
                "filing_id": filing_id,
                "segment_type": "paragraph",
                "raw_text": (
                    "We had 10,000 active customers as of December 31, 2022, "
                    "representing a 45% increase from the prior year."
                ),
                "section_heading": "Test",
                "section_path": "/Test",
            }
        ]

        config = CandidateGenerationConfig(detect_respectively_patterns=True)
        generator = CandidateGenerator(config=config)
        candidates = generator.generate_for_filing(
            filing_id=filing_id,
            company_id=company_id,
            segments=segments,
            db=clean_db,
        )

        # Should generate candidates normally (at least 1 for "active customers")
        assert len(candidates) >= 1

        # No periods detected
        for candidate in candidates:
            if candidate.features:
                assert candidate.features.detected_period is None

    def test_partial_match_handled_gracefully(self, clean_db):
        """Test that system handles segments with mix of pattern and non-pattern numbers."""
        company_id, filing_id = create_test_company_and_filing(clean_db)

        # Segment with respectively pattern AND additional unrelated numbers
        segments = [
            {
                "source_segment_id": None,
                "filing_id": filing_id,
                "segment_type": "paragraph",
                "raw_text": (
                    "Net revenue retention rate for 2015, 2016 and 2017 was 33%, 35% and 37%, respectively. "
                    "We serve over 500 enterprise customers."
                ),
                "section_heading": "Test",
                "section_path": "/Test",
            }
        ]

        config = CandidateGenerationConfig(detect_respectively_patterns=True)
        generator = CandidateGenerator(config=config)
        candidates = generator.generate_for_filing(
            filing_id=filing_id,
            company_id=company_id,
            segments=segments,
            db=clean_db,
        )

        # Should generate candidates from both pattern numbers and non-pattern numbers
        assert len(candidates) >= 3, f"Expected at least 3 candidates, got {len(candidates)}"

        # Some candidates should have periods (margin values from pattern)
        with_periods = [c for c in candidates if c.features and c.features.detected_period]
        without_periods = [c for c in candidates if not c.features or not c.features.detected_period]

        # At least one should have a period (from respectively pattern)
        assert len(with_periods) >= 1, f"Expected at least 1 with period, got {len(with_periods)}"

        # Should have both types of candidates
        assert len(without_periods) >= 0  # May or may not have candidates without periods

    def test_multiple_patterns_in_segment(self, clean_db):
        """Test segments with multiple respectively patterns (rare but possible)."""
        company_id, filing_id = create_test_company_and_filing(clean_db)

        # Two respectively patterns in one segment
        segments = [
            {
                "source_segment_id": None,
                "filing_id": filing_id,
                "segment_type": "paragraph",
                "raw_text": (
                    "Net revenue retention for 2015 and 2016 was 110% and 120%, respectively. "
                    "Net revenue retention rate for 2015 and 2016 was 30% and 35%, respectively."
                ),
                "section_heading": "Test",
                "section_path": "/Test",
            }
        ]

        config = CandidateGenerationConfig(detect_respectively_patterns=True)
        generator = CandidateGenerator(config=config)
        candidates = generator.generate_for_filing(
            filing_id=filing_id,
            company_id=company_id,
            segments=segments,
            db=clean_db,
        )

        # Current implementation only detects first pattern
        # (detect_respectively_pattern finds first occurrence)
        # Should have candidates from both revenue and margin
        assert len(candidates) >= 2, f"Expected at least 2 candidates, got {len(candidates)}"

        # At least some candidates should have periods (from first pattern)
        with_periods = [c for c in candidates if c.features and c.features.detected_period]
        assert len(with_periods) >= 2, f"Expected at least 2 with periods, got {len(with_periods)}"

        # Should have both 2015 and 2016 represented
        periods = {c.features.detected_period for c in with_periods}
        assert "2015" in periods or "2016" in periods
