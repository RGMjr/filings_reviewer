"""
Segment Enricher - Enrich classified segments with richness metadata.

This module computes richness metadata for SourceSegments after classification:
- Metric density (metrics per 100 characters)
- Distinct metric count
- Temporal trend detection
- Cohort breakdown detection
- Image/chart detection
- (Future: richness score)

The enricher operates on in-memory objects without database dependencies.
"""

import logging
import re
from typing import List, Optional, Pattern

from bs4 import BeautifulSoup, Tag

from .models import SourceSegment

logger = logging.getLogger(__name__)


class SegmentEnricher:
    """
    Enrich classified segments with richness metadata.

    This class computes additional metadata for SourceSegments that have
    already been classified by MetricClassifier. It operates on in-memory
    objects and does not require database access.

    Current capabilities (G4-G7):
    - metric_density: metrics per 100 characters
    - distinct_metric_count: count of unique metric IDs
    - contains_temporal_trend: segment discusses multiple time periods (G5)
    - contains_cohort_breakdown: segment contains cohort analysis patterns (G6)
    - image_count: count of meaningful images/charts in segment (G7)

    Future capabilities (G8):
    - richness_score (G8)
    """

    # Keywords that indicate a decorative (non-meaningful) image (G7)
    DECORATIVE_KEYWORDS: List[str] = ["icon", "logo", "bullet", "arrow", "spacer"]

    # Compiled regex patterns for temporal trend detection (G5)
    # Year pattern: 4-digit years in range 2000-2099
    YEAR_PATTERN: Pattern[str] = re.compile(r"\b20\d{2}\b")

    # Fiscal period pattern: FY2023, FY 2022, Q1 2023, Q4 2022, etc.
    FISCAL_PERIOD_PATTERN: Pattern[str] = re.compile(
        r"\b(?:FY|Q[1-4])\s*20\d{2}\b", re.IGNORECASE
    )

    # Year-over-year language patterns (case-insensitive)
    YOY_PATTERNS: List[Pattern[str]] = [
        re.compile(r"\byear[- ]over[- ]year\b", re.IGNORECASE),
        re.compile(r"\byoy\b", re.IGNORECASE),
        re.compile(
            r"\bcompared to (?:the )?(?:prior|previous|same)\s+(?:year|period)\b",
            re.IGNORECASE,
        ),
    ]

    # Compiled regex patterns for cohort breakdown detection (G6)
    COHORT_PATTERNS: List[Pattern[str]] = [
        # Percentage breakdowns with customer/user context
        # Matches: "44.4% of consumers", "15% of users"
        re.compile(
            r"\b\d+(?:\.\d+)?%\s+of\s+(?:customers?|users?|consumers?)\b",
            re.IGNORECASE,
        ),
        # Matches: "X% were new customers", "X% are enterprise users"
        re.compile(
            r"\b\d+(?:\.\d+)?%\s+(?:were|are)\s+\w+\s+(?:customers?|users?|consumers?)\b",
            re.IGNORECASE,
        ),
        re.compile(
            r"\b(?:new|existing|repeat|returning)\s+(?:customers?|users?|consumers?)\s+"
            r"(?:represented|accounted for)",
            re.IGNORECASE,
        ),
        # Explicit cohort analysis language
        re.compile(r"\bcohort\s+analysis\b", re.IGNORECASE),
        re.compile(
            r"\bby\s+(?:acquisition|tenure|vintage)\s+cohort\b", re.IGNORECASE
        ),
        re.compile(r"\bcustomers?\s+acquired\s+in\s+20\d{2}\b", re.IGNORECASE),
        # Customer segmentation language
        re.compile(
            r"\b(?:first|second|third|subsequent)[- ]?year\s+customers?\b",
            re.IGNORECASE,
        ),
        re.compile(
            r"\b(?:new|existing)\s+vs\.?\s+(?:existing|new)\s+customers?\b",
            re.IGNORECASE,
        ),
        re.compile(r"\bcustomer\s+(?:age|tenure|lifetime)\b", re.IGNORECASE),
    ]

    def __init__(self) -> None:
        """Initialize enricher (stateless, patterns compiled at class level)."""
        pass

    def enrich_batch(self, segments: List[SourceSegment]) -> List[SourceSegment]:
        """
        Enrich all segments with richness metadata.

        Args:
            segments: Classified segments to enrich (mutated in place)

        Returns:
            Same segments list with enrichment fields populated
        """
        if not segments:
            logger.info("No segments to enrich")
            return segments

        enriched_count = 0
        warning_count = 0

        for segment in segments:
            try:
                self._enrich_segment(segment)
                enriched_count += 1
            except Exception as e:
                logger.warning(
                    f"Failed to enrich segment {segment.sequence_index}: {e}"
                )
                warning_count += 1

        logger.info(
            f"Enriched {enriched_count} segments"
            + (f" ({warning_count} warnings)" if warning_count else "")
        )

        return segments

    def _enrich_segment(self, segment: SourceSegment) -> None:
        """
        Enrich single segment (mutates in place).

        Args:
            segment: Segment to enrich
        """
        # Compute metric density and distinct count (G4)
        segment.metric_density = self._compute_metric_density(segment)
        segment.distinct_metric_count = self._compute_distinct_metric_count(segment)

        # Detect temporal trends (G5)
        segment.contains_temporal_trend = self._detect_temporal_trends(segment)

        # Detect cohort breakdowns (G6)
        segment.contains_cohort_breakdown = self._detect_cohort_breakdowns(segment)

        # Detect images/charts (G7)
        segment.image_count = self._detect_images(segment)

        # Future enrichments (G8) will be added here:
        # - self._compute_richness_score(segment)

    def _compute_metric_density(self, segment: SourceSegment) -> float:
        """
        Compute metrics per 100 characters.

        Formula: (unique_metrics / text_length) * 100

        Args:
            segment: Segment to compute density for

        Returns:
            Metric density rounded to 2 decimal places, or 0.0 for edge cases
        """
        # Handle edge cases
        raw_text = segment.raw_text
        if raw_text is None:
            return 0.0

        text_length = len(raw_text)
        if text_length == 0:
            return 0.0

        candidate_metric_ids = segment.candidate_metric_ids
        if candidate_metric_ids is None:
            return 0.0

        unique_metrics = len(set(candidate_metric_ids))
        if unique_metrics == 0:
            return 0.0

        # Compute density: (unique_metrics / text_length) * 100
        density = (unique_metrics / text_length) * 100

        return round(density, 2)

    def _compute_distinct_metric_count(self, segment: SourceSegment) -> int:
        """
        Compute count of unique metric IDs in segment.

        Args:
            segment: Segment to count metrics for

        Returns:
            Count of unique metric IDs, or 0 for edge cases
        """
        candidate_metric_ids = segment.candidate_metric_ids
        if candidate_metric_ids is None:
            return 0

        return len(set(candidate_metric_ids))

    def _detect_temporal_trends(self, segment: SourceSegment) -> bool:
        """
        Detect if segment discusses multiple time periods.

        Returns True if any of these conditions are met:
        - 2+ distinct years (2000-2099) are mentioned
        - 2+ distinct fiscal periods (FY/Q1-Q4) are mentioned
        - Year-over-year comparison language is present

        Args:
            segment: Segment to analyze for temporal trends

        Returns:
            True if temporal trend detected, False otherwise
        """
        text = segment.raw_text

        # Handle edge cases: None, empty, or non-string
        if text is None:
            return False
        if not isinstance(text, str):
            logger.warning(
                f"Non-string raw_text in segment {segment.sequence_index}: {type(text)}"
            )
            return False
        if not text:
            return False

        # Check for multiple distinct years (primary signal)
        years = set(self.YEAR_PATTERN.findall(text))
        if len(years) >= 2:
            return True

        # Check for multiple distinct fiscal periods (secondary signal)
        fiscal_periods = set(self.FISCAL_PERIOD_PATTERN.findall(text.upper()))
        if len(fiscal_periods) >= 2:
            return True

        # Check for year-over-year language (tertiary signal)
        for pattern in self.YOY_PATTERNS:
            if pattern.search(text):
                return True

        return False

    def _detect_cohort_breakdowns(self, segment: SourceSegment) -> bool:
        """
        Detect if segment contains cohort analysis patterns.

        Returns True if any of these conditions are met:
        - Percentage breakdowns with customer/user context
        - Explicit cohort analysis keywords
        - New/existing customer segmentation language
        - 2+ metric IDs containing 'cohort' or 'tenure'

        Args:
            segment: Segment to analyze for cohort patterns

        Returns:
            True if cohort breakdown detected, False otherwise
        """
        text = segment.raw_text

        # Handle edge cases: None, empty, or non-string
        if text is None:
            return False
        if not isinstance(text, str):
            logger.warning(
                f"Non-string raw_text in segment {segment.sequence_index}: {type(text)}"
            )
            return False
        if not text:
            return False

        # Check regex patterns for cohort language
        for pattern in self.COHORT_PATTERNS:
            if pattern.search(text):
                return True

        # Check for multiple cohort-related metric IDs (quaternary signal)
        candidate_metric_ids = segment.candidate_metric_ids
        if candidate_metric_ids:
            cohort_metrics = [
                m
                for m in candidate_metric_ids
                if "cohort" in m.lower() or "tenure" in m.lower()
            ]
            if len(cohort_metrics) >= 2:
                return True

        return False

    def _detect_images(self, segment: SourceSegment) -> int:
        """
        Count meaningful images/charts in segment HTML.

        Counts <img>, <svg>, and <canvas> tags, filtering out decorative
        images (small icons, logos, bullets, etc.).

        Args:
            segment: Segment to analyze for images

        Returns:
            Count of meaningful images/charts (0 for edge cases or errors)
        """
        raw_html = segment.raw_html

        # Handle edge cases: None or empty
        if raw_html is None:
            return 0
        if not raw_html:
            return 0

        try:
            soup = BeautifulSoup(raw_html, "html.parser")

            # Count SVG and canvas (always meaningful - typically charts)
            svg_count = len(soup.find_all("svg"))
            canvas_count = len(soup.find_all("canvas"))

            # Count meaningful images (filtered for decorative elements)
            img_tags = soup.find_all("img")
            meaningful_imgs = [
                img for img in img_tags if not self._is_decorative_image(img)
            ]

            return len(meaningful_imgs) + svg_count + canvas_count

        except Exception as e:
            logger.debug(f"Error parsing HTML for images: {e}")
            return 0

    def _is_decorative_image(self, img: Tag) -> bool:
        """
        Check if image tag is decorative (icon, logo, bullet, etc.).

        An image is considered decorative if any of:
        - Width attribute < 100 pixels
        - Height attribute < 100 pixels
        - Class contains decorative keywords (icon, logo, bullet, arrow, spacer)
        - Alt text contains decorative keywords

        Args:
            img: BeautifulSoup Tag element for an <img> tag

        Returns:
            True if image is decorative and should be filtered out
        """
        # Check width attribute
        width = self._parse_dimension(img.get("width", ""))
        if width is not None and width < 100:
            return True

        # Check height attribute
        height = self._parse_dimension(img.get("height", ""))
        if height is not None and height < 100:
            return True

        # Build combined text from class and alt attributes for keyword check
        classes_attr = img.get("class")
        if classes_attr is None:
            class_text = ""
        elif isinstance(classes_attr, list):
            class_text = " ".join(str(c) for c in classes_attr)
        else:
            class_text = str(classes_attr)

        alt_attr = img.get("alt")
        alt_text = str(alt_attr) if alt_attr is not None else ""

        combined = (class_text + " " + alt_text).lower()

        # Check for decorative keywords
        for keyword in self.DECORATIVE_KEYWORDS:
            if keyword in combined:
                return True

        return False

    def _parse_dimension(self, value: object) -> Optional[int]:
        """
        Parse width/height attribute, returning None if not a pixel value.

        Handles:
        - Integer strings: "100" -> 100
        - Pixel suffix: "100px" -> 100
        - Percentage values: "100%" -> None (not a pixel value)
        - Empty/missing: "" -> None

        Args:
            value: The width or height attribute value (can be str or other types)

        Returns:
            Integer pixel value, or None if not parseable as pixels
        """
        if value is None:
            return None

        # Convert to string if not already
        if not isinstance(value, str):
            value = str(value)

        if not value:
            return None

        # Strip whitespace and remove 'px' suffix
        value = value.strip().lower()
        if value.endswith("px"):
            value = value[:-2].strip()

        # Percentage values are not pixel counts
        if "%" in value:
            return None

        # Try to parse as integer
        if value.isdigit():
            return int(value)

        return None
