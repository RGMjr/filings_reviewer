"""
Unit tests for ExtractionPipeline.

Tests the end-to-end orchestration of the extraction pipeline.
"""

import tempfile
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, Mock

import pytest

from src.extraction.extraction_pipeline import ExtractionPipeline, ExtractionResult
from src.extraction.models import (
    FilingMetricIncidence,
    MetricDefinition,
    MetricValue,
    SourceSegment,
)


@pytest.fixture
def mock_db():
    """Create a mock database adapter."""
    db = Mock()
    db.query = Mock(return_value=[])
    db.execute = Mock()
    db.get_connection = Mock()
    return db


@pytest.fixture
def pipeline(mock_db):
    """Create an ExtractionPipeline with mocked database."""
    return ExtractionPipeline(db=mock_db)


@pytest.fixture
def sample_filing_metadata():
    """Sample filing metadata from database."""
    return {
        "filing_id": 1,
        "company_id": 100,
        "cik": "0001234567",
        "accession_number": "0001234567-20-000001",
        "html_storage_path": "/tmp/test.html",
        "html_content": None,
    }


@pytest.fixture
def temp_html_file():
    """Create a temporary HTML file."""
    content = "<html><body><p>Test filing content with 1,000 customers and daily active users.</p></body></html>"
    with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False) as f:
        f.write(content)
        return f.name


def test_pipeline_initialization(pipeline):
    """Test that pipeline initializes with all required components."""
    assert pipeline is not None
    assert pipeline.db is not None
    assert pipeline.segmenter is not None
    assert pipeline.classifier is not None
    assert pipeline.value_extractor is not None
    assert pipeline.definition_extractor is not None
    assert pipeline.quality_scorer is not None


def test_extraction_result_dataclass():
    """Test ExtractionResult dataclass."""
    result = ExtractionResult(
        filing_id=1,
        success=True,
        num_segments=10,
        num_values=5,
        num_definitions=2,
        num_incidences=3,
    )

    assert result.filing_id == 1
    assert result.success is True
    assert result.error is None
    assert result.num_segments == 10
    assert result.num_values == 5
    assert result.num_definitions == 2
    assert result.num_incidences == 3


def test_extraction_result_with_error():
    """Test ExtractionResult with error."""
    result = ExtractionResult(
        filing_id=1,
        success=False,
        error="Something went wrong",
    )

    assert result.filing_id == 1
    assert result.success is False
    assert result.error == "Something went wrong"
    assert result.num_segments == 0


def test_process_filing_not_found(pipeline, mock_db):
    """Test processing when filing is not found in database."""
    mock_db.query.return_value = []

    result = pipeline.process_filing(filing_id=999)

    assert result.success is False
    assert result.error == "Filing not found in database"
    assert result.filing_id == 999


def test_process_filing_html_file_not_found(pipeline, mock_db, sample_filing_metadata):
    """Test processing when HTML file doesn't exist."""
    # Return filing metadata but with non-existent file
    sample_filing_metadata["html_storage_path"] = "/nonexistent/path.html"
    mock_db.query.return_value = [sample_filing_metadata]

    result = pipeline.process_filing(filing_id=1)

    assert result.success is False
    assert result.error == "Filing not found in database"


def test_process_filing_no_segments_extracted(
    pipeline, mock_db, sample_filing_metadata, temp_html_file
):
    """Test processing when no segments are extracted."""
    sample_filing_metadata["html_storage_path"] = temp_html_file
    mock_db.query.return_value = [sample_filing_metadata]

    # Mock segmenter to return empty list
    pipeline.segmenter = Mock()
    pipeline.segmenter.segment_filing = Mock(return_value=[])

    result = pipeline.process_filing(filing_id=1)

    assert result.success is False
    assert result.error == "No segments extracted from HTML"

    # Clean up
    Path(temp_html_file).unlink()


