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
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Set, Tuple

from src.extraction.metric_classifier import MetricClassifier
from src.review.confidence_scoring import ConfidenceScorer, METRIC_EXPECTED_FORMATS
from src.review.context_extraction import ContextExtractor, DEFAULT_CONTEXT_WORDS
from src.review.exceptions import (
    CandidateGenerationError,
    NumberProcessingError,
    SegmentProcessingError,
)
from src.review.false_positive_filter import (
    DATE_CONTEXT_PATTERNS,
    FALSE_POSITIVE_CONTEXT_PATTERNS,
    FalsePositiveFilter,
    MIN_METRIC_VALUE,
    YEAR_MIN,
    YEAR_MAX,
)
from src.review.feature_extractor import (
    DEFINITION_PATTERNS,
    PERIOD_PATTERNS,
    RISK_FACTORS_PATTERNS,
    FeatureExtractor,
)
from src.review.keyword_matching import (
    METRIC_KEYWORDS,
    SPECIFIC_KEYWORD_PATTERNS,
    KeywordMatch,
    KeywordMatcher,
)
from src.review.models import CandidateFeatures, ProcessingStats, ReviewCandidate
from src.review.number_parsing import NUMBER_REGEX, NumberMatch, NumberParser

logger = logging.getLogger(__name__)


# =============================================================================
# Number Detection Patterns
# =============================================================================

# Number parsing functionality moved to src/review/number_parsing.py (P1.3)
# NUMBER_REGEX and NumberMatch are now imported from that module


# =============================================================================
# Metric Keywords (imported from keyword_matching.py)
# =============================================================================

# METRIC_KEYWORDS and SPECIFIC_KEYWORD_PATTERNS moved to
# src/review/keyword_matching.py (P1.3)
# They are imported from that module to maintain single source of truth


# =============================================================================
# Feature Detection Patterns (imported from feature_extractor)
# =============================================================================
# DEFINITION_PATTERNS, PERIOD_PATTERNS, and RISK_FACTORS_PATTERNS are now
# imported from src.review.feature_extractor to maintain single source of truth.


# =============================================================================
# False Positive Detection (imported from false_positive_filter.py)
# =============================================================================

# DATE_CONTEXT_PATTERNS, FALSE_POSITIVE_CONTEXT_PATTERNS, YEAR_MIN,
# YEAR_MAX, and MIN_METRIC_VALUE moved to src/review/false_positive_filter.py (P1.3)
# They are imported from that module to maintain single source of truth


# =============================================================================
# Configuration
# =============================================================================

