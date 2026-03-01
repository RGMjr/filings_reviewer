"""
Stage 2: Section Classification.

Classifies document segments into semantic sections of SEC filings.

Key responsibilities:
- Detect section headings by styling and text patterns
- Classify sections: Cover, Risk Factors, MD&A, Business, Financials, Notes, etc.
- Assign section_type and section_path to each Segment
- Mark filterable sections (Exhibits, Signatures)
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from src.extraction_v2.exceptions import V2FatalError
from src.extraction_v2.models import SectionType, Segment
from src.extraction_v2.text_utils import normalize_text

if TYPE_CHECKING:
    from src.extraction_v2 import pipeline

logger = logging.getLogger(__name__)


class SectionClassificationStage:
    """
    Stage 2: Section Classification.

    Identifies semantic sections in SEC filings and assigns section_type
    and section_path to each Segment.

    Pipeline responsibilities:
    - Detect section headings using styling and text patterns
    - Classify sections based on known SEC filing structure
    - Assign section_type enum to each Segment
    - Build hierarchical section_path for each Segment
    - Mark high-value sections (MD&A, Business) for later confidence scoring
    """

    # Section detection patterns (normalized, case-insensitive)
    SECTION_PATTERNS = {
        SectionType.RISK_FACTORS: [
            r"^ITEM\s*1A[\.\:]?\s*RISK\s*FACTORS",
            r"^RISK\s*FACTORS$",
            r"^PART\s*I[I]?\s*[\-\:]\s*RISK\s*FACTORS",
        ],
        SectionType.MDA: [
            r"^ITEM\s*7[\.\:]?\s*MANAGEMENT.{0,5}S?\s*DISCUSSION",
            r"^MANAGEMENT.{0,5}S?\s*DISCUSSION\s*(AND|&)\s*ANALYSIS",
            r"^MD\s*&?\s*A$",
        ],
        SectionType.BUSINESS: [
            r"^ITEM\s*1[\.\:]?\s*BUSINESS$",
            r"^BUSINESS$",
            r"^DESCRIPTION\s*OF\s*BUSINESS",
        ],
        SectionType.FINANCIALS: [
            r"^ITEM\s*8[\.\:]?\s*FINANCIAL\s*STATEMENTS",
            r"^FINANCIAL\s*STATEMENTS\s*(AND|&)\s*SUPPLEMENTARY",
            r"^CONSOLIDATED\s*(BALANCE\s*SHEETS?|STATEMENTS?)",
        ],
        SectionType.NOTES: [
            r"^NOTES?\s*TO\s*(THE\s*)?(CONSOLIDATED\s*)?FINANCIAL",
            r"^NOTE\s*\d+",
        ],
        SectionType.EXHIBITS: [
            r"^ITEM\s*15[\.\:]?\s*EXHIBITS",
            r"^EXHIBITS?\s*(AND|&)\s*FINANCIAL",
            r"^EXHIBIT\s*INDEX",
        ],
        SectionType.SIGNATURES: [
            r"^SIGNATURES?$",
            r"^POWER\s*OF\s*ATTORNEY",
        ],
    }

    # Heading detection constants
    MAX_HEADING_LENGTH = 200  # Max characters for a heading
    UPPERCASE_THRESHOLD = 0.7  # Minimum ratio of uppercase chars for heading detection

    # Section heading prefixes
    HEADING_PREFIXES = [
        r"^PART\s+(I{1,3}|IV|V|VI{0,3}|IX|X)\b",
        r"^ITEM\s+\d+[A-Z]?[\.\:]?",
        r"^SECTION\s+\d+",
    ]

    def __init__(self) -> None:
        """Initialize the section classification stage."""
        # Compile regex patterns for performance
        self._compiled_patterns: dict[SectionType, list[re.Pattern[str]]] = {}
        for section_type, patterns in self.SECTION_PATTERNS.items():
            self._compiled_patterns[section_type] = [
                re.compile(pattern, re.IGNORECASE) for pattern in patterns
            ]

        self._heading_prefix_patterns = [
            re.compile(pattern, re.IGNORECASE) for pattern in self.HEADING_PREFIXES
        ]

    def _is_mostly_uppercase(self, text: str) -> bool:
        """
        Check if text is mostly uppercase (>70% of letters).

        Args:
            text: Text to check

        Returns:
            True if mostly uppercase
        """
        # Get only alphabetic characters
        letters = [c for c in text if c.isalpha()]
        if not letters:
            return False

        uppercase_count = sum(1 for c in letters if c.isupper())
        ratio = uppercase_count / len(letters)
        return ratio >= self.UPPERCASE_THRESHOLD

    def _has_heading_prefix(self, text: str) -> bool:
        """
        Check if text starts with a section heading prefix (PART, ITEM, etc.).

        Args:
            text: Text to check

        Returns:
            True if text starts with a known heading prefix
        """
        for pattern in self._heading_prefix_patterns:
            if pattern.match(text):
                return True
        return False

    def _is_section_heading(self, segment: Segment) -> bool:
        """
        Determine if a segment is likely a section heading.

        A segment is likely a heading if:
        1. Text length < 200 characters
        2. Contains mostly uppercase characters (>70%)
        3. Starts with "PART", "ITEM", or numbered section
        4. XPath suggests structural element (h1, h2, etc.)

        Args:
            segment: Segment to check

        Returns:
            True if segment is likely a section heading
        """
        # Check text length
        if len(segment.text) > self.MAX_HEADING_LENGTH:
            return False

        # Normalize text
        normalized = normalize_text(segment.text)

        # Check for heading prefix
        if self._has_heading_prefix(normalized):
            return True

        # Check if mostly uppercase
        if self._is_mostly_uppercase(normalized):
            return True

        # Check XPath for heading elements
        xpath_lower = segment.dom_locator.lower()
        if any(tag in xpath_lower for tag in ["/h1[", "/h2[", "/h3[", "/h4[", "/h5[", "/h6["]):
            return True

        return False

    def _detect_section_type(self, text: str) -> SectionType:
        """
        Detect section type from heading text using pattern matching.

        Args:
            text: Heading text to classify

        Returns:
            Detected SectionType or SectionType.UNKNOWN if no match
        """
        normalized = normalize_text(text)

        # Try each section type's patterns
        for section_type, patterns in self._compiled_patterns.items():
            for pattern in patterns:
                if pattern.search(normalized):
                    logger.debug(
                        f"Detected section {section_type.value} from text: {normalized[:50]}"
                    )
                    return section_type

        return SectionType.UNKNOWN

    def _build_section_path(self, section_type: SectionType) -> list[str]:
        """
        Build hierarchical section path for a section type.

        Args:
            section_type: Section type to build path for

        Returns:
            List of section names forming the path
        """
        # For now, simple single-level paths
        # Future: support nested sections (e.g., ["Business", "Products"])
        if section_type == SectionType.UNKNOWN:
            return ["Unknown"]

        # Convert enum value to title case for display
        # e.g., "risk_factors" -> "Risk Factors"
        display_name = section_type.value.replace("_", " ").title()
        return [display_name]

    def process(self, context: pipeline.PipelineContext) -> pipeline.StageResult:
        """
        Classify document sections and assign section_type to segments.

        Algorithm:
        1. Start with COVER section (default for beginning)
        2. Scan segments sequentially
        3. When a section heading is detected, switch current section
        4. Assign current section to all segments until next heading
        5. Build section_path for hierarchical context

        Args:
            context: Pipeline context with segments from Stage 1

        Returns:
            StageResult with processing metrics
        """
        # Import here to avoid circular import
        from src.extraction_v2.pipeline import PipelineStage, StageResult

        start_time = datetime.now(UTC)
        errors: list[str] = []
        warnings: list[str] = []

        try:
            # Validate input
            if not context.segments:
                warnings.append("No segments to classify")
                return StageResult(
                    stage=PipelineStage.SECTION_CLASSIFICATION,
                    success=True,
                    duration_ms=0,
                    items_processed=0,
                    items_output=0,
                    warnings=warnings,
                )

            logger.info(f"Classifying sections for {len(context.segments)} segments")

            # Initialize section tracking
            current_section = SectionType.COVER
            section_path = self._build_section_path(current_section)
            sections_detected: dict[SectionType, int] = {SectionType.COVER: 0}

            # Process each segment
            for segment in context.segments:
                # Check if this segment starts a new section
                if self._is_section_heading(segment):
                    detected_section = self._detect_section_type(segment.text)

                    if detected_section != SectionType.UNKNOWN:
                        # Switch to new section
                        current_section = detected_section
                        section_path = self._build_section_path(current_section)

                        # Track section detection
                        sections_detected[current_section] = (
                            sections_detected.get(current_section, 0) + 1
                        )

                        logger.debug(
                            f"Section heading detected: {current_section.value} "
                            f"at segment {segment.sequence}"
                        )

                # Assign section to segment
                segment.section_type = current_section
                segment.section_path = section_path.copy()

            # Summary logging
            logger.info(f"Section classification complete. Detected sections: {sections_detected}")

            # Calculate duration
            duration_ms = int((datetime.now(UTC) - start_time).total_seconds() * 1000)

            return StageResult(
                stage=PipelineStage.SECTION_CLASSIFICATION,
                success=True,
                duration_ms=duration_ms,
                items_processed=len(context.segments),
                items_output=len(context.segments),
                errors=errors,
                warnings=warnings,
                metadata={
                    "sections_detected": {k.value: v for k, v in sections_detected.items()},
                    "section_types": list(set(s.section_type.value for s in context.segments)),
                },
            )

        except V2FatalError:
            raise
        except Exception as e:
            raise V2FatalError(str(e), stage_name="section_classification") from e
