"""
Candidate Generator - Generate review candidates from filing segments.

This module scans source segments for numbers near metric keywords,
creating candidates for human review. It implements a high-recall
detection strategy to catch potential metrics.

Algorithm:
1. For each segment, find all numbers using regex
2. For each number, find metric keywords within 100 characters
3. Deduplicate by (number_position, metric_id)
4. Extract context (30-50 words each direction)
5. Create ReviewCandidate objects for bulk insert
"""

import logging
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Set, Tuple

from src.extraction.metric_classifier import MetricClassifier
from src.review.feature_extractor import (
    DEFINITION_PATTERNS,
    PERIOD_PATTERNS,
    RISK_FACTORS_PATTERNS,
    FeatureExtractor,
)
from src.review.models import CandidateFeatures, ReviewCandidate

logger = logging.getLogger(__name__)


# =============================================================================
# Custom Exceptions
# =============================================================================


class CandidateGenerationError(Exception):
    """Base exception for candidate generation errors."""

    pass


class SegmentProcessingError(CandidateGenerationError):
    """Error processing a specific segment."""

    def __init__(
        self,
        message: str,
        segment_id: Optional[int] = None,
        original_error: Optional[Exception] = None,
    ):
        super().__init__(message)
        self.segment_id = segment_id
        self.original_error = original_error


class NumberProcessingError(CandidateGenerationError):
    """Error processing a specific number match."""

    def __init__(
        self,
        message: str,
        number_text: Optional[str] = None,
        position: Optional[int] = None,
        original_error: Optional[Exception] = None,
    ):
        super().__init__(message)
        self.number_text = number_text
        self.position = position
        self.original_error = original_error


@dataclass
class ProcessingStats:
    """Statistics from candidate generation processing."""

    segments_processed: int = 0
    segments_failed: int = 0
    numbers_found: int = 0
    numbers_failed: int = 0
    candidates_generated: int = 0
    false_positives_filtered: int = 0
    duplicates_removed: int = 0

    @property
    def segment_success_rate(self) -> float:
        """Percentage of segments successfully processed."""
        total = self.segments_processed + self.segments_failed
        if total == 0:
            return 1.0
        return self.segments_processed / total

    @property
    def number_success_rate(self) -> float:
        """Percentage of numbers successfully processed."""
        total = self.numbers_found + self.numbers_failed
        if total == 0:
            return 1.0
        return self.numbers_found / total

    def log_summary(self, filing_id: int) -> None:
        """Log a summary of processing stats."""
        logger.info(
            f"Filing {filing_id} stats: "
            f"segments={self.segments_processed}/{self.segments_processed + self.segments_failed}, "
            f"numbers={self.numbers_found}, "
            f"filtered={self.false_positives_filtered}, "
            f"duplicates={self.duplicates_removed}, "
            f"candidates={self.candidates_generated}"
        )
        if self.segments_failed > 0:
            logger.warning(
                f"Filing {filing_id}: {self.segments_failed} segments failed to process"
            )
        if self.numbers_failed > 0:
            logger.warning(
                f"Filing {filing_id}: {self.numbers_failed} numbers failed to process"
            )
        if self.duplicates_removed > 0:
            logger.debug(
                f"Filing {filing_id}: {self.duplicates_removed} duplicate candidates removed"
            )


# =============================================================================
# Number Detection Patterns
# =============================================================================

# Pattern to match numbers with optional currency, commas, decimals, and suffixes
# Supports both comma-separated (1,234,567) and plain integers (1234567)
NUMBER_PATTERN = r"""
    (?P<currency>\$)?                           # Optional currency symbol
    \s*
    (?P<number>
        -?                                      # Optional negative sign
        (?:
            \d{1,3}(?:,\d{3})+                 # Comma-separated (1,234 or 1,234,567)
            |
            \d+                                 # Or plain integer (1234567)
        )
        (?:\.\d+)?                              # Optional decimal part
    )
    \s*
    (?P<suffix>million|billion|thousand|mn|bn|k|m|b|%|percent)?  # Optional suffix
"""

NUMBER_REGEX = re.compile(NUMBER_PATTERN, re.IGNORECASE | re.VERBOSE)


# =============================================================================
# Metric Keywords (imported from metric_classifier.py)
# =============================================================================

# Import keywords from the authoritative source to ensure consistency
# between candidate generation and metric classification
METRIC_KEYWORDS: Dict[str, List[str]] = MetricClassifier.METRIC_KEYWORDS


