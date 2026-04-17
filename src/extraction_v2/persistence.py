"""
V2 Extraction Pipeline Persistence Layer.

Provides database persistence for V2 extraction results:
- Documents (v2_documents)
- Segments (v2_segments)
- Tables and Cells (v2_tables, v2_table_cells)
- Image Assets (v2_image_assets)
- Metric Facts (v2_metric_facts)

All operations are idempotent (safe to re-run).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Any

from src.extraction_v2.models import (
    Cell,
    ChartData,
    Document,
    ImageAsset,
    MetricDefinition,
    MetricFact,
    Segment,
    Table,
)

if TYPE_CHECKING:
    from src.extraction_v2.pipeline import PipelineResult
    from src.infra.db import DatabaseAdapter

logger = logging.getLogger(__name__)


@dataclass
class PersistenceResult:
    """Result from a persistence operation."""

    success: bool
    documents_upserted: int = 0
    segments_upserted: int = 0
    tables_upserted: int = 0
    cells_upserted: int = 0
    images_upserted: int = 0
    facts_upserted: int = 0
    definitions_upserted: int = 0
    errors: list[str] | None = None

    @property
    def total_upserted(self) -> int:
        """Total number of records upserted."""
        return (
            self.documents_upserted
            + self.segments_upserted
            + self.tables_upserted
            + self.cells_upserted
            + self.images_upserted
            + self.facts_upserted
            + self.definitions_upserted
        )


def _serialize_chart_data(chart_data: ChartData | None) -> str | None:
    """Serialize ChartData to JSON string for JSONB storage."""
    if chart_data is None:
        return None

    return json.dumps(
        {
            "chart_type": chart_data.chart_type.value,
            "title": chart_data.title,
            "x_axis_label": chart_data.x_axis_label,
            "y_axis_label": chart_data.y_axis_label,
            "series": [
                {
                    "name": s.name,
                    "points": [
                        {
                            "x": p.x,
                            "y": p.y,
                            "label": p.label,
                            "bbox": p.bbox.to_dict() if p.bbox else None,
                        }
                        for p in s.points
                    ],
                }
                for s in chart_data.series
            ],
            "annotations": [
                {
                    "text": a.text,
                    "value": a.value,
                    "unit": a.unit,
                    "category": a.category,
                    "period": a.period,
                }
                for a in chart_data.annotations
            ],
        }
    )


class V2PersistenceAdapter:
    """
    Persistence adapter for V2 extraction pipeline results.

    Provides upsert operations for all V2 tables with JSONB serialization
    and transaction support.
    """

    def __init__(self, db: DatabaseAdapter) -> None:
        """
        Initialize the persistence adapter.

        Args:
            db: V1 DatabaseAdapter for connection management
        """
        self._db = db

    def persist_document(
        self,
        document: Document,
        filing_id: int,
        segment_count: int = 0,
        table_count: int = 0,
        image_count: int = 0,
        fact_count: int = 0,
        status: str = "complete",
    ) -> str:
        """
        Upsert a V2 document record.

        Args:
            document: Document model from pipeline
            filing_id: Database filing ID (foreign key)
            segment_count: Number of segments extracted
            table_count: Number of tables reconstructed
            image_count: Number of images processed
            fact_count: Number of facts extracted
            status: Processing status

        Returns:
            The doc_id (UUID) of the upserted document
        """
        with self._db.transaction() as conn:
            with conn.cursor() as cur:
                self._persist_document_in_tx(
                    cur,
                    document,
                    filing_id,
                    segment_count,
                    table_count,
                    image_count,
                    fact_count,
                    status,
                )
        logger.debug(f"Upserted document: filing_id={filing_id}, doc_id={document.doc_id}")
        return document.doc_id

    def persist_segments(
        self,
        segments: list[Segment],
        filing_id: int,
    ) -> int:
        """
        Batch upsert V2 segments.

        Args:
            segments: List of Segment models from pipeline
            filing_id: Database filing ID (foreign key)

        Returns:
            Number of segments upserted
        """
        with self._db.transaction() as conn:
            with conn.cursor() as cur:
                count = self._persist_segments_in_tx(cur, segments, filing_id)
        logger.debug(f"Upserted {count} segments for filing_id={filing_id}")
        return count

    def persist_tables(
        self,
        tables: list[Table],
        filing_id: int,
    ) -> tuple[int, int]:
        """
        Upsert V2 tables and their cells.

        Args:
            tables: List of Table models from pipeline
            filing_id: Database filing ID (foreign key)

        Returns:
            Tuple of (tables_upserted, cells_upserted)
        """
        with self._db.transaction() as conn:
            with conn.cursor() as cur:
                table_count, cell_count = self._persist_tables_in_tx(cur, tables, filing_id)
        logger.debug(f"Upserted {table_count} tables, {cell_count} cells for filing_id={filing_id}")
        return table_count, cell_count

    def _cell_to_params(self, cell: Cell, table_id: str) -> dict[str, Any]:
        """Convert Cell model to database parameters."""
        return {
            "table_id": table_id,
            "row_idx": cell.row,
            "col_idx": cell.col,
            "cell_text": cell.text,
            "is_header": cell.is_header,
            "is_stub": cell.is_stub,
            "header_path": cell.header_path or [],
            "stub_path": cell.stub_path or [],
            "rowspan": cell.rowspan,
            "colspan": cell.colspan,
            "dom_locator": cell.dom_locator,
        }

    def persist_images(
        self,
        images: list[ImageAsset],
        filing_id: int,
    ) -> int:
        """
        Upsert V2 image assets.

        Args:
            images: List of ImageAsset models from pipeline
            filing_id: Database filing ID (foreign key)

        Returns:
            Number of images upserted
        """
        with self._db.transaction() as conn:
            with conn.cursor() as cur:
                count = self._persist_images_in_tx(cur, images, filing_id)
        logger.debug(f"Upserted {count} images for filing_id={filing_id}")
        return count

    def persist_facts(
        self,
        facts: list[MetricFact],
        filing_id: int,
    ) -> int:
        """
        Upsert V2 metric facts using identity-based conflict resolution.

        Uses the identity tuple (doc_id, canonical_metric_id, period, unit,
        scope, cohort_def, customer_type) for cross-run deduplication.
        Falls back to fact_id-based conflict for backwards compatibility.

        Args:
            facts: List of MetricFact models from pipeline
            filing_id: Database filing ID (foreign key)

        Returns:
            Number of facts upserted
        """
        with self._db.transaction() as conn:
            with conn.cursor() as cur:
                count = self._persist_facts_in_tx(cur, facts, filing_id)
        logger.debug(f"Upserted {count} facts for filing_id={filing_id}")
        return count

    def persist_pipeline_result(
        self,
        result: PipelineResult,
        filing_id: int,
        document_type: str = "sec_filing",
        ticker: str | None = None,
        document_date: date | None = None,
        transcript_source: str | None = None,
    ) -> PersistenceResult:
        """
        Persist a complete pipeline result in a single transaction.

        Args:
            result: PipelineResult from V2 pipeline execution
            filing_id: Database filing ID (foreign key)

        Returns:
            PersistenceResult with counts and any errors
        """
        errors: list[str] = []

        try:
            with self._db.transaction() as conn:
                with conn.pipeline(), conn.cursor() as cur:
                    # 1. Persist document
                    doc_count = self._persist_document_in_tx(
                        cur,
                        result.document,
                        filing_id,
                        len(result.segments),
                        len(result.tables),
                        len(result.images),
                        len(result.facts),
                        "complete" if result.success else "failed",
                        error_message=result.error_message,
                        document_type=document_type,
                        ticker=ticker,
                        document_date=document_date,
                        transcript_source=transcript_source,
                    )

                    # 2. Persist segments
                    seg_count = self._persist_segments_in_tx(cur, result.segments, filing_id)

                    # 3. Persist tables and cells
                    table_count, cell_count = self._persist_tables_in_tx(
                        cur, result.tables, filing_id
                    )

                    # 4. Persist images
                    img_count = self._persist_images_in_tx(cur, result.images, filing_id)

                    # 5. Persist facts
                    fact_count = self._persist_facts_in_tx(cur, result.facts, filing_id)

                    # 6. Persist definitions
                    def_count = self._persist_definitions_in_tx(cur, result.definitions, filing_id)

            logger.info(
                f"Persisted pipeline result for filing_id={filing_id}: "
                f"{seg_count} segments, {table_count} tables, {cell_count} cells, "
                f"{img_count} images, {fact_count} facts, {def_count} definitions"
            )

            return PersistenceResult(
                success=True,
                documents_upserted=doc_count,
                segments_upserted=seg_count,
                tables_upserted=table_count,
                cells_upserted=cell_count,
                images_upserted=img_count,
                facts_upserted=fact_count,
                definitions_upserted=def_count,
            )

        except Exception as e:
            logger.exception(f"Failed to persist pipeline result: {e}")
            errors.append(str(e))
            return PersistenceResult(success=False, errors=errors)

    def _persist_document_in_tx(
        self,
        cur: Any,
        document: Document,
        filing_id: int,
        segment_count: int,
        table_count: int,
        image_count: int,
        fact_count: int,
        status: str,
        error_message: str | None = None,
        document_type: str = "sec_filing",
        ticker: str | None = None,
        document_date: date | None = None,
        transcript_source: str | None = None,
    ) -> int:
        """Persist document within an existing transaction."""
        sql = """
            INSERT INTO v2_documents (
                filing_id, parse_version,
                segment_count, table_count, image_count, fact_count,
                status, error_message, parse_completed_at, extract_completed_at, created_at,
                document_type, ticker, document_date, transcript_source
            )
            VALUES (
                %(filing_id)s, %(parse_version)s,
                %(segment_count)s, %(table_count)s, %(image_count)s, %(fact_count)s,
                %(status)s, %(error_message)s, %(parse_completed_at)s, %(extract_completed_at)s, NOW(),
                %(document_type)s, %(ticker)s, %(document_date)s, %(transcript_source)s
            )
            ON CONFLICT (filing_id) DO UPDATE SET
                parse_version = EXCLUDED.parse_version,
                segment_count = EXCLUDED.segment_count,
                table_count = EXCLUDED.table_count,
                image_count = EXCLUDED.image_count,
                fact_count = EXCLUDED.fact_count,
                status = EXCLUDED.status,
                error_message = EXCLUDED.error_message,
                extract_completed_at = EXCLUDED.extract_completed_at,
                document_type = EXCLUDED.document_type,
                ticker = EXCLUDED.ticker,
                document_date = EXCLUDED.document_date,
                transcript_source = EXCLUDED.transcript_source,
                updated_at = NOW()
        """

        params = {
            "filing_id": filing_id,
            "parse_version": document.parse_version,
            "segment_count": segment_count,
            "table_count": table_count,
            "image_count": image_count,
            "fact_count": fact_count,
            "status": status,
            "error_message": error_message,
            "parse_completed_at": document.created_at,
            "extract_completed_at": datetime.now(UTC),
            "document_type": document_type,
            "ticker": ticker,
            "document_date": document_date,
            "transcript_source": transcript_source,
        }

        cur.execute(sql, params)
        return 1

    def _persist_segments_in_tx(
        self,
        cur: Any,
        segments: list[Segment],
        filing_id: int,
    ) -> int:
        """Persist segments within an existing transaction."""
        if not segments:
            return 0

        sql = """
            INSERT INTO v2_segments (
                segment_id, doc_id, segment_type, segment_text,
                dom_locator, section_path, section_type, sequence_idx,
                prev_segment_id, next_segment_id, created_at
            )
            VALUES (
                %(segment_id)s, %(doc_id)s, %(segment_type)s, %(segment_text)s,
                %(dom_locator)s, %(section_path)s, %(section_type)s, %(sequence_idx)s,
                %(prev_segment_id)s, %(next_segment_id)s, NOW()
            )
            ON CONFLICT (segment_id) DO UPDATE SET
                segment_type = EXCLUDED.segment_type,
                segment_text = EXCLUDED.segment_text,
                dom_locator = EXCLUDED.dom_locator,
                section_path = EXCLUDED.section_path,
                section_type = EXCLUDED.section_type,
                sequence_idx = EXCLUDED.sequence_idx,
                prev_segment_id = EXCLUDED.prev_segment_id,
                next_segment_id = EXCLUDED.next_segment_id
        """

        params_list = [
            {
                "segment_id": segment.segment_id,
                "doc_id": filing_id,
                "segment_type": segment.segment_type.value,
                "segment_text": segment.text,
                "dom_locator": segment.dom_locator,
                "section_path": segment.section_path or [],
                "section_type": segment.section_type.value if segment.section_type else None,
                "sequence_idx": segment.sequence,
                "prev_segment_id": segment.prev_id,
                "next_segment_id": segment.next_id,
            }
            for segment in segments
        ]
        cur.executemany(sql, params_list)
        return len(params_list)

    def _persist_tables_in_tx(
        self,
        cur: Any,
        tables: list[Table],
        filing_id: int,
    ) -> tuple[int, int]:
        """Persist tables and cells within an existing transaction."""
        if not tables:
            return 0, 0

        table_sql = """
            INSERT INTO v2_tables (
                table_id, doc_id, segment_id, dom_locator,
                section_path, section_type,
                row_count, col_count, header_rows, stub_cols,
                raw_html, created_at
            )
            VALUES (
                %(table_id)s, %(doc_id)s, %(segment_id)s, %(dom_locator)s,
                %(section_path)s, %(section_type)s,
                %(row_count)s, %(col_count)s, %(header_rows)s, %(stub_cols)s,
                %(raw_html)s, NOW()
            )
            ON CONFLICT (table_id) DO UPDATE SET
                segment_id = EXCLUDED.segment_id,
                dom_locator = EXCLUDED.dom_locator,
                section_path = EXCLUDED.section_path,
                section_type = EXCLUDED.section_type,
                row_count = EXCLUDED.row_count,
                col_count = EXCLUDED.col_count,
                header_rows = EXCLUDED.header_rows,
                stub_cols = EXCLUDED.stub_cols,
                raw_html = EXCLUDED.raw_html
        """

        cell_sql = """
            INSERT INTO v2_table_cells (
                cell_id, table_id, row_idx, col_idx, cell_text,
                is_header, is_stub, header_path, stub_path,
                rowspan, colspan, dom_locator
            )
            VALUES (
                gen_random_uuid(), %(table_id)s, %(row_idx)s, %(col_idx)s, %(cell_text)s,
                %(is_header)s, %(is_stub)s, %(header_path)s, %(stub_path)s,
                %(rowspan)s, %(colspan)s, %(dom_locator)s
            )
            ON CONFLICT (table_id, row_idx, col_idx) DO UPDATE SET
                cell_text = EXCLUDED.cell_text,
                is_header = EXCLUDED.is_header,
                is_stub = EXCLUDED.is_stub,
                header_path = EXCLUDED.header_path,
                stub_path = EXCLUDED.stub_path,
                rowspan = EXCLUDED.rowspan,
                colspan = EXCLUDED.colspan,
                dom_locator = EXCLUDED.dom_locator
        """

        table_params_list = [
            {
                "table_id": table.table_id,
                "doc_id": filing_id,
                "segment_id": None,  # v2_tables.segment_id FKs to V1 source_segments; not used in V2
                "dom_locator": table.dom_locator,
                "section_path": table.section_path or [],
                "section_type": table.section_type.value if table.section_type else None,
                "row_count": table.row_count,
                "col_count": table.col_count,
                "header_rows": table.header_rows,
                "stub_cols": table.stub_cols,
                "raw_html": None,
            }
            for table in tables
        ]
        cell_params_list = [
            self._cell_to_params(cell, table.table_id)
            for table in tables
            for cell in table.cells
        ]
        cur.executemany(table_sql, table_params_list)
        cur.executemany(cell_sql, cell_params_list)
        return len(table_params_list), len(cell_params_list)

    def _persist_images_in_tx(
        self,
        cur: Any,
        images: list[ImageAsset],
        filing_id: int,
    ) -> int:
        """Persist images within an existing transaction."""
        if not images:
            return 0

        sql = """
            INSERT INTO v2_image_assets (
                img_id, doc_id, segment_id, filename, file_path,
                width, height, dom_locator, nearby_text,
                section_path, section_type,
                classification, relevance_score,
                ocr_text, ocr_table_id, chart_type, chart_data,
                processed, confidence, requires_manual, created_at
            )
            VALUES (
                %(img_id)s, %(doc_id)s, %(segment_id)s, %(filename)s, %(file_path)s,
                %(width)s, %(height)s, %(dom_locator)s, %(nearby_text)s,
                %(section_path)s, %(section_type)s,
                %(classification)s, %(relevance_score)s,
                %(ocr_text)s, %(ocr_table_id)s, %(chart_type)s, %(chart_data)s,
                %(processed)s, %(confidence)s, %(requires_manual)s, NOW()
            )
            ON CONFLICT (img_id) DO UPDATE SET
                segment_id = EXCLUDED.segment_id,
                filename = EXCLUDED.filename,
                file_path = EXCLUDED.file_path,
                width = EXCLUDED.width,
                height = EXCLUDED.height,
                dom_locator = EXCLUDED.dom_locator,
                nearby_text = EXCLUDED.nearby_text,
                section_path = EXCLUDED.section_path,
                section_type = EXCLUDED.section_type,
                classification = EXCLUDED.classification,
                relevance_score = EXCLUDED.relevance_score,
                ocr_text = EXCLUDED.ocr_text,
                ocr_table_id = EXCLUDED.ocr_table_id,
                chart_type = EXCLUDED.chart_type,
                chart_data = EXCLUDED.chart_data,
                processed = EXCLUDED.processed,
                confidence = EXCLUDED.confidence,
                requires_manual = EXCLUDED.requires_manual
        """

        params_list = [
            {
                "img_id": image.img_id,
                "doc_id": filing_id,
                "segment_id": None,  # v2_image_assets.segment_id FKs to V1 source_segments; not used in V2
                "filename": image.filename,
                "file_path": image.file_path,
                "width": image.width,
                "height": image.height,
                "dom_locator": image.dom_locator,
                "nearby_text": image.nearby_text,
                "section_path": image.section_path or [],
                "section_type": image.section_type.value if image.section_type else None,
                "classification": image.classification.value,
                "relevance_score": image.relevance_score,
                "ocr_text": image.ocr_text,
                "ocr_table_id": image.ocr_table.table_id if image.ocr_table else None,
                "chart_type": image.chart_data.chart_type.value if image.chart_data else None,
                "chart_data": _serialize_chart_data(image.chart_data),
                "processed": image.processed,
                "confidence": image.confidence,
                "requires_manual": image.requires_manual_capture,
            }
            for image in images
        ]
        cur.executemany(sql, params_list)
        return len(params_list)

    def _fact_to_params(self, fact: MetricFact, filing_id: int) -> dict[str, Any]:
        """Convert MetricFact to database parameters."""
        return {
            "fact_id": fact.fact_id,
            "doc_id": filing_id,
            "canonical_metric_id": fact.canonical_metric_id,
            "value": fact.value,
            "value_raw": fact.value_raw,
            "unit": fact.unit.value,
            "currency": fact.currency or ("USD" if fact.unit.value == "currency" else None),
            "period_type": fact.period_type.value if fact.period_type else None,
            "period_start": fact.period_start,
            "period_end": fact.period_end,
            "scope": fact.scope.value,
            "scope_detail": fact.scope_detail,
            "cohort_def": fact.cohort_def,
            "cohort_type": fact.cohort_type,
            "customer_type": fact.customer_type,
            "source_type": fact.source_type.value,
            "source_locator": json.dumps(fact.source_locator.to_dict()),
            "evidence_pack": json.dumps(fact.evidence_pack.to_dict()),
            "confidence": fact.confidence,
            "extraction_method": fact.extraction_method.value,
            "requires_review": fact.requires_review,
            "review_reason": fact.review_reason,
            "review_status": fact.review_status.value,
            "alternate_evidence": fact.alternate_evidence or [],
            "primary_fact_id": None,  # Populated for alternate facts
            "pipeline_version": fact.pipeline_version,
            "cross_source_confirmed": fact.cross_source_confirmed,
            "confirming_source_types": fact.confirming_source_types or [],
        }

    def _persist_facts_in_tx(
        self,
        cur: Any,
        facts: list[MetricFact],
        filing_id: int,
    ) -> int:
        """Persist facts within an existing transaction using delete-then-insert."""
        if not facts:
            return 0

        # Delete existing facts for this filing before inserting fresh results.
        # This is idempotent and handles re-runs correctly without requiring a
        # complex unique index across nullable expression columns.
        cur.execute(
            "DELETE FROM v2_metric_facts WHERE doc_id = %(filing_id)s", {"filing_id": filing_id}
        )

        sql = """
            INSERT INTO v2_metric_facts (
                fact_id, doc_id, canonical_metric_id,
                value, value_raw, unit, currency,
                period_type, period_start, period_end,
                scope, scope_detail, cohort_def, cohort_type, customer_type,
                source_type, source_locator, evidence_pack,
                confidence, extraction_method, requires_review, review_reason, review_status,
                alternate_evidence, primary_fact_id, pipeline_version, created_at,
                cross_source_confirmed, confirming_source_types
            )
            VALUES (
                %(fact_id)s, %(doc_id)s, %(canonical_metric_id)s,
                %(value)s, %(value_raw)s, %(unit)s, %(currency)s,
                %(period_type)s, %(period_start)s, %(period_end)s,
                %(scope)s, %(scope_detail)s, %(cohort_def)s, %(cohort_type)s, %(customer_type)s,
                %(source_type)s, %(source_locator)s, %(evidence_pack)s,
                %(confidence)s, %(extraction_method)s, %(requires_review)s, %(review_reason)s, %(review_status)s,
                %(alternate_evidence)s, %(primary_fact_id)s, %(pipeline_version)s, NOW(),
                %(cross_source_confirmed)s, %(confirming_source_types)s
            )
        """

        params_list = [self._fact_to_params(fact, filing_id) for fact in facts]

        # Deduplicate by identity key to avoid unique constraint violations when
        # the pipeline produces two facts with the same (metric, period, unit,
        # scope, cohort) tuple. Keep the highest-confidence occurrence.
        seen: dict[tuple, dict] = {}
        for p in params_list:
            key = (
                p["doc_id"],
                p["canonical_metric_id"],
                p["period_start"],
                p["period_end"],
                p["unit"],
                p["scope"],
                p["cohort_def"] or "",
                p["customer_type"] or "",
            )
            existing = seen.get(key)
            if existing is None or p["confidence"] > existing["confidence"]:
                seen[key] = p
        deduped = list(seen.values())

        cur.executemany(sql, deduped)
        return len(deduped)

    def persist_definitions(
        self,
        definitions: list[MetricDefinition],
        filing_id: int,
    ) -> int:
        """
        Upsert V2 metric definitions.

        Args:
            definitions: List of MetricDefinition models from pipeline
            filing_id: Database filing ID (foreign key)

        Returns:
            Number of definitions upserted
        """
        if not definitions:
            return 0
        with self._db.transaction() as conn:
            with conn.cursor() as cur:
                count = self._persist_definitions_in_tx(cur, definitions, filing_id)
        logger.debug(f"Upserted {count} definitions for filing_id={filing_id}")
        return count

    def persist_quality_scores(
        self,
        scores: list[Any],
        filing_id: int,
    ) -> int:
        """
        Persist quality scores to V1's filing_metric_incidence table.

        Uses DELETE + INSERT for idempotency (matches V1 pattern).

        Args:
            scores: List of FilingMetricIncidence objects from V2QualityScorer
            filing_id: Database filing ID

        Returns:
            Number of rows inserted
        """
        if not scores:
            return 0

        with self._db.transaction() as conn:
            with conn.cursor() as cur:
                # Delete existing scores for this filing
                cur.execute(
                    "DELETE FROM filing_metric_incidence WHERE filing_id = %(filing_id)s",
                    {"filing_id": filing_id},
                )

                # Insert new scores
                sql = """
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
                    )
                    VALUES (
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
                """
                params_list = [score.to_dict() for score in scores]
                cur.executemany(sql, params_list)
                count = len(params_list)

        logger.debug(f"Inserted {count} quality scores for filing_id={filing_id}")
        return count

    def _persist_definitions_in_tx(
        self,
        cur: Any,
        definitions: list[MetricDefinition],
        filing_id: int,
    ) -> int:
        """Persist definitions within an existing transaction."""
        if not definitions:
            return 0

        sql = """
            INSERT INTO v2_metric_definitions (
                definition_id, doc_id, canonical_metric_id,
                definition_text, definition_text_normalized,
                methodology_text, methodology_text_normalized,
                definition_segment_id, methodology_segment_id,
                alignment_flag, created_at
            )
            VALUES (
                %(definition_id)s, %(doc_id)s, %(canonical_metric_id)s,
                %(definition_text)s, %(definition_text_normalized)s,
                %(methodology_text)s, %(methodology_text_normalized)s,
                %(definition_segment_id)s, %(methodology_segment_id)s,
                %(alignment_flag)s, NOW()
            )
            ON CONFLICT (doc_id, canonical_metric_id) DO UPDATE SET
                definition_text = EXCLUDED.definition_text,
                definition_text_normalized = EXCLUDED.definition_text_normalized,
                methodology_text = EXCLUDED.methodology_text,
                methodology_text_normalized = EXCLUDED.methodology_text_normalized,
                definition_segment_id = EXCLUDED.definition_segment_id,
                methodology_segment_id = EXCLUDED.methodology_segment_id,
                alignment_flag = EXCLUDED.alignment_flag,
                updated_at = NOW()
        """
        params_list = [
            {
                "definition_id": defn.definition_id,
                "doc_id": filing_id,
                "canonical_metric_id": defn.canonical_metric_id,
                "definition_text": defn.definition_text,
                "definition_text_normalized": defn.definition_text_normalized,
                "methodology_text": defn.methodology_text,
                "methodology_text_normalized": defn.methodology_text_normalized,
                "definition_segment_id": defn.definition_segment_id,
                "methodology_segment_id": defn.methodology_segment_id,
                "alignment_flag": defn.alignment_flag,
            }
            for defn in definitions
        ]
        cur.executemany(sql, params_list)
        return len(params_list)
