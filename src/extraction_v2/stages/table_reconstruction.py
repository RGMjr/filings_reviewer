"""
V2 Table Reconstruction Stage

This stage processes table segments and reconstructs their structure using the existing
TableReconstructor. It converts HTML table elements into normalized Table objects with:
- Resolved colspan/rowspan
- Header row and stub column detection
- header_path and stub_path for each cell

Design source: V2 PRD - Phase 3 (Table Reconstruction)
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING

from bs4 import BeautifulSoup

from src.extraction_v2.models import SegmentType
from src.extraction_v2.table_reconstructor import TableReconstructor

if TYPE_CHECKING:
    from src.extraction_v2.pipeline import PipelineContext, PipelineStage, StageResult  # noqa: F401

logger = logging.getLogger(__name__)


class TableReconstructionStage:
    """
    Stage 3: Table Reconstruction.

    Processes table segments and converts them to structured Table objects with
    resolved spans and structural metadata.

    Key responsibilities:
    - Filter segments to table type only
    - Parse segment raw_html to extract <table> elements
    - Use TableReconstructor to normalize table structure
    - Link reconstructed tables back to source segments
    - Store tables in pipeline context
    """

    def __init__(self) -> None:
        """Initialize with a TableReconstructor instance."""
        self._reconstructor = TableReconstructor()

    def process(self, context: PipelineContext) -> StageResult:
        """
        Reconstruct tables from table segments.

        Args:
            context: Pipeline context with segments from ingestion stage

        Returns:
            StageResult with processing metrics and any errors
        """
        start_time = datetime.utcnow()
        tables_processed = 0
        tables_skipped = 0
        errors: list[str] = []
        warnings: list[str] = []

        # Get table segments
        table_segments = [seg for seg in context.segments if seg.segment_type == SegmentType.TABLE]

        logger.info(f"Table reconstruction: processing {len(table_segments)} table segments")

        for segment in table_segments:
            try:
                # Parse HTML to extract table element
                soup = BeautifulSoup(segment.raw_html, "lxml")
                table_elem = soup.find("table")

                if not table_elem:
                    # Segment marked as table but no <table> element found
                    warnings.append(
                        f"Segment {segment.segment_id} marked as TABLE but no <table> element found"
                    )
                    tables_skipped += 1
                    continue

                # Check table size limits before expensive reconstruction
                rows = table_elem.find_all("tr")
                cols = max((len(r.find_all(["td", "th"])) for r in rows), default=0)
                if len(rows) > context.config.max_table_rows or cols > context.config.max_table_cols:
                    warnings.append(
                        f"Segment {segment.segment_id} skipped: table too large "
                        f"({len(rows)} rows, {cols} cols) — "
                        f"limits are {context.config.max_table_rows}x{context.config.max_table_cols}"
                    )
                    tables_skipped += 1
                    continue

                # Reconstruct table structure
                table = self._reconstructor.reconstruct(table_elem)

                # Link back to source segment
                table.segment_id = segment.segment_id

                # Copy section context from segment
                table.section_type = segment.section_type
                table.section_path = segment.section_path.copy()

                # Copy DOM locator
                table.dom_locator = segment.dom_locator

                # Add to context
                context.tables.append(table)
                tables_processed += 1

                logger.debug(
                    f"Reconstructed table {table.table_id} from segment {segment.segment_id}: "
                    f"{table.row_count}x{table.col_count}, "
                    f"{table.header_rows} header rows, {table.stub_cols} stub cols"
                )

            except Exception as e:
                error_msg = f"Failed to reconstruct table from segment {segment.segment_id}: {e}"
                logger.error(error_msg)
                errors.append(error_msg)
                tables_skipped += 1

        # Calculate duration
        end_time = datetime.utcnow()
        duration_ms = int((end_time - start_time).total_seconds() * 1000)

        # Partial errors are warnings if at least one table succeeded
        if tables_processed > 0 and errors:
            warnings.extend(errors)
            errors = []

        # Log summary
        logger.info(
            f"Table reconstruction complete: "
            f"{tables_processed} tables reconstructed, "
            f"{tables_skipped} skipped, "
            f"{len(errors)} errors in {duration_ms}ms"
        )

        # Import at runtime to avoid circular import
        from src.extraction_v2.pipeline import PipelineStage, StageResult

        return StageResult(
            stage=PipelineStage.TABLE_RECONSTRUCTION,
            success=tables_processed > 0 or len(table_segments) == 0,
            duration_ms=duration_ms,
            items_processed=len(table_segments),
            items_output=tables_processed,
            errors=errors,
            warnings=warnings,
            metadata={
                "tables_processed": tables_processed,
                "tables_skipped": tables_skipped,
            },
        )
