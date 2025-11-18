"""
Unit tests for ExtractionPipeline.

Tests the end-to-end orchestration of the extraction pipeline.
"""

import tempfile
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch, call

import pytest

from src.extraction.extraction_pipeline import ExtractionPipeline, ExtractionResult
from src.extraction.models import SourceSegment, MetricValue, MetricDefinition, FilingMetricIncidence
from decimal import Decimal


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
        'filing_id': 1,
        'company_id': 100,
        'cik': '0001234567',
        'accession_number': '0001234567-20-000001',
        'html_storage_path': '/tmp/test.html',
    }


@pytest.fixture
def temp_html_file():
    """Create a temporary HTML file."""
    content = "<html><body><p>Test filing content with 1,000 customers and daily active users.</p></body></html>"
    with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False) as f:
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
    sample_filing_metadata['html_storage_path'] = '/nonexistent/path.html'
    mock_db.query.return_value = [sample_filing_metadata]

    result = pipeline.process_filing(filing_id=1)

    assert result.success is False
    assert result.error == "Filing not found in database"


def test_process_filing_no_segments_extracted(pipeline, mock_db, sample_filing_metadata, temp_html_file):
    """Test processing when no segments are extracted."""
    sample_filing_metadata['html_storage_path'] = temp_html_file
    mock_db.query.return_value = [sample_filing_metadata]

    # Mock segmenter to return empty list
    pipeline.segmenter = Mock()
    pipeline.segmenter.segment_filing = Mock(return_value=[])

    result = pipeline.process_filing(filing_id=1)

    assert result.success is False
    assert result.error == "No segments extracted from HTML"

    # Clean up
    Path(temp_html_file).unlink()


def test_process_filing_successful(pipeline, mock_db, sample_filing_metadata, temp_html_file):
    """Test successful filing processing."""
    sample_filing_metadata['html_storage_path'] = temp_html_file
    mock_db.query.return_value = [sample_filing_metadata]

    # Mock all pipeline components
    mock_segments = [
        SourceSegment(
            filing_id=1,
            segment_type="paragraph",
            sequence_index=0,
            raw_text="Test segment",
            candidate_metric_ids=["cm_daily_active_users"],
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
    pipeline.definition_extractor.extract_definitions = Mock(return_value=mock_definitions)
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

    assert stats['total'] == 0
    assert stats['success'] == 0
    assert stats['failed'] == 0


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

    assert stats['total'] == 2
    assert stats['success'] == 1
    assert stats['failed'] == 1
    assert stats['total_segments'] == 10
    assert stats['total_values'] == 5
    assert stats['total_definitions'] == 2
    assert stats['total_incidences'] == 3


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

    assert stats['total'] == 3
    assert stats['success'] == 3
    assert stats['failed'] == 0
    assert stats['total_segments'] == 15
    assert stats['total_values'] == 6
    assert stats['total_definitions'] == 3
    assert stats['total_incidences'] == 3


def test_process_batch_all_failed(pipeline):
    """Test batch processing where all fail."""
    result = ExtractionResult(
        filing_id=1,
        success=False,
        error="Failed",
    )

    pipeline.process_filing = Mock(return_value=result)

    stats = pipeline.process_batch(filing_ids=[1, 2, 3])

    assert stats['total'] == 3
    assert stats['success'] == 0
    assert stats['failed'] == 3
    assert stats['total_segments'] == 0


def test_get_filing_metadata(pipeline, mock_db, sample_filing_metadata, temp_html_file):
    """Test _get_filing_metadata method."""
    sample_filing_metadata['html_storage_path'] = temp_html_file
    mock_db.query.return_value = [sample_filing_metadata]

    filing = pipeline._get_filing_metadata(filing_id=1)

    assert filing is not None
    assert filing['filing_id'] == 1
    assert filing['company_id'] == 100
    assert filing['html_storage_path'] == temp_html_file

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
    sample_filing_metadata['html_storage_path'] = '/nonexistent/file.html'
    mock_db.query.return_value = [sample_filing_metadata]

    filing = pipeline._get_filing_metadata(filing_id=1)

    assert filing is None


def test_get_filing_metadata_null_path(pipeline, mock_db, sample_filing_metadata):
    """Test _get_filing_metadata when html_storage_path is None."""
    sample_filing_metadata['html_storage_path'] = None
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
        filing_id=1,
        segments=segments,
        values=[],
        definitions=[],
        incidences=[]
    )

    # Verify connection was used
    mock_db.get_connection.assert_called_once()
    # Verify cleanup SQL was executed
    assert mock_cursor.execute.called


def test_pipeline_components_integration(pipeline):
    """Test that all pipeline components are properly initialized."""
    # Components should be actual instances, not mocks (in real usage)
    from src.extraction.html_segmenter import HTMLSegmenter
    from src.extraction.metric_classifier import MetricClassifier
    from src.extraction.value_extractor import ValueExtractor
    from src.extraction.definition_extractor import DefinitionExtractor
    from src.extraction.quality_scorer import QualityScorer

    assert isinstance(pipeline.segmenter, HTMLSegmenter)
    assert isinstance(pipeline.classifier, MetricClassifier)
    assert isinstance(pipeline.value_extractor, ValueExtractor)
    assert isinstance(pipeline.definition_extractor, DefinitionExtractor)
    assert isinstance(pipeline.quality_scorer, QualityScorer)
