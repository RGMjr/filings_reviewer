"""
Segment Enricher - Enrich classified segments with richness metadata.

This module computes richness metadata for SourceSegments after classification:
- Metric density (metrics per 100 characters)
- Distinct metric count
- Temporal trend detection
- Cohort breakdown detection
- Image/chart detection
- Richness score (composite 0-10 score identifying "goldmine" segments)

Also provides clustering utilities (module-level functions):
- cluster_goldmine_segments(): Group adjacent high-richness segments
- summarize_cluster(): Generate statistics for a cluster

The enricher operates on in-memory objects without database dependencies.
"""

import logging
import re
from typing import Any, Dict, List, Optional, Pattern, Set

from bs4 import BeautifulSoup, Tag

from .models import SourceSegment

logger = logging.getLogger(__name__)


class SegmentEnricher:
    """
    Enrich classified segments with richness metadata.

    This class computes additional metadata for SourceSegments that have
    already been classified by MetricClassifier. It operates on in-memory
    objects and does not require database access.

    Current capabilities (G4-G8):
    - metric_density: metrics per 100 characters
    - distinct_metric_count: count of unique metric IDs
    - contains_temporal_trend: segment discusses multiple time periods (G5)
    - contains_cohort_breakdown: segment contains cohort analysis patterns (G6)
    - image_count: count of meaningful images/charts in segment (G7)
    - richness_score: composite score 0-10 identifying "goldmine" segments (G8)
    """

    # Threshold score for identifying "goldmine" segments (G8)
    GOLDMINE_THRESHOLD: float = 6.0

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

        # Log goldmine statistics (G8)
        goldmines = [
            s for s in segments if (s.richness_score or 0) >= self.GOLDMINE_THRESHOLD
        ]
        if goldmines:
            avg_richness = sum(s.richness_score or 0 for s in goldmines) / len(goldmines)
            logger.info(
                f"Found {len(goldmines)} goldmine segments (avg richness: {avg_richness:.1f})"
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

        # Compute richness score (G8) - MUST be last, depends on other enrichments
        segment.richness_score = self._compute_richness_score(segment)

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

    def _compute_richness_score(self, segment: SourceSegment) -> float:
        """
        Compute composite richness score (0-10).

        Formula components (max 10 points total):
        - Base confidence: 0-3 points (classifier_confidence * 3.0)
        - Metric density: 0-2 points (min(distinct_metric_count * 0.5, 2.0))
        - Temporal trends: 1 point if contains_temporal_trend
        - Cohort breakdowns: 1.5 points if contains_cohort_breakdown
        - Definitions: 1 point if contains_definition_flag
        - Images: 0-1.5 points (min(image_count * 0.5, 1.5))

        Segments scoring >= 6.0 are considered "goldmines" - high-value
        sections with dense metrics, temporal trends, cohort analysis,
        definitions, and/or visual content.

        Args:
            segment: Enriched segment with all fields populated

        Returns:
            Richness score (0.0-10.0), rounded to 2 decimal places
        """
        score = 0.0

        # Base confidence (max 3.0)
        confidence = segment.classifier_confidence or 0.0
        score += confidence * 3.0

        # Metric density bonus (max 2.0)
        metric_count = segment.distinct_metric_count or 0
        score += min(metric_count * 0.5, 2.0)

        # Boolean flag bonuses
        if segment.contains_temporal_trend:
            score += 1.0
        if segment.contains_cohort_breakdown:
            score += 1.5
        if segment.contains_definition_flag:
            score += 1.0

        # Image bonus (max 1.5)
        image_count = segment.image_count or 0
        score += min(image_count * 0.5, 1.5)

        # Cap at 10.0 and round to 2 decimal places
        return round(min(score, 10.0), 2)


# =============================================================================
# Clustering Utilities (G9) - Module-level functions
# =============================================================================


def cluster_goldmine_segments(
    segments: List[SourceSegment],
    richness_threshold: float = 6.0,
    max_gap: int = 3,
) -> List[List[SourceSegment]]:
    """
    Group adjacent high-richness segments into clusters.

    Clusters are formed by grouping segments that:
    1. Meet or exceed the richness_threshold
    2. Are adjacent within max_gap sequence indices

    Args:
        segments: List of enriched segments with richness_score populated
        richness_threshold: Minimum richness_score to include (default 6.0)
        max_gap: Maximum gap in sequence_index between adjacent segments
                 in same cluster (default 3)

    Returns:
        List of clusters, where each cluster is a list of SourceSegments
        sorted by sequence_index. Empty list if no goldmine segments found.

    Example:
        >>> enricher = SegmentEnricher()
        >>> enricher.enrich_batch(segments)
        >>> clusters = cluster_goldmine_segments(segments)
        >>> for cluster in clusters:
        ...     summary = summarize_cluster(cluster)
        ...     print(f"Cluster: {summary['segment_count']} segments")
    """
    if not segments:
        return []

    # Filter segments meeting threshold, handling None richness_score
    goldmines: List[SourceSegment] = []
    for seg in segments:
        # Skip segments with None sequence_index
        if seg.sequence_index is None:
            logger.warning(
                f"Segment with None sequence_index skipped during clustering "
                f"(filing_id={seg.filing_id})"
            )
            continue

        # Treat None richness_score as 0.0
        score = seg.richness_score if seg.richness_score is not None else 0.0
        if score >= richness_threshold:
            goldmines.append(seg)

    if not goldmines:
        return []

    # Sort by sequence_index
    goldmines.sort(key=lambda s: s.sequence_index)

    # Group into clusters based on gap
    clusters: List[List[SourceSegment]] = []
    current_cluster: List[SourceSegment] = [goldmines[0]]

    for i in range(1, len(goldmines)):
        prev_idx = goldmines[i - 1].sequence_index
        curr_idx = goldmines[i].sequence_index
        # Type narrowing - we already filtered None values above
        assert prev_idx is not None and curr_idx is not None

        gap = curr_idx - prev_idx
        if gap <= max_gap:
            # Adjacent - add to current cluster
            current_cluster.append(goldmines[i])
        else:
            # Gap too large - start new cluster
            clusters.append(current_cluster)
            current_cluster = [goldmines[i]]

    # Don't forget the last cluster
    clusters.append(current_cluster)

    return clusters


def summarize_cluster(cluster: List[SourceSegment]) -> Dict[str, Any]:
    """
    Generate summary statistics for a cluster of segments.

    Args:
        cluster: List of SourceSegments in a cluster (typically from
                 cluster_goldmine_segments output)

    Returns:
        Dictionary with cluster statistics:
        - start_sequence: int - first segment's sequence_index
        - end_sequence: int - last segment's sequence_index
        - segment_count: int - number of segments in cluster
        - section_heading: Optional[str] - first segment's section_heading
        - avg_richness: float - mean richness_score (rounded to 2 decimals)
        - unique_metrics: int - count of distinct metric IDs across all segments
        - has_definition: bool - any segment has contains_definition_flag=True
        - has_cohorts: bool - any segment has contains_cohort_breakdown=True
        - has_temporal: bool - any segment has contains_temporal_trend=True
        - has_images: bool - any segment has image_count > 0

        Returns empty dict if cluster is empty.

    Example:
        >>> summary = summarize_cluster(cluster)
        >>> print(f"Cluster spans segments {summary['start_sequence']}-{summary['end_sequence']}")
        >>> print(f"Average richness: {summary['avg_richness']}")
    """
    if not cluster:
        return {}

    # Sort cluster by sequence_index to ensure correct start/end
    sorted_cluster = sorted(cluster, key=lambda s: s.sequence_index or 0)

    # Compute sequence range
    start_seq = sorted_cluster[0].sequence_index or 0
    end_seq = sorted_cluster[-1].sequence_index or 0

    # Compute average richness (treating None as 0.0)
    richness_scores = [
        s.richness_score if s.richness_score is not None else 0.0
        for s in sorted_cluster
    ]
    avg_richness = sum(richness_scores) / len(richness_scores)

    # Collect unique metrics across all segments
    all_metrics: Set[str] = set()
    for seg in sorted_cluster:
        if seg.candidate_metric_ids:
            all_metrics.update(seg.candidate_metric_ids)

    # Aggregate boolean flags
    has_definition = any(s.contains_definition_flag for s in sorted_cluster)
    has_cohorts = any(s.contains_cohort_breakdown for s in sorted_cluster)
    has_temporal = any(s.contains_temporal_trend for s in sorted_cluster)
    has_images = any((s.image_count or 0) > 0 for s in sorted_cluster)

    return {
        "start_sequence": start_seq,
        "end_sequence": end_seq,
        "segment_count": len(sorted_cluster),
        "section_heading": sorted_cluster[0].section_heading,
        "avg_richness": round(avg_richness, 2),
        "unique_metrics": len(all_metrics),
        "has_definition": has_definition,
        "has_cohorts": has_cohorts,
        "has_temporal": has_temporal,
        "has_images": has_images,
    }
