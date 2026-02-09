"""
Data models for human-in-the-loop review system.

These models represent candidates for review, human decisions,
and learned patterns before they're written to the database.

Schema alignment: sql/07_create_review_schema.sql
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any, NotRequired, TypedDict

if TYPE_CHECKING:
    from src.review.boundary_detection import TextBoundary
    from src.review.keyword_matching import KeywordMatch
    from src.review.number_parsing import NumberMatch

logger = logging.getLogger(__name__)


# =============================================================================
# TypedDicts for database row structures
# =============================================================================


class SegmentDict(TypedDict):
    """
    Type definition for source segment dictionaries returned from database.

    Source segments represent parsed sections of SEC filing documents (paragraphs,
    tables, headings, etc.) and are the primary input to the candidate generation
    pipeline.

    This TypedDict documents the expected structure of segment dicts returned by
    `DatabaseAdapter.get_source_segments_for_filing()` and consumed by
    `CandidateGenerator.generate_for_filing()`.

    Required Fields:
        source_segment_id: Primary key identifier for this segment
        filing_id: Foreign key to the parent filing
        segment_type: Type of segment ('paragraph', 'table', 'heading', 'list_item')
        raw_text: Plain text content of the segment (primary data for analysis)
        sequence_index: Ordinal position within the filing (for ordering)
        created_at: Timestamp when segment was created
        updated_at: Timestamp when segment was last modified

    Optional Fields:
        section_path: Dot-separated path of section headings (e.g., "1.Business.1.1.Overview")
        section_heading: Immediate parent section heading text
        html_selector: CSS selector path to locate segment in original HTML
        char_start_offset: Character offset where segment starts in full document
        char_end_offset: Character offset where segment ends in full document
        page_number: PDF page number (if available from filing)
        raw_html: Original HTML markup for the segment
        candidate_metric_ids: Array of metric IDs detected by classifier
        contains_definition_flag: Whether segment contains metric definitions
        contains_methodology_flag: Whether segment contains methodology descriptions
        contains_numeric_disclosure_flag: Whether segment contains numeric values
        classifier_confidence: Confidence score from metric classifier (0.0-1.0)

    Example Usage:
        >>> from src.infra.db import DatabaseAdapter
        >>> from src.review import CandidateGenerator
        >>>
        >>> db = DatabaseAdapter("postgresql://user:pass@localhost/filings_analysis")
        >>> segments: List[SegmentDict] = db.get_source_segments_for_filing(filing_id=123)
        >>>
        >>> generator = CandidateGenerator()
        >>> candidates = generator.generate_for_filing(
        ...     filing_id=123,
        ...     company_id=456,
        ...     segments=segments,
        ... )

    Database Source:
        Populated by `DatabaseAdapter.get_source_segments_for_filing()` from
        the `source_segments` table. See sql/01_create_schema.sql for table definition.

    Type Safety:
        Using this TypedDict enables mypy to catch type errors when accessing
        segment dict keys, improving code quality and reducing runtime errors.
    """

    # Required fields (NOT NULL in database)
    source_segment_id: int
    filing_id: int
    segment_type: str
    raw_text: str
    sequence_index: int
    created_at: datetime
    updated_at: datetime

    # Optional fields (nullable in database or not always present)
    section_path: NotRequired[str | None]
    section_heading: NotRequired[str | None]
    html_selector: NotRequired[str | None]
    char_start_offset: NotRequired[int | None]
    char_end_offset: NotRequired[int | None]
    page_number: NotRequired[int | None]
    raw_html: NotRequired[str | None]
    candidate_metric_ids: NotRequired[list[str] | None]
    contains_definition_flag: NotRequired[bool | None]
    contains_methodology_flag: NotRequired[bool | None]
    contains_numeric_disclosure_flag: NotRequired[bool | None]
    classifier_confidence: NotRequired[float | None]


# =============================================================================
# Enumeration Constants (aligned with SQL CHECK constraints)
# =============================================================================

# CandidateFeatures / ReviewCandidate
KEYWORD_POSITIONS = ("before", "after")
NUMBER_FORMATS = ("integer", "decimal", "percentage", "currency")

# ReviewCandidate.review_status
REVIEW_STATUSES = ("pending", "in_progress", "reviewed", "skipped")

# ReviewDecision.decision
DECISION_TYPES = ("accept", "reject", "reclassify")

# ReviewDecision.rejection_category
# Note: Display text may differ from enum value (see review.html template)
REJECTION_CATEGORIES = (
    "wrong_metric",  # Display: "Wrong Metric Type" - number is a metric, but wrong type
    "not_a_metric",  # Display: "Not a Customer Metric" - value is outside CMASB scope
    "wrong_value",  # Display: "Wrong Value Extracted" - right metric but wrong value
    "wrong_period",  # Display: "Wrong Time Period" - right metric but wrong period
    "duplicate",  # Display: "Duplicate" - already captured elsewhere
    "other",  # Display: "Other" - see rejection_reason for details
)

# LearnedPattern.pattern_type
PATTERN_TYPES = ("accept_rule", "reject_rule", "feature_weight")

# LearnedPattern.status
PATTERN_STATUSES = ("candidate", "approved", "rejected", "deprecated")

# =============================================================================
# Image Review Constants (aligned with sql/09_create_image_review_schema.sql)
# =============================================================================

# ImageReviewCandidate.review_status
IMAGE_REVIEW_STATUSES = ("pending", "reviewed", "skipped")

# ImageReviewCandidate.detection_tier
IMAGE_DETECTION_TIERS = ("tier_1_cohort", "tier_2_large", "tier_3_all", "seed_list")

# ImageReviewDecision.decision
IMAGE_DECISIONS = ("relevant", "not_relevant")

# ImageReviewDecision.chart_type
IMAGE_CHART_TYPES = (
    "cohort_table",
    "cohort_heatmap",
    "line_chart",
    "bar_chart",
    "stacked_bar",
    "other_chart",
    "mixed",
)

# Display labels for chart types (for dropdowns)
IMAGE_CHART_TYPE_LABELS: dict[str, str] = {
    "cohort_table": "Cohort Table",
    "cohort_heatmap": "Cohort Heatmap",
    "line_chart": "Line Chart",
    "bar_chart": "Bar Chart",
    "stacked_bar": "Stacked Bar",
    "other_chart": "Other Chart",
    "mixed": "Mixed",
}

# ImageReviewDecision.rejection_reason
IMAGE_REJECTION_REASONS = (
    "decorative",
    "not_a_chart",
    "wrong_subject",
    "duplicate",
    "unreadable",
    "other",
)

# Display labels for rejection reasons (for dropdowns)
IMAGE_REJECTION_REASON_LABELS: dict[str, str] = {
    "decorative": "Decorative (logo, icon)",
    "not_a_chart": "Not a Chart",
    "wrong_subject": "Wrong Subject",
    "duplicate": "Duplicate",
    "unreadable": "Unreadable",
    "other": "Other",
}

# Detection tier priority for sorting (lower = higher priority)
IMAGE_TIER_PRIORITY = {
    "seed_list": 0,
    "tier_1_cohort": 1,
    "tier_2_large": 2,
    "tier_3_all": 3,
}


# =============================================================================
# CandidateFeatures
# =============================================================================


@dataclass
class CandidateFeatures:
    """
    ML features computed for a review candidate.

    Used to analyze patterns in accepted vs rejected candidates
    and to generate improved extraction rules.
    """

    # Distance features
    keyword_distance: int  # Characters from number to keyword
    keyword_position: str  # 'before' | 'after' - keyword relative to number

    # Context features
    is_in_table: bool  # Table vs paragraph
    is_in_risk_factors: bool  # High false positive section
    contains_definition_language: bool  # "we define", "defined as", etc.
    has_period_mention: bool  # Date/quarter nearby

    # Number features
    number_format: str  # 'integer' | 'decimal' | 'percentage' | 'currency'
    value_magnitude: float | None = None  # Log10 of absolute value
    surrounding_numbers_count: int = 0  # Other numbers within context window

    # Section features
    section_name: str | None = None  # Section heading if available

    # Additional computed features
    context_word_count: int = 0

    # L1: Respectively pattern detection (Phase 2)
    detected_period: str | None = None  # e.g., "2015", "Q1 2016", "FY2017"
    respectively_confidence: float | None = None  # Pattern confidence 0.0-1.0

    # L4: Context-dependent multiplier tracking (E1 optimization)
    context_type: str | None = None  # 'table' | 'parenthetical' | 'bullet' | 'copula' | 'preposition' | 'default'

    # P1.6: Same-sentence tracking for deduplication preference
    is_same_sentence: bool = False  # True if keyword and value are in the same sentence

    # Phase 7: Context prefix matching (segmentation redesign)
    from_context_prefix: bool = False  # True if keyword was found in context_prefix, not main text

    def __post_init__(self) -> None:
        """Validate enumerated fields."""
        if self.keyword_position not in KEYWORD_POSITIONS:
            raise ValueError(
                f"Invalid keyword_position '{self.keyword_position}'. "
                f"Must be one of: {KEYWORD_POSITIONS}"
            )
        if self.number_format not in NUMBER_FORMATS:
            raise ValueError(
                f"Invalid number_format '{self.number_format}'. "
                f"Must be one of: {NUMBER_FORMATS}"
            )
        # Validate context_type if provided
        if self.context_type is not None:
            valid_context_types = {'table', 'parenthetical', 'bullet', 'copula', 'preposition', 'default'}
            if self.context_type not in valid_context_types:
                raise ValueError(
                    f"Invalid context_type '{self.context_type}'. "
                    f"Must be one of: {valid_context_types}"
                )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSONB storage."""
        return {
            "keyword_distance": self.keyword_distance,
            "keyword_position": self.keyword_position,
            "is_in_table": self.is_in_table,
            "is_in_risk_factors": self.is_in_risk_factors,
            "contains_definition_language": self.contains_definition_language,
            "has_period_mention": self.has_period_mention,
            "number_format": self.number_format,
            "value_magnitude": self.value_magnitude,
            "surrounding_numbers_count": self.surrounding_numbers_count,
            "section_name": self.section_name,
            "context_word_count": self.context_word_count,
            "detected_period": self.detected_period,
            "respectively_confidence": self.respectively_confidence,
            "context_type": self.context_type,
            "is_same_sentence": self.is_same_sentence,
            "from_context_prefix": self.from_context_prefix,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CandidateFeatures":
        """Create from dictionary (e.g., from JSONB)."""
        return cls(
            keyword_distance=data.get("keyword_distance", 0),
            keyword_position=data.get("keyword_position", "after"),
            is_in_table=data.get("is_in_table", False),
            is_in_risk_factors=data.get("is_in_risk_factors", False),
            contains_definition_language=data.get(
                "contains_definition_language", False
            ),
            has_period_mention=data.get("has_period_mention", False),
            number_format=data.get("number_format", "integer"),
            value_magnitude=data.get("value_magnitude"),
            surrounding_numbers_count=data.get("surrounding_numbers_count", 0),
            section_name=data.get("section_name"),
            context_word_count=data.get("context_word_count", 0),
            detected_period=data.get("detected_period"),  # L1: Respectively pattern
            respectively_confidence=data.get("respectively_confidence"),  # L1
            context_type=data.get("context_type"),  # L4: Context multiplier type
            is_same_sentence=data.get("is_same_sentence", False),  # P1.6: Same-sentence tracking
            from_context_prefix=data.get("from_context_prefix", False),  # Phase 7: Context prefix matching
        )


# =============================================================================
# ReviewCandidate
# =============================================================================


@dataclass
class ReviewCandidate:
    """
    A candidate metric awaiting human review.

    Corresponds to the review_candidates database table.
    """

    # Required foreign keys
    filing_id: int
    company_id: int

    # Location and context
    char_position: int  # Character offset in segment/document
    context_text: str  # 30-50 words each direction around number
    raw_number_text: str  # The raw text of the extracted number

    # Keyword match info (required per schema)
    triggering_keyword: str  # The keyword that triggered this candidate
    keyword_distance: int  # Characters from number to keyword
    keyword_position: str  # 'before' | 'after' (required per schema)

    # Optional foreign key
    source_segment_id: int | None = None

    # Parsed value (may fail to parse)
    parsed_value: Decimal | None = None
    parsed_unit: str | None = None  # 'count' | '%' | 'usd' | etc.

    # Classification
    suggested_metric_id: str | None = None
    suggestion_confidence: float | None = None

    # ML features (stored as JSONB)
    features: CandidateFeatures | None = None

    # Status
    review_status: str = "pending"  # 'pending' | 'in_progress' | 'reviewed' | 'skipped'
    review_batch_id: int | None = None

    # Database fields
    candidate_id: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        """Validate enumerated fields."""
        if self.keyword_position not in KEYWORD_POSITIONS:
            raise ValueError(
                f"Invalid keyword_position '{self.keyword_position}'. "
                f"Must be one of: {KEYWORD_POSITIONS}"
            )
        if self.review_status not in REVIEW_STATUSES:
            raise ValueError(
                f"Invalid review_status '{self.review_status}'. "
                f"Must be one of: {REVIEW_STATUSES}"
            )
        if self.suggestion_confidence is not None:
            if not (0 <= self.suggestion_confidence <= 1):
                raise ValueError(
                    f"suggestion_confidence must be between 0 and 1, "
                    f"got {self.suggestion_confidence}"
                )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for database insertion."""
        return {
            "filing_id": self.filing_id,
            "company_id": self.company_id,
            "source_segment_id": self.source_segment_id,
            "char_position": self.char_position,
            "context_text": self.context_text,
            "raw_number_text": self.raw_number_text,
            "parsed_value": self.parsed_value,
            "parsed_unit": self.parsed_unit,
            "triggering_keyword": self.triggering_keyword,
            "keyword_distance": self.keyword_distance,
            "keyword_position": self.keyword_position,
            "suggested_metric_id": self.suggested_metric_id,
            "suggestion_confidence": self.suggestion_confidence,
            "features": self.features.to_dict() if self.features else None,
            "review_status": self.review_status,
            "review_batch_id": self.review_batch_id,
        }

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "ReviewCandidate":
        """Create from database row."""
        features_data = row.get("features")
        features = (
            CandidateFeatures.from_dict(features_data) if features_data else None
        )

        return cls(
            candidate_id=row.get("candidate_id"),
            filing_id=row["filing_id"],
            company_id=row["company_id"],
            source_segment_id=row.get("source_segment_id"),
            char_position=row["char_position"],
            context_text=row["context_text"],
            raw_number_text=row["raw_number_text"],
            parsed_value=row.get("parsed_value"),
            parsed_unit=row.get("parsed_unit"),
            triggering_keyword=row["triggering_keyword"],
            keyword_distance=row["keyword_distance"],
            keyword_position=row["keyword_position"],
            suggested_metric_id=row.get("suggested_metric_id"),
            suggestion_confidence=row.get("suggestion_confidence"),
            features=features,
            review_status=row.get("review_status", "pending"),
            review_batch_id=row.get("review_batch_id"),
            created_at=row.get("created_at"),
            updated_at=row.get("updated_at"),
        )


# =============================================================================
# ReviewDecision
# =============================================================================


@dataclass
class ReviewDecision:
    """
    A human review decision for a candidate.

    Corresponds to the review_decisions database table.
    """

    # Required fields
    candidate_id: int
    decision: str  # 'accept' | 'reject' | 'reclassify'

    # Metric assignment (required for accept/reclassify per schema)
    assigned_metric_id: str | None = None

    # Rejection details (when decision='reject')
    rejection_reason: str | None = None  # Free text explanation
    rejection_category: str | None = None  # Categorical reason

    # Reviewer metadata
    reviewer_notes: str | None = None
    review_time_seconds: int | None = None

    # Database fields
    decision_id: int | None = None
    created_at: datetime | None = None

    def __post_init__(self) -> None:
        """Validate decision type, rejection category, and business rules."""
        if self.decision not in DECISION_TYPES:
            raise ValueError(
                f"Invalid decision '{self.decision}'. "
                f"Must be one of: {DECISION_TYPES}"
            )
        if (
            self.rejection_category
            and self.rejection_category not in REJECTION_CATEGORIES
        ):
            raise ValueError(
                f"Invalid rejection_category '{self.rejection_category}'. "
                f"Must be one of: {REJECTION_CATEGORIES}"
            )
        # Business rule: accept/reclassify require assigned_metric_id
        if self.decision in ("accept", "reclassify") and not self.assigned_metric_id:
            raise ValueError(
                f"Decision '{self.decision}' requires assigned_metric_id"
            )
        # Business rule: rejection_category only makes sense for reject
        if self.decision != "reject" and self.rejection_category:
            raise ValueError(
                f"rejection_category should only be set when decision='reject', "
                f"got decision='{self.decision}'"
            )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for database insertion."""
        return {
            "candidate_id": self.candidate_id,
            "decision": self.decision,
            "assigned_metric_id": self.assigned_metric_id,
            "rejection_reason": self.rejection_reason,
            "rejection_category": self.rejection_category,
            "reviewer_notes": self.reviewer_notes,
            "review_time_seconds": self.review_time_seconds,
        }

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "ReviewDecision":
        """Create from database row."""
        return cls(
            decision_id=row.get("decision_id"),
            candidate_id=row["candidate_id"],
            decision=row["decision"],
            assigned_metric_id=row.get("assigned_metric_id"),
            rejection_reason=row.get("rejection_reason"),
            rejection_category=row.get("rejection_category"),
            reviewer_notes=row.get("reviewer_notes"),
            review_time_seconds=row.get("review_time_seconds"),
            created_at=row.get("created_at"),
        )


# =============================================================================
# LearnedPattern
# =============================================================================


@dataclass
class LearnedPattern:
    """
    A pattern learned from review decisions.

    Corresponds to the learned_patterns database table.
    Patterns can be used to automatically classify future candidates.
    """

    # Required fields
    pattern_type: str  # 'accept_rule' | 'reject_rule' | 'feature_weight'
    pattern_name: str  # Human-readable name
    pattern_definition: dict[str, Any]  # Rule definition as JSONB

    # Optional metric scope
    metric_id: str | None = None  # If pattern is metric-specific

    # Description
    pattern_description: str | None = None  # Longer description

    # Performance metrics (aligned with schema column names)
    precision_score: float | None = None  # Precision on training data
    recall_score: float | None = None  # Recall on training data
    f1_score: float | None = None  # F1 score
    sample_count: int | None = None  # Number of samples matched

    # Status and approval
    status: str = "candidate"  # 'candidate' | 'approved' | 'rejected' | 'deprecated'
    approved_at: datetime | None = None
    approved_by: str | None = None

    # Database fields
    pattern_id: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        """Validate pattern type and status."""
        if self.pattern_type not in PATTERN_TYPES:
            raise ValueError(
                f"Invalid pattern_type '{self.pattern_type}'. "
                f"Must be one of: {PATTERN_TYPES}"
            )
        if self.status not in PATTERN_STATUSES:
            raise ValueError(
                f"Invalid status '{self.status}'. "
                f"Must be one of: {PATTERN_STATUSES}"
            )
        # Validate score ranges
        for score_name, score_val in [
            ("precision_score", self.precision_score),
            ("recall_score", self.recall_score),
            ("f1_score", self.f1_score),
        ]:
            if score_val is not None and not (0 <= score_val <= 1):
                raise ValueError(
                    f"{score_name} must be between 0 and 1, got {score_val}"
                )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for database insertion."""
        return {
            "pattern_type": self.pattern_type,
            "metric_id": self.metric_id,
            "pattern_name": self.pattern_name,
            "pattern_description": self.pattern_description,
            "pattern_definition": self.pattern_definition,
            "precision_score": self.precision_score,
            "recall_score": self.recall_score,
            "f1_score": self.f1_score,
            "sample_count": self.sample_count,
            "status": self.status,
            "approved_at": self.approved_at,
            "approved_by": self.approved_by,
        }

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "LearnedPattern":
        """Create from database row."""
        return cls(
            pattern_id=row.get("pattern_id"),
            pattern_type=row["pattern_type"],
            metric_id=row.get("metric_id"),
            pattern_name=row["pattern_name"],
            pattern_description=row.get("pattern_description"),
            pattern_definition=row["pattern_definition"],
            precision_score=row.get("precision_score"),
            recall_score=row.get("recall_score"),
            f1_score=row.get("f1_score"),
            sample_count=row.get("sample_count"),
            status=row.get("status", "candidate"),
            approved_at=row.get("approved_at"),
            approved_by=row.get("approved_by"),
            created_at=row.get("created_at"),
            updated_at=row.get("updated_at"),
        )

    def matches(self, features: CandidateFeatures) -> bool:
        """
        Check if this pattern matches the given features.

        The pattern_definition contains rules like:
        {
            "conditions": [
                {"field": "is_in_risk_factors", "op": "eq", "value": True},
                {"field": "keyword_distance", "op": "gt", "value": 50}
            ],
            "logic": "and"  # or "or"
        }

        Supported operators:
        - eq, ne: equality/inequality
        - gt, lt, gte, lte: numeric comparisons
        - in: value in list
        - contains: substring match (for strings)
        """
        definition = self.pattern_definition
        conditions = definition.get("conditions", [])
        logic = definition.get("logic", "and")

        if not conditions:
            return False

        features_dict = features.to_dict()
        results: list[bool] = []

        for condition in conditions:
            field_name = condition.get("field")
            op = condition.get("op", "eq")
            expected = condition.get("value")

            actual = features_dict.get(field_name)

            if op == "eq":
                results.append(actual == expected)
            elif op == "ne":
                results.append(actual != expected)
            elif op == "gt":
                results.append(
                    actual is not None
                    and expected is not None
                    and actual > expected
                )
            elif op == "lt":
                results.append(
                    actual is not None
                    and expected is not None
                    and actual < expected
                )
            elif op == "gte":
                results.append(
                    actual is not None
                    and expected is not None
                    and actual >= expected
                )
            elif op == "lte":
                results.append(
                    actual is not None
                    and expected is not None
                    and actual <= expected
                )
            elif op == "in":
                results.append(actual in expected if expected else False)
            elif op == "contains":
                results.append(
                    expected in actual
                    if actual and isinstance(actual, str)
                    else False
                )
            else:
                # Unknown operator - treat as non-match
                results.append(False)

        if logic == "and":
            return all(results)
        elif logic == "or":
            return any(results)
        else:
            return all(results)


# =============================================================================
# ProcessingStats
# =============================================================================


@dataclass
class ProcessingStats:
    """Statistics from candidate generation processing."""

    segments_processed: int = 0
    segments_failed: int = 0
    numbers_found: int = 0
    numbers_failed: int = 0
    candidates_generated: int = 0
    false_positives_filtered: int = 0
    filtered_by_learned_rules: int = 0
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
            f"learned_rules_filtered={self.filtered_by_learned_rules}, "
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
# SegmentProcessingContext (REV-07 refactoring support)
# =============================================================================


@dataclass(frozen=True)
class SegmentProcessingContext:
    """
    Immutable context passed through all processing phases of _process_segment.

    This dataclass captures all pre-computed data structures needed during
    segment processing, enabling the decomposition of _process_segment into
    smaller, focused helper methods.

    All fields are computed once during the preparation phase and remain
    constant throughout processing. The frozen=True ensures immutability.
    """

    # Core segment data
    text: str
    source_segment_id: int | None
    filing_id: int
    company_id: int
    segment: SegmentDict

    # Pre-computed structures (computed once, used many times)
    numbers: tuple[NumberMatch, ...]  # Immutable tuple for frozen dataclass
    all_keywords: tuple[KeywordMatch, ...]  # Pre-computed keyword matches
    word_positions: tuple[tuple[int, int, str], ...] | None  # For context extraction

    # Boundary detection results
    boundaries: tuple[TextBoundary, ...] | None  # Semantic boundaries
    sentence_boundaries: tuple[TextBoundary, ...] | None  # Sentence boundaries

    # Table parsing (optional, only for table segments)
    # Note: Can't be frozen since parsers are mutable, stored as Any
    table_row_parser: Any | None

    # Metadata
    context_prefix: str  # From previous segment (Phase 7)
    segment_type: str | None  # 'paragraph', 'table', etc.


# =============================================================================
# SegmentStats (REV-07 refactoring support)
# =============================================================================


@dataclass
class SegmentStats:
    """
    Mutable statistics tracker for segment processing.

    Tracks counts during _process_segment execution. Unlike ProcessingStats
    (which tracks filing-level stats), this tracks per-segment statistics
    that get rolled up into ProcessingStats.
    """

    numbers_found: int = 0
    numbers_processed: int = 0
    numbers_failed: int = 0
    false_positives_filtered: int = 0
    candidates_generated: int = 0
    filtered_by_learned_rules: int = 0
    filtered_by_type_validation: int = 0
    excluded_by_number_context: int = 0

    def inc(self, field_name: str, amount: int = 1) -> None:
        """Increment a stat field by amount."""
        current = getattr(self, field_name, 0)
        setattr(self, field_name, current + amount)

    def to_dict(self) -> dict[str, int]:
        """Convert to dict for backward compatibility with existing code."""
        return {
            "numbers_found": self.numbers_found,
            "numbers_processed": self.numbers_processed,
            "numbers_failed": self.numbers_failed,
            "false_positives_filtered": self.false_positives_filtered,
            "candidates_generated": self.candidates_generated,
            "filtered_by_learned_rules": self.filtered_by_learned_rules,
            "filtered_by_type_validation": self.filtered_by_type_validation,
            "excluded_by_number_context": self.excluded_by_number_context,
        }
