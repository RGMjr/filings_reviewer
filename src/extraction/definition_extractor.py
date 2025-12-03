"""
Definition Extractor - Extract metric definitions and methodologies.

This module extracts textual definitions and calculation methodologies
for metrics from classified segments.
"""

import logging
import re
from typing import List, Optional, TYPE_CHECKING

from .models import SourceSegment, MetricDefinition

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
        self, segments: List[SourceSegment], company_id: int
    ) -> List[MetricDefinition]:
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

        # Extract definition for each metric
        for metric_id, metric_segs in metric_segments.items():
            definition = self._extract_metric_definition(
                metric_id, metric_segs, company_id
            )
            if definition:
                definitions.append(definition)

        logger.info(f"Extracted {len(definitions)} metric definitions")
        return definitions

    def _group_segments_by_metric(self, segments: List[SourceSegment]) -> dict:
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

    def _extract_metric_definition(
        self, metric_id: str, segments: List[SourceSegment], company_id: int
    ) -> Optional[MetricDefinition]:
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

        # Extract and normalize text
        definition_text = None
        definition_segment_id = None
        if definition_segments:
            # Use the first definition segment
            seg = definition_segments[0]
            definition_text = self._normalize_definition_text(seg.raw_text)
            definition_segment_id = (
                seg.sequence_index
            )  # Store sequence_index temporarily

        methodology_text = None
        methodology_segment_id = None
        if methodology_segments:
            # Use the first methodology segment
            seg = methodology_segments[0]
            methodology_text = self._normalize_definition_text(seg.raw_text)
            methodology_segment_id = (
                seg.sequence_index
            )  # Store sequence_index temporarily

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
            definition_raw_text=(
                definition_segments[0].raw_text if definition_segments else None
            ),
            methodology_raw_text=(
                methodology_segments[0].raw_text if methodology_segments else None
            ),
            definition_segment_id=definition_segment_id,
            methodology_segment_id=methodology_segment_id,
            alignment_flag=alignment_flag,
        )

        return definition

    def _extract_definition_with_llm(
        self, metric_id: str, segments: List[SourceSegment], company_id: int
    ) -> Optional[MetricDefinition]:
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
                if item["metric_name"] == metric_id or metric_id in item["metric_name"]:
                    # Extract definition text
                    definition_text = item["definition_text"]

                    # Check if it includes calculation methodology
                    includes_calculation = item.get("includes_calculation", False)

                    # Get the quote
                    quote = item.get("quote", "")

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

    def assess_alignment(self, metric_id: str, issuer_definition: Optional[str]) -> str:
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
    segments: List[SourceSegment], company_id: int
) -> List[MetricDefinition]:
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
