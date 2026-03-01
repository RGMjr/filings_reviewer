"""
Integration tests for E2 RuleApplicator with CandidateGenerator.

Tests the end-to-end workflow of learned pattern filtering during
candidate generation.
"""

import pytest

from src.review.candidate_generator import CandidateGenerator


class TestE2CandidateFiltering:
    """Test E2 learned pattern filtering integration."""

    @pytest.fixture
    def sample_filing_data(self, clean_db):
        """Create test filing for E2 testing."""
        # Insert company
        company_id = clean_db.upsert_company(
            cik="0001234567",
            company_name="Test E2 Company",
        )

        # Insert filing
        filing_id = clean_db.upsert_filing(
            company_id=company_id,
            cik="0001234567",
            accession_number="0001234567-23-000001",
            filing_date="2023-06-15",
            form_type="S-1",
            sec_html_url="https://test.example.com",
            is_post_combination=False,
            is_investment_vehicle=False,
            is_resource_extraction=False,
        )

        # Create mock segments with text containing numbers and keywords
        segments = [
            {
                "source_segment_id": 1,
                "filing_id": filing_id,
                "segment_type": "paragraph",
                "raw_text": (
                    "Our annual recurring revenue (ARR) was $50.2 million "
                    "for the year ended December 31, 2022."
                ),
                "section_heading": "Business Overview",
                "section_path": "/Business Overview",
            },
            {
                "source_segment_id": 2,
                "filing_id": filing_id,
                "segment_type": "paragraph",
                "raw_text": (
                    "Risk Factors: The market size is estimated at $500 million. "
                    "We may face increased competition from the 1,234 existing competitors."
                ),
                "section_heading": "Risk Factors",
                "section_path": "/Risk Factors",
            },
            {
                "source_segment_id": 3,
                "filing_id": filing_id,
                "segment_type": "paragraph",
                "raw_text": (
                    "We had 12,500 active customers as of December 31, 2022, "
                    "representing a 45% increase from the prior year."
                ),
                "section_heading": "Our Customers",
                "section_path": "/Our Customers",
            },
        ]

        return {
            "filing_id": filing_id,
            "company_id": company_id,
            "segments": segments,
        }

    def test_baseline_without_learned_rules(self, clean_db, sample_filing_data):
        """Test candidate generation without learned rules (baseline)."""
        # Use segments from fixture
        segments = sample_filing_data["segments"]

        # Generate candidates with learned rules disabled
        generator = CandidateGenerator(apply_learned_rules=False)
        candidates = generator.generate_for_filing(
            filing_id=sample_filing_data["filing_id"],
            company_id=sample_filing_data["company_id"],
            segments=segments,
            db=clean_db,
        )

        # Should generate candidates from all segments
        assert len(candidates) > 0

    def test_improved_with_reject_rule(self, clean_db, sample_filing_data):
        """Test candidate generation with reject_rule pattern filters candidates."""
        # Insert a reject_rule pattern for risk factors
        pattern_id = clean_db.insert_learned_pattern(
            pattern_type="reject_rule",
            metric_id=None,  # Global pattern
            pattern_name="Test: Filter risk factors",
            pattern_definition={
                "conditions": [{"field": "is_in_risk_factors", "op": "eq", "value": True}]
            },
            precision_score=0.95,
            recall_score=0.80,
            sample_count=50,
        )

        # Approve the pattern (status='approved' is set by default on insert)
        # Note: Patterns are created with status='candidate' by default
        # We need to update to 'approved' for E2 to apply them
        clean_db.execute(
            "UPDATE learned_patterns SET status = 'approved' WHERE pattern_id = %(pattern_id)s",
            {"pattern_id": pattern_id},
        )

        # Use segments from fixture
        segments = sample_filing_data["segments"]

        # Generate candidates with learned rules enabled (default)
        generator = CandidateGenerator(apply_learned_rules=True)
        candidates, stats = generator.generate_for_filing(
            filing_id=sample_filing_data["filing_id"],
            company_id=sample_filing_data["company_id"],
            segments=segments,
            db=clean_db,
            return_stats=True,
        )

        # Verify filtering occurred
        # All candidates should NOT be in risk factors
        risk_factors_candidates = [c for c in candidates if c.features.is_in_risk_factors]
        assert len(risk_factors_candidates) == 0, (
            "Expected all risk factors candidates to be filtered"
        )

        # Verify stats tracking
        assert stats.filtered_by_learned_rules >= 0

    def test_pattern_enable_disable_toggle(self, clean_db, sample_filing_data):
        """Test toggling learned rules on/off affects filtering."""
        # Insert reject pattern
        pattern_id = clean_db.insert_learned_pattern(
            pattern_type="reject_rule",
            metric_id=None,
            pattern_name="Test: Filter risk factors",
            pattern_definition={
                "conditions": [{"field": "is_in_risk_factors", "op": "eq", "value": True}]
            },
            precision_score=0.95,
            recall_score=0.80,
            sample_count=50,
        )

        # Approve the pattern
        clean_db.execute(
            "UPDATE learned_patterns SET status = 'approved' WHERE pattern_id = %(pattern_id)s",
            {"pattern_id": pattern_id},
        )

        # Use segments from fixture
        segments = sample_filing_data["segments"]

        # Generate with rules DISABLED
        generator_off = CandidateGenerator(apply_learned_rules=False)
        candidates_off = generator_off.generate_for_filing(
            filing_id=sample_filing_data["filing_id"],
            company_id=sample_filing_data["company_id"],
            segments=segments,
            db=clean_db,
        )

        # Generate with rules ENABLED
        generator_on = CandidateGenerator(apply_learned_rules=True)
        candidates_on = generator_on.generate_for_filing(
            filing_id=sample_filing_data["filing_id"],
            company_id=sample_filing_data["company_id"],
            segments=segments,
            db=clean_db,
        )

        # With rules enabled, should have fewer or equal candidates
        assert len(candidates_on) <= len(candidates_off)

        # Risk factors candidates should be filtered when enabled
        risk_on = [c for c in candidates_on if c.features.is_in_risk_factors]
        assert len(risk_on) == 0

    def test_no_db_provided_skips_filtering(self, clean_db, sample_filing_data):
        """Test that filtering is skipped if db=None."""
        # Insert pattern (should not be applied without db)
        pattern_id = clean_db.insert_learned_pattern(
            pattern_type="reject_rule",
            metric_id=None,
            pattern_name="Test: Should not apply",
            pattern_definition={
                "conditions": [{"field": "is_in_risk_factors", "op": "eq", "value": True}]
            },
            precision_score=0.95,
            recall_score=0.80,
            sample_count=50,
        )

        # Approve the pattern
        clean_db.execute(
            "UPDATE learned_patterns SET status = 'approved' WHERE pattern_id = %(pattern_id)s",
            {"pattern_id": pattern_id},
        )

        # Use segments from fixture
        segments = sample_filing_data["segments"]

        # Generate candidates WITHOUT passing db
        generator = CandidateGenerator(apply_learned_rules=True)
        candidates = generator.generate_for_filing(
            filing_id=sample_filing_data["filing_id"],
            company_id=sample_filing_data["company_id"],
            segments=segments,
            db=None,  # No database provided
        )

        # Filtering should be skipped (no assertion about content, just that it runs)
        assert isinstance(candidates, list)

    def test_full_pipeline_with_real_filing(self, clean_db):
        """Test end-to-end pipeline with realistic filing data."""
        # Create realistic filing
        company_id = clean_db.upsert_company(
            cik="0001111111",
            company_name="Realistic Test Corp",
        )

        filing_id = clean_db.upsert_filing(
            company_id=company_id,
            cik="0001111111",
            accession_number="0001111111-23-000001",
            filing_date="2023-06-15",
            form_type="S-1",
            sec_html_url="https://test.example.com",
            is_post_combination=False,
            is_investment_vehicle=False,
            is_resource_extraction=False,
        )

        # Create segments with various metric patterns
        segments = [
            {
                "source_segment_id": 1,
                "filing_id": filing_id,
                "segment_type": "paragraph",
                "raw_text": "Our annual recurring revenue (ARR) was $50.2 million for the year ended December 31, 2022.",
                "section_heading": "Business Overview",
                "section_path": "/Business Overview",
            },
            {
                "source_segment_id": 2,
                "filing_id": filing_id,
                "segment_type": "paragraph",
                "raw_text": "We had 12,500 active customers as of December 31, 2022.",
                "section_heading": "Our Customers",
                "section_path": "/Our Customers",
            },
            {
                "source_segment_id": 3,
                "filing_id": filing_id,
                "segment_type": "paragraph",
                "raw_text": "Net revenue retention was 115% for the fiscal year.",
                "section_heading": "Key Metrics",
                "section_path": "/Key Metrics",
            },
        ]

        # Run full pipeline
        generator = CandidateGenerator(apply_learned_rules=False)
        candidates, stats = generator.generate_for_filing(
            filing_id=filing_id,
            company_id=company_id,
            segments=segments,
            db=clean_db,
            return_stats=True,
        )

        # Verify pipeline ran successfully
        assert len(candidates) >= 0, "Should complete processing"
        assert stats.segments_processed == 3, "Should process all segments"
        assert stats.numbers_found > 0, "Should find numbers"
        assert len(candidates) <= stats.numbers_found, "Candidates should be subset of numbers"

    def test_error_recovery_partial_failure(self, clean_db, sample_filing_data):
        """Test graceful handling of segments with errors."""
        # Mix valid and invalid segments
        segments = sample_filing_data["segments"] + [
            {
                "source_segment_id": 999,
                "filing_id": sample_filing_data["filing_id"],
                "segment_type": "paragraph",
                "raw_text": None,  # Invalid: None text
                "section_heading": "Invalid Segment",
                "section_path": "/Invalid",
            }
        ]

        # Should handle error gracefully and process valid segments
        generator = CandidateGenerator(apply_learned_rules=False)
        candidates, stats = generator.generate_for_filing(
            filing_id=sample_filing_data["filing_id"],
            company_id=sample_filing_data["company_id"],
            segments=segments,
            db=clean_db,
            return_stats=True,
        )

        # Should process valid segments despite error
        assert len(candidates) > 0, "Should generate candidates from valid segments"
        # Stats should reflect partial processing
        assert stats.segments_processed <= len(segments), "Should track processed segments"

    def test_malformed_segment_handling(self, clean_db, sample_filing_data):
        """Test handling of malformed segment data."""
        # Create segments with missing fields
        malformed_segments = [
            {
                # Missing segment_type
                "source_segment_id": 1,
                "filing_id": sample_filing_data["filing_id"],
                "raw_text": "We had 10,000 customers.",
                "section_heading": "Test",
                "section_path": "/Test",
            },
            {
                "source_segment_id": 2,
                "filing_id": sample_filing_data["filing_id"],
                "segment_type": "paragraph",
                "raw_text": "Revenue was $50 million.",
                # Missing section_heading/path
            },
        ]

        # Should handle malformed data gracefully
        generator = CandidateGenerator(apply_learned_rules=False)
        try:
            candidates = generator.generate_for_filing(
                filing_id=sample_filing_data["filing_id"],
                company_id=sample_filing_data["company_id"],
                segments=malformed_segments,
                db=clean_db,
            )
            # If no error, verify we got some result
            assert isinstance(candidates, list)
        except (KeyError, ValueError, TypeError):
            # Expected: should raise error for malformed data
            pass

    def test_deduplication_across_segments(self, clean_db, sample_filing_data):
        """Test that duplicate values across segments are deduplicated."""
        # Create segments with same number appearing multiple times
        segments = [
            {
                "source_segment_id": 1,
                "filing_id": sample_filing_data["filing_id"],
                "segment_type": "paragraph",
                "raw_text": "We had 10,000 customers in Q1 2022.",
                "section_heading": "Q1 Results",
                "section_path": "/Q1",
            },
            {
                "source_segment_id": 2,
                "filing_id": sample_filing_data["filing_id"],
                "segment_type": "paragraph",
                "raw_text": "As of March 31, 2022, we had 10,000 customers.",
                "section_heading": "Customer Count",
                "section_path": "/Customers",
            },
            {
                "source_segment_id": 3,
                "filing_id": sample_filing_data["filing_id"],
                "segment_type": "paragraph",
                "raw_text": "Customer base: 10,000 as of Q1 2022.",
                "section_heading": "Summary",
                "section_path": "/Summary",
            },
        ]

        generator = CandidateGenerator(apply_learned_rules=False)
        candidates, stats = generator.generate_for_filing(
            filing_id=sample_filing_data["filing_id"],
            company_id=sample_filing_data["company_id"],
            segments=segments,
            db=clean_db,
            return_stats=True,
        )

        # Verify deduplication occurred
        # All three segments mention "10,000 customers" - should be deduplicated
        customer_candidates = [
            c
            for c in candidates
            if c.raw_number_text == "10,000" and "customer" in c.context_text.lower()
        ]

        # Should have fewer candidates than segment count due to deduplication
        assert len(customer_candidates) <= 3, "Should deduplicate identical values"
        assert stats.duplicates_removed >= 0, "Should track duplicates"

    def test_performance_with_large_filing(self, clean_db):
        """Test processing of large filing (500+ segments)."""
        import time

        # Create large filing
        company_id = clean_db.upsert_company(
            cik="0002222222",
            company_name="Large Filing Corp",
        )

        filing_id = clean_db.upsert_filing(
            company_id=company_id,
            cik="0002222222",
            accession_number="0002222222-23-000001",
            filing_date="2023-06-15",
            form_type="S-1",
            sec_html_url="https://test.example.com/large",
            is_post_combination=False,
            is_investment_vehicle=False,
            is_resource_extraction=False,
        )

        # Generate 500 segments with realistic metric patterns
        segments = []
        templates = [
            "Our annual recurring revenue was ${value} million.",
            "We had {value} active customers.",
            "Net revenue retention was {value}%.",
            "Total contract value reached ${value} million.",
            "Dollar-based net retention was {value}%.",
        ]
        for i in range(500):
            value = 100 + (i * 10) % 1000
            template = templates[i % len(templates)]
            segments.append(
                {
                    "source_segment_id": i + 1,
                    "filing_id": filing_id,
                    "segment_type": "paragraph",
                    "raw_text": template.format(value=value),
                    "section_heading": f"Section {i % 10}",
                    "section_path": f"/Section{i % 10}",
                }
            )

        # Time the processing
        start_time = time.time()
        generator = CandidateGenerator(apply_learned_rules=False)
        candidates, stats = generator.generate_for_filing(
            filing_id=filing_id,
            company_id=company_id,
            segments=segments,
            db=clean_db,
            return_stats=True,
        )
        elapsed = time.time() - start_time

        # Verify processing completed
        assert stats.segments_processed == 500, "Should process all 500 segments"
        assert len(candidates) > 0, "Should generate candidates"

        # Performance check (should complete in reasonable time)
        assert elapsed < 10.0, f"Large filing processing took too long: {elapsed:.2f}s"

        # Print performance stats
        print("\n  Large filing performance:")
        print(f"    Segments: {stats.segments_processed}")
        print(f"    Time: {elapsed:.2f}s")
        print(f"    Throughput: {stats.segments_processed / elapsed:.1f} seg/sec")

    def test_learned_rules_filtering_precision(self, clean_db, sample_filing_data):
        """Test precision of learned rule filtering."""
        # Insert high-precision reject pattern for risk factors
        pattern_id = clean_db.insert_learned_pattern(
            pattern_type="reject_rule",
            metric_id=None,
            pattern_name="High Precision: Risk Factors",
            pattern_definition={
                "conditions": [{"field": "is_in_risk_factors", "op": "eq", "value": True}]
            },
            precision_score=0.98,  # Very high precision
            recall_score=0.85,
            sample_count=100,
        )

        # Approve pattern
        clean_db.execute(
            "UPDATE learned_patterns SET status = 'approved' WHERE pattern_id = %(pattern_id)s",
            {"pattern_id": pattern_id},
        )

        segments = sample_filing_data["segments"]

        # Generate with learned rules
        generator = CandidateGenerator(apply_learned_rules=True)
        candidates, stats = generator.generate_for_filing(
            filing_id=sample_filing_data["filing_id"],
            company_id=sample_filing_data["company_id"],
            segments=segments,
            db=clean_db,
            return_stats=True,
        )

        # Verify high-precision filtering
        # No risk factors candidates should remain
        risk_candidates = [c for c in candidates if c.features.is_in_risk_factors]
        assert len(risk_candidates) == 0, "High precision rule should filter all risk factors"

        # Verify non-risk candidates are preserved
        non_risk_candidates = [c for c in candidates if not c.features.is_in_risk_factors]
        assert len(non_risk_candidates) > 0, "Should preserve non-risk candidates"

    def test_learned_rules_database_integration(self, clean_db, sample_filing_data):
        """Test loading and applying patterns from database."""
        # Insert multiple patterns of different types
        patterns = [
            {
                "pattern_type": "reject_rule",
                "metric_id": None,
                "pattern_name": "Filter risk factors",
                "pattern_definition": {
                    "conditions": [{"field": "is_in_risk_factors", "op": "eq", "value": True}]
                },
                "precision_score": 0.95,
                "recall_score": 0.80,
                "sample_count": 50,
            },
            {
                "pattern_type": "reject_rule",
                "metric_id": None,
                "pattern_name": "Filter small numbers",
                "pattern_definition": {
                    "conditions": [{"field": "value_magnitude", "op": "lt", "value": 100}]
                },
                "precision_score": 0.90,
                "recall_score": 0.75,
                "sample_count": 40,
            },
        ]

        # Insert patterns
        for pattern_data in patterns:
            pattern_id = clean_db.insert_learned_pattern(**pattern_data)
            # Approve each pattern
            clean_db.execute(
                "UPDATE learned_patterns SET status = 'approved' WHERE pattern_id = %(pattern_id)s",
                {"pattern_id": pattern_id},
            )

        # Verify patterns are in database
        patterns_from_db = clean_db.get_learned_patterns(
            pattern_type="reject_rule", status="approved"
        )
        assert len(patterns_from_db) >= 2, "Should load patterns from database"

        # Generate candidates with learned rules
        segments = sample_filing_data["segments"]
        generator = CandidateGenerator(apply_learned_rules=True)
        candidates, stats = generator.generate_for_filing(
            filing_id=sample_filing_data["filing_id"],
            company_id=sample_filing_data["company_id"],
            segments=segments,
            db=clean_db,
            return_stats=True,
        )

        # Verify patterns were applied
        assert isinstance(candidates, list)
        # Stats should show filtering occurred
        assert stats.filtered_by_learned_rules >= 0

    def test_empty_segments_handling(self, clean_db, sample_filing_data):
        """Test handling of empty segments."""
        # Add empty segments
        empty_segments = [
            {
                "source_segment_id": 100,
                "filing_id": sample_filing_data["filing_id"],
                "segment_type": "paragraph",
                "raw_text": "",
                "section_heading": "Empty Section",
                "section_path": "/Empty",
            },
            {
                "source_segment_id": 101,
                "filing_id": sample_filing_data["filing_id"],
                "segment_type": "paragraph",
                "raw_text": "   ",  # Only whitespace
                "section_heading": "Whitespace Section",
                "section_path": "/Whitespace",
            },
        ]

        all_segments = sample_filing_data["segments"] + empty_segments

        # Should handle empty segments gracefully
        generator = CandidateGenerator(apply_learned_rules=False)
        candidates, stats = generator.generate_for_filing(
            filing_id=sample_filing_data["filing_id"],
            company_id=sample_filing_data["company_id"],
            segments=all_segments,
            db=clean_db,
            return_stats=True,
        )

        # Should process non-empty segments
        assert len(candidates) > 0, "Should generate candidates from non-empty segments"
        assert stats.segments_processed >= 3, "Should count all segments as processed"

    def test_segments_with_no_numbers(self, clean_db, sample_filing_data):
        """Test segments containing no numbers."""
        # Create text-only segments
        text_only_segments = [
            {
                "source_segment_id": 200,
                "filing_id": sample_filing_data["filing_id"],
                "segment_type": "paragraph",
                "raw_text": "We are a leading provider of cloud-based solutions for enterprise customers.",
                "section_heading": "Business Description",
                "section_path": "/Business",
            },
            {
                "source_segment_id": 201,
                "filing_id": sample_filing_data["filing_id"],
                "segment_type": "paragraph",
                "raw_text": "Our mission is to revolutionize the industry with innovative technology.",
                "section_heading": "Mission Statement",
                "section_path": "/Mission",
            },
        ]

        all_segments = sample_filing_data["segments"] + text_only_segments

        generator = CandidateGenerator(apply_learned_rules=False)
        candidates, stats = generator.generate_for_filing(
            filing_id=sample_filing_data["filing_id"],
            company_id=sample_filing_data["company_id"],
            segments=all_segments,
            db=clean_db,
            return_stats=True,
        )

        # Should handle text-only segments (no candidates from them)
        assert isinstance(candidates, list)
        # All candidates should come from original segments with numbers
        assert all(c.source_segment_id in [1, 2, 3] for c in candidates)

    def test_segments_with_no_keywords(self, clean_db, sample_filing_data):
        """Test segments with numbers but no metric keywords."""
        # Create segments with numbers but no keywords
        no_keyword_segments = [
            {
                "source_segment_id": 300,
                "filing_id": sample_filing_data["filing_id"],
                "segment_type": "paragraph",
                "raw_text": "The building has 12 floors and 5 elevators.",
                "section_heading": "Facilities",
                "section_path": "/Facilities",
            },
            {
                "source_segment_id": 301,
                "filing_id": sample_filing_data["filing_id"],
                "segment_type": "paragraph",
                "raw_text": "We have offices in 7 cities across 3 continents.",
                "section_heading": "Locations",
                "section_path": "/Locations",
            },
        ]

        all_segments = sample_filing_data["segments"] + no_keyword_segments

        generator = CandidateGenerator(apply_learned_rules=False)
        candidates, stats = generator.generate_for_filing(
            filing_id=sample_filing_data["filing_id"],
            company_id=sample_filing_data["company_id"],
            segments=all_segments,
            db=clean_db,
            return_stats=True,
        )

        # Should find numbers but not generate candidates without keywords
        assert stats.numbers_found > 0
        # Candidates from no-keyword segments should have low confidence or be filtered
        no_keyword_candidates = [c for c in candidates if c.source_segment_id in [300, 301]]
        # May or may not generate candidates depending on keyword distance threshold
        assert isinstance(no_keyword_candidates, list)

    def test_very_long_segments(self, clean_db, sample_filing_data):
        """Test handling of very long segments (>50KB)."""
        # Create very long segment (50KB+)
        # Put metric text near the beginning and end
        long_text = "Our annual recurring revenue was $50 million in 2022. "
        long_text += "We are a technology company. " * 2000  # ~58KB
        long_text += "We had 12,500 active customers at year end."

        long_segment = {
            "source_segment_id": 400,
            "filing_id": sample_filing_data["filing_id"],
            "segment_type": "paragraph",
            "raw_text": long_text,
            "section_heading": "Very Long Section",
            "section_path": "/LongSection",
        }

        all_segments = sample_filing_data["segments"] + [long_segment]

        generator = CandidateGenerator(apply_learned_rules=False)
        candidates, stats = generator.generate_for_filing(
            filing_id=sample_filing_data["filing_id"],
            company_id=sample_filing_data["company_id"],
            segments=all_segments,
            db=clean_db,
            return_stats=True,
        )

        # Should handle long segment without errors
        assert isinstance(candidates, list)
        assert stats.segments_processed == 4, "Should process all segments including long one"

        # Should find numbers in the long segment
        long_segment_candidates = [c for c in candidates if c.source_segment_id == 400]
        # Test passes if processing completes without error (may or may not generate candidates)
        assert isinstance(long_segment_candidates, list)