# =============================================================================
# Feature Detection Patterns (imported from feature_extractor)
# =============================================================================
# DEFINITION_PATTERNS, PERIOD_PATTERNS, and RISK_FACTORS_PATTERNS are now
# imported from src.review.feature_extractor to maintain single source of truth.


# =============================================================================
# False Positive Detection Patterns
# =============================================================================

# Date patterns - to detect if a number is part of a date
DATE_CONTEXT_PATTERNS = [
    # MM/DD/YYYY or DD/MM/YYYY
    re.compile(r"\d{1,2}/\d{1,2}/\d{2,4}"),
    # Month DD, YYYY
    re.compile(
        r"(?:January|February|March|April|May|June|July|August|September|"
        r"October|November|December)\s+\d{1,2},?\s+\d{4}",
        re.IGNORECASE,
    ),
    # DD Month YYYY
    re.compile(
        r"\d{1,2}\s+(?:January|February|March|April|May|June|July|August|"
        r"September|October|November|December)\s+\d{4}",
        re.IGNORECASE,
    ),
]

# Patterns that indicate a number is NOT a metric (contextual false positives)
FALSE_POSITIVE_CONTEXT_PATTERNS = [
    # Page references: "page 123", "pages 10-20"
    re.compile(r"\bpages?\s+\d+", re.IGNORECASE),
    # Note references: "Note 5", "Notes 1-3"
    re.compile(r"\bnotes?\s+\d+", re.IGNORECASE),
    # Section references: "Section 5.1"
    re.compile(r"\bsections?\s+\d+", re.IGNORECASE),
    # Item references: "Item 1A"
    re.compile(r"\bitems?\s+\d+", re.IGNORECASE),
    # Version numbers: "Version 2.0", "v2.1"
    re.compile(r"\b(?:version|v)\s*\d+(?:\.\d+)*", re.IGNORECASE),
    # Exhibit references: "Exhibit 10.1"
    re.compile(r"\bexhibits?\s+\d+", re.IGNORECASE),
    # Table references: "Table 1"
    re.compile(r"\btables?\s+\d+", re.IGNORECASE),
    # Figure references: "Figure 3"
    re.compile(r"\bfigures?\s+\d+", re.IGNORECASE),
    # Footnote references: "[1]", "(1)"
    re.compile(r"[\[\(]\d+[\]\)]"),
    # Chapter references: "Chapter 5"
    re.compile(r"\bchapters?\s+\d+", re.IGNORECASE),
    # Part references: "Part II"
    re.compile(r"\bparts?\s+(?:I{1,3}|IV|V|VI{0,3}|\d+)", re.IGNORECASE),
]

# Year range - numbers in this range are likely years, not metrics
YEAR_MIN = 1990
YEAR_MAX = 2100

# Minimum value threshold - very small numbers are rarely metrics
MIN_METRIC_VALUE = 10  # Filter out single-digit numbers by default


# =============================================================================
# Confidence Scoring Constants
# =============================================================================

# Expected number formats for each metric type
METRIC_EXPECTED_FORMATS: Dict[str, List[str]] = {
    # Customer counts - expect integers
    "cm_active_customers_total": ["integer", "currency"],  # "$X customers" appears
    "cm_active_customers_enterprise": ["integer"],
    "cm_active_customers_smb": ["integer"],
    "cm_total_users": ["integer"],
    "cm_dau": ["integer"],
    "cm_mau": ["integer"],
    # Revenue metrics - expect currency or percentages
    "cm_arr": ["currency"],
    "cm_mrr": ["currency"],
    "cm_revenue_per_customer": ["currency", "decimal"],
    "cm_aov": ["currency", "decimal"],
    "cm_cac": ["currency"],
    "cm_ltv": ["currency"],
    # Retention metrics - expect percentages or decimals
    "cm_nrr": ["percentage", "decimal"],
    "cm_grr": ["percentage", "decimal"],
    "cm_churn_rate": ["percentage", "decimal"],
    "cm_customer_churn_rate": ["percentage", "decimal"],
    "cm_logo_retention": ["percentage", "decimal"],
    # Growth metrics - expect percentages or integers
    "cm_new_customers": ["integer"],
    "cm_net_customer_additions": ["integer"],
    "cm_customer_growth_rate": ["percentage"],
}

