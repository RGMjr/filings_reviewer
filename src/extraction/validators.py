"""
Validators for extraction modules.

Provides validation functions for inputs and outputs of extraction modules
(html_segmenter, metric_classifier). Raises ValidationError for invalid inputs.
"""

import os
from pathlib import Path

from .exceptions import ValidationError
from .models import SourceSegment


class SegmentValidator:
    """Validates HTMLSegmenter inputs and outputs.

    Provides static methods for validating filing IDs, HTML paths, and
    source segments.
    """

    @staticmethod
    def validate_filing_id(filing_id: int) -> None:
        """Validate filing ID.

        Args:
            filing_id: Database filing ID

        Raises:
            ValidationError: If filing_id is not a positive integer
        """
        if not isinstance(filing_id, int):
            raise ValidationError(
                f"filing_id must be an integer, got {type(filing_id).__name__}",
                field_name="filing_id",
                invalid_value=filing_id,
            )

        if filing_id <= 0:
            raise ValidationError(
                f"filing_id must be positive, got {filing_id}",
                field_name="filing_id",
                invalid_value=filing_id,
            )

    @staticmethod
    def validate_html_path(html_path: str) -> Path:
        """Validate HTML file path.

        Args:
            html_path: Path to HTML file

        Returns:
            Resolved absolute Path object

        Raises:
            ValidationError: If path is invalid
            FileNotFoundError: If file doesn't exist
            PermissionError: If file is not readable
        """
        if not isinstance(html_path, str):
            raise ValidationError(
                f"html_path must be a string, got {type(html_path).__name__}",
                field_name="html_path",
                invalid_value=html_path,
            )

        if not html_path.strip():
            raise ValidationError(
                "html_path cannot be empty", field_name="html_path", invalid_value=html_path
            )

        # Security: check for path traversal attempts
        if ".." in html_path or html_path.startswith("/"):
            pass  # Allow absolute paths and parent references for now

        path = Path(html_path)

        if not path.exists():
            raise FileNotFoundError(f"HTML file not found: {html_path}")

        if not path.is_file():
            raise ValidationError(
                f"Path is not a file: {html_path}", field_name="html_path", invalid_value=html_path
            )

        if not os.access(path, os.R_OK):
            raise PermissionError(f"Cannot read file: {html_path}")

        return path.resolve()

    @staticmethod
    def validate_segment(segment: SourceSegment) -> None:
        """Validate source segment structure.

        Args:
            segment: SourceSegment to validate

        Raises:
            ValidationError: If segment is invalid
        """
        if not isinstance(segment, SourceSegment):
            raise ValidationError(
                f"segment must be SourceSegment instance, got {type(segment).__name__}",
                field_name="segment",
                invalid_value=type(segment).__name__,
            )

        # Validate filing_id
        if segment.filing_id <= 0:
            raise ValidationError(
                f"Segment filing_id must be positive, got {segment.filing_id}",
                field_name="filing_id",
                invalid_value=segment.filing_id,
            )

        # Validate segment_type
        if not segment.segment_type:
            raise ValidationError(
                "Segment must have segment_type",
                field_name="segment_type",
                invalid_value=segment.segment_type,
            )

        # Validate sequence_index for non-empty segments
        if (
            segment.raw_text is not None
            and isinstance(segment.raw_text, str)
            and len(segment.raw_text) > 0
            and segment.sequence_index < 0
        ):
            raise ValidationError(
                f"Segment sequence_index must be >= 0, got {segment.sequence_index}",
                field_name="sequence_index",
                invalid_value=segment.sequence_index,
            )

    @staticmethod
    def validate_min_max_length(min_length: int, max_length: int) -> None:
        """Validate min/max segment length parameters.

        Args:
            min_length: Minimum segment length
            max_length: Maximum segment length

        Raises:
            ValidationError: If lengths are invalid
        """
        if not isinstance(min_length, int) or not isinstance(max_length, int):
            raise ValidationError(
                "min_length and max_length must be integers",
                field_name="length",
                invalid_value=(min_length, max_length),
            )

        if min_length < 0:
            raise ValidationError(
                f"min_length must be non-negative, got {min_length}",
                field_name="min_length",
                invalid_value=min_length,
            )

        if max_length <= 0:
            raise ValidationError(
                f"max_length must be positive, got {max_length}",
                field_name="max_length",
                invalid_value=max_length,
            )

        if min_length > max_length:
            raise ValidationError(
                f"min_length ({min_length}) must be <= max_length ({max_length})",
                field_name="length",
                invalid_value=(min_length, max_length),
            )


class ClassificationValidator:
    """Validates metric classification inputs and outputs.

    Provides static methods for validating confidence scores and metric IDs.
    """

    @staticmethod
    def validate_confidence(score: float, field_name: str = "confidence") -> None:
        """Validate confidence score is in [0, 1] range.

        Args:
            score: Confidence score to validate
            field_name: Name of field for error message

        Raises:
            ValidationError: If score is out of range
        """
        if not isinstance(score, (int, float)):
            raise ValidationError(
                f"{field_name} must be a number, got {type(score).__name__}",
                field_name=field_name,
                invalid_value=score,
            )

        if not (0.0 <= score <= 1.0):
            raise ValidationError(
                f"{field_name} must be in [0, 1] range, got {score}",
                field_name=field_name,
                invalid_value=score,
            )

    @staticmethod
    def validate_metric_ids(metric_ids: list[str]) -> None:
        """Validate metric ID list.

        Args:
            metric_ids: List of metric IDs

        Raises:
            ValidationError: If metric_ids is invalid
        """
        if not isinstance(metric_ids, list):
            raise ValidationError(
                f"metric_ids must be a list, got {type(metric_ids).__name__}",
                field_name="metric_ids",
                invalid_value=metric_ids,
            )

        for i, metric_id in enumerate(metric_ids):
            if not isinstance(metric_id, str):
                raise ValidationError(
                    f"metric_ids[{i}] must be a string, got {type(metric_id).__name__}",
                    field_name=f"metric_ids[{i}]",
                    invalid_value=metric_id,
                )

            if not metric_id.strip():
                raise ValidationError(
                    f"metric_ids[{i}] cannot be empty",
                    field_name=f"metric_ids[{i}]",
                    invalid_value=metric_id,
                )

    @staticmethod
    def validate_segment_for_classification(segment: SourceSegment) -> None:
        """Validate segment has required fields for classification.

        Args:
            segment: Segment to validate

        Raises:
            ValidationError: If segment is missing required fields
        """
        # Use SegmentValidator for basic validation
        SegmentValidator.validate_segment(segment)

        # Additional checks for classification
        if segment.raw_text is None:
            raise ValidationError(
                "Segment must have raw_text for classification",
                field_name="raw_text",
                invalid_value=None,
            )

        if not isinstance(segment.raw_text, str):
            raise ValidationError(
                f"Segment raw_text must be a string, got {type(segment.raw_text).__name__}",
                field_name="raw_text",
                invalid_value=type(segment.raw_text).__name__,
            )
