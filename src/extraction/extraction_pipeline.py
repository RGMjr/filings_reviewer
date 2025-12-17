"""
Extraction Pipeline - End-to-end metric extraction orchestration.

This module orchestrates the complete extraction pipeline:
1. HTML Segmentation
2. Metric Classification
3. Value Extraction
4. Definition Extraction
5. Quality Scoring
6. Database Storage
"""

import logging
from pathlib import Path
from typing import List, Dict, Optional, TYPE_CHECKING
from dataclasses import dataclass

from src.infra.db import DatabaseAdapter
from .html_segmenter import HTMLSegmenter
from .metric_classifier import MetricClassifier
from .segment_enricher import SegmentEnricher, cluster_goldmine_segments
from .value_extractor import ValueExtractor
from .definition_extractor import DefinitionExtractor
from .quality_scorer import QualityScorer
from .models import (
    SourceSegment,
    MetricValue,
    MetricDefinition,
    FilingMetricIncidence,
)

if TYPE_CHECKING:
    from ..llm.openai_client import OpenAIClient

logger = logging.getLogger(__name__)


@dataclass
class ExtractionResult:
    """Result of processing a single filing."""

    filing_id: int
    success: bool
    error: Optional[str] = None
    num_segments: int = 0
    num_values: int = 0
    num_definitions: int = 0
    num_incidences: int = 0


