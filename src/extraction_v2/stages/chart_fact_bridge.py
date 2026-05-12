from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from src.extraction_v2.chart.metric_classifier import ChartMetricClassifier
from src.extraction_v2.chart.table_metric_classifier import score_ocr_table
from src.extraction_v2.models import DetectedMetric

if TYPE_CHECKING:
    from src.extraction_v2.pipeline import PipelineContext, StageResult

logger = logging.getLogger(__name__)


class ChartFactBridgeStage:
    def process(self, context: PipelineContext) -> StageResult:
        from src.extraction_v2.pipeline import PipelineStage, StageResult

        start_time = datetime.now(UTC)

        if not context.config.enable_chart_fact_bridge:
            duration_ms = int((datetime.now(UTC) - start_time).total_seconds() * 1000)
            return StageResult(
                stage=PipelineStage.CHART_FACT_BRIDGE,
                success=True,
                duration_ms=duration_ms,
                items_processed=0,
                items_output=0,
            )

        classifier = ChartMetricClassifier(config=context.config)
        kw_override = context.config.keyword_override

        images_scanned = 0
        metrics_detected = 0
        images_below_confidence = 0

        for image in context.images:
            if image.chart_data is not None:
                # --- CHART branch ---
                # Guard 1 — image confidence gate
                if (
                    image.confidence is not None
                    and image.confidence < context.config.chart_image_min_confidence
                ):
                    images_below_confidence += 1
                    continue

                images_scanned += 1

                candidates = classifier.classify_all(image.chart_data, image.nearby_text or "")
                image.detected_metrics = [
                    DetectedMetric(metric_id=m, score=s)
                    for m, s in candidates
                    if s >= context.config.chart_presence_min_score
                ]
                metrics_detected += len(image.detected_metrics)

                if image.detected_metrics:
                    logger.debug(
                        "ChartFactBridgeStage: img_id=%s detected_metrics=%s (chart)",
                        image.img_id,
                        [(d.metric_id, d.score) for d in image.detected_metrics],
                    )

            elif image.ocr_table is not None:
                # --- TABLE_IMAGE branch (A3, 2026-04-28) ---
                # Score the OCR-reconstructed table for per-metric presence using
                # header_path + stub_path keyword matching (same logic as _scan_table
                # in candidate_generation).  Emit (metric_id, score) pairs into
                # v2_image_assets.detected_metrics via the same channel charts use.
                images_scanned += 1

                candidates = score_ocr_table(
                    image.ocr_table,
                    image.nearby_text or "",
                    keyword_override=kw_override,
                )
                image.detected_metrics = [
                    DetectedMetric(metric_id=m, score=s)
                    for m, s in candidates
                    if s >= context.config.chart_presence_min_score
                ]
                metrics_detected += len(image.detected_metrics)

                if image.detected_metrics:
                    logger.debug(
                        "ChartFactBridgeStage: img_id=%s detected_metrics=%s (ocr_table)",
                        image.img_id,
                        [(d.metric_id, d.score) for d in image.detected_metrics],
                    )

        duration_ms = int((datetime.now(UTC) - start_time).total_seconds() * 1000)
        return StageResult(
            stage=PipelineStage.CHART_FACT_BRIDGE,
            success=True,
            duration_ms=duration_ms,
            items_processed=images_scanned,
            items_output=metrics_detected,
            metadata={
                "images_scanned": images_scanned,
                "metrics_detected": metrics_detected,
                "images_below_confidence": images_below_confidence,
            },
        )
