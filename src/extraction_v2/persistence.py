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
from datetime import datetime
from typing import TYPE_CHECKING, Any

from src.extraction_v2.models import (
    Cell,
    ChartData,
    Document,
    ImageAsset,
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
        sql = """
            INSERT INTO v2_documents (
                doc_id, filing_id, parse_version,
                segment_count, table_count, image_count, fact_count,
                status, parse_completed_at, extract_completed_at, created_at
            )
            VALUES (
                %(doc_id)s, %(filing_id)s, %(parse_version)s,
                %(segment_count)s, %(table_count)s, %(image_count)s, %(fact_count)s,
                %(status)s, %(parse_completed_at)s, %(extract_completed_at)s, NOW()
            )
            ON CONFLICT (filing_id) DO UPDATE SET
                parse_version = EXCLUDED.parse_version,
                segment_count = EXCLUDED.segment_count,
                table_count = EXCLUDED.table_count,
                image_count = EXCLUDED.image_count,
                fact_count = EXCLUDED.fact_count,
                status = EXCLUDED.status,
                extract_completed_at = EXCLUDED.extract_completed_at,
                updated_at = NOW()
            RETURNING doc_id
        """

        params = {
            "doc_id": document.doc_id,
            "filing_id": filing_id,
            "parse_version": document.parse_version,
            "segment_count": segment_count,
            "table_count": table_count,
            "image_count": image_count,
            "fact_count": fact_count,
            "status": status,
            "parse_completed_at": document.created_at,
            "extract_completed_at": datetime.utcnow(),
        }

        with self._db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                result = cur.fetchone()
                doc_id: str = str(result["doc_id"]) if result else document.doc_id

        logger.debug(f"Upserted document: filing_id={filing_id}, doc_id={doc_id}")
        return doc_id

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

        count = 0
        with self._db.get_connection() as conn:
            with conn.cursor() as cur:
                for segment in segments:
                    params = {
                        "segment_id": segment.segment_id,
                        "doc_id": filing_id,
                        "segment_type": segment.segment_type.value,
                        "segment_text": segment.text,
                        "dom_locator": segment.dom_locator,
                        "section_path": segment.section_path or [],
                        "section_type": segment.section_type.value
                        if segment.section_type
                        else None,
                        "sequence_idx": segment.sequence,
                        "prev_segment_id": segment.prev_id,
                        "next_segment_id": segment.next_id,
                    }
                    cur.execute(sql, params)
                    count += 1

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

        table_count = 0
        cell_count = 0

        with self._db.get_connection() as conn:
            with conn.cursor() as cur:
                for table in tables:
                    # Upsert table
                    table_params = {
                        "table_id": table.table_id,
                        "doc_id": filing_id,
                        "segment_id": table.segment_id or None,
                        "dom_locator": table.dom_locator,
                        "section_path": table.section_path or [],
                        "section_type": table.section_type.value
                        if table.section_type
                        else None,
                        "row_count": table.row_count,
                        "col_count": table.col_count,
                        "header_rows": table.header_rows,
                        "stub_cols": table.stub_cols,
                        "raw_html": None,  # Not stored by default
                    }
                    cur.execute(table_sql, table_params)
                    table_count += 1

                    # Upsert cells
                    for cell in table.cells:
                        cell_params = self._cell_to_params(cell, table.table_id)
                        cur.execute(cell_sql, cell_params)
                        cell_count += 1

        logger.debug(
            f"Upserted {table_count} tables, {cell_count} cells for filing_id={filing_id}"
        )
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

        count = 0
        with self._db.get_connection() as conn:
            with conn.cursor() as cur:
                for image in images:
                    params = {
                        "img_id": image.img_id,
                        "doc_id": filing_id,
                        "segment_id": image.segment_id,
                        "filename": image.filename,
                        "file_path": image.file_path,
                        "width": image.width,
                        "height": image.height,
                        "dom_locator": image.dom_locator,
                        "nearby_text": image.nearby_text,
                        "section_path": image.section_path or [],
                        "section_type": image.section_type.value
                        if image.section_type
                        else None,
                        "classification": image.classification.value,
                        "relevance_score": image.relevance_score,
                        "ocr_text": image.ocr_text,
                        "ocr_table_id": image.ocr_table.table_id
                        if image.ocr_table
                        else None,
                        "chart_type": image.chart_data.chart_type.value
                        if image.chart_data
                        else None,
                        "chart_data": _serialize_chart_data(image.chart_data),
                        "processed": image.processed,
                        "confidence": image.confidence,
                        "requires_manual": image.requires_manual_capture,
                    }
                    cur.execute(sql, params)
                    count += 1

        logger.debug(f"Upserted {count} images for filing_id={filing_id}")
        return count

    def persist_facts(
        self,
        facts: list[MetricFact],
        filing_id: int,
    ) -> int:
        """
        Upsert V2 metric facts.

        Args:
            facts: List of MetricFact models from pipeline
            filing_id: Database filing ID (foreign key)

        Returns:
            Number of facts upserted
        """
        if not facts:
            return 0

        sql = """
            INSERT INTO v2_metric_facts (
                fact_id, doc_id, canonical_metric_id,
                value, value_raw, unit, currency,
                period_type, period_start, period_end,
                scope, scope_detail, cohort_def, customer_type,
                source_type, source_locator, evidence_pack,
                confidence, extraction_method, requires_review, review_reason, review_status,
                alternate_evidence, pipeline_version, created_at
            )
            VALUES (
                %(fact_id)s, %(doc_id)s, %(canonical_metric_id)s,
                %(value)s, %(value_raw)s, %(unit)s, %(currency)s,
                %(period_type)s, %(period_start)s, %(period_end)s,
                %(scope)s, %(scope_detail)s, %(cohort_def)s, %(customer_type)s,
                %(source_type)s, %(source_locator)s, %(evidence_pack)s,
                %(confidence)s, %(extraction_method)s, %(requires_review)s, %(review_reason)s, %(review_status)s,
                %(alternate_evidence)s, %(pipeline_version)s, NOW()
            )
            ON CONFLICT (fact_id) DO UPDATE SET
                canonical_metric_id = EXCLUDED.canonical_metric_id,
                value = EXCLUDED.value,
                value_raw = EXCLUDED.value_raw,
                unit = EXCLUDED.unit,
                currency = EXCLUDED.currency,
                period_type = EXCLUDED.period_type,
                period_start = EXCLUDED.period_start,
                period_end = EXCLUDED.period_end,
                scope = EXCLUDED.scope,
                scope_detail = EXCLUDED.scope_detail,
                cohort_def = EXCLUDED.cohort_def,
                customer_type = EXCLUDED.customer_type,
                source_type = EXCLUDED.source_type,
                source_locator = EXCLUDED.source_locator,
                evidence_pack = EXCLUDED.evidence_pack,
                confidence = EXCLUDED.confidence,
                extraction_method = EXCLUDED.extraction_method,
                requires_review = EXCLUDED.requires_review,
                review_reason = EXCLUDED.review_reason,
                review_status = EXCLUDED.review_status,
                alternate_evidence = EXCLUDED.alternate_evidence,
                pipeline_version = EXCLUDED.pipeline_version,
                updated_at = NOW()
        """

        count = 0
        with self._db.get_connection() as conn:
            with conn.cursor() as cur:
                for fact in facts:
                    params = {
                        "fact_id": fact.fact_id,
                        "doc_id": filing_id,
                        "canonical_metric_id": fact.canonical_metric_id,
                        "value": fact.value,
                        "value_raw": fact.value_raw,
                        "unit": fact.unit.value,
                        "currency": fact.currency,
                        "period_type": fact.period_type.value
                        if fact.period_type
                        else None,
                        "period_start": fact.period_start,
                        "period_end": fact.period_end,
                        "scope": fact.scope.value,
                        "scope_detail": fact.scope_detail,
                        "cohort_def": fact.cohort_def,
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
                        "pipeline_version": fact.pipeline_version,
                    }
                    cur.execute(sql, params)
                    count += 1

        logger.debug(f"Upserted {count} facts for filing_id={filing_id}")
        return count

    def persist_pipeline_result(
        self,
        result: PipelineResult,
        filing_id: int,
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
                with conn.cursor() as cur:
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
                    )

                    # 2. Persist segments
                    seg_count = self._persist_segments_in_tx(
                        cur, result.segments, filing_id
                    )

                    # 3. Persist tables and cells
                    table_count, cell_count = self._persist_tables_in_tx(
                        cur, result.tables, filing_id
                    )

                    # 4. Persist images
                    img_count = self._persist_images_in_tx(
                        cur, result.images, filing_id
                    )

                    # 5. Persist facts
                    fact_count = self._persist_facts_in_tx(
                        cur, result.facts, filing_id
                    )

            logger.info(
                f"Persisted pipeline result for filing_id={filing_id}: "
                f"{seg_count} segments, {table_count} tables, {cell_count} cells, "
                f"{img_count} images, {fact_count} facts"
            )

            return PersistenceResult(
                success=True,
                documents_upserted=doc_count,
                segments_upserted=seg_count,
                tables_upserted=table_count,
                cells_upserted=cell_count,
                images_upserted=img_count,
                facts_upserted=fact_count,
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
    ) -> int:
        """Persist document within an existing transaction."""
        sql = """
            INSERT INTO v2_documents (
                doc_id, filing_id, parse_version,
                segment_count, table_count, image_count, fact_count,
                status, parse_completed_at, extract_completed_at, created_at
            )
            VALUES (
                %(doc_id)s, %(filing_id)s, %(parse_version)s,
                %(segment_count)s, %(table_count)s, %(image_count)s, %(fact_count)s,
                %(status)s, %(parse_completed_at)s, %(extract_completed_at)s, NOW()
            )
            ON CONFLICT (filing_id) DO UPDATE SET
                parse_version = EXCLUDED.parse_version,
                segment_count = EXCLUDED.segment_count,
                table_count = EXCLUDED.table_count,
                image_count = EXCLUDED.image_count,
                fact_count = EXCLUDED.fact_count,
                status = EXCLUDED.status,
                extract_completed_at = EXCLUDED.extract_completed_at,
                updated_at = NOW()
        """

        params = {
            "doc_id": document.doc_id,
            "filing_id": filing_id,
            "parse_version": document.parse_version,
            "segment_count": segment_count,
            "table_count": table_count,
            "image_count": image_count,
            "fact_count": fact_count,
            "status": status,
            "parse_completed_at": document.created_at,
            "extract_completed_at": datetime.utcnow(),
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

        count = 0
        for segment in segments:
            params = {
                "segment_id": segment.segment_id,
                "doc_id": filing_id,
                "segment_type": segment.segment_type.value,
                "segment_text": segment.text,
                "dom_locator": segment.dom_locator,
                "section_path": segment.section_path or [],
                "section_type": segment.section_type.value
                if segment.section_type
                else None,
                "sequence_idx": segment.sequence,
                "prev_segment_id": segment.prev_id,
                "next_segment_id": segment.next_id,
            }
            cur.execute(sql, params)
            count += 1

        return count

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

        table_count = 0
        cell_count = 0

        for table in tables:
            table_params = {
                "table_id": table.table_id,
                "doc_id": filing_id,
                "segment_id": table.segment_id or None,
                "dom_locator": table.dom_locator,
                "section_path": table.section_path or [],
                "section_type": table.section_type.value if table.section_type else None,
                "row_count": table.row_count,
                "col_count": table.col_count,
                "header_rows": table.header_rows,
                "stub_cols": table.stub_cols,
                "raw_html": None,
            }
            cur.execute(table_sql, table_params)
            table_count += 1

            for cell in table.cells:
                cell_params = self._cell_to_params(cell, table.table_id)
                cur.execute(cell_sql, cell_params)
                cell_count += 1

        return table_count, cell_count

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

        count = 0
        for image in images:
            params = {
                "img_id": image.img_id,
                "doc_id": filing_id,
                "segment_id": image.segment_id,
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
                "chart_type": image.chart_data.chart_type.value
                if image.chart_data
                else None,
                "chart_data": _serialize_chart_data(image.chart_data),
                "processed": image.processed,
                "confidence": image.confidence,
                "requires_manual": image.requires_manual_capture,
            }
            cur.execute(sql, params)
            count += 1

        return count

    def _persist_facts_in_tx(
        self,
        cur: Any,
        facts: list[MetricFact],
        filing_id: int,
    ) -> int:
        """Persist facts within an existing transaction."""
        if not facts:
            return 0

        sql = """
            INSERT INTO v2_metric_facts (
                fact_id, doc_id, canonical_metric_id,
                value, value_raw, unit, currency,
                period_type, period_start, period_end,
                scope, scope_detail, cohort_def, customer_type,
                source_type, source_locator, evidence_pack,
                confidence, extraction_method, requires_review, review_reason, review_status,
                alternate_evidence, pipeline_version, created_at
            )
            VALUES (
                %(fact_id)s, %(doc_id)s, %(canonical_metric_id)s,
                %(value)s, %(value_raw)s, %(unit)s, %(currency)s,
                %(period_type)s, %(period_start)s, %(period_end)s,
                %(scope)s, %(scope_detail)s, %(cohort_def)s, %(customer_type)s,
                %(source_type)s, %(source_locator)s, %(evidence_pack)s,
                %(confidence)s, %(extraction_method)s, %(requires_review)s, %(review_reason)s, %(review_status)s,
                %(alternate_evidence)s, %(pipeline_version)s, NOW()
            )
            ON CONFLICT (fact_id) DO UPDATE SET
                canonical_metric_id = EXCLUDED.canonical_metric_id,
                value = EXCLUDED.value,
                value_raw = EXCLUDED.value_raw,
                unit = EXCLUDED.unit,
                currency = EXCLUDED.currency,
                period_type = EXCLUDED.period_type,
                period_start = EXCLUDED.period_start,
                period_end = EXCLUDED.period_end,
                scope = EXCLUDED.scope,
                scope_detail = EXCLUDED.scope_detail,
                cohort_def = EXCLUDED.cohort_def,
                customer_type = EXCLUDED.customer_type,
                source_type = EXCLUDED.source_type,
                source_locator = EXCLUDED.source_locator,
                evidence_pack = EXCLUDED.evidence_pack,
                confidence = EXCLUDED.confidence,
                extraction_method = EXCLUDED.extraction_method,
                requires_review = EXCLUDED.requires_review,
                review_reason = EXCLUDED.review_reason,
                review_status = EXCLUDED.review_status,
                alternate_evidence = EXCLUDED.alternate_evidence,
                pipeline_version = EXCLUDED.pipeline_version,
                updated_at = NOW()
        """

        count = 0
        for fact in facts:
            params = {
                "fact_id": fact.fact_id,
                "doc_id": filing_id,
                "canonical_metric_id": fact.canonical_metric_id,
                "value": fact.value,
                "value_raw": fact.value_raw,
                "unit": fact.unit.value,
                "currency": fact.currency,
                "period_type": fact.period_type.value if fact.period_type else None,
                "period_start": fact.period_start,
                "period_end": fact.period_end,
                "scope": fact.scope.value,
                "scope_detail": fact.scope_detail,
                "cohort_def": fact.cohort_def,
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
                "pipeline_version": fact.pipeline_version,
            }
            cur.execute(sql, params)
            count += 1

        return count