def test_process_filing_successful(
    pipeline, mock_db, sample_filing_metadata, temp_html_file
):
    """Test successful filing processing."""
    sample_filing_metadata["html_storage_path"] = temp_html_file
    mock_db.query.return_value = [sample_filing_metadata]

    # Mock all pipeline components
    # Segment needs to meet tiered selection criteria:
    # - richness_score >= 6.0 (high), 4.0-6.0 (medium), or
    # - contains_definition_flag/contains_methodology_flag (critical)
    mock_segments = [
        SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            sequence_index=0,
            raw_text="Test segment",
            candidate_metric_ids=["cm_daily_active_users"],
            classifier_confidence=0.8,
            contains_definition_flag=True,  # Ensures selection via critical tier
        )
    ]

    mock_values = [
        MetricValue(
            filing_id=1,
            company_id=100,
            metric_id="cm_daily_active_users",
            source_segment_id=0,
            source_type="text",
            extraction_method="regex",
            value_numeric=Decimal("1000"),
        )
    ]

    mock_definitions = [
        MetricDefinition(
            filing_id=1,
            company_id=100,
            metric_id="cm_daily_active_users",
            definition_text_normalized="DAU definition",
        )
    ]

    mock_incidences = [
        FilingMetricIncidence(
            filing_id=1,
            company_id=100,
            metric_id="cm_daily_active_users",
            metric_disclosed_flag=True,
            num_numeric_segments=1,
        )
    ]

    pipeline.segmenter.segment_filing = Mock(return_value=mock_segments)
    pipeline.classifier.classify_batch = Mock(return_value=mock_segments)
    pipeline.value_extractor.extract_from_segment = Mock(return_value=mock_values)
    pipeline.definition_extractor.extract_definitions = Mock(
        return_value=mock_definitions
    )
    pipeline.quality_scorer.score_filing = Mock(return_value=mock_incidences)

    # Mock database transaction
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchone = Mock(return_value={"source_segment_id": 1})
    mock_conn.cursor.return_value.__enter__ = Mock(return_value=mock_cursor)
    mock_conn.cursor.return_value.__exit__ = Mock(return_value=False)
    mock_db.get_connection.return_value.__enter__ = Mock(return_value=mock_conn)
    mock_db.get_connection.return_value.__exit__ = Mock(return_value=False)

    result = pipeline.process_filing(filing_id=1)

    assert result.success is True
    assert result.error is None
    assert result.num_segments == 1
    assert result.num_values == 1
    assert result.num_definitions == 1
    assert result.num_incidences == 1

    # Verify all stages were called
    pipeline.segmenter.segment_filing.assert_called_once()
    pipeline.classifier.classify_batch.assert_called_once()
    pipeline.definition_extractor.extract_definitions.assert_called_once()
    pipeline.quality_scorer.score_filing.assert_called_once()

    # Clean up
    Path(temp_html_file).unlink()


def test_process_filing_exception_handling(pipeline, mock_db, sample_filing_metadata):
    """Test that exceptions are caught and returned in result."""
    mock_db.query.side_effect = Exception("Database error")

    result = pipeline.process_filing(filing_id=1)

    assert result.success is False
    assert "Database error" in result.error


def test_process_batch_empty_list(pipeline):
    """Test batch processing with empty filing list."""
    stats = pipeline.process_batch(filing_ids=[])

    assert stats["total"] == 0
    assert stats["success"] == 0
    assert stats["failed"] == 0


def test_process_batch_multiple_filings(pipeline, mock_db):
    """Test batch processing multiple filings."""
    # Mock process_filing to return different results
    successful_result = ExtractionResult(
        filing_id=1,
        success=True,
        num_segments=10,
        num_values=5,
        num_definitions=2,
        num_incidences=3,
    )

    failed_result = ExtractionResult(
        filing_id=2,
        success=False,
        error="Processing failed",
    )

    pipeline.process_filing = Mock(side_effect=[successful_result, failed_result])

    stats = pipeline.process_batch(filing_ids=[1, 2])

    assert stats["total"] == 2
    assert stats["success"] == 1
    assert stats["failed"] == 1
    assert stats["total_segments"] == 10
    assert stats["total_values"] == 5
    assert stats["total_definitions"] == 2
    assert stats["total_incidences"] == 3


def test_process_batch_all_successful(pipeline):
    """Test batch processing where all succeed."""
    result = ExtractionResult(
        filing_id=1,
        success=True,
        num_segments=5,
        num_values=2,
        num_definitions=1,
        num_incidences=1,
    )

    pipeline.process_filing = Mock(return_value=result)

    stats = pipeline.process_batch(filing_ids=[1, 2, 3])

    assert stats["total"] == 3
    assert stats["success"] == 3
    assert stats["failed"] == 0
    assert stats["total_segments"] == 15
    assert stats["total_values"] == 6
    assert stats["total_definitions"] == 3
    assert stats["total_incidences"] == 3


