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

Basic Usage:
    >>> from src.review import CandidateGenerator
    >>> from src.infra.db import DatabaseAdapter
    >>>
    >>> # Initialize with default config
    >>> db = DatabaseAdapter("postgresql://user:pass@localhost/filings_analysis")
    >>> generator = CandidateGenerator()
    >>>
    >>> # Fetch segments for a filing
    >>> segments = db.get_source_segments_for_filing(filing_id=123)
    >>>
    >>> # Generate candidates
    >>> candidates = generator.generate_for_filing(
    ...     filing_id=123,
    ...     company_id=456,
    ...     segments=segments,
    ... )
    >>>
    >>> # Save to database
    >>> db.bulk_insert_review_candidates([c.to_dict() for c in candidates])
    >>> print(f"Generated {len(candidates)} candidates")

Using Configuration Presets:
    >>> from src.review.config import (
    ...     get_high_precision_config,
    ...     get_high_recall_config,
    ...     get_fast_config,
    ... )
    >>>
    >>> # High precision: Fewer false positives, stricter matching
    >>> hp_generator = CandidateGenerator(config=get_high_precision_config())
    >>> hp_candidates = hp_generator.generate_for_filing(
    ...     filing_id=123, company_id=456, segments=segments
    ... )
    >>>
    >>> # High recall: Maximum coverage, more false positives
    >>> hr_generator = CandidateGenerator(config=get_high_recall_config())
    >>> hr_candidates = hr_generator.generate_for_filing(
    ...     filing_id=123, company_id=456, segments=segments
    ... )
    >>>
    >>> # Fast: Optimized for speed, no confidence scoring
    >>> fast_generator = CandidateGenerator(config=get_fast_config())
    >>> fast_candidates = fast_generator.generate_for_filing(
    ...     filing_id=123, company_id=456, segments=segments
    ... )

Custom Configuration:
    >>> from src.review.config import CandidateGenerationConfig
    >>>
    >>> # Create custom config for your use case
    >>> custom_config = CandidateGenerationConfig(
    ...     max_keyword_distance=75,        # Moderate proximity
    ...     min_metric_value=50,            # Filter small numbers
    ...     filter_false_positives=True,    # Enable filtering
    ...     compute_confidence=True,        # Enable confidence scoring
    ...     apply_learned_rules=True,       # Apply E2 patterns
    ...     min_pattern_precision=0.80,     # High-confidence patterns only
    ... )
    >>> custom_generator = CandidateGenerator(config=custom_config)
    >>> candidates = custom_generator.generate_for_filing(
    ...     filing_id=123, company_id=456, segments=segments
    ... )

Getting Statistics:
    >>> # Request processing statistics
    >>> candidates, stats = generator.generate_for_filing(
    ...     filing_id=123,
    ...     company_id=456,
    ...     segments=segments,
    ...     return_stats=True,
    ... )
    >>> print(f"Segments processed: {stats.segments_processed}")
    >>> print(f"Numbers found: {stats.numbers_found}")
    >>> print(f"False positives filtered: {stats.false_positives_filtered}")
    >>> print(f"Candidates generated: {stats.candidates_generated}")
    >>> print(f"Success rate: {stats.segment_success_rate:.1%}")

Convenience Wrapper (Recommended for simple workflows):
    >>> from src.review.helpers import generate_candidates_for_filing
    >>>
    >>> # One-liner that fetches segments and generates candidates
    >>> candidates = generate_candidates_for_filing(
    ...     db=db,
    ...     filing_id=123,
    ...     company_id=456,
    ... )

Backward Compatibility (Old API still works):
    >>> # Old style: individual parameters
    >>> generator = CandidateGenerator(
    ...     max_keyword_distance=50,
    ...     filter_false_positives=True,
    ...     min_value=100,  # Old parameter name
    ... )
    >>>
    >>> # New style: config object (recommended)
    >>> from src.review.config import CandidateGenerationConfig
    >>> config = CandidateGenerationConfig(
    ...     max_keyword_distance=50,
    ...     filter_false_positives=True,
    ...     min_metric_value=100,  # New parameter name
    ... )
    >>> generator = CandidateGenerator(config=config)