# Keywords that are more specific (multi-word) get a bonus
# Single-word keywords like "customers" are ambiguous
SPECIFIC_KEYWORD_PATTERNS = [
    r"active\s+customers?",
    r"enterprise\s+customers?",
    r"paying\s+customers?",
    r"total\s+customers?",
    r"net\s+revenue\s+retention",
    r"gross\s+revenue\s+retention",
    r"net\s+dollar\s+retention",
    r"customer\s+acquisition\s+cost",
    r"lifetime\s+value",
    r"average\s+revenue\s+per",
    r"annual\s+recurring\s+revenue",
    r"monthly\s+recurring\s+revenue",
    r"daily\s+active\s+users?",
    r"monthly\s+active\s+users?",
]


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class NumberMatch:
    """A number found in text with position and parsed value."""

    start: int  # Character position in text
    end: int  # End position
    raw_text: str  # Original text (e.g., "$1,234.56 million")
    value: Optional[Decimal]  # Parsed numeric value
    unit: Optional[str]  # Detected unit ('count', '%', 'usd', etc.)


@dataclass
class KeywordMatch:
    """A keyword match found in text."""

    start: int  # Character position
    end: int  # End position
    keyword: str  # The matched text
    metric_id: str  # Associated metric ID
    pattern: str  # The regex pattern that matched


# =============================================================================
# ConfidenceScorer Class
# =============================================================================


class ConfidenceScorer:
    """
    Computes suggestion confidence for review candidates.

    The confidence score ranges from 0.0 (likely false positive) to 1.0
    (high confidence). It combines multiple signals:

    - Keyword distance: Closer = higher confidence
    - Keyword position: 'before' pattern is slightly stronger
    - Definition language: "we define X as..." is very strong signal
    - Period mention: Time context suggests real metric
    - Risk factors penalty: High false positive section
    - Format match: Number format matches metric type expectation
    - Keyword specificity: Multi-word keywords are more specific
    - Surrounding numbers penalty: Many numbers = ambiguous context

    Score interpretation:
    - 0.0-0.3: Low confidence (probable false positive)
    - 0.3-0.5: Moderate (needs careful review)
    - 0.5-0.7: Good (probably correct)
    - 0.7-1.0: High (very likely correct)
    """

    # Scoring weights
    BASE_SCORE = 0.30  # Starting score for any candidate
    DISTANCE_MAX_WEIGHT = 0.25  # Max bonus for close distance
    POSITION_BEFORE_BONUS = 0.05  # Bonus if keyword is before number
    DEFINITION_BONUS = 0.20  # Bonus for definition language
    PERIOD_BONUS = 0.05  # Bonus for period mention
    FORMAT_MATCH_BONUS = 0.10  # Bonus if format matches metric type
    SPECIFIC_KEYWORD_BONUS = 0.10  # Bonus for multi-word specific keyword
    RISK_FACTORS_PENALTY = 0.25  # Penalty for risk factors section
    SURROUNDING_NUMBERS_PENALTY_MAX = 0.15  # Max penalty for many numbers
    TABLE_AMBIGUITY_PENALTY = 0.05  # Penalty for table without definition

    def __init__(self, max_keyword_distance: int = 100):
        """
        Initialize the confidence scorer.

        Args:
            max_keyword_distance: Maximum distance for keyword matching
                                 (used to scale distance score)
        """
        self.max_keyword_distance = max_keyword_distance
        # Compile specific keyword patterns
        self._specific_patterns = [
            re.compile(p, re.IGNORECASE) for p in SPECIFIC_KEYWORD_PATTERNS
        ]

    def compute_confidence(
        self,
        keyword_distance: int,
        keyword_position: str,
        keyword: str,
        metric_id: str,
        features: CandidateFeatures,
    ) -> float:
        """
        Compute confidence score for a candidate.

        Args:
            keyword_distance: Character distance from number to keyword
            keyword_position: 'before' or 'after'
            keyword: The triggering keyword text
            metric_id: The suggested metric ID
            features: CandidateFeatures for this candidate

        Returns:
            Confidence score between 0.0 and 1.0
        """
        score = self.BASE_SCORE

        # Distance score: linear decay from max bonus at 0 to 0 at max_distance
        distance_ratio = 1.0 - min(
            keyword_distance / self.max_keyword_distance, 1.0
        )
        score += self.DISTANCE_MAX_WEIGHT * distance_ratio

        # Position bonus: keyword before number is slightly more reliable
        if keyword_position == "before":
            score += self.POSITION_BEFORE_BONUS

        # Definition language bonus: strong signal
        if features.contains_definition_language:
            score += self.DEFINITION_BONUS

        # Period mention bonus: suggests time-specific metric
        if features.has_period_mention:
            score += self.PERIOD_BONUS

        # Format match bonus: number format matches expected for metric
        expected_formats = METRIC_EXPECTED_FORMATS.get(metric_id, [])
        if features.number_format in expected_formats:
            score += self.FORMAT_MATCH_BONUS

        # Specific keyword bonus: multi-word keywords are more reliable
        if self._is_specific_keyword(keyword):
            score += self.SPECIFIC_KEYWORD_BONUS

        # Risk factors penalty: high false positive section
        if features.is_in_risk_factors:
            score -= self.RISK_FACTORS_PENALTY

        # Surrounding numbers penalty: many numbers suggests ambiguous context
        # Scale penalty: 0 at 0-2 numbers, max at 10+ numbers
        if features.surrounding_numbers_count > 2:
            ratio = min((features.surrounding_numbers_count - 2) / 8.0, 1.0)
            score -= self.SURROUNDING_NUMBERS_PENALTY_MAX * ratio

        # Table context: ambiguous if no definition language
        if features.is_in_table and not features.contains_definition_language:
            score -= self.TABLE_AMBIGUITY_PENALTY

        # Clamp to valid range
        return max(0.0, min(1.0, score))

    def _is_specific_keyword(self, keyword: str) -> bool:
        """
        Check if keyword is a specific multi-word pattern.

        Args:
            keyword: The keyword text

        Returns:
            True if keyword matches a specific pattern
        """
        keyword_lower = keyword.lower()
        for pattern in self._specific_patterns:
            if pattern.search(keyword_lower):
                return True
        return False