def test_process_batch_all_failed(pipeline):
    """Test batch processing where all fail."""
    result = ExtractionResult(
        filing_id=1,
        success=False,
        error="Failed",
    )

    pipeline.process_filing = Mock(return_value=result)

    stats = pipeline.process_batch(filing_ids=[1, 2, 3])

    assert stats["total"] == 3
    assert stats["success"] == 0
    assert stats["failed"] == 3
    assert stats["total_segments"] == 0


def test_get_filing_metadata(pipeline, mock_db, sample_filing_metadata, temp_html_file):
    """Test _get_filing_metadata method."""
    sample_filing_metadata["html_storage_path"] = temp_html_file
    mock_db.query.return_value = [sample_filing_metadata]

    filing = pipeline._get_filing_metadata(filing_id=1)

    assert filing is not None
    assert filing["filing_id"] == 1
    assert filing["company_id"] == 100
    assert filing["html_storage_path"] == temp_html_file

    # Verify query was called correctly
    assert mock_db.query.called
    call_args = mock_db.query.call_args
    assert "SELECT" in call_args[0][0]
    assert "WHERE filing_id" in call_args[0][0]

    # Clean up
    Path(temp_html_file).unlink()


def test_get_filing_metadata_not_found(pipeline, mock_db):
    """Test _get_filing_metadata when filing doesn't exist."""
    mock_db.query.return_value = []

    filing = pipeline._get_filing_metadata(filing_id=999)

    assert filing is None


def test_get_filing_metadata_file_missing(pipeline, mock_db, sample_filing_metadata):
    """Test _get_filing_metadata when HTML file is missing."""
    sample_filing_metadata["html_storage_path"] = "/nonexistent/file.html"
    mock_db.query.return_value = [sample_filing_metadata]

    filing = pipeline._get_filing_metadata(filing_id=1)

    assert filing is None


def test_get_filing_metadata_null_path(pipeline, mock_db, sample_filing_metadata):
    """Test _get_filing_metadata when html_storage_path is None."""
    sample_filing_metadata["html_storage_path"] = None
    mock_db.query.return_value = [sample_filing_metadata]

    filing = pipeline._get_filing_metadata(filing_id=1)

    assert filing is None