See Also:
    - config.py: Configuration presets and CandidateGenerationConfig
    - helpers.py: Convenience wrappers for common workflows
    - models.py: ReviewCandidate and ProcessingStats data structures
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.review.marker_row_parser import MarkerRowParser
    from src.review.table_structure import TableRowParser

from src.review.confidence_scoring import ConfidenceScorer
from src.review.config import (
    DEFAULT_CONFIG,
    DEFAULT_CONTEXT_WORDS,
    MAX_KEYWORD_DISTANCE,
    CandidateGenerationConfig,
)
from src.review.context_extraction import ContextExtractor
from src.review.deduplicator import deduplicate_candidates
from src.review.exceptions import (
    NumberProcessingError,
    SegmentProcessingError,
)
from src.review.false_positive_filter import (
    COUNT_ONLY_METRICS,
    DOLLAR_ONLY_METRICS,
    PERCENTAGE_ONLY_METRICS,
    FalsePositiveFilter,
    is_count_format,
    is_dollar_format,
    is_percentage_format,
    should_treat_as_percentage,
)
from src.review.feature_extractor import (
    FeatureExtractor,
)
from src.review.keyword_matching import (
    KeywordMatch,
    KeywordMatcher,
)
from src.review.models import (
    CandidateFeatures,
    ProcessingStats,
    ReviewCandidate,
    SegmentDict,
)
from src.review.number_parsing import NumberMatch, NumberParser

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
    # (imported from config.py for centralized configuration)
    MAX_KEYWORD_DISTANCE = MAX_KEYWORD_DISTANCE

    # Context extraction settings (imported from config.py)
    CONTEXT_WORDS = DEFAULT_CONTEXT_WORDS  # Words to extract each direction

    def __init__(
        self,
        config: CandidateGenerationConfig | None = None,
        # Deprecated parameters (for backward compatibility)
        max_keyword_distance: int | None = None,
        context_words: int | None = None,
        filter_false_positives: bool | None = None,
        min_value: int | None = None,
        filter_years: bool | None = None,
        compute_confidence: bool | None = None,
        apply_learned_rules: bool | None = None,
    ):
        """
        Initialize the candidate generator.

        Args:
            config: Configuration object. If None, uses DEFAULT_CONFIG or builds from deprecated params.

            # Deprecated parameters (use config instead):
            max_keyword_distance: DEPRECATED - Use config.max_keyword_distance
            context_words: DEPRECATED - Use config.context_words
            filter_false_positives: DEPRECATED - Use config.filter_false_positives
            min_value: DEPRECATED - Use config.min_metric_value
            filter_years: DEPRECATED - Use config.filter_years
            compute_confidence: DEPRECATED - Use config.compute_confidence
            apply_learned_rules: DEPRECATED - Use config.apply_learned_rules
        """
        # Handle config parameter vs deprecated individual parameters
        if config is not None:
            # Use provided config
            self.config = config
        elif any(
            param is not None
            for param in [
                max_keyword_distance,
                context_words,
                filter_false_positives,
                min_value,
                filter_years,
                compute_confidence,
                apply_learned_rules,
            ]
        ):
            # Build config from deprecated parameters (backward compatibility)
            self.config = CandidateGenerationConfig(
                max_keyword_distance=max_keyword_distance
                if max_keyword_distance is not None
                else DEFAULT_CONFIG.max_keyword_distance,
                context_words=context_words
                if context_words is not None
                else DEFAULT_CONFIG.context_words,
                filter_false_positives=filter_false_positives
                if filter_false_positives is not None
                else DEFAULT_CONFIG.filter_false_positives,
                min_metric_value=min_value
                if min_value is not None
                else DEFAULT_CONFIG.min_metric_value,
                filter_years=filter_years
                if filter_years is not None
                else DEFAULT_CONFIG.filter_years,
                compute_confidence=compute_confidence
                if compute_confidence is not None
                else DEFAULT_CONFIG.compute_confidence,
                apply_learned_rules=apply_learned_rules
                if apply_learned_rules is not None
                else DEFAULT_CONFIG.apply_learned_rules,
            )
        else:
            # Use default config
            self.config = DEFAULT_CONFIG

        # Set convenience attributes for backward compatibility
        self.max_keyword_distance = self.config.max_keyword_distance
        self.context_words = self.config.context_words
        self.filter_false_positives = self.config.filter_false_positives
        self.min_value = self.config.min_metric_value
        self.filter_years = self.config.filter_years
        self.compute_confidence = self.config.compute_confidence
        self.apply_learned_rules = self.config.apply_learned_rules

        # Initialize confidence scorer with config
        self._confidence_scorer = ConfidenceScorer(
            max_keyword_distance=self.config.max_keyword_distance,
            config=self.config,
        )

        # Initialize feature extractor
        self._feature_extractor = FeatureExtractor()

        # Initialize number parser (P1.3 - extracted to separate module)
        self._number_parser = NumberParser()

        # Initialize keyword matcher (P1.3 - extracted to separate module, P1 enhanced, P1.5 sentence-aware, L4 multiplier)
        self._keyword_matcher = KeywordMatcher(
            max_keyword_distance=self.config.max_keyword_distance,
            prefer_closest_keyword=self.config.prefer_closest_keyword,
            respect_bullet_boundaries=self.config.respect_bullet_boundaries,
            respect_sentence_boundaries=self.config.respect_sentence_boundaries,
            log_ambiguous_matches=self.config.log_ambiguous_matches,
            ambiguity_threshold=self.config.ambiguity_threshold,
            post_value_distance_multiplier=self.config.post_value_distance_multiplier,
        )

        # Initialize false positive filter (P1.3 - extracted to separate module)
        self._false_positive_filter = FalsePositiveFilter(
            filter_enabled=self.config.filter_false_positives,
            min_value=self.config.min_metric_value,
            filter_years=self.config.filter_years,
            toc_proximity_chars=self.config.toc_proximity_chars,
            toc_dot_leader_window=self.config.toc_dot_leader_window,
            filter_financial_statements=self.config.filter_financial_statements,  # HRV-10/11
            financial_statement_proximity_chars=self.config.financial_statement_proximity_chars,
        )

        # Initialize context extractor (P1.3 - extracted to separate module)
        self._context_extractor = ContextExtractor(context_words=self.config.context_words)

        # Cache for word positions during segment processing (optimization for P1.2)
        # This avoids re-parsing text into words for every number in a segment
        self._current_segment_words: list[tuple[int, int, str]] | None = None

        # Lazy-loaded RuleApplicator (E2 integration)
        self._rule_applicator: Any | None = None

    def _get_rule_applicator(self, db: Any) -> Any | None:
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
        segments: list[SegmentDict],
        return_stats: bool = False,
        db: Any | None = None,
    ) -> list[ReviewCandidate] | tuple[list[ReviewCandidate], ProcessingStats]:
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
            except SegmentProcessingError as e:
                # Known segment-level error (validation failures, etc.)
                stats.segments_failed += 1
                logger.error(
                    f"Segment processing error for segment {segment_id} in filing {filing_id}: {e}"
                )
                # Continue processing other segments
            except (ValueError, TypeError, AttributeError) as e:
                # Unexpected but recoverable error in segment processing
                stats.segments_failed += 1
                logger.error(
                    f"Unexpected error processing segment {segment_id} in filing {filing_id}: "
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
        self, candidates: list[ReviewCandidate]
    ) -> tuple[list[ReviewCandidate], int]:
        """
        Remove duplicate candidates based on (parsed_value, suggested_metric_id, detected_period).

        Delegates to the standalone deduplicate_candidates function for reusability.
        P1.6: Passes prefer_same_sentence config setting for same-sentence preference.

        Args:
            candidates: List of candidates to deduplicate

        Returns:
            Tuple of (deduplicated_candidates, duplicates_removed_count)
        """
        return deduplicate_candidates(
            candidates,
            prefer_same_sentence=self.config.prefer_same_sentence_in_dedup,
        )

    def _process_segment(
        self,
        filing_id: int,
        company_id: int,
        segment: SegmentDict,
        db: Any | None = None,
    ) -> tuple[list[ReviewCandidate], dict[str, int]]:
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

        # Skip definition segments - they explain metrics but don't contain values (EI-1)
        if segment.get("contains_definition_flag"):
            logger.debug(
                f"Skipping definition segment {source_segment_id}: "
                "contains_definition_flag is True"
            )
            return [], segment_stats

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

        # Pre-compute semantic boundaries once for efficiency (P1 enhancement)
        # This enables boundary-aware keyword matching to avoid cross-boundary false positives
        from src.review.boundary_detection import BoundaryDetector

        boundaries = None
        detector: BoundaryDetector | None = None
        if self.config.enable_boundary_detection:
            detector = BoundaryDetector()
            boundaries = detector.find_boundaries(text)
            logger.debug(f"Detected {len(boundaries)} semantic boundaries in segment")

        # Pre-compute sentence boundaries for P1.5 sentence-aware filtering
        # This enables sentence-aware keyword matching to avoid cross-sentence false positives
        sentence_boundaries = None
        if self.config.detect_sentences:
            if detector is None:  # Reuse detector if already created
                detector = BoundaryDetector()
            segment_type = segment.get("segment_type")
            # Disable sentence detection for tables (configurable)
            if segment_type == "table" and not self.config.sentence_detection_for_tables:
                # Table segments get single boundary to prevent false negatives
                pass  # sentence_boundaries stays None, fallback to no sentence filtering
            else:
                sentence_boundaries = detector.find_sentence_boundaries(text, segment_type)
                if sentence_boundaries:
                    logger.debug(
                        f"Detected {len(sentence_boundaries)} sentences in segment"
                    )

        # Pre-compute table row structure for table row filtering
        # This prevents keywords in one row from matching with numbers in another row
        table_row_parser: MarkerRowParser | TableRowParser | None = None
        raw_html = segment.get("raw_html", "")

        # Check for markers first (more reliable when present)
        if " [ROW] " in text or " [CELL] " in text:
            from src.review.marker_row_parser import MarkerRowParser
            table_row_parser = MarkerRowParser(text)
        elif raw_html and ('<table' in raw_html.lower()):
            from src.review.table_structure import TableRowParser
            table_row_parser = TableRowParser(raw_html, text)

        if table_row_parser is not None and table_row_parser.is_table():
            logger.debug(
                f"Parsed {len(table_row_parser.get_rows())} table rows for row-aware matching"
            )

        # Track (number_position, metric_id) pairs to avoid duplicates
        seen: set[tuple[int, str]] = set()

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

                keyword_matches = self._find_keywords_near_number(
                    num, all_keywords, boundaries, sentence_boundaries, segment, table_row_parser
                )

                # Phase 7: If no nearby keywords found, check context_prefix
                # Context prefix contains the last sentence from the previous segment,
                # which may provide relevant keyword context for list items, etc.
                context_prefix_raw = segment.get("context_prefix", "")
                context_prefix = str(context_prefix_raw) if context_prefix_raw else ""
                from_context_prefix = False
                if not keyword_matches and context_prefix:
                    # Search context_prefix for keywords
                    context_keywords = self._find_all_keywords(context_prefix)
                    if context_keywords:
                        # Use context keywords (they won't have "nearby" relationship to number)
                        # Take first keyword per metric for simplicity
                        seen_metrics: set[str] = set()
                        for ck in context_keywords:
                            if ck.metric_id not in seen_metrics:
                                keyword_matches.append(ck)
                                seen_metrics.add(ck.metric_id)
                        from_context_prefix = True
                        logger.debug(
                            f"Found {len(keyword_matches)} keywords in context_prefix "
                            f"for number {num.raw_text!r}"
                        )

                for kw in keyword_matches:
                    # Deduplicate by (number_position, metric_id)
                    key = (num.start, kw.metric_id)
                    if key in seen:
                        continue
                    seen.add(key)

                    # Early exclusion check around NUMBER position
                    # This catches FPs where number is near exclusion context
                    # (e.g., contribution margin values matched to take rate)
                    should_exclude, reason = self._keyword_matcher.should_exclude_for_number_context(
                        metric_id=kw.metric_id,
                        text=text,
                        number_position=num.start,
                    )
                    if should_exclude:
                        segment_stats["excluded_by_number_context"] = (
                            segment_stats.get("excluded_by_number_context", 0) + 1
                        )
                        logger.debug(f"Excluded candidate: {reason}")
                        continue

                    # Calculate distance and position
                    # For context_prefix matches, use a special "large" distance
                    if from_context_prefix:
                        distance = 500  # Indicates "from context, not nearby"
                        keyword_position = "before"  # Context is from previous segment
                    else:
                        distance = self._calculate_distance(num, kw)
                        # L3: Use direction from KeywordMatch (handle "at" edge case by mapping to "before")
                        # Rationale: When keyword and number are at same position, treat as "before" (no penalty)
                        # since there's no temporal "after" relationship in reading order
                        keyword_position = "after" if kw.direction == "after" else "before"

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

                    # L4/E1: Compute context type for multiplier optimization
                    context_type = self._keyword_matcher.get_context_type(
                        text=text,
                        number_position=num.start,
                        keyword_position=kw.start,
                        keyword_direction=kw.direction if kw.direction else keyword_position,
                        boundaries=boundaries,
                        segment_type=segment.get("segment_type"),
                    )
                    features.context_type = context_type

                    # P1.6: Track if keyword and number are in the same sentence
                    if sentence_boundaries and not from_context_prefix:
                        number_sentence = self._keyword_matcher._get_boundary_at_position(
                            num.start, sentence_boundaries
                        )
                        keyword_sentence = self._keyword_matcher._get_boundary_at_position(
                            kw.start, sentence_boundaries
                        )
                        features.is_same_sentence = (
                            number_sentence is not None
                            and keyword_sentence is not None
                            and number_sentence == keyword_sentence
                        )
                    elif from_context_prefix:
                        # Context prefix matches are never "same sentence" (different segments)
                        features.is_same_sentence = False
                    else:
                        # Without sentence detection, assume same sentence (conservative)
                        features.is_same_sentence = True

                    # Phase 7: Track if keyword came from context_prefix
                    features.from_context_prefix = from_context_prefix

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

                        # Phase 7: Apply 0.8x confidence penalty for context_prefix matches
                        # These matches are less certain since keyword is in a different segment
                        if from_context_prefix and confidence is not None:
                            confidence = confidence * 0.8
                            logger.debug(
                                f"Applied 0.8x confidence penalty for context_prefix match: "
                                f"{confidence:.3f}"
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

            except NumberProcessingError as e:
                # Known number-level error (already defined but not yet raised internally)
                segment_stats["numbers_failed"] += 1
                logger.warning(
                    f"Number processing error for {num.raw_text!r} at position {num.start}: {e}"
                )
                # Continue processing other numbers
            except (ValueError, TypeError, AttributeError, KeyError) as e:
                # Unexpected but recoverable error in number processing
                segment_stats["numbers_failed"] += 1
                logger.warning(
                    f"Unexpected error processing number {num.raw_text!r} at position {num.start}: "
                    f"{type(e).__name__}: {e}"
                )
                # Continue processing other numbers

        # Clear cached word positions (P1.2 optimization cleanup)
        self._current_segment_words = None

        # L1: Enrich with respectively patterns (before learned rules filtering)
        candidates = self._enrich_with_respectively_patterns(
            candidates=candidates,
            segment_text=text,
        )

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

        # HRV Type Validation: Filter candidates with wrong format for metric type
        if self.config.filter_false_positives:  # Reuse FP filter flag
            filtered_candidates = []
            for candidate in candidates:
                metric_id = candidate.suggested_metric_id
                raw_text = candidate.raw_number_text
                unit = candidate.parsed_unit or "count"
                context_text = candidate.context_text  # FIX-A: Get context for context-aware checks

                # Check if metric has type constraints
                type_mismatch = False
                mismatch_reason = None

                if metric_id in PERCENTAGE_ONLY_METRICS:
                    # FIX-A: Use context-aware percentage detection for retention metrics
                    if not should_treat_as_percentage(metric_id, raw_text, unit, context_text):
                        type_mismatch = True
                        mismatch_reason = f"{metric_id} expects percentage, got {unit}"

                elif metric_id in DOLLAR_ONLY_METRICS:
                    if not is_dollar_format(raw_text, unit):
                        type_mismatch = True
                        mismatch_reason = f"{metric_id} expects dollar amount, got {unit}"

                elif metric_id in COUNT_ONLY_METRICS:
                    if not is_count_format(raw_text, unit):
                        type_mismatch = True
                        mismatch_reason = f"{metric_id} expects count, got {unit}"

                if type_mismatch:
                    segment_stats["filtered_by_type_validation"] = segment_stats.get("filtered_by_type_validation", 0) + 1
                    logger.debug(
                        f"Filtered by type validation: {mismatch_reason} "
                        f"(value={candidate.parsed_value}, raw={raw_text})"
                    )
                else:
                    filtered_candidates.append(candidate)

            candidates = filtered_candidates

        return candidates, segment_stats

    def _find_numbers(self, text: str) -> list[NumberMatch]:
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
    ) -> tuple[bool, str | None]:
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

    def _find_all_keywords(self, text: str) -> list[KeywordMatch]:
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
        all_keywords: list[KeywordMatch],
        boundaries: list[Any] | None = None,
        sentence_boundaries: list[Any] | None = None,
        segment: SegmentDict | None = None,
        table_row_parser: Any | None = None,
    ) -> list[KeywordMatch]:
        """
        Find metric keywords within max_keyword_distance of a number.

        Delegates to KeywordMatcher (P1.3 - extracted to separate module, P1 enhanced, P1.5 sentence-aware).

        Args:
            number: The NumberMatch to search around
            all_keywords: Pre-computed list of all keyword matches in text
            boundaries: Optional list of TextBoundary objects for boundary-aware matching (P1 enhancement)
            sentence_boundaries: Optional list of TextBoundary objects for sentence-aware matching (P1.5 enhancement)
            segment: Optional segment dict for context (L4 Option C)
            table_row_parser: Optional TableRowParser for table row filtering

        Returns:
            List of KeywordMatch objects within range (one per metric)
        """
        # Extract text and segment_type for L4 Option C context detection
        text = segment.get("raw_text", "") if segment else ""
        segment_type = segment.get("segment_type") if segment else None

        return self._keyword_matcher.find_keywords_near_number(
            number,
            all_keywords,
            boundaries,
            sentence_boundaries,
            text=text,
            segment_type=segment_type,
            table_row_parser=table_row_parser,
        )

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
        segment: SegmentDict,
        all_numbers: list[NumberMatch],
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
            segment = {}  # type: ignore[unreachable]

        # Defensive: ensure all_numbers is a list
        if not isinstance(all_numbers, list):
            all_numbers = []  # type: ignore[unreachable]

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

    def _enrich_with_respectively_patterns(
        self,
        candidates: list[ReviewCandidate],
        segment_text: str,
    ) -> list[ReviewCandidate]:
        """
        Enrich candidates with period associations from respectively patterns (L1).

        Detects patterns like:
            "Revenue for 2015, 2016 and 2017 was $1M, $2M and $3M, respectively."

        And enriches matching candidates with detected_period="2015" etc. in features.

        Args:
            candidates: Candidates generated from segment
            segment_text: Full segment text to search for patterns

        Returns:
            Enriched candidates with detected_period in features
        """
        # Skip if disabled
        if not self.config.detect_respectively_patterns:
            return candidates

        # L1-P1.2: Detect patterns (single or multiple depending on config)
        from src.review.respectively_parser import (
            detect_all_respectively_patterns,
            detect_respectively_pattern,
        )

        if self.config.detect_all_respectively_patterns:
            # Detect ALL patterns in segment
            patterns = detect_all_respectively_patterns(
                segment_text,
                min_confidence=self.config.respectively_min_confidence
            )
        else:
            # Backward compatible: detect only first pattern
            pattern = detect_respectively_pattern(
                segment_text,
                min_confidence=self.config.respectively_min_confidence
            )
            patterns = [pattern] if pattern else []

        # No patterns found
        if not patterns:
            return candidates

        # Build lookup: normalized value -> (period, confidence)
        # If multiple patterns have same value, use highest confidence
        value_to_period: dict[str, tuple[str, float]] = {}
        for pattern in patterns:
            for value_text, period_text in pattern.associations:
                normalized = self._normalize_value_text(value_text)

                # Keep highest confidence if duplicate
                if normalized in value_to_period:
                    existing_confidence = value_to_period[normalized][1]
                    if pattern.confidence > existing_confidence:
                        value_to_period[normalized] = (period_text, pattern.confidence)
                else:
                    value_to_period[normalized] = (period_text, pattern.confidence)

        # Enrich candidates
        enriched_count = 0
        for candidate in candidates:
            # Try to match candidate value to pattern value
            normalized_candidate = self._normalize_value_text(
                candidate.raw_number_text or ""
            )

            if normalized_candidate in value_to_period:
                period, confidence = value_to_period[normalized_candidate]

                # Update features
                if candidate.features:
                    candidate.features.detected_period = period
                    candidate.features.respectively_confidence = confidence
                    enriched_count += 1

        if enriched_count > 0:
            logger.info(
                f"Enriched {enriched_count}/{len(candidates)} candidates with "
                f"{len(patterns)} respectively pattern(s)"
            )

        return candidates

    def _normalize_value_text(self, value_text: str) -> str:
        """
        Normalize value text for matching (remove spaces, standardize units).

        L1-P1.3 Enhancement: Standardizes magnitude suffixes for consistent matching.

        Used to match candidate raw_number_text with respectively pattern values.
        Handles variations like "million" vs "M", "billion" vs "B", etc.

        Examples:
            "$1M" -> "$1m"
            "$ 1 M" -> "$1m"
            "$1 million" -> "$1m"
            "$1Million" -> "$1m"
            "33.0%" -> "33.0%"
            "1.42" -> "1.42"
            "10 thousand" -> "10k"
            "5bn" -> "5b"

        Args:
            value_text: Raw value text to normalize

        Returns:
            Normalized text for matching
        """
        # Remove spaces
        normalized = value_text.replace(" ", "")

        # Standardize magnitude suffixes (long form → short form, then lowercase)
        # Order matters: do long forms first to avoid partial replacements
        replacements = [
            ("million", "m"),
            ("Million", "m"),
            ("MILLION", "m"),
            ("billion", "b"),
            ("Billion", "b"),
            ("BILLION", "b"),
            ("thousand", "k"),
            ("Thousand", "k"),
            ("THOUSAND", "k"),
            ("mn", "m"),  # Alternate short form
            ("MN", "m"),
            ("Mn", "m"),
            ("bn", "b"),  # Alternate short form
            ("BN", "b"),
            ("Bn", "b"),
            ("M", "m"),  # Lowercase remaining
            ("B", "b"),
            ("K", "k"),
        ]

        for old, new in replacements:
            normalized = normalized.replace(old, new)

        return normalized


# =============================================================================
# Convenience Functions
# =============================================================================

# generate_candidates_for_filing() moved to src/review/helpers.py