# =============================================================================
# CandidateGenerator Class
# =============================================================================


class CandidateGenerator:
    """
    Generates review candidates from source segments.

    The generator scans text for numbers near metric keywords and creates
    ReviewCandidate objects for human review. It uses a high-recall strategy
    to avoid missing potential metrics.
    """

    # Maximum character distance between number and keyword
    MAX_KEYWORD_DISTANCE = 100

    # Context extraction settings
    CONTEXT_WORDS = 40  # Words to extract each direction

    def __init__(
        self,
        max_keyword_distance: int = 100,
        context_words: int = 40,
        filter_false_positives: bool = True,
        min_value: Optional[int] = None,
        filter_years: bool = True,
        compute_confidence: bool = True,
    ):
        """
        Initialize the candidate generator.

        Args:
            max_keyword_distance: Maximum chars between number and keyword
            context_words: Words to extract for context each direction
            filter_false_positives: Enable false positive filtering (default True)
            min_value: Minimum numeric value to consider (default MIN_METRIC_VALUE)
            filter_years: Filter out numbers that look like years (default True)
            compute_confidence: Compute suggestion_confidence scores (default True)
        """
        self.max_keyword_distance = max_keyword_distance
        self.context_words = context_words
        self.filter_false_positives = filter_false_positives
        self.min_value = min_value if min_value is not None else MIN_METRIC_VALUE
        self.filter_years = filter_years
        self.compute_confidence = compute_confidence

        # Initialize confidence scorer
        self._confidence_scorer = ConfidenceScorer(
            max_keyword_distance=max_keyword_distance
        )

        # Initialize feature extractor
        self._feature_extractor = FeatureExtractor()

        # Compile keyword patterns for performance
        self._compiled_patterns: Dict[str, List[re.Pattern]] = {}
        for metric_id, patterns in METRIC_KEYWORDS.items():
            self._compiled_patterns[metric_id] = [
                re.compile(p, re.IGNORECASE) for p in patterns
            ]

    def generate_for_filing(
        self,
        filing_id: int,
        company_id: int,
        segments: List[Dict[str, Any]],
        return_stats: bool = False,
    ) -> List[ReviewCandidate] | Tuple[List[ReviewCandidate], ProcessingStats]:
        """
        Generate candidates from all segments of a filing.

        Args:
            filing_id: The filing ID
            company_id: The company ID
            segments: List of segment dicts from database
            return_stats: If True, return (candidates, stats) tuple

        Returns:
            List of ReviewCandidate objects (not yet saved to DB)
            If return_stats=True, returns tuple of (candidates, ProcessingStats)
        """
        candidates = []
        stats = ProcessingStats()

        for segment in segments:
            # Safely get segment_id for logging (segment might not be a dict)
            segment_id = (
                segment.get("source_segment_id")
                if isinstance(segment, dict)
                else None
            )
            try:
                segment_candidates, segment_stats = self._process_segment(
                    filing_id=filing_id,
                    company_id=company_id,
                    segment=segment,
                )
                candidates.extend(segment_candidates)
                stats.segments_processed += 1
                stats.numbers_found += segment_stats.get("numbers_found", 0)
                stats.numbers_failed += segment_stats.get("numbers_failed", 0)
                stats.false_positives_filtered += segment_stats.get(
                    "false_positives_filtered", 0
                )
                stats.candidates_generated += len(segment_candidates)
            except Exception as e:
                stats.segments_failed += 1
                logger.error(
                    f"Error processing segment {segment_id} in filing {filing_id}: "
                    f"{type(e).__name__}: {e}"
                )
                # Continue processing other segments

        # Deduplicate candidates across segments
        candidates, duplicates_removed = self._deduplicate_candidates(candidates)
        stats.duplicates_removed = duplicates_removed

        stats.log_summary(filing_id)

        if return_stats:
            return candidates, stats
        return candidates

    def _deduplicate_candidates(
        self, candidates: List[ReviewCandidate]
    ) -> Tuple[List[ReviewCandidate], int]:
        """
        Remove duplicate candidates based on (parsed_value, suggested_metric_id).

        When duplicates exist, keep the one with highest suggestion_confidence.
        If confidence is equal or None, keep the first occurrence.

        Args:
            candidates: List of candidates to deduplicate

        Returns:
            Tuple of (deduplicated_candidates, duplicates_removed_count)
        """
        if not candidates:
            return [], 0

        # Group candidates by (parsed_value, suggested_metric_id)
        # Use string representation of Decimal to handle None values
        groups: Dict[Tuple[str, Optional[str]], List[ReviewCandidate]] = {}

        for candidate in candidates:
            # Create key - convert Decimal to string for hashing
            value_key = (
                str(candidate.parsed_value)
                if candidate.parsed_value is not None
                else "None"
            )
            key = (value_key, candidate.suggested_metric_id)

            if key not in groups:
                groups[key] = []
            groups[key].append(candidate)

        # Select best candidate from each group
        deduplicated = []
        for group in groups.values():
            if len(group) == 1:
                deduplicated.append(group[0])
            else:
                # Sort by confidence (descending), None values last
                sorted_group = sorted(
                    group,
                    key=lambda c: (
                        c.suggestion_confidence is not None,
                        c.suggestion_confidence or 0,
                    ),
                    reverse=True,
                )
                deduplicated.append(sorted_group[0])

        duplicates_removed = len(candidates) - len(deduplicated)
        return deduplicated, duplicates_removed

    def _process_segment(
        self,
        filing_id: int,
        company_id: int,
        segment: Dict[str, Any],
    ) -> Tuple[List[ReviewCandidate], Dict[str, int]]:
        """
        Process a single segment to find candidates.

        Args:
            filing_id: The filing ID
            company_id: The company ID
            segment: Segment dict from database

        Returns:
            Tuple of (candidates, segment_stats)
            segment_stats contains counts for numbers_found, numbers_failed,
            false_positives_filtered
        """
        segment_stats = {
            "numbers_found": 0,
            "numbers_failed": 0,
            "false_positives_filtered": 0,
        }

        # Validate segment dict
        if not isinstance(segment, dict):
            raise SegmentProcessingError(
                f"Segment must be a dict, got {type(segment).__name__}"
            )

        text = segment.get("raw_text", "")
        if not text:
            return [], segment_stats

        # Validate text is a string
        if not isinstance(text, str):
            raise SegmentProcessingError(
                f"raw_text must be a string, got {type(text).__name__}",
                segment_id=segment.get("source_segment_id"),
            )

        source_segment_id = segment.get("source_segment_id")
        candidates = []

        # Find all numbers in the segment
        numbers = self._find_numbers(text)
        if not numbers:
            return [], segment_stats

        segment_stats["numbers_found"] = len(numbers)

        # Pre-compute all keyword matches once for efficiency
        # This avoids re-searching the text for every number
        all_keywords = self._find_all_keywords(text)

        # Track (number_position, metric_id) pairs to avoid duplicates
        seen: Set[Tuple[int, str]] = set()

        # For each number, find nearby keywords
        for num in numbers:
            try:
                # Filter out likely false positives
                is_fp, fp_reason = self._is_likely_false_positive(text, num)
                if is_fp:
                    logger.debug(
                        f"Filtered false positive: {num.raw_text!r} ({fp_reason})"
                    )
                    segment_stats["false_positives_filtered"] += 1
                    continue

                keyword_matches = self._find_keywords_near_number(num, all_keywords)

                for kw in keyword_matches:
                    # Deduplicate by (number_position, metric_id)
                    key = (num.start, kw.metric_id)
                    if key in seen:
                        continue
                    seen.add(key)

                    # Calculate distance and position
                    distance = self._calculate_distance(num, kw)
                    keyword_position = "before" if kw.start < num.start else "after"

                    # Extract context
                    context = self._extract_context(text, num.start)

                    # Compute ML features
                    features = self._compute_features(
                        number=num,
                        keyword_distance=distance,
                        keyword_position=keyword_position,
                        context_text=context,
                        segment=segment,
                        all_numbers=numbers,
                    )

                    # Compute confidence score
                    confidence = None
                    if self.compute_confidence:
                        confidence = self._confidence_scorer.compute_confidence(
                            keyword_distance=distance,
                            keyword_position=keyword_position,
                            keyword=kw.keyword,
                            metric_id=kw.metric_id,
                            features=features,
                        )

                    candidate = ReviewCandidate(
                        filing_id=filing_id,
                        company_id=company_id,
                        source_segment_id=source_segment_id,
                        char_position=num.start,
                        context_text=context,
                        raw_number_text=num.raw_text,
                        parsed_value=num.value,
                        parsed_unit=num.unit,
                        triggering_keyword=kw.keyword,
                        keyword_distance=distance,
                        keyword_position=keyword_position,
                        suggested_metric_id=kw.metric_id,
                        suggestion_confidence=confidence,
                        features=features,
                    )
                    candidates.append(candidate)

            except Exception as e:
                segment_stats["numbers_failed"] += 1
                logger.warning(
                    f"Error processing number {num.raw_text!r} at position {num.start}: "
                    f"{type(e).__name__}: {e}"
                )
                # Continue processing other numbers

        return candidates, segment_stats

    def _find_numbers(self, text: str) -> List[NumberMatch]:
        """
        Find all numbers in text.

        Args:
            text: The text to search

        Returns:
            List of NumberMatch objects
        """
        matches = []

        for match in NUMBER_REGEX.finditer(text):
            full_match = match.group(0)
            raw_text = full_match.strip()

            # Skip very short matches (likely false positives)
            if len(raw_text) < 1:
                continue

            # Parse the value
            value, unit = self._parse_number(match)

            # Skip if we couldn't parse a meaningful value
            if value is None:
                continue

            # Calculate actual position after stripping whitespace
            # The match may include leading/trailing whitespace
            leading_ws = len(full_match) - len(full_match.lstrip())
            actual_start = match.start() + leading_ws
            actual_end = actual_start + len(raw_text)

            matches.append(
                NumberMatch(
                    start=actual_start,
                    end=actual_end,
                    raw_text=raw_text,
                    value=value,
                    unit=unit,
                )
            )

        return matches

    def _parse_number(
        self, match: re.Match
    ) -> Tuple[Optional[Decimal], Optional[str]]:
        """
        Parse a number match into value and unit.

        Args:
            match: Regex match object

        Returns:
            Tuple of (parsed_value, unit)
        """
        groups = match.groupdict()
        currency = groups.get("currency")
        number_str = groups.get("number", "")
        suffix = groups.get("suffix", "")

        # Remove commas
        number_str = number_str.replace(",", "")

        try:
            value = Decimal(number_str)
        except (InvalidOperation, ValueError):
            return None, None

        # Apply suffix multiplier
        if suffix:
            suffix_lower = suffix.lower()
            if suffix_lower in ("million", "mn", "m"):
                value *= Decimal("1000000")
            elif suffix_lower in ("billion", "bn", "b"):
                value *= Decimal("1000000000")
            elif suffix_lower in ("thousand", "k"):
                value *= Decimal("1000")

        # Determine unit
        if suffix and suffix.lower() in ("%", "percent"):
            unit = "%"
        elif currency:
            unit = "usd"
        else:
            unit = "count"

        return value, unit

    def _is_likely_false_positive(
        self, text: str, number: NumberMatch
    ) -> Tuple[bool, Optional[str]]:
        """
        Check if a number match is likely a false positive.

        Filters out:
        - Numbers that are part of dates (12/31/2023)
        - Numbers that look like years (1990-2100)
        - Page/note/section/exhibit references
        - Version numbers
        - Numbers below minimum threshold

        Args:
            text: The full text containing the number
            number: The NumberMatch to check

        Returns:
            Tuple of (is_false_positive, reason)
            reason is None if not a false positive
        """
        if not self.filter_false_positives:
            return False, None

        value = number.value
        start = number.start
        end = number.end

        # Check minimum value threshold (skip for percentages, currency, and decimals)
        # Decimals like 1.25 could be ratios (e.g., NRR of 125%)
        if number.unit == "count" and value is not None:
            is_decimal = "." in number.raw_text
            if not is_decimal and abs(float(value)) < self.min_value:
                return True, "below_min_value"

        # Check if number looks like a year (only for plain integers)
        if self.filter_years and number.unit == "count":
            if value is not None and YEAR_MIN <= float(value) <= YEAR_MAX:
                # Additional check: is it a 4-digit integer without decimal?
                if "." not in number.raw_text and len(number.raw_text.replace(",", "")) == 4:
                    return True, "likely_year"

        # Check if number is part of a date pattern
        # Look at surrounding context (30 chars each side)
        context_start = max(0, start - 30)
        context_end = min(len(text), end + 30)
        local_context = text[context_start:context_end]

        # Calculate the number's position relative to the local context
        num_rel_start = start - context_start
        num_rel_end = end - context_start

        for pattern in DATE_CONTEXT_PATTERNS:
            match = pattern.search(local_context)
            if match:
                # Check if our number overlaps with the date match (in local coords)
                if num_rel_start >= match.start() and num_rel_end <= match.end():
                    return True, "part_of_date"

        # Check for false positive context patterns (page refs, notes, etc.)
        for pattern in FALSE_POSITIVE_CONTEXT_PATTERNS:
            match = pattern.search(local_context)
            if match:
                # Check if our number overlaps with the reference pattern
                if num_rel_start >= match.start() and num_rel_end <= match.end():
                    return True, "reference_number"

        return False, None

    def _find_all_keywords(self, text: str) -> List[KeywordMatch]:
        """
        Find all metric keywords in text (pre-computation for efficiency).

        This method searches the text once for all patterns, avoiding
        redundant searches when checking multiple numbers.

        Args:
            text: The full text to search

        Returns:
            List of all KeywordMatch objects found, sorted by position
        """
        all_matches = []

        for metric_id, patterns in self._compiled_patterns.items():
            for pattern in patterns:
                for match in pattern.finditer(text):
                    all_matches.append(
                        KeywordMatch(
                            start=match.start(),
                            end=match.end(),
                            keyword=match.group(),
                            metric_id=metric_id,
                            pattern=pattern.pattern,
                        )
                    )

        # Sort by position for potential early-exit optimizations
        all_matches.sort(key=lambda m: m.start)
        return all_matches

    def _find_keywords_near_number(
        self,
        number: NumberMatch,
        all_keywords: List[KeywordMatch],
    ) -> List[KeywordMatch]:
        """
        Find metric keywords within max_keyword_distance of a number.

        Uses pre-computed keyword matches for efficiency.

        Args:
            number: The NumberMatch to search around
            all_keywords: Pre-computed list of all keyword matches in text

        Returns:
            List of KeywordMatch objects within range (one per metric)
        """
        matches = []
        seen_metrics: Set[str] = set()

        for kw in all_keywords:
            # Skip if we already have a match for this metric
            if kw.metric_id in seen_metrics:
                continue

            # Calculate distance
            dist = self._calculate_distance_from_positions(
                number.start, number.end, kw.start, kw.end
            )

            if dist <= self.max_keyword_distance:
                matches.append(kw)
                seen_metrics.add(kw.metric_id)

        return matches

    def _calculate_distance(self, number: NumberMatch, keyword: KeywordMatch) -> int:
        """
        Calculate character distance between number and keyword.

        Args:
            number: NumberMatch
            keyword: KeywordMatch

        Returns:
            Minimum distance in characters
        """
        return self._calculate_distance_from_positions(
            number.start, number.end, keyword.start, keyword.end
        )

    def _calculate_distance_from_positions(
        self, n_start: int, n_end: int, k_start: int, k_end: int
    ) -> int:
        """
        Calculate distance between two spans.

        If spans overlap, distance is 0.
        Otherwise, distance is the gap between them.
        """
        if n_end <= k_start:
            # Number is before keyword
            return k_start - n_end
        elif k_end <= n_start:
            # Keyword is before number
            return n_start - k_end
        else:
            # Overlapping
            return 0

    def _extract_context(self, text: str, position: int) -> str:
        """
        Extract context words around a position.

        Args:
            text: The full text
            position: Character position to center on

        Returns:
            Context string with ~context_words words each direction
        """
        # Split into words with positions
        words = []
        for match in re.finditer(r"\S+", text):
            words.append((match.start(), match.end(), match.group()))

        if not words:
            return text[:500] if len(text) > 500 else text

        # Find the word containing or nearest to position
        center_idx = 0
        min_dist = float("inf")
        for i, (start, end, _) in enumerate(words):
            if start <= position < end:
                center_idx = i
                break
            dist = min(abs(start - position), abs(end - position))
            if dist < min_dist:
                min_dist = dist
                center_idx = i

        # Extract words around center
        start_idx = max(0, center_idx - self.context_words)
        end_idx = min(len(words), center_idx + self.context_words + 1)

        # Get text span
        context_start = words[start_idx][0]
        context_end = words[end_idx - 1][1]

        return text[context_start:context_end]

    def _compute_features(
        self,
        number: NumberMatch,
        keyword_distance: int,
        keyword_position: str,
        context_text: str,
        segment: Dict[str, Any],
        all_numbers: List[NumberMatch],
    ) -> CandidateFeatures:
        """
        Compute ML features for a candidate.

        Delegates to FeatureExtractor for feature computation.

        Args:
            number: The NumberMatch for this candidate
            keyword_distance: Distance to triggering keyword
            keyword_position: 'before' or 'after'
            context_text: Extracted context around number
            segment: Segment dict with metadata
            all_numbers: All numbers found in the segment

        Returns:
            CandidateFeatures instance
        """
        # Defensive: ensure segment is a dict
        if not isinstance(segment, dict):
            segment = {}

        # Defensive: ensure all_numbers is a list
        if not isinstance(all_numbers, list):
            all_numbers = []

        # Delegate to feature extractor
        return self._feature_extractor.compute_features(
            number_value=number.value,
            number_unit=number.unit,
            number_raw_text=number.raw_text,
            keyword_distance=keyword_distance,
            keyword_position=keyword_position,
            context_text=context_text,
            segment_type=segment.get("segment_type"),
            section_heading=segment.get("section_heading"),
            section_path=segment.get("section_path"),
            surrounding_numbers_count=max(0, len(all_numbers) - 1),
        )


