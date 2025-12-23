"""
Definition Extractor - Extract metric definitions and methodologies.

This module extracts textual definitions and calculation methodologies
for metrics from classified segments.
"""

import logging
import re
from typing import TYPE_CHECKING, Optional

from .models import MetricDefinition, SourceSegment
from .value_extractor import map_llm_name_to_metric_id, verify_quote_in_source

if TYPE_CHECKING:
    from ..llm.openai_client import OpenAIClient

logger = logging.getLogger(__name__)


class DefinitionExtractor:
    """
    Extract metric definitions and methodologies from source segments.

    Extracts:
    1. Definition text (what the metric means)
    2. Methodology text (how it's calculated)
    3. Assesses alignment with CMASB canonical definitions
    """

    TOP_SEGMENTS_PER_METRIC = 3
    HIGH_CONFIDENCE_THRESHOLD = 0.75

    # Canonical definitions for alignment assessment
    CANONICAL_DEFINITIONS = {
        "cm_new_customers_acquired": {
            "keywords": [
                "first",
                "qualifying",
                "economic",
                "activity",
                "purchase",
                "transaction",
                "period",
            ],
            "definition": "Count of unique customers whose first qualifying economic activity with the company occurs in the reporting period.",
        },
        "cm_customers_period_end_by_tenure": {
            "keywords": [
                "active",
                "period",
                "end",
                "tenure",
                "cohort",
                "time",
                "since",
            ],
            "definition": "Number of customers active at period end, broken down by tenure cohorts.",
        },
        "cm_revenue_by_cohort": {
            "keywords": [
                "revenue",
                "gaap",
                "cohort",
                "acquisition",
                "tenure",
                "period",
            ],
            "definition": "Recognized GAAP revenue in the period, attributed to customer cohorts.",
        },
        "cm_transactions_by_cohort": {
            "keywords": ["transactions", "purchase", "cohort", "completed"],
            "definition": "Number of completed purchase transactions in the period, grouped by customer cohort.",
        },
    }

    def __init__(self, llm_client: Optional["OpenAIClient"] = None):
        """
        Initialize the definition extractor.

        Args:
            llm_client: Optional OpenAI client for LLM-enhanced extraction.
                       If provided, LLM extraction will be tried first before
                       falling back to rule-based extraction.
        """
        self.llm_client = llm_client

    def extract_definitions(
        self, segments: list[SourceSegment], company_id: int
    ) -> list[MetricDefinition]:
        """
        Extract definitions for all metrics found in segments.

        Args:
            segments: List of classified source segments
            company_id: Company ID

        Returns:
            List of MetricDefinition objects
        """
        definitions = []

        # Group segments by metric
        metric_segments = self._group_segments_by_metric(segments)
        priority_metric_ids = self._get_priority_metric_ids(segments)
        metric_segments = self._filter_metric_segments(
            metric_segments, priority_metric_ids
        )

        # Extract definition for each metric
        for metric_id, metric_segs in metric_segments.items():
            definition = self._extract_metric_definition(
                metric_id, metric_segs, company_id
            )
            if definition:
                definitions.append(definition)

        logger.info(f"Extracted {len(definitions)} metric definitions")
        return definitions

    def _group_segments_by_metric(self, segments: list[SourceSegment]) -> dict:
        """
        Group segments by the metrics they mention.

        Returns:
            Dictionary mapping metric_id -> list of segments
        """
        metric_segments = {}

        for seg in segments:
            for metric_id in seg.candidate_metric_ids or []:
                if metric_id not in metric_segments:
                    metric_segments[metric_id] = []
                metric_segments[metric_id].append(seg)

        return metric_segments

    def _get_priority_metric_ids(self, segments: list[SourceSegment]) -> set[str]:
        """
        Build a priority set combining filing high-confidence candidates and CMASB metrics.
        """

        high_confidence_candidates = {
            metric_id
            for seg in segments
            if (seg.classifier_confidence or 0) >= self.HIGH_CONFIDENCE_THRESHOLD
            for metric_id in seg.candidate_metric_ids or []
        }

        try:
            from .metric_classifier import MetricClassifier

            cmasb_priority = (
                MetricClassifier.CMASB_CORE_METRICS
                | MetricClassifier.CMASB_EXTENDED_METRICS
            )
        except Exception:
            cmasb_priority = set()

        return high_confidence_candidates | set(cmasb_priority)

    def _filter_metric_segments(
        self, metric_segments: dict[str, list[SourceSegment]], preferred_metric_ids: set[str]
    ) -> dict[str, list[SourceSegment]]:
        """
        Keep top-confidence segments per metric and prefer priority candidates.
        """

        filtered: dict[str, list[SourceSegment]] = {}

        for metric_id, segs in metric_segments.items():
            sorted_segs = sorted(
                segs,
                key=lambda s: s.classifier_confidence or 0.0,
                reverse=True,
            )

            is_priority_metric = metric_id in preferred_metric_ids
            preferred = [
                seg
                for seg in sorted_segs
                if is_priority_metric
                and metric_id in (seg.candidate_metric_ids or [])
            ]

            preferred_ids = {id(seg) for seg in preferred}
            fallback = [seg for seg in sorted_segs if id(seg) not in preferred_ids]
            ordered = preferred + fallback

            filtered[metric_id] = ordered[: self.TOP_SEGMENTS_PER_METRIC]

        return filtered

    def _select_verified_snippet(
        self,
        candidate_segments: list[SourceSegment],
        all_segments: list[SourceSegment],
    ) -> tuple[str | None, int | None, str | None]:
        """
        Select the first candidate whose snippet can be verified in the source set.
        """

        if not candidate_segments:
            return None, None, None

        combined_text = " ".join(seg.raw_text for seg in all_segments if seg.raw_text)

        for seg in candidate_segments:
            snippet = seg.raw_text or ""
            if not snippet:
                continue

            if verify_quote_in_source(snippet, combined_text):
                return self._normalize_definition_text(snippet), seg.sequence_index, snippet

        return None, None, None

    def _extract_metric_definition(
        self, metric_id: str, segments: list[SourceSegment], company_id: int
    ) -> MetricDefinition | None:
        """
        Extract definition for a specific metric from its segments.

        Uses hybrid extraction strategy:
        1. Try LLM extraction if LLM client is available
        2. Fall back to rule-based extraction if LLM fails or not available

        Args:
            metric_id: Metric ID
            segments: Segments mentioning this metric
            company_id: Company ID

        Returns:
            MetricDefinition or None
        """
        # Find segments with definitions
        definition_segments = [s for s in segments if s.contains_definition_flag]
        methodology_segments = [s for s in segments if s.contains_methodology_flag]

        if not definition_segments and not methodology_segments:
            return None  # No definition or methodology found

        # Try LLM extraction first if available
        if self.llm_client:
            try:
                logger.info(
                    f"Attempting LLM definition extraction for metric {metric_id}"
                )
                definition = self._extract_definition_with_llm(
                    metric_id, definition_segments + methodology_segments, company_id
                )
                if definition:
                    logger.info(f"LLM definition extraction succeeded for {metric_id}")
                    return definition
                else:
                    logger.info(
                        "LLM extraction returned no definition, falling back to rules"
                    )
            except Exception as e:
                logger.warning(f"LLM definition extraction failed for {metric_id}: {e}")
                logger.info("Falling back to rule-based extraction")

        # Fall back to rule-based extraction
        logger.debug(f"Using rule-based definition extraction for {metric_id}")

        # Extract and normalize text from verified snippets
        definition_text, definition_segment_id, definition_raw_text = (
            self._select_verified_snippet(definition_segments, segments)
        )

        methodology_text, methodology_segment_id, methodology_raw_text = (
            self._select_verified_snippet(methodology_segments, segments)
        )

        if not definition_text and not methodology_text:
            return None

        # Assess alignment with canonical definition
        alignment_flag = self.assess_alignment(metric_id, definition_text)

        # Get filing_id from first segment
        filing_id = segments[0].filing_id

        definition = MetricDefinition(
            filing_id=filing_id,
            company_id=company_id,
            metric_id=metric_id,
            definition_text_normalized=definition_text,
            methodology_text_normalized=methodology_text,
            definition_raw_text=definition_raw_text,
            methodology_raw_text=methodology_raw_text,
            definition_segment_id=definition_segment_id,
            methodology_segment_id=methodology_segment_id,
            alignment_flag=alignment_flag,
        )

        return definition

    def _extract_definition_with_llm(
        self, metric_id: str, segments: list[SourceSegment], company_id: int
    ) -> MetricDefinition | None:
        """
        Extract definition using LLM.

        Args:
            metric_id: Metric ID
            segments: Segments that may contain definitions
            company_id: Company ID

        Returns:
            MetricDefinition or None
        """
        if not self.llm_client:
            raise ValueError("LLM client not available")

        if not segments:
            return None

        # Import here to avoid circular imports
        from ..llm.prompts import PromptTemplates

        # Combine text from all segments (up to 8000 chars)
        combined_text = " ".join(seg.raw_text for seg in segments)[:8000]

        # Create prompt
        prompt = PromptTemplates.definition_extraction(
            segment_text=combined_text, metric_names=metric_id
        )

        # Get LLM response
        response = self.llm_client.complete(
            prompt, system_message=PromptTemplates.SYSTEM_DEFINITION_EXTRACTION
        )

        # Parse response
        try:
            data = PromptTemplates.parse_json_response(response.content)

            if not PromptTemplates.validate_definition_extraction_response(data):
                logger.warning("LLM definition response failed validation")
                return None

            # Find the definition for our metric
            for item in data:
                # Use metric name mapping to match LLM names to canonical IDs
                llm_metric_name = item.get("metric_name")
                mapped_id = map_llm_name_to_metric_id(llm_metric_name)

                # Check if the mapped ID matches our target metric
                if mapped_id == metric_id:
                    # Extract definition text
                    definition_text = item["definition_text"]

                    # Check if it includes calculation methodology
                    includes_calculation = item.get("includes_calculation", False)

                    # Get the quote
                    quote = item.get("quote", "")

                    # Verify quote exists in source
                    if quote:
                        if not verify_quote_in_source(quote, combined_text):
                            truncated_quote = (
                                quote[:100] + "..." if len(quote) > 100 else quote
                            )
                            logger.warning(
                                f"Quote verification failed for definition extraction: {metric_id}. "
                                f"Falling back to rule-based. Quote: '{truncated_quote}'"
                            )
                            return None  # Fall back to rule-based extraction
                    else:
                        logger.info(
                            f"LLM returned empty quote for definition extraction: {metric_id} - "
                            "accepting without verification"
                        )

                    # Assess alignment with canonical definition
                    alignment_flag = self.assess_alignment(metric_id, definition_text)

                    # Get filing_id from first segment
                    filing_id = segments[0].filing_id

                    # Split into definition and methodology if calculation is included
                    methodology_text = None
                    if includes_calculation:
                        # For now, use the same text for both
                        # In the future, could use LLM to separate them
                        methodology_text = definition_text

                    definition = MetricDefinition(
                        filing_id=filing_id,
                        company_id=company_id,
                        metric_id=metric_id,
                        definition_text_normalized=self._normalize_definition_text(
                            definition_text
                        ),
                        methodology_text_normalized=(
                            self._normalize_definition_text(methodology_text)
                            if methodology_text
                            else None
                        ),
                        definition_raw_text=quote,
                        methodology_raw_text=quote if includes_calculation else None,
                        definition_segment_id=segments[0].sequence_index,
                        methodology_segment_id=(
                            segments[0].sequence_index if includes_calculation else None
                        ),
                        alignment_flag=alignment_flag,
                    )

                    return definition

            # No matching definition found
            logger.info(f"LLM did not find definition for {metric_id}")
            return None

        except Exception as e:
            logger.error(f"Failed to parse LLM definition response: {e}")
            return None

    def _normalize_definition_text(self, text: str) -> str:
        """
        Clean and normalize definition text.

        - Remove excess whitespace
        - Normalize punctuation
        - Truncate to reasonable length
        """
        # Remove excess whitespace
        normalized = re.sub(r"\s+", " ", text).strip()

        # Truncate if too long (keep first 500 chars)
        if len(normalized) > 500:
            normalized = normalized[:500] + "..."

        return normalized

    def assess_alignment(self, metric_id: str, issuer_definition: str | None) -> str:
        """
        Assess alignment between issuer and CMASB canonical definitions.

        Args:
            metric_id: Metric ID
            issuer_definition: Issuer's definition text

        Returns:
            'aligned', 'partial', 'not_aligned', or 'unknown'
        """
        if not issuer_definition:
            return "unknown"

        canonical = self.CANONICAL_DEFINITIONS.get(metric_id)
        if not canonical:
            return "unknown"  # No canonical definition available

        # Simple keyword overlap approach
        issuer_lower = issuer_definition.lower()
        keywords = canonical["keywords"]

        # Count how many canonical keywords appear in issuer definition
        matches = sum(1 for kw in keywords if kw in issuer_lower)
        overlap_ratio = matches / len(keywords) if keywords else 0

        # Classify alignment
        if overlap_ratio >= 0.7:
            return "aligned"
        elif overlap_ratio >= 0.3:
            return "partial"
        elif overlap_ratio > 0:
            return "not_aligned"
        else:
            return "unknown"


# Convenience function
def extract_definitions(
    segments: list[SourceSegment], company_id: int
) -> list[MetricDefinition]:
    """
    Convenience function to extract definitions from segments.

    Args:
        segments: List of classified source segments
        company_id: Company ID

    Returns:
        List of MetricDefinition objects
    """
    extractor = DefinitionExtractor()
    return extractor.extract_definitions(segments, company_id)
