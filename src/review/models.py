"""
Data models for human-in-the-loop review system.

These models represent candidates for review, human decisions,
and learned patterns before they're written to the database.
"""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional


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
    sentence_position: Optional[int] = None  # Position of number in sentence

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
            "sentence_position": self.sentence_position,
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
            sentence_position=data.get("sentence_position"),
        )


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

    # Keyword match info
    triggering_keyword: str  # The keyword that triggered this candidate
    keyword_distance: int  # Characters from number to keyword

    # Optional foreign key
    source_segment_id: Optional[int] = None

    # Parsed value (may fail to parse)
    parsed_value: Optional[Decimal] = None
    parsed_unit: Optional[str] = None  # 'count' | '%' | 'usd' | etc.

    # Keyword position
    keyword_position: Optional[str] = None  # 'before' | 'after'

    # Classification
    suggested_metric_id: Optional[str] = None
    suggestion_confidence: Optional[float] = None

    # ML features (stored as JSONB)
    features: Optional[CandidateFeatures] = None

    # Status
    review_status: str = "pending"  # 'pending' | 'reviewed' | 'skipped'
    review_batch_id: Optional[int] = None

    # Database fields
    candidate_id: Optional[int] = None
    created_at: Optional[datetime] = None

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
            CandidateFeatures.from_dict(features_data)
            if features_data
            else None
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
            keyword_position=row.get("keyword_position"),
            suggested_metric_id=row.get("suggested_metric_id"),
            suggestion_confidence=row.get("suggestion_confidence"),
            features=features,
            review_status=row.get("review_status", "pending"),
            review_batch_id=row.get("review_batch_id"),
            created_at=row.get("created_at"),
        )


# Valid decision types
DECISION_TYPES = ("accept", "reject", "reclassify")

# Valid rejection categories
REJECTION_CATEGORIES = (
    "wrong_metric",  # Number is a metric, but wrong type (e.g., CAC labeled as customer count)
    "not_a_metric",  # Number is not a customer metric at all
    "wrong_value",  # Right metric type but wrong value extracted
    "duplicate",  # Already captured elsewhere
    "uncertain",  # Reviewer unsure, needs more context
)


@dataclass
class ReviewDecision:
    """
    A human review decision for a candidate.

    Corresponds to the review_decisions database table.
    """

    # Required fields
    candidate_id: int
    decision: str  # 'accept' | 'reject' | 'reclassify'

    # Reclassification (when decision='reclassify' or 'accept')
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

    def __post_init__(self):
        """Validate decision type and rejection category."""
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


# Valid pattern types
PATTERN_TYPES = ("accept_rule", "reject_rule")

# Valid pattern statuses
PATTERN_STATUSES = ("candidate", "active", "deprecated")


@dataclass
class LearnedPattern:
    """
    A pattern learned from review decisions.

    Corresponds to the learned_patterns database table.
    Patterns can be used to automatically classify future candidates.
    """

    # Required fields
    pattern_type: str  # 'accept_rule' | 'reject_rule'
    pattern_name: str  # Human-readable name
    pattern_definition: Dict[str, Any]  # Rule definition as JSONB

    # Optional metric scope
    metric_id: Optional[str] = None  # If pattern is metric-specific

    # Performance metrics
    precision: Optional[float] = None  # Precision on training data
    recall: Optional[float] = None  # Recall on training data
    support: Optional[int] = None  # Number of examples matched

    # Status
    status: str = "candidate"  # 'candidate' | 'active' | 'deprecated'

    # Database fields
    pattern_id: Optional[int] = None
    created_at: Optional[datetime] = None

    def __post_init__(self):
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

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for database insertion."""
        return {
            "pattern_type": self.pattern_type,
            "metric_id": self.metric_id,
            "pattern_name": self.pattern_name,
            "pattern_definition": self.pattern_definition,
            "precision": self.precision,
            "recall": self.recall,
            "status": self.status,
        }

    @classmethod
    def from_row(cls, row: Dict[str, Any]) -> "LearnedPattern":
        """Create from database row."""
        return cls(
            pattern_id=row.get("pattern_id"),
            pattern_type=row["pattern_type"],
            metric_id=row.get("metric_id"),
            pattern_name=row["pattern_name"],
            pattern_definition=row["pattern_definition"],
            precision=row.get("precision"),
            recall=row.get("recall"),
            support=row.get("support"),
            status=row.get("status", "candidate"),
            created_at=row.get("created_at"),
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
                results.append(False)

        if logic == "and":
            return all(results)
        elif logic == "or":
            return any(results)
        else:
            return all(results)