# METRIC_EXPECTED_FORMATS moved to src/review/confidence_scoring.py
# ConfidenceScorer moved to src/review/confidence_scoring.py
# SPECIFIC_KEYWORD_PATTERNS moved to src/review/keyword_matching.py (P1.3)
# NumberMatch dataclass moved to src/review/number_parsing.py (P1.3)
# KeywordMatch dataclass moved to src/review/keyword_matching.py (P1.3)


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

    # Context extraction settings (imported from context_extraction.py)
    CONTEXT_WORDS = DEFAULT_CONTEXT_WORDS  # Words to extract each direction

    def __init__(
        self,
        max_keyword_distance: int = 100,
        context_words: int = 40,
        filter_false_positives: bool = True,
        min_value: Optional[int] = None,
        filter_years: bool = True,
        compute_confidence: bool = True,
        apply_learned_rules: bool = True,
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
            apply_learned_rules: Apply learned patterns from E1 to filter candidates (default True)
        """
        self.max_keyword_distance = max_keyword_distance
        self.context_words = context_words
        self.filter_false_positives = filter_false_positives
        self.min_value = min_value if min_value is not None else MIN_METRIC_VALUE
        self.filter_years = filter_years
        self.compute_confidence = compute_confidence
        self.apply_learned_rules = apply_learned_rules

        # Initialize confidence scorer
        self._confidence_scorer = ConfidenceScorer(
            max_keyword_distance=max_keyword_distance
        )

        # Initialize feature extractor
        self._feature_extractor = FeatureExtractor()

        # Initialize number parser (P1.3 - extracted to separate module)
        self._number_parser = NumberParser()

        # Initialize keyword matcher (P1.3 - extracted to separate module)
        self._keyword_matcher = KeywordMatcher(max_keyword_distance=max_keyword_distance)

        # Initialize false positive filter (P1.3 - extracted to separate module)
        self._false_positive_filter = FalsePositiveFilter(
            filter_enabled=filter_false_positives,
            min_value=self.min_value,
            filter_years=filter_years,
        )

        # Initialize context extractor (P1.3 - extracted to separate module)
        self._context_extractor = ContextExtractor(context_words=context_words)

        # Cache for word positions during segment processing (optimization for P1.2)
        # This avoids re-parsing text into words for every number in a segment
        self._current_segment_words: Optional[List[Tuple[int, int, str]]] = None

        # Lazy-loaded RuleApplicator (E2 integration)
        self._rule_applicator = None

    def _get_rule_applicator(self, db):
        """
        Lazy-load RuleApplicator for E2 learned pattern filtering.

        Args:
            db: DatabaseAdapter instance (needed for pattern loading)

        Returns:
            RuleApplicator instance

        Note:
            Only loads RuleApplicator if apply_learned_rules=True.
            Caches the instance for reuse across segments.
        """
        if self._rule_applicator is None and self.apply_learned_rules:
            from src.review.rule_applicator import RuleApplicator

            self._rule_applicator = RuleApplicator(db)
        return self._rule_applicator

    def generate_for_filing(
        self,
        filing_id: int,
        company_id: int,
        segments: List[Dict[str, Any]],
        return_stats: bool = False,
        db=None,
    ) -> List[ReviewCandidate] | Tuple[List[ReviewCandidate], ProcessingStats]:
        """
        Generate candidates from all segments of a filing.

        Args:
            filing_id: The filing ID
            company_id: The company ID
            segments: List of segment dicts from database
            return_stats: If True, return (candidates, stats) tuple
            db: Optional DatabaseAdapter for learned rules filtering (E2)

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
                    db=db,
                )
                candidates.extend(segment_candidates)
                stats.segments_processed += 1
                stats.numbers_found += segment_stats.get("numbers_found", 0)
                stats.numbers_failed += segment_stats.get("numbers_failed", 0)
                stats.false_positives_filtered += segment_stats.get(
                    "false_positives_filtered", 0
                )
                stats.filtered_by_learned_rules += segment_stats.get(
                    "filtered_by_learned_rules", 0
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
        db=None,
    ) -> Tuple[List[ReviewCandidate], Dict[str, int]]:
        """
        Process a single segment to find candidates.

        Args:
            filing_id: The filing ID
            company_id: The company ID
            segment: Segment dict from database
            db: Optional DatabaseAdapter for learned rules filtering (E2)

        Returns:
            Tuple of (candidates, segment_stats)
            segment_stats contains counts for numbers_found, numbers_failed,
            false_positives_filtered, filtered_by_learned_rules
        """
        segment_stats = {
            "numbers_found": 0,
            "numbers_failed": 0,
            "false_positives_filtered": 0,
            "filtered_by_learned_rules": 0,
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

        # Pre-compute all keyword matches once for efficiency (P1.1 optimization)
        # This avoids re-searching the text for every number
        all_keywords = self._find_all_keywords(text)

        # Pre-compute word positions once for efficiency (P1.2 optimization)
        # This avoids re-parsing text for context extraction for every number
        self._current_segment_words = self._context_extractor.parse_text_into_words(text)

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

        # Clear cached word positions (P1.2 optimization cleanup)
        self._current_segment_words = None

        # E2: Apply learned pattern filtering if enabled
        if self.apply_learned_rules and db is not None:
            applicator = self._get_rule_applicator(db)
            if applicator is not None:
                filtered_candidates = []
                for candidate in candidates:
                    should_filter, reason = applicator.should_filter(
                        candidate, candidate.features
                    )
                    if should_filter:
                        segment_stats["filtered_by_learned_rules"] += 1
                        logger.debug(
                            f"Filtered candidate by learned rule: {reason} "
                            f"(value={candidate.parsed_value}, metric={candidate.suggested_metric_id})"
                        )
                    else:
                        filtered_candidates.append(candidate)
                candidates = filtered_candidates

        return candidates, segment_stats

    def _find_numbers(self, text: str) -> List[NumberMatch]:
        """
        Find all numbers in text.

        Delegates to NumberParser (P1.3 - extracted to separate module).

        Args:
            text: The text to search

        Returns:
            List of NumberMatch objects
        """
        return self._number_parser.find_numbers(text)

    # _parse_number method removed - now part of NumberParser (P1.3)

    def _is_likely_false_positive(
        self, text: str, number: NumberMatch
    ) -> Tuple[bool, Optional[str]]:
        """
        Check if a number match is likely a false positive.

        Delegates to FalsePositiveFilter (P1.3 - extracted to separate module).

        Args:
            text: The full text containing the number
            number: The NumberMatch to check

        Returns:
            Tuple of (is_false_positive, reason)
            reason is None if not a false positive
        """
        return self._false_positive_filter.is_false_positive(text, number)

    def _find_all_keywords(self, text: str) -> List[KeywordMatch]:
        """
        Find all metric keywords in text.

        Delegates to KeywordMatcher (P1.3 - extracted to separate module).

        Args:
            text: The full text to search

        Returns:
            List of all KeywordMatch objects found, sorted by position
        """
        return self._keyword_matcher.find_all_keywords(text)

    def _find_keywords_near_number(
        self,
        number: NumberMatch,
        all_keywords: List[KeywordMatch],
    ) -> List[KeywordMatch]:
        """
        Find metric keywords within max_keyword_distance of a number.

        Delegates to KeywordMatcher (P1.3 - extracted to separate module).

        Args:
            number: The NumberMatch to search around
            all_keywords: Pre-computed list of all keyword matches in text

        Returns:
            List of KeywordMatch objects within range (one per metric)
        """
        return self._keyword_matcher.find_keywords_near_number(number, all_keywords)

    def _calculate_distance(self, number: NumberMatch, keyword: KeywordMatch) -> int:
        """
        Calculate character distance between number and keyword.

        Delegates to KeywordMatcher (P1.3 - extracted to separate module).

        Args:
            number: NumberMatch
            keyword: KeywordMatch

        Returns:
            Minimum distance in characters
        """
        return self._keyword_matcher.calculate_distance(number, keyword)

    def _extract_context(self, text: str, position: int) -> str:
        """
        Extract context words around a position.

        Delegates to ContextExtractor (P1.3 - extracted to separate module).
        Uses cached word positions if available (optimization P1.2).

        Args:
            text: The full text
            position: Character position to center on

        Returns:
            Context string with ~context_words words each direction
        """
        return self._context_extractor.extract_context(
            text, position, cached_words=self._current_segment_words
        )

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

# generate_candidates_for_filing() moved to src/review/helpers.py
