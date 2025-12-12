"""
Data models for human-in-the-loop review system.

These models represent candidates for review, human decisions,
and learned patterns before they're written to the database.

Schema alignment: sql/07_create_review_schema.sql
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


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
REJECTION_CATEGORIES = (
    "wrong_metric",  # Number is a metric, but wrong type
    "not_a_metric",  # Number is not a customer metric at all
    "wrong_value",  # Right metric type but wrong value extracted
    "wrong_period",  # Right metric but wrong time period
    "duplicate",  # Already captured elsewhere
    "other",  # Other reason (see rejection_reason)
)

# LearnedPattern.pattern_type
PATTERN_TYPES = ("accept_rule", "reject_rule", "feature_weight")

# LearnedPattern.status
PATTERN_STATUSES = ("candidate", "approved", "rejected", "deprecated")


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
    value_magnitude: Optional[float] = None  # Log10 of absolute value
    surrounding_numbers_count: int = 0  # Other numbers within context window

    # Section features
    section_name: Optional[str] = None  # Section heading if available

    # Additional computed features
    context_word_count: int = 0

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

    def to_dict(self) -> Dict[str, Any]:
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
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CandidateFeatures":
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
    source_segment_id: Optional[int] = None

    # Parsed value (may fail to parse)
    parsed_value: Optional[Decimal] = None
    parsed_unit: Optional[str] = None  # 'count' | '%' | 'usd' | etc.

    # Classification
    suggested_metric_id: Optional[str] = None
    suggestion_confidence: Optional[float] = None

    # ML features (stored as JSONB)
    features: Optional[CandidateFeatures] = None

    # Status
    review_status: str = "pending"  # 'pending' | 'in_progress' | 'reviewed' | 'skipped'
    review_batch_id: Optional[int] = None

    # Database fields
    candidate_id: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

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

    def to_dict(self) -> Dict[str, Any]:
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
    def from_row(cls, row: Dict[str, Any]) -> "ReviewCandidate":
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
    assigned_metric_id: Optional[str] = None

    # Rejection details (when decision='reject')
    rejection_reason: Optional[str] = None  # Free text explanation
    rejection_category: Optional[str] = None  # Categorical reason

    # Reviewer metadata
    reviewer_notes: Optional[str] = None
    review_time_seconds: Optional[int] = None

    # Database fields
    decision_id: Optional[int] = None
    created_at: Optional[datetime] = None

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

    def to_dict(self) -> Dict[str, Any]:
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
    def from_row(cls, row: Dict[str, Any]) -> "ReviewDecision":
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
    pattern_definition: Dict[str, Any]  # Rule definition as JSONB

    # Optional metric scope
    metric_id: Optional[str] = None  # If pattern is metric-specific

    # Description
    pattern_description: Optional[str] = None  # Longer description

    # Performance metrics (aligned with schema column names)
    precision_score: Optional[float] = None  # Precision on training data
    recall_score: Optional[float] = None  # Recall on training data
    f1_score: Optional[float] = None  # F1 score
    sample_count: Optional[int] = None  # Number of samples matched

    # Status and approval
    status: str = "candidate"  # 'candidate' | 'approved' | 'rejected' | 'deprecated'
    approved_at: Optional[datetime] = None
    approved_by: Optional[str] = None

    # Database fields
    pattern_id: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

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

    def to_dict(self) -> Dict[str, Any]:
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
    def from_row(cls, row: Dict[str, Any]) -> "LearnedPattern":
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
        results: List[bool] = []

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
