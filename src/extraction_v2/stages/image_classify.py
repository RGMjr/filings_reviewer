"""Stage 5.6 — Vision API metric-classify.

Calls ``VisionClient.analyze_image_for_metric_classification`` once per chart /
table image when ``PipelineConfig.enable_metric_classify`` is True. Emits an
``ImageClassificationRecord`` per image into ``context.image_classifications``;
persistence (``V2PersistenceAdapter._persist_image_classifications_in_tx``)
writes them to ``v2_image_classifications``.

Distinct from ``ChartFactBridgeStage`` (rule-based keyword classifier that
populates ``v2_image_assets.detected_metrics``). Both stages can run in the
same pipeline pass and write to their own stores.

Provider/model come from ``config.vision_classify_provider`` and
``config.vision_classify_model`` so classify can use a different model than
OCR / chart-read (bake-off memo 2026-04-23 picked gemini-flash for classify,
while OCR stays on the default provider).
"""

from __future__ import annotations

import logging
import os
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from src.extraction_v2.models import ImageAsset, ImageClassification, ImageClassificationRecord
from src.infra.image_storage import get_image_storage
from src.llm.vision_client import VisionClient

if TYPE_CHECKING:
    from src.extraction_v2.pipeline import PipelineContext, StageResult

logger = logging.getLogger(__name__)

# Keep in lock-step with the CHECK constraint on v2_image_classifications.
# rejection_reason — see sql/45.
_CLASSIFIABLE_IMAGE_TYPES = (ImageClassification.CHART, ImageClassification.TABLE_IMAGE)


class ImageClassifyStage:
    """Vision API metric-classify stage. Runs AFTER ChartFactBridgeStage."""

    PROMPT_VERSION: int = 1

    def process(self, context: PipelineContext) -> StageResult:
        from src.extraction_v2.pipeline import PipelineStage, StageResult

        start_time = datetime.now(UTC)

        if not context.config.enable_metric_classify:
            return _empty_result(PipelineStage, StageResult, start_time)

        candidates = [
            img
            for img in context.images
            if img.classification in _CLASSIFIABLE_IMAGE_TYPES
            and img.file_path  # persistence required file_path
        ]

        if not candidates:
            return _empty_result(PipelineStage, StageResult, start_time)

        provider = context.config.vision_classify_provider
        model = context.config.vision_classify_model
        client = _build_client(provider, model)

        records_emitted = 0
        api_errors = 0

        for image in candidates:
            record = self._classify_one(image, client, provider, model)
            if record is None:
                api_errors += 1
                continue
            context.image_classifications.append(record)
            records_emitted += 1

        duration_ms = int((datetime.now(UTC) - start_time).total_seconds() * 1000)
        return StageResult(
            stage=PipelineStage.IMAGE_CLASSIFY,
            success=True,
            duration_ms=duration_ms,
            items_processed=len(candidates),
            items_output=records_emitted,
            metadata={
                "provider": provider,
                "model": model,
                "api_errors": api_errors,
                "prompt_version": self.PROMPT_VERSION,
            },
        )

    def _classify_one(
        self,
        image: ImageAsset,
        client: VisionClient,
        provider: str,
        model: str,
    ) -> ImageClassificationRecord | None:
        """Classify one image. Returns None on API / parse failure."""
        try:
            image_bytes = get_image_storage().get_bytes(image.file_path)  # type: ignore[arg-type]
        except (FileNotFoundError, OSError) as exc:
            logger.warning(
                "ImageClassifyStage: missing image bytes img_id=%s path=%s err=%s",
                image.img_id,
                image.file_path,
                exc,
            )
            return None

        t0 = time.perf_counter()
        try:
            parsed = client.analyze_image_for_metric_classification(image_bytes=image_bytes)
        except Exception:  # noqa: BLE001 — log and continue; don't fail the filing
            logger.exception(
                "ImageClassifyStage: vision API call failed img_id=%s",
                image.img_id,
            )
            return None
        latency_ms = int((time.perf_counter() - t0) * 1000)

        if parsed is None:
            return None

        cost_usd = float(parsed.pop("_cost_usd", 0.0))

        predicted_metrics = [
            {"metric_id": m, "score": parsed["confidence"]} for m in parsed["predicted_metrics"]
        ]

        return ImageClassificationRecord(
            img_id=image.img_id,
            predicted_metrics=predicted_metrics,
            confidence=parsed["confidence"],
            rejection_reason=parsed["rejection_reason"],
            reasoning=parsed["reasoning"] or None,
            provider=provider,
            model=model,
            prompt_version=self.PROMPT_VERSION,
            cost_usd=cost_usd,
            latency_ms=latency_ms,
        )


def _build_client(provider: str, model: str) -> VisionClient:
    """Build a VisionClient configured for the classify-specific provider/model.

    Uses env override so the underlying VisionClient picks the right backend
    without changing the shared process-wide provider state.
    """
    prior_provider = os.environ.get("VISION_PROVIDER")
    prior_ocr_model = os.environ.get("VISION_MODEL_OCR")
    os.environ["VISION_PROVIDER"] = provider
    os.environ["VISION_MODEL_OCR"] = model
    try:
        return VisionClient()
    finally:
        # Restore so downstream stages don't see classify's overrides.
        if prior_provider is None:
            os.environ.pop("VISION_PROVIDER", None)
        else:
            os.environ["VISION_PROVIDER"] = prior_provider
        if prior_ocr_model is None:
            os.environ.pop("VISION_MODEL_OCR", None)
        else:
            os.environ["VISION_MODEL_OCR"] = prior_ocr_model


def _empty_result(PipelineStage, StageResult, start_time):  # noqa: N803
    duration_ms = int((datetime.now(UTC) - start_time).total_seconds() * 1000)
    return StageResult(
        stage=PipelineStage.IMAGE_CLASSIFY,
        success=True,
        duration_ms=duration_ms,
        items_processed=0,
        items_output=0,
    )