class ExtractionPipeline:
    """
    Orchestrate the complete metric extraction pipeline.

    Pipeline stages:
    1. Segment HTML into source_segments
    2. Classify segments for metric content
    3. Extract numeric values from segments
    4. Extract definitions and methodologies
    5. Compute quality scores and incidence
    6. Write all results to database
    """

    def __init__(
        self, db: DatabaseAdapter, llm_client: Optional["OpenAIClient"] = None
    ):
        """
        Initialize the extraction pipeline.

        Args:
            db: Database adapter
            llm_client: Optional OpenAI client for LLM-enhanced extraction.
                       If provided, extractors will use LLM with rule-based fallback.
                       If not provided, only rule-based extraction will be used.
        """
        self.db = db
        self.llm_client = llm_client
        self.segmenter = HTMLSegmenter()
        self.classifier = MetricClassifier()
        self.enricher = SegmentEnricher()
        self.value_extractor = ValueExtractor(llm_client=llm_client)
        self.definition_extractor = DefinitionExtractor(llm_client=llm_client)
        self.quality_scorer = QualityScorer()

        if llm_client:
            logger.info("✓ Pipeline initialized with LLM-enhanced extraction and enrichment")
        else:
            logger.info("✓ Pipeline initialized with rule-based extraction and enrichment")

    def process_filing(self, filing_id: int) -> ExtractionResult:
        """
        Run full extraction pipeline for a single filing.

        Steps:
            1. Fetch filing metadata from database
            2. Segment HTML
            3. Classify segments
            4. Extract values
            5. Extract definitions
            6. Compute quality scores
            7. Write all to database in a transaction

        Args:
            filing_id: Database filing ID

        Returns:
            ExtractionResult with processing summary
        """
        logger.info(f"Processing filing {filing_id}")

        try:
            # Step 0: Fetch filing metadata
            filing = self._get_filing_metadata(filing_id)
            if not filing:
                return ExtractionResult(
                    filing_id=filing_id,
                    success=False,
                    error="Filing not found in database",
                )

            # Step 1: Segment HTML
            logger.info("  Stage 1: Segmenting HTML")
            segments = self.segmenter.segment_filing(
                filing_id=filing_id, html_path=filing["html_storage_path"]
            )

            if not segments:
                return ExtractionResult(
                    filing_id=filing_id,
                    success=False,
                    error="No segments extracted from HTML",
                )

            # Step 2: Classify segments
            logger.info(f"  Stage 2: Classifying {len(segments)} segments")
            classified_segments = self.classifier.classify_batch(segments)

            # Step 2b: Enrich segments with richness metadata
            logger.info(f"  Stage 2b: Enriching {len(classified_segments)} segments")
            self.enricher.enrich_batch(classified_segments)  # mutates in place

            # Step 2c: Tiered segment selection
            logger.info("  Stage 2c: Selecting segments via tiered prioritization")
            selected_segments = self._select_segments_tiered(classified_segments)

            # Log goldmine statistics
            goldmines = [s for s in selected_segments if (s.richness_score or 0) >= 6.0]
            clusters = cluster_goldmine_segments(goldmines) if goldmines else []
            logger.info(f"  Identified {len(goldmines)} goldmine segments in {len(clusters)} clusters")

            # Step 3: Extract values (from selected segments)
            logger.info(f"  Stage 3: Extracting values from {len(selected_segments)} segments")
            all_values = []
            for seg in selected_segments:
                values = self.value_extractor.extract_from_segment(
                    seg, company_id=filing["company_id"]
                )
                all_values.extend(values)

            # Step 4: Extract definitions (from selected segments)
            logger.info(f"  Stage 4: Extracting definitions from {len(selected_segments)} segments")
            definitions = self.definition_extractor.extract_definitions(
                selected_segments, company_id=filing["company_id"]
            )

            # Step 5: Compute quality scores (based on selected segments)
            logger.info("  Stage 5: Computing quality scores")
            incidences = self.quality_scorer.score_filing(
                filing_id=filing_id,
                company_id=filing["company_id"],
                segments=selected_segments,
                values=all_values,
                definitions=definitions,
            )

            # Step 6: Write to database
            logger.info("  Stage 6: Writing to database")
            self._write_results(
                filing_id, selected_segments, all_values, definitions, incidences
            )

            logger.info(f"✓ Successfully processed filing {filing_id}")
            logger.info(
                f"    Total segments: {len(classified_segments)}, Selected: {len(selected_segments)}, "
                + f"Goldmines: {len(goldmines)}, Values: {len(all_values)}, "
                + f"Definitions: {len(definitions)}, Incidences: {len(incidences)}"
            )

            return ExtractionResult(
                filing_id=filing_id,
                success=True,
                num_segments=len(selected_segments),
                num_values=len(all_values),
                num_definitions=len(definitions),
                num_incidences=len(incidences),
            )

        except (ValueError, KeyError) as e:
            # Data/validation errors - filing data is invalid or missing expected fields
            logger.error(
                f"✗ Data error processing filing {filing_id}: {e}", exc_info=True
            )
            return ExtractionResult(filing_id=filing_id, success=False, error=str(e))

        except (IOError, OSError) as e:
            # File system errors - HTML file not found or unreadable
            logger.error(
                f"✗ File error processing filing {filing_id}: {e}", exc_info=True
            )
            return ExtractionResult(filing_id=filing_id, success=False, error=str(e))

        except Exception as e:
            # Unexpected errors - log with full details for debugging
            logger.critical(
                f"✗ Unexpected error processing filing {filing_id}: "
                f"{type(e).__name__}: {e}",
                exc_info=True,
            )
            return ExtractionResult(filing_id=filing_id, success=False, error=str(e))

    def process_batch(self, filing_ids: List[int]) -> Dict[str, int]:
        """
        Process multiple filings.

        Args:
            filing_ids: List of filing IDs to process

        Returns:
            Statistics dictionary with counts
        """
        logger.info(f"Processing batch of {len(filing_ids)} filings")

        stats = {
            "total": len(filing_ids),
            "success": 0,
            "failed": 0,
            "total_segments": 0,
            "total_values": 0,
            "total_definitions": 0,
            "total_incidences": 0,
        }

        for i, filing_id in enumerate(filing_ids):
            logger.info(f"[{i+1}/{len(filing_ids)}] Processing filing {filing_id}")

            result = self.process_filing(filing_id)

            if result.success:
                stats["success"] += 1
                stats["total_segments"] += result.num_segments
                stats["total_values"] += result.num_values
                stats["total_definitions"] += result.num_definitions
                stats["total_incidences"] += result.num_incidences
            else:
                stats["failed"] += 1
                logger.error(f"  Failed: {result.error}")

        logger.info("")
        logger.info("=" * 80)
        logger.info("Batch Processing Summary")
        logger.info("=" * 80)
        logger.info(f"Total filings: {stats['total']}")
        logger.info(f"Successful: {stats['success']}")
        logger.info(f"Failed: {stats['failed']}")
        logger.info(f"Total segments: {stats['total_segments']}")
        logger.info(f"Total values: {stats['total_values']}")
        logger.info(f"Total definitions: {stats['total_definitions']}")
        logger.info(f"Total incidences: {stats['total_incidences']}")
        logger.info("=" * 80)

        return stats

    def _get_filing_metadata(self, filing_id: int) -> Optional[dict]:
        """Fetch filing metadata from database."""
        result = self.db.query(
            """
            SELECT filing_id, company_id, cik, accession_number, html_storage_path
            FROM filings
            WHERE filing_id = %(filing_id)s
        """,
            {"filing_id": filing_id},
        )

        if not result:
            return None

        filing = result[0]

        # Check if HTML file exists
        if (
            not filing["html_storage_path"]
            or not Path(filing["html_storage_path"]).exists()
        ):
            logger.error(f"HTML file not found: {filing['html_storage_path']}")
            return None

        return filing

    def _select_segments_tiered(
        self, segments: List[SourceSegment]
    ) -> List[SourceSegment]:
        """
        Select segments using tiered prioritization.

        Tiers (processed in order, deduplicated):
        1. High richness (>= 6.0) - up to 30 segments
        2. Medium richness (4.0-6.0) - up to 40 segments
        3. Critical flags (definitions/methodologies) - remainder up to 80 total

        Args:
            segments: Enriched segments with richness_score populated

        Returns:
            Selected segments, deduplicated and sorted by richness
        """
        RICHNESS_THRESHOLD = 6.0
        MEDIUM_THRESHOLD = 4.0
        MAX_HIGH_RICHNESS = 30
        MAX_MEDIUM_RICHNESS = 40
        MAX_TOTAL = 80

        selected_ids: set[int] = set()  # Use object id for deduplication
        result: List[SourceSegment] = []

        # Tier 1: High richness (goldmines)
        high_richness = sorted(
            [s for s in segments if (s.richness_score or 0) >= RICHNESS_THRESHOLD],
            key=lambda s: s.richness_score or 0,
            reverse=True,
        )[:MAX_HIGH_RICHNESS]

        for seg in high_richness:
            if id(seg) not in selected_ids:
                result.append(seg)
                selected_ids.add(id(seg))

        high_count = len(result)

        # Tier 2: Medium richness (supporting context)
        medium_richness = sorted(
            [
                s
                for s in segments
                if MEDIUM_THRESHOLD <= (s.richness_score or 0) < RICHNESS_THRESHOLD
            ],
            key=lambda s: s.richness_score or 0,
            reverse=True,
        )[:MAX_MEDIUM_RICHNESS]

        for seg in medium_richness:
            if id(seg) not in selected_ids:
                result.append(seg)
                selected_ids.add(id(seg))

        medium_count = len(result) - high_count

        # Tier 3: Critical flags (definitions/methodologies)
        critical = [
            s
            for s in segments
            if (s.contains_definition_flag or s.contains_methodology_flag)
            and id(s) not in selected_ids
        ]

        critical_count = 0
        for seg in critical:
            if len(result) >= MAX_TOTAL:
                break
            result.append(seg)
            selected_ids.add(id(seg))
            critical_count += 1

        logger.info(
            f"  Selected: {high_count} high-richness, {medium_count} medium-richness, "
            f"{critical_count} critical (total: {len(result)})"
        )

        return result

    def _write_results(
        self,
        filing_id: int,
        segments: List[SourceSegment],
        values: List[MetricValue],
        definitions: List[MetricDefinition],
        incidences: List[FilingMetricIncidence],
    ):
        """
        Write all extraction results to database in a transaction.

        Args:
            filing_id: Filing ID
            segments: Source segments
            values: Metric values
            definitions: Metric definitions
            incidences: Filing-metric incidences
        """
        # Use database transaction for atomicity
        # If any insert fails, everything rolls back

        cleanup_sql = [
            "DELETE FROM filing_metric_incidence WHERE filing_id = %(filing_id)s",
            "DELETE FROM metric_definitions WHERE filing_id = %(filing_id)s",
            "DELETE FROM metric_values WHERE filing_id = %(filing_id)s",
            "DELETE FROM source_segments WHERE filing_id = %(filing_id)s",
        ]

        with self.db.get_connection() as conn:
            with conn.cursor() as cur:
                # Remove any prior extraction artifacts for this filing so re-runs are idempotent.
                for statement in cleanup_sql:
                    cur.execute(statement, {"filing_id": filing_id})

                # Insert source segments
                segment_id_map: Dict[int, int] = {}
                for seg in segments:
                    cur.execute(
                        """
                        INSERT INTO source_segments (
                            filing_id, segment_type, section_path, section_heading,
                            sequence_index, raw_text, raw_html,
                            candidate_metric_ids,
                            contains_definition_flag,
                            contains_methodology_flag,
                            contains_numeric_disclosure_flag,
                            classifier_confidence,
                            metric_density,
                            distinct_metric_count,
                            contains_temporal_trend,
                            contains_cohort_breakdown,
                            image_count,
                            richness_score
                        ) VALUES (
                            %(filing_id)s, %(segment_type)s, %(section_path)s, %(section_heading)s,
                            %(sequence_index)s, %(raw_text)s, %(raw_html)s,
                            %(candidate_metric_ids)s,
                            %(contains_definition_flag)s,
                            %(contains_methodology_flag)s,
                            %(contains_numeric_disclosure_flag)s,
                            %(classifier_confidence)s,
                            %(metric_density)s,
                            %(distinct_metric_count)s,
                            %(contains_temporal_trend)s,
                            %(contains_cohort_breakdown)s,
                            %(image_count)s,
                            %(richness_score)s
                        )
                        RETURNING source_segment_id
                        """,
                        seg.to_dict(),
                    )
                    result = cur.fetchone()
                    if result:
                        db_id = result["source_segment_id"]
                        segment_id_map[seg.sequence_index] = db_id
                        seg.source_segment_id = db_id

                # Update values with actual segment IDs
                valid_values: List[MetricValue] = []
                for val in values:
                    if val.source_segment_id in segment_id_map:
                        val.source_segment_id = segment_id_map[val.source_segment_id]
                        valid_values.append(val)
                    else:
                        logger.warning(
                            "Skipping metric value for filing %s because segment %s was not persisted",
                            filing_id,
                            val.source_segment_id,
                        )

                # Insert metric values
                for val in valid_values:
                    cur.execute(
                        """
                        INSERT INTO metric_values (
                            filing_id, company_id, metric_id, source_segment_id,
                            source_type, extraction_method,
                            value_numeric, value_text, unit, currency,
                            period_start, period_end, period_type,
                            cohort_type, cohort_bucket_raw, cohort_bucket_normalized,
                            segment_dimension, segment_value,
                            qa_status, qa_notes, alignment_flag
                        ) VALUES (
                            %(filing_id)s, %(company_id)s, %(metric_id)s, %(source_segment_id)s,
                            %(source_type)s, %(extraction_method)s,
                            %(value_numeric)s, %(value_text)s, %(unit)s, %(currency)s,
                            %(period_start)s, %(period_end)s, %(period_type)s,
                            %(cohort_type)s, %(cohort_bucket_raw)s, %(cohort_bucket_normalized)s,
                            %(segment_dimension)s, %(segment_value)s,
                            %(qa_status)s, %(qa_notes)s, %(alignment_flag)s
                        )
                        """,
                        val.to_dict(),
                    )

                # Update definitions with actual segment IDs
                valid_definitions: List[MetricDefinition] = []
                for defn in definitions:
                    if (
                        defn.definition_segment_id is not None
                        and defn.definition_segment_id in segment_id_map
                    ):
                        defn.definition_segment_id = segment_id_map[
                            defn.definition_segment_id
                        ]

                    if (
                        defn.methodology_segment_id is not None
                        and defn.methodology_segment_id in segment_id_map
                    ):
                        defn.methodology_segment_id = segment_id_map[
                            defn.methodology_segment_id
                        ]
                    valid_definitions.append(defn)

                # Insert metric definitions
                for defn in valid_definitions:
                    cur.execute(
                        """
                        INSERT INTO metric_definitions (
                            filing_id, company_id, metric_id,
                            definition_version_in_filing,
                            definition_text_normalized, methodology_text_normalized,
                            definition_raw_text, methodology_raw_text,
                            definition_segment_id, methodology_segment_id,
                            alignment_flag, alignment_notes
                        ) VALUES (
                            %(filing_id)s, %(company_id)s, %(metric_id)s,
                            %(definition_version_in_filing)s,
                            %(definition_text_normalized)s, %(methodology_text_normalized)s,
                            %(definition_raw_text)s, %(methodology_raw_text)s,
                            %(definition_segment_id)s, %(methodology_segment_id)s,
                            %(alignment_flag)s, %(alignment_notes)s
                        )
                        """,
                        defn.to_dict(),
                    )

                # Update incidences with actual segment IDs
                for inc in incidences:
                    if (
                        inc.primary_definition_segment_id is not None
                        and inc.primary_definition_segment_id in segment_id_map
                    ):
                        inc.primary_definition_segment_id = segment_id_map[
                            inc.primary_definition_segment_id
                        ]
                    elif inc.primary_definition_segment_id is not None:
                        # Segment not in map, set to None to avoid FK violation
                        inc.primary_definition_segment_id = None

                    if (
                        inc.primary_methodology_segment_id is not None
                        and inc.primary_methodology_segment_id in segment_id_map
                    ):
                        inc.primary_methodology_segment_id = segment_id_map[
                            inc.primary_methodology_segment_id
                        ]
                    elif inc.primary_methodology_segment_id is not None:
                        # Segment not in map, set to None to avoid FK violation
                        inc.primary_methodology_segment_id = None

                # Insert filing-metric incidences
                for inc in incidences:
                    cur.execute(
                        """
                        INSERT INTO filing_metric_incidence (
                            filing_id, company_id, metric_id,
                            metric_disclosed_flag,
                            num_numeric_segments, num_definition_segments, num_methodology_segments,
                            primary_definition_segment_id, primary_methodology_segment_id,
                            quality_overall_score, quality_definition_score,
                            quality_methodology_score, quality_completeness_score,
                            quality_comparability_score,
                            alignment_flag, quality_notes,
                            has_cohort_breakdown_flag, has_tenure_breakdown_flag,
                            has_acquisition_cohort_flag
                        ) VALUES (
                            %(filing_id)s, %(company_id)s, %(metric_id)s,
                            %(metric_disclosed_flag)s,
                            %(num_numeric_segments)s, %(num_definition_segments)s, %(num_methodology_segments)s,
                            %(primary_definition_segment_id)s, %(primary_methodology_segment_id)s,
                            %(quality_overall_score)s, %(quality_definition_score)s,
                            %(quality_methodology_score)s, %(quality_completeness_score)s,
                            %(quality_comparability_score)s,
                            %(alignment_flag)s, %(quality_notes)s,
                            %(has_cohort_breakdown_flag)s, %(has_tenure_breakdown_flag)s,
                            %(has_acquisition_cohort_flag)s
                        )
                        """,
                        inc.to_dict(),
                    )

        logger.info(f"    Inserted {len(segments)} source segments")
        logger.info(f"    Inserted {len(valid_values)} metric values")
        logger.info(f"    Inserted {len(valid_definitions)} metric definitions")
        logger.info(f"    Inserted {len(incidences)} filing-metric incidences")