# =============================================================================
# Convenience Functions
# =============================================================================


def generate_candidates_for_filing(
    db,
    filing_id: int,
    generator: Optional[CandidateGenerator] = None,
    save: bool = False,
    batch_id: Optional[int] = None,
) -> List[ReviewCandidate]:
    """
    Generate and optionally save candidates for a filing.

    Args:
        db: DatabaseAdapter instance
        filing_id: Filing ID to process
        generator: Optional CandidateGenerator instance (creates default if None)
        save: If True, bulk insert candidates to database
        batch_id: Optional batch ID to assign to saved candidates

    Returns:
        List of generated ReviewCandidate objects (with candidate_id set if saved)

    Raises:
        ValueError: If filing not found
    """
    # Get filing info
    filing = db.get_filing_with_company(filing_id)
    if not filing:
        raise ValueError(f"Filing not found: {filing_id}")

    company_id = filing["company_id"]

    # Get segments
    segments = db.get_source_segments_for_filing(filing_id)
    if not segments:
        logger.warning(f"No segments found for filing {filing_id}")
        return []

    # Generate candidates
    if generator is None:
        generator = CandidateGenerator()

    candidates = generator.generate_for_filing(
        filing_id=filing_id,
        company_id=company_id,
        segments=segments,
    )

    # Optionally save to database
    if save and candidates:
        # Convert to dicts for bulk insert
        candidate_dicts = []
        for c in candidates:
            d = c.to_dict()
            if batch_id is not None:
                d["review_batch_id"] = batch_id
            candidate_dicts.append(d)

        # Bulk insert and get IDs
        candidate_ids = db.bulk_insert_review_candidates(candidate_dicts)

        # Update candidate objects with their IDs
        for candidate, cid in zip(candidates, candidate_ids):
            candidate.candidate_id = cid

        logger.info(
            f"Saved {len(candidate_ids)} candidates for filing {filing_id}"
        )

    return candidates
