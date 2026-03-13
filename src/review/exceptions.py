"""
Custom exceptions for the review module.

This module defines the exception hierarchy for candidate generation
and review processing errors. All exceptions inherit from
CandidateGenerationError for easy catching of review-related errors.

Exception Hierarchy:
    CandidateGenerationError (base)
    ├── SegmentProcessingError (segment-level errors)
    └── NumberProcessingError (number-level errors)
"""



class CandidateGenerationError(Exception):
    """Base exception for candidate generation errors."""

    pass


class SegmentProcessingError(CandidateGenerationError):
    """Error processing a specific segment."""

    def __init__(
        self,
        message: str,
        segment_id: int | None = None,
        original_error: Exception | None = None,
    ):
        super().__init__(message)
        self.segment_id = segment_id
        self.original_error = original_error


class NumberProcessingError(CandidateGenerationError):
    """Error processing a specific number match."""

    def __init__(
        self,
        message: str,
        number_text: str | None = None,
        position: int | None = None,
        original_error: Exception | None = None,
    ):
        super().__init__(message)
        self.number_text = number_text
        self.position = position
        self.original_error = original_error