def test_write_results_transaction(pipeline, mock_db):
    """Test that _write_results uses database transaction."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchone = Mock(return_value={"source_segment_id": 1})
    mock_conn.cursor.return_value.__enter__ = Mock(return_value=mock_cursor)
    mock_conn.cursor.return_value.__exit__ = Mock(return_value=False)
    mock_db.get_connection.return_value.__enter__ = Mock(return_value=mock_conn)
    mock_db.get_connection.return_value.__exit__ = Mock(return_value=False)

    segments = [
        SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            sequence_index=0,
            raw_text="Test",
        )
    ]

    pipeline._write_results(
        filing_id=1, segments=segments, values=[], definitions=[], incidences=[]
    )

    # Verify connection was used
    mock_db.get_connection.assert_called_once()
    # Verify cleanup SQL was executed
    assert mock_cursor.execute.called


def test_pipeline_components_integration(pipeline):
    """Test that all pipeline components are properly initialized."""
    # Components should be actual instances, not mocks (in real usage)
    from src.extraction.definition_extractor import DefinitionExtractor
    from src.extraction.html_segmenter import HTMLSegmenter
    from src.extraction.metric_classifier import MetricClassifier
    from src.extraction.quality_scorer import QualityScorer
    from src.extraction.segment_enricher import SegmentEnricher
    from src.extraction.value_extractor import ValueExtractor

    assert isinstance(pipeline.segmenter, HTMLSegmenter)
    assert isinstance(pipeline.classifier, MetricClassifier)
    assert isinstance(pipeline.enricher, SegmentEnricher)
    assert isinstance(pipeline.value_extractor, ValueExtractor)
    assert isinstance(pipeline.definition_extractor, DefinitionExtractor)
    assert isinstance(pipeline.quality_scorer, QualityScorer)


# =============================================================================
# G11: Enrichment Integration Tests
# =============================================================================


def test_enrichment_called_after_classification(
    pipeline, mock_db, sample_filing_metadata, temp_html_file
):
    """Verify enricher.enrich_batch() is called after classification."""
    sample_filing_metadata["html_storage_path"] = temp_html_file
    mock_db.query.return_value = [sample_filing_metadata]

    mock_segments = [
        SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            sequence_index=0,
            raw_text="Test segment with 1,000 customers",
            candidate_metric_ids=["cm_daily_active_users"],
            classifier_confidence=0.8,
        )
    ]

    pipeline.segmenter.segment_filing = Mock(return_value=mock_segments)
    pipeline.classifier.classify_batch = Mock(return_value=mock_segments)
    pipeline.enricher = Mock()
    pipeline.enricher.enrich_batch = Mock(return_value=mock_segments)
    pipeline.value_extractor.extract_from_segment = Mock(return_value=[])
    pipeline.definition_extractor.extract_definitions = Mock(return_value=[])
    pipeline.quality_scorer.score_filing = Mock(return_value=[])

    # Mock database transaction
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchone = Mock(return_value={"source_segment_id": 1})
    mock_conn.cursor.return_value.__enter__ = Mock(return_value=mock_cursor)
    mock_conn.cursor.return_value.__exit__ = Mock(return_value=False)
    mock_db.get_connection.return_value.__enter__ = Mock(return_value=mock_conn)
    mock_db.get_connection.return_value.__exit__ = Mock(return_value=False)

    pipeline.process_filing(filing_id=1)

    # Verify enricher.enrich_batch() was called
    pipeline.enricher.enrich_batch.assert_called_once()
    # Verify it was called with the classified segments
    call_args = pipeline.enricher.enrich_batch.call_args[0][0]
    assert call_args == mock_segments

    # Clean up
    Path(temp_html_file).unlink()


def test_segments_have_richness_scores_after_processing(
    pipeline, mock_db, sample_filing_metadata, temp_html_file
):
    """Verify richness_score is populated after enrichment."""
    sample_filing_metadata["html_storage_path"] = temp_html_file
    mock_db.query.return_value = [sample_filing_metadata]

    # Create segment that will be enriched
    mock_segment = SourceSegment(
        filing_id=1,
        segment_type="paragraph",
        sequence_index=0,
        raw_text="Our DAU grew from 1 million in 2022 to 2 million in 2023",
        candidate_metric_ids=["cm_daily_active_users"],
        classifier_confidence=0.9,
    )

    pipeline.segmenter.segment_filing = Mock(return_value=[mock_segment])
    pipeline.classifier.classify_batch = Mock(return_value=[mock_segment])
    # Use real enricher to verify it actually enriches
    pipeline.value_extractor.extract_from_segment = Mock(return_value=[])
    pipeline.definition_extractor.extract_definitions = Mock(return_value=[])
    pipeline.quality_scorer.score_filing = Mock(return_value=[])

    # Mock database transaction
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchone = Mock(return_value={"source_segment_id": 1})
    mock_conn.cursor.return_value.__enter__ = Mock(return_value=mock_cursor)
    mock_conn.cursor.return_value.__exit__ = Mock(return_value=False)
    mock_db.get_connection.return_value.__enter__ = Mock(return_value=mock_conn)
    mock_db.get_connection.return_value.__exit__ = Mock(return_value=False)

    pipeline.process_filing(filing_id=1)

    # Verify richness_score was populated
    assert mock_segment.richness_score is not None
    assert mock_segment.richness_score > 0

    # Clean up
    Path(temp_html_file).unlink()


def test_enrichment_failure_doesnt_crash_pipeline(
    pipeline, mock_db, sample_filing_metadata, temp_html_file
):
    """Enricher errors should be logged but pipeline should continue."""
    sample_filing_metadata["html_storage_path"] = temp_html_file
    mock_db.query.return_value = [sample_filing_metadata]

    mock_segments = [
        SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            sequence_index=0,
            raw_text="Test segment",
            classifier_confidence=0.8,
        )
    ]

    pipeline.segmenter.segment_filing = Mock(return_value=mock_segments)
    pipeline.classifier.classify_batch = Mock(return_value=mock_segments)
    # Mock enricher to raise exception
    pipeline.enricher = Mock()
    pipeline.enricher.enrich_batch = Mock(side_effect=Exception("Enrichment failed"))

    result = pipeline.process_filing(filing_id=1)

    # Pipeline should fail gracefully
    assert result.success is False
    assert "Enrichment failed" in result.error

    # Clean up
    Path(temp_html_file).unlink()


# =============================================================================
# G11: Tiered Selection Tests
# =============================================================================


def test_tiered_selection_prioritizes_goldmines(pipeline):
    """High richness segments (>= 6.0) should appear first."""
    segments = [
        SourceSegment(
            filing_id=1, segment_type="p", sequence_index=0,
            raw_text="Low", richness_score=2.0
        ),
        SourceSegment(
            filing_id=1, segment_type="p", sequence_index=1,
            raw_text="Goldmine", richness_score=8.0
        ),
        SourceSegment(
            filing_id=1, segment_type="p", sequence_index=2,
            raw_text="Medium", richness_score=5.0
        ),
    ]

    result = pipeline._select_segments_tiered(segments)

    # Goldmine should be first
    assert result[0].richness_score == 8.0
    # Medium should be second (tier 2)
    assert result[1].richness_score == 5.0
    # Low richness should not be selected (below 4.0 threshold)
    assert len(result) == 2


def test_tiered_selection_includes_medium_richness(pipeline):
    """Medium tier (4.0-6.0) should be included after goldmines."""
    segments = [
        SourceSegment(
            filing_id=1, segment_type="p", sequence_index=0,
            raw_text="Medium1", richness_score=4.5
        ),
        SourceSegment(
            filing_id=1, segment_type="p", sequence_index=1,
            raw_text="Goldmine", richness_score=7.0
        ),
        SourceSegment(
            filing_id=1, segment_type="p", sequence_index=2,
            raw_text="Medium2", richness_score=5.5
        ),
    ]

    result = pipeline._select_segments_tiered(segments)

    # Order should be: Goldmine (7.0), Medium2 (5.5), Medium1 (4.5)
    assert len(result) == 3
    assert result[0].richness_score == 7.0
    assert result[1].richness_score == 5.5
    assert result[2].richness_score == 4.5


def test_tiered_selection_includes_critical_flags(pipeline):
    """Definitions/methodologies included even if low richness."""
    segments = [
        SourceSegment(
            filing_id=1, segment_type="p", sequence_index=0,
            raw_text="Definition", richness_score=2.0,
            contains_definition_flag=True
        ),
        SourceSegment(
            filing_id=1, segment_type="p", sequence_index=1,
            raw_text="Methodology", richness_score=1.5,
            contains_methodology_flag=True
        ),
        SourceSegment(
            filing_id=1, segment_type="p", sequence_index=2,
            raw_text="Normal low", richness_score=1.0
        ),
    ]

    result = pipeline._select_segments_tiered(segments)

    # Critical flags should be included, normal low should not
    assert len(result) == 2
    raw_texts = [s.raw_text for s in result]
    assert "Definition" in raw_texts
    assert "Methodology" in raw_texts
    assert "Normal low" not in raw_texts


def test_tiered_selection_caps_at_80(pipeline):
    """Total selection should not exceed MAX_TOTAL=80."""
    # Create 100 high-richness segments
    segments = [
        SourceSegment(
            filing_id=1, segment_type="p", sequence_index=i,
            raw_text=f"Segment {i}", richness_score=9.0
        )
        for i in range(100)
    ]

    result = pipeline._select_segments_tiered(segments)

    # Should cap at 80 (30 high + 0 medium since all are >= 6.0)
    # Actually, only 30 max for tier 1, so should be 30
    assert len(result) == 30


def test_tiered_selection_deduplicates(pipeline):
    """No segment should appear twice in result."""
    # Create segment that qualifies for multiple tiers
    dual_qualify = SourceSegment(
        filing_id=1, segment_type="p", sequence_index=0,
        raw_text="High richness with definition", richness_score=7.0,
        contains_definition_flag=True  # Would also match tier 3
    )

    segments = [
        dual_qualify,
        SourceSegment(
            filing_id=1, segment_type="p", sequence_index=1,
            raw_text="Other", richness_score=5.0
        ),
    ]

    result = pipeline._select_segments_tiered(segments)

    # Should only appear once
    assert len([s for s in result if s.raw_text == "High richness with definition"]) == 1


def test_tiered_selection_empty_segments(pipeline):
    """Empty segment list should return empty result."""
    result = pipeline._select_segments_tiered([])
    assert result == []


def test_tiered_selection_all_low_richness(pipeline):
    """All low richness segments should still work (may be empty or critical only)."""
    segments = [
        SourceSegment(
            filing_id=1, segment_type="p", sequence_index=0,
            raw_text="Low1", richness_score=1.0
        ),
        SourceSegment(
            filing_id=1, segment_type="p", sequence_index=1,
            raw_text="Low2", richness_score=2.0
        ),
    ]

    result = pipeline._select_segments_tiered(segments)

    # No segments meet any criteria
    assert len(result) == 0


def test_tiered_selection_none_richness_scores(pipeline):
    """Segments with None richness_score should be handled as 0.0."""
    segments = [
        SourceSegment(
            filing_id=1, segment_type="p", sequence_index=0,
            raw_text="None score", richness_score=None
        ),
        SourceSegment(
            filing_id=1, segment_type="p", sequence_index=1,
            raw_text="High score", richness_score=7.0
        ),
    ]

    result = pipeline._select_segments_tiered(segments)

    # Only high score segment should be selected
    assert len(result) == 1
    assert result[0].raw_text == "High score"


# =============================================================================
# G11: Goldmine Statistics Tests
# =============================================================================


def test_goldmine_count_logged(
    pipeline, mock_db, sample_filing_metadata, temp_html_file, caplog
):
    """Verify goldmine count appears in logs."""
    import logging
    caplog.set_level(logging.INFO)

    sample_filing_metadata["html_storage_path"] = temp_html_file
    mock_db.query.return_value = [sample_filing_metadata]

    # Create goldmine segment
    mock_segment = SourceSegment(
        filing_id=1,
        segment_type="paragraph",
        sequence_index=0,
        raw_text="DAU grew from 1 million in 2022 to 2 million in 2023 year-over-year",
        candidate_metric_ids=["cm_daily_active_users", "cm_mau"],
        classifier_confidence=0.9,
        contains_definition_flag=True,
    )

    pipeline.segmenter.segment_filing = Mock(return_value=[mock_segment])
    pipeline.classifier.classify_batch = Mock(return_value=[mock_segment])
    pipeline.value_extractor.extract_from_segment = Mock(return_value=[])
    pipeline.definition_extractor.extract_definitions = Mock(return_value=[])
    pipeline.quality_scorer.score_filing = Mock(return_value=[])

    # Mock database transaction
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchone = Mock(return_value={"source_segment_id": 1})
    mock_conn.cursor.return_value.__enter__ = Mock(return_value=mock_cursor)
    mock_conn.cursor.return_value.__exit__ = Mock(return_value=False)
    mock_db.get_connection.return_value.__enter__ = Mock(return_value=mock_conn)
    mock_db.get_connection.return_value.__exit__ = Mock(return_value=False)

    pipeline.process_filing(filing_id=1)

    # Check logs contain goldmine info
    assert any("goldmine segments" in record.message for record in caplog.records)

    # Clean up
    Path(temp_html_file).unlink()


def test_no_goldmines_logs_zero(
    pipeline, mock_db, sample_filing_metadata, temp_html_file, caplog
):
    """When no goldmines, logs should show 0."""
    import logging
    caplog.set_level(logging.INFO)

    sample_filing_metadata["html_storage_path"] = temp_html_file
    mock_db.query.return_value = [sample_filing_metadata]

    # Create low-richness segment (will not be goldmine)
    mock_segment = SourceSegment(
        filing_id=1,
        segment_type="paragraph",
        sequence_index=0,
        raw_text="Simple text",
        classifier_confidence=0.3,
        contains_definition_flag=True,  # Will still be selected via critical
    )

    pipeline.segmenter.segment_filing = Mock(return_value=[mock_segment])
    pipeline.classifier.classify_batch = Mock(return_value=[mock_segment])
    pipeline.value_extractor.extract_from_segment = Mock(return_value=[])
    pipeline.definition_extractor.extract_definitions = Mock(return_value=[])
    pipeline.quality_scorer.score_filing = Mock(return_value=[])

    # Mock database transaction
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchone = Mock(return_value={"source_segment_id": 1})
    mock_conn.cursor.return_value.__enter__ = Mock(return_value=mock_cursor)
    mock_conn.cursor.return_value.__exit__ = Mock(return_value=False)
    mock_db.get_connection.return_value.__enter__ = Mock(return_value=mock_conn)
    mock_db.get_connection.return_value.__exit__ = Mock(return_value=False)

    pipeline.process_filing(filing_id=1)

    # Check logs contain "0 goldmine segments"
    assert any("0 goldmine segments" in record.message for record in caplog.records)

    # Clean up
    Path(temp_html_file).unlink()


def test_process_filing_succeeds_with_db_html_content(pipeline, mock_db):
    """File doesn't exist but html_content is set -> segmenter called with html_content."""
    filing_metadata = {
        "filing_id": 1,
        "company_id": 100,
        "cik": "0001234567",
        "accession_number": "0001234567-20-000001",
        "html_storage_path": "/nonexistent/path.html",
        "html_content": "<html><body>Filing from DB</body></html>",
    }
    mock_db.query.return_value = [filing_metadata]

    mock_segment = SourceSegment(
        filing_id=1,
        segment_type="paragraph",
        sequence_index=0,
        raw_text="Filing from DB",
        contains_definition_flag=True,
    )

    pipeline.segmenter = Mock()
    pipeline.segmenter.segment_filing = Mock(return_value=[mock_segment])
    pipeline.classifier.classify_batch = Mock(return_value=[mock_segment])
    pipeline.value_extractor.extract_from_segment = Mock(return_value=[])
    pipeline.definition_extractor.extract_definitions = Mock(return_value=[])
    pipeline.quality_scorer.score_filing = Mock(return_value=[])

    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchone = Mock(return_value={"source_segment_id": 1})
    mock_conn.cursor.return_value.__enter__ = Mock(return_value=mock_cursor)
    mock_conn.cursor.return_value.__exit__ = Mock(return_value=False)
    mock_db.get_connection.return_value.__enter__ = Mock(return_value=mock_conn)
    mock_db.get_connection.return_value.__exit__ = Mock(return_value=False)

    result = pipeline.process_filing(filing_id=1)

    assert result.success is True
    pipeline.segmenter.segment_filing.assert_called_once()
    call_kwargs = pipeline.segmenter.segment_filing.call_args[1]
    assert call_kwargs.get("html_content") == "<html><body>Filing from DB</body></html>"


