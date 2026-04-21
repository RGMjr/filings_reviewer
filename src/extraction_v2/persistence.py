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

from src.extraction_v2.exceptions import ReviewedFilingError
from src.extraction_v2.models import (
    Cell,
    ChartData,
    Document,
    ImageAsset,
    MetricDefinition,
    MetricFact,
    Segment,
    SourceType,
    Table,
)
from src.shared.keyword_config import match_nearby_text

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
                count, _img_id_map = self._persist_images_in_tx(cur, images, filing_id)
        logger.debug(f"Upserted {count} images for filing_id={filing_id}")
        return count

    def persist_facts(
        self,
        facts: list[MetricFact],
        filing_id: int,
        *,
        force: bool = False,
        chart_only: bool = False,
    ) -> int:
        """
        Upsert V2 metric facts using identity-based conflict resolution.

        Uses the identity tuple (doc_id, canonical_metric_id, period, unit,
        scope, cohort_def, customer_type) for cross-run deduplication.
        Falls back to fact_id-based conflict for backwards compatibility.

        Args:
            facts: List of MetricFact models from pipeline
            filing_id: Database filing ID (foreign key)
            force: If True, proceed even when the filing has existing human
                review decisions (which will be CASCADE-deleted). Default
                False raises ``ReviewedFilingError`` in that case.
            chart_only: If True, restrict the operation to ``source_type='chart'``
                facts. Inbound ``facts`` are filtered to chart facts only,
                the DELETE is scoped so text facts survive, and the guard
                counts decisions on chart facts only. Used for Issue #35
                backfills.

        Returns:
            Number of facts upserted
        """
        with self._db.transaction() as conn:
            with conn.cursor() as cur:
                count = self._persist_facts_in_tx(
                    cur, facts, filing_id, force=force, chart_only=chart_only
                )
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
        *,
        force: bool = False,
        chart_only: bool = False,
    ) -> PersistenceResult:
        """
        Persist a complete pipeline result in a single transaction.

        Args:
            result: PipelineResult from V2 pipeline execution
            filing_id: Database filing ID (foreign key)
            force: If True, proceed even when the filing has existing human
                review decisions (which will be CASCADE-deleted). Default
                False raises ``ReviewedFilingError`` in that case.
            chart_only: If True, only chart-sourced facts are written.
                The fact-persistence DELETE is scoped to chart facts so
                text facts and their reviewer decisions are preserved.
                Other persistence steps (documents, segments, tables,
                images, definitions) run normally — they are idempotent
                via ON CONFLICT and do not touch reviewer decisions.
                Used for Issue #35 chart-fact backfills.

        Returns:
            PersistenceResult with counts and any errors
        """
        errors: list[str] = []

        try:
            with self._db.transaction() as conn:
                with conn.cursor() as cur:
                    # Bulk inserts (document, segments, tables/cells) run under
                    # pipeline mode for batched round-trips. Image persistence
                    # uses RETURNING to harvest the stable DB-side img_id on
                    # conflict, which psycopg3 can't interleave with pending
                    # pipeline results — so it runs after the pipeline exits.
                    with conn.pipeline():
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

                    # 4. Persist images. img_id_map captures cases where an
                    # existing DB row's img_id was preserved on conflict —
                    # fresh in-memory ImageAsset.img_id values (random uuid4
                    # per run) differ from the stable DB value, so we must
                    # remap before persisting facts.
                    img_count, img_id_map = self._persist_images_in_tx(
                        cur, result.images, filing_id, force=force
                    )

                    if img_id_map:
                        for image in result.images:
                            if image.img_id in img_id_map:
                                image.img_id = img_id_map[image.img_id]
                        for fact in result.facts:
                            locator = fact.source_locator
                            if locator is not None and locator.img_id in img_id_map:
                                locator.img_id = img_id_map[locator.img_id]

                    # 5. Persist facts
                    fact_count = self._persist_facts_in_tx(
                        cur, result.facts, filing_id, force=force, chart_only=chart_only
                    )

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

        except ReviewedFilingError:
            # Guard must surface to the caller so CLIs can distinguish
            # "reviewed filing, needs --force-reextract" from generic failure.
            raise
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
            self._cell_to_params(cell, table.table_id) for table in tables for cell in table.cells
        ]
        cur.executemany(table_sql, table_params_list)
        cur.executemany(cell_sql, cell_params_list)
        return len(table_params_list), len(cell_params_list)

    # Classifications the review UI renders; see
    # get_image_review_candidates_for_filing_v2 in src/infra/db.py.
    _VISIBLE_IMAGE_CLASSIFICATIONS = frozenset({"chart", "table_image", "unknown"})
    # Classifications the UI filters out (UI predicate:
    # classification NOT IN ('decorative', 'logo', 'signature')).
    _HIDDEN_IMAGE_CLASSIFICATIONS = frozenset({"decorative", "logo", "signature"})

    def _persist_images_in_tx(
        self,
        cur: Any,
        images: list[ImageAsset],
        filing_id: int,
        *,
        force: bool = False,
    ) -> tuple[int, dict[str, str]]:
        """Persist images within an existing transaction.

        Returns ``(count, img_id_map)`` where ``img_id_map`` maps each in-memory
        ``ImageAsset.img_id`` whose row already existed in the DB to the stable
        ``img_id`` of the existing row. Entries are only present for rows
        resolved via ON CONFLICT — first-time inserts are omitted.

        Guards against silently hiding human review decisions: if any incoming
        image would re-classify a previously-decided image from a visible
        classification (chart/table_image/unknown) into a hidden one
        (decorative/logo/signature), raises ``ReviewedFilingError`` unless
        ``force=True``. Unlike the fact guard, this does not delete anything —
        the upsert preserves ``img_id`` and the decision row survives, but the
        UI filter would drop the asset from the review queue.
        """
        if not images:
            return 0, {}

        # Guard: refuse to re-classify decided images into hidden set without
        # explicit opt-in. Check runs before the upsert loop so the transaction
        # aborts cleanly before any write.
        incoming_hidden_filenames = [
            image.filename
            for image in images
            if image.classification.value in self._HIDDEN_IMAGE_CLASSIFICATIONS and image.filename
        ]
        if incoming_hidden_filenames:
            cur.execute(
                """
                SELECT v.filename, v.classification
                  FROM v2_image_assets v
                  JOIN v2_image_review_decisions rd ON rd.img_id = v.img_id
                 WHERE v.doc_id = %(filing_id)s
                   AND v.filename = ANY(%(filenames)s)
                """,
                {"filing_id": filing_id, "filenames": incoming_hidden_filenames},
            )
            existing_decided: dict[str, str] = {}
            for row in cur.fetchall():
                fname = row["filename"] if isinstance(row, dict) else row[0]
                cls = row["classification"] if isinstance(row, dict) else row[1]
                existing_decided[fname] = cls

            hidden_transitions = [
                image.filename
                for image in images
                if image.filename in existing_decided
                and existing_decided[image.filename] in self._VISIBLE_IMAGE_CLASSIFICATIONS
                and image.classification.value in self._HIDDEN_IMAGE_CLASSIFICATIONS
            ]
            if hidden_transitions:
                if not force:
                    # reviewer_count=0 because v2_image_review_decisions does
                    # not track reviewer identity (see sql/29).
                    raise ReviewedFilingError(
                        filing_id=filing_id,
                        decision_count=len(hidden_transitions),
                        reviewer_count=0,
                        context="image classifications",
                    )
                logger.warning(
                    "force-reextract hiding reviewed images: "
                    "filing_id=%s hidden_image_count=%s filenames=%s",
                    filing_id,
                    len(hidden_transitions),
                    hidden_transitions,
                )

        # Upsert on (doc_id, filename), NOT on img_id: ImageAsset.img_id is a
        # fresh random UUID per extraction run, so keying on img_id would
        # insert a new row every time and orphan decisions in
        # v2_image_review_decisions (which FK to img_id). The UNIQUE constraint
        # added in sql/34_dedup_v2_image_assets.sql backs this target. img_id
        # is deliberately absent from the DO UPDATE SET list to preserve the
        # existing value on conflict.
        sql = """
            INSERT INTO v2_image_assets (
                img_id, doc_id, filename, file_path,
                width, height, dom_locator, nearby_text,
                section_path, section_type,
                classification, relevance_score,
                ocr_text, ocr_table_id, chart_type, chart_data,
                processed, confidence, requires_manual,
                detected_keywords, created_at
            )
            VALUES (
                %(img_id)s, %(doc_id)s, %(filename)s, %(file_path)s,
                %(width)s, %(height)s, %(dom_locator)s, %(nearby_text)s,
                %(section_path)s, %(section_type)s,
                %(classification)s, %(relevance_score)s,
                %(ocr_text)s, %(ocr_table_id)s, %(chart_type)s, %(chart_data)s,
                %(processed)s, %(confidence)s, %(requires_manual)s,
                %(detected_keywords)s, NOW()
            )
            ON CONFLICT (doc_id, filename) DO UPDATE SET
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
                requires_manual = EXCLUDED.requires_manual,
                detected_keywords = EXCLUDED.detected_keywords
            RETURNING img_id
        """

        params_list = [
            {
                "img_id": image.img_id,
                "doc_id": filing_id,
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
                "detected_keywords": match_nearby_text(
                    ((image.nearby_text or "") + " " + (image.ocr_text or "")).strip()
                )
                or None,
            }
            for image in images
        ]

        img_id_map: dict[str, str] = {}
        for params in params_list:
            cur.execute(sql, params)
            row = cur.fetchone()
            if row is None:
                continue
            returned_img_id = str(row["img_id"]) if isinstance(row, dict) else str(row[0])
            in_memory_img_id = str(params["img_id"])
            if returned_img_id != in_memory_img_id:
                img_id_map[in_memory_img_id] = returned_img_id

        return len(params_list), img_id_map

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
        *,
        force: bool = False,
        chart_only: bool = False,
    ) -> int:
        """Persist facts within an existing transaction using delete-then-insert.

        Guards against silent destruction of human review decisions: if any
        fact for ``filing_id`` has a row in ``v2_review_decisions``, raises
        ``ReviewedFilingError`` unless ``force=True``.

        When ``chart_only=True``, only chart-sourced facts are touched:
        inbound ``facts`` are filtered to ``source_type='chart'``, the DELETE
        is scoped to ``source_type='chart'``, and the reviewed-filing guard
        counts decisions on chart facts only. Text facts and any reviewer
        decisions on them are left untouched. Used for Issue #35 backfills
        of missing chart facts on filings with accumulated reviewer work
        on text facts.
        """
        if chart_only:
            facts = [f for f in facts if f.source_type == SourceType.CHART]

        if not facts:
            return 0

        # chart_only scopes the guard + DELETE to chart facts so text facts
        # (and their reviewer decisions) survive the DELETE below, which
        # would otherwise CASCADE through v2_review_decisions.fact_id.
        params: dict[str, Any] = {"filing_id": filing_id}
        where_scope = "doc_id = %(filing_id)s"
        if chart_only:
            params["source_type"] = SourceType.CHART.value
            where_scope += " AND source_type = %(source_type)s"

        # Guard: refuse to wipe human review decisions without explicit opt-in.
        cur.execute(
            f"""
            SELECT COUNT(*) AS decision_count,
                   COUNT(DISTINCT rd.reviewer_id) AS reviewer_count
              FROM v2_metric_facts mf
              JOIN v2_review_decisions rd ON rd.fact_id = mf.fact_id
             WHERE mf.{where_scope}
            """,
            params,
        )
        row = cur.fetchone()
        decision_count = int(row["decision_count"]) if row else 0
        reviewer_count = int(row["reviewer_count"]) if row else 0
        if decision_count > 0:
            if not force:
                raise ReviewedFilingError(
                    filing_id=filing_id,
                    decision_count=decision_count,
                    reviewer_count=reviewer_count,
                )
            logger.warning(
                "force-reextract purging reviewed filing: "
                "filing_id=%s purged_decision_count=%s distinct_reviewer_count=%s chart_only=%s",
                filing_id,
                decision_count,
                reviewer_count,
                chart_only,
            )

        # Delete-then-insert is idempotent and avoids a unique index across
        # nullable expression columns.
        cur.execute(f"DELETE FROM v2_metric_facts WHERE {where_scope}", params)

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
                p["source_type"],
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
