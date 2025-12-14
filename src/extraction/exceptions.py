"""
Extraction exceptions.

Custom exception hierarchy for extraction layer modules (html_segmenter, metric_classifier, etc.).
Provides specific exception types for better error handling and debugging.
"""

from typing import Any, List, Optional


class ExtractionError(Exception):
    """Base exception for extraction layer errors."""

    pass


class HTMLParsingError(ExtractionError):
    """HTML parsing failures.

    Raised when HTML structure is invalid or cannot be parsed.

    Examples:
    - Malformed HTML that BeautifulSoup cannot parse
    - Missing expected HTML elements (BODY, TEXT tags)
    - Invalid nesting or structure
    """

    def __init__(self, message: str, filing_id: Optional[int] = None, html_path: Optional[str] = None):
        """Initialize HTML parsing error.

        Args:
            message: Error description
            filing_id: Database filing ID if available
            html_path: Path to HTML file if available
        """
        super().__init__(message)
        self.filing_id = filing_id
        self.html_path = html_path


class EncodingError(ExtractionError):
    """File encoding issues.

    Raised when file encoding cannot be determined or decoded.

    Examples:
    - UTF-8 decode fails
    - Latin-1 fallback also fails
    - Mixed/invalid encoding in file
    """

    def __init__(
        self, message: str, file_path: str, attempted_encodings: Optional[List[str]] = None, position: Optional[int] = None
    ):
        """Initialize encoding error.

        Args:
            message: Error description
            file_path: Path to file with encoding issues
            attempted_encodings: List of encodings attempted (e.g., ['utf-8', 'latin-1'])
            position: Byte position where decode failed (if known)
        """
        super().__init__(message)
        self.file_path = file_path
        self.attempted_encodings = attempted_encodings or []
        self.position = position


class ValidationError(ExtractionError):
    """Input validation failures.

    Raised when inputs to extraction functions fail validation.

    Examples:
    - Invalid filing_id (negative or zero)
    - File path doesn't exist
    - Invalid segment structure
    - Confidence score out of [0, 1] range
    """

    def __init__(self, message: str, field_name: Optional[str] = None, invalid_value: Optional[Any] = None):
        """Initialize validation error.

        Args:
            message: Error description
            field_name: Name of field that failed validation
            invalid_value: The invalid value that was provided
        """
        super().__init__(message)
        self.field_name = field_name
        self.invalid_value = invalid_value