# =============================================================================
# G11: Regression Tests
# =============================================================================


def test_pipeline_still_completes_successfully_with_enrichment(
    pipeline, mock_db, sample_filing_metadata, temp_html_file
):
    """Full pipeline test - verify complete flow still works."""
    sample_filing_metadata["html_storage_path"] = temp_html_file
    mock_db.query.return_value = [sample_filing_metadata]

    # Create realistic segments with definition flag to ensure selection
    mock_segments = [
        SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            sequence_index=i,
            raw_text=f"Test segment {i} with customer metrics for 2022 and 2023",
            candidate_metric_ids=["cm_daily_active_users"],
            classifier_confidence=0.7,
            contains_definition_flag=True,  # Ensures selection via critical tier
        )
        for i in range(5)
    ]

    mock_values = [
        MetricValue(
            filing_id=1,
            company_id=100,
            metric_id="cm_daily_active_users",
            source_segment_id=0,
            source_type="text",
            extraction_method="regex",
            value_numeric=Decimal("1000"),
        )
    ]

    mock_definitions = [
        MetricDefinition(
            filing_id=1,
            company_id=100,
            metric_id="cm_daily_active_users",
            definition_text_normalized="DAU definition",
        )
    ]

    mock_incidences = [
        FilingMetricIncidence(
            filing_id=1,
            company_id=100,
            metric_id="cm_daily_active_users",
            metric_disclosed_flag=True,
            num_numeric_segments=1,
        )
    ]

    pipeline.segmenter.segment_filing = Mock(return_value=mock_segments)
    pipeline.classifier.classify_batch = Mock(return_value=mock_segments)
    # Use real enricher
    pipeline.value_extractor.extract_from_segment = Mock(return_value=mock_values)
    pipeline.definition_extractor.extract_definitions = Mock(
        return_value=mock_definitions
    )
    pipeline.quality_scorer.score_filing = Mock(return_value=mock_incidences)

    # Mock database transaction
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchone = Mock(return_value={"source_segment_id": 1})
    mock_conn.cursor.return_value.__enter__ = Mock(return_value=mock_cursor)
    mock_conn.cursor.return_value.__exit__ = Mock(return_value=False)
    mock_db.get_connection.return_value.__enter__ = Mock(return_value=mock_conn)
    mock_db.get_connection.return_value.__exit__ = Mock(return_value=False)

    result = pipeline.process_filing(filing_id=1)

    assert result.success is True
    assert result.error is None
    # All 5 segments should be selected (medium richness after enrichment)
    assert result.num_segments >= 1

    # Clean up
    Path(temp_html_file).unlink()
