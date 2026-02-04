"""
Stage 5: OCR & Chart Extraction.

Processes high-relevance images to extract structured data:
- TABLE_IMAGE: Run OCR to extract text, then reconstruct into Table object
- CHART: Use vision model to extract labeled data values (never interpolate)

Design principle: "Charts only when labeled" - extract ONLY explicit data labels
shown on charts, never interpolate values from axis positions.

Key responsibilities:
- Process images with relevance_score >= MIN_RELEVANCE_FOR_PROCESSING
- Extract table structures via OCR API
- Extract chart data via vision model (labeled values only)
- Set confidence scores and manual capture flags
- Track API costs and respect limits
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING

from src.extraction_v2.models import (
    ImageAsset,
    ImageClassification,
)

if TYPE_CHECKING:
    from src.extraction_v2 import pipeline

logger = logging.getLogger(__name__)


class OCRExtractionStage:
    """
    Stage 5: OCR & Chart Extraction - process high-relevance images.

    Pipeline responsibilities:
    - Process images with relevance_score >= threshold
    - Extract table structures from TABLE_IMAGE via OCR
    - Extract chart data from CHART via vision model
    - Set processed=True and confidence after extraction
    - Mark low-confidence results for manual capture
    - Track API costs and respect limits
    """

    # Processing thresholds
    MIN_RELEVANCE_FOR_PROCESSING: float = 0.3  # Must match ImageTriageStage
    OCR_CONFIDENCE_THRESHOLD: float = 0.5  # Below this, mark for manual

    # Cost control limits (per document)
    MAX_OCR_CALLS_PER_DOCUMENT: int = 20
    MAX_CHART_CALLS_PER_DOCUMENT: int = 10

    def __init__(self, vision_client: object | None = None) -> None:
        """
        Initialize the OCR extraction stage.

        Args:
            vision_client: Optional vision API client (OpenAI Vision).
                          If None, will be created on first use.
        """
        self._vision_client = vision_client
        self._api_call_count = 0
        self._ocr_call_count = 0
        self._chart_call_count = 0

    @property
    def vision_client(self) -> object:
        """Lazy-load vision client to avoid import errors in tests."""
        if self._vision_client is None:
            # Import here to avoid circular dependency
            from src.extraction_v2.vision_client import OpenAIVisionClient

            self._vision_client = OpenAIVisionClient()
        return self._vision_client

    def _should_process(self, asset: ImageAsset) -> bool:
        """
        Determine if image should be processed.

        Args:
            asset: Image to check

        Returns:
            True if should be processed
        """
        # Skip if already processed
        if asset.processed:
            return False

        # Skip if below relevance threshold
        if asset.relevance_score < self.MIN_RELEVANCE_FOR_PROCESSING:
            return False

        # Skip decorative/logo/signature
        if asset.classification in {
            ImageClassification.DECORATIVE,
            ImageClassification.LOGO,
            ImageClassification.SIGNATURE,
        }:
            return False

        # Skip if no file path
        if not asset.file_path:
            logger.warning(f"Image {asset.img_id} has no file_path, skipping")
            return False

        return True

    def process_table_image(self, asset: ImageAsset) -> None:
        """
        Extract table from image using OCR.

        Placeholder for AC-2 implementation.

        Args:
            asset: Image asset to process (modified in place)
        """
        # TODO: AC-2 - Implement OCR extraction
        logger.info(f"Processing table image {asset.img_id} (not implemented)")
        asset.processed = True
        asset.confidence = 0.0
        asset.requires_manual_capture = True

    def process_chart(self, asset: ImageAsset) -> None:
        """
        Extract labeled values from chart.

        CRITICAL: Only extract values that are EXPLICITLY labeled on the chart.
        Never interpolate values from axis positions.

        Placeholder for AC-3 implementation.

        Args:
            asset: Image asset to process (modified in place)
        """
        # TODO: AC-3 - Implement chart extraction
        logger.info(f"Processing chart {asset.img_id} (not implemented)")
        asset.processed = True
        asset.confidence = 0.0
        asset.requires_manual_capture = True

    def process(self, context: pipeline.PipelineContext) -> pipeline.StageResult:
        """
        Process high-relevance images with OCR/Vision.

        Modifies context.images in place, setting:
        - ocr_text/ocr_table for TABLE_IMAGE
        - chart_data for CHART
        - processed=True
        - confidence scores
        - requires_manual_capture flags

        Args:
            context: Pipeline context with images list

        Returns:
            StageResult with extraction counts and metadata
        """
        # Import here to avoid circular import
        from src.extraction_v2.pipeline import PipelineStage, StageResult

        start_time = datetime.utcnow()
        errors: list[str] = []
        warnings: list[str] = []

        # Reset API call counters for this document
        self._api_call_count = 0
        self._ocr_call_count = 0
        self._chart_call_count = 0

        processed_count = 0
        skipped_count = 0
        manual_capture_count = 0

        try:
            # Handle empty images list
            if not context.images:
                logger.info("No images to process")
                duration_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)
                return StageResult(
                    stage=PipelineStage.OCR_CHART_EXTRACTION,
                    success=True,
                    duration_ms=duration_ms,
                    items_processed=0,
                    items_output=0,
                    errors=errors,
                    warnings=warnings,
                    metadata={"message": "No images to process"},
                )

            # Process each relevant image
            for asset in context.images:
                # Check if should process
                if not self._should_process(asset):
                    skipped_count += 1
                    continue

                # Check API call limits
                if asset.classification == ImageClassification.TABLE_IMAGE:
                    if self._ocr_call_count >= self.MAX_OCR_CALLS_PER_DOCUMENT:
                        msg = f"OCR call limit ({self.MAX_OCR_CALLS_PER_DOCUMENT}) reached"
                        warnings.append(msg)
                        logger.warning(msg)
                        break
                elif asset.classification == ImageClassification.CHART:
                    if self._chart_call_count >= self.MAX_CHART_CALLS_PER_DOCUMENT:
                        msg = f"Chart call limit ({self.MAX_CHART_CALLS_PER_DOCUMENT}) reached"
                        warnings.append(msg)
                        logger.warning(msg)
                        break

                # Process based on classification
                try:
                    if asset.classification == ImageClassification.TABLE_IMAGE:
                        self.process_table_image(asset)
                        self._ocr_call_count += 1
                    elif asset.classification == ImageClassification.CHART:
                        self.process_chart(asset)
                        self._chart_call_count += 1
                    else:
                        # Unknown type - skip
                        logger.debug(f"Skipping image {asset.img_id} with classification {asset.classification}")
                        skipped_count += 1
                        continue

                    self._api_call_count += 1
                    processed_count += 1

                    if asset.requires_manual_capture:
                        manual_capture_count += 1

                except Exception as e:
                    # Log error but continue processing other images
                    error_msg = f"Error processing {asset.img_id}: {str(e)}"
                    errors.append(error_msg)
                    logger.error(error_msg, exc_info=True)

                    # Mark for manual capture
                    asset.requires_manual_capture = True
                    asset.processed = True
                    asset.confidence = 0.0
                    manual_capture_count += 1

            duration_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)

            return StageResult(
                stage=PipelineStage.OCR_CHART_EXTRACTION,
                success=len(errors) == 0,
                duration_ms=duration_ms,
                items_processed=processed_count,
                items_output=processed_count,
                errors=errors,
                warnings=warnings,
                metadata={
                    "ocr_calls": self._ocr_call_count,
                    "chart_calls": self._chart_call_count,
                    "total_api_calls": self._api_call_count,
                    "manual_capture_count": manual_capture_count,
                    "skipped_count": skipped_count,
                },
            )

        except Exception as e:
            # Catastrophic error - fail the stage
            error_msg = f"OCR extraction stage failed: {str(e)}"
            errors.append(error_msg)
            logger.error(error_msg, exc_info=True)

            duration_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)

            return StageResult(
                stage=PipelineStage.OCR_CHART_EXTRACTION,
                success=False,
                duration_ms=duration_ms,
                items_processed=processed_count,
                items_output=processed_count,
                errors=errors,
                warnings=warnings,
                metadata={
                    "ocr_calls": self._ocr_call_count,
                    "chart_calls": self._chart_call_count,
                    "total_api_calls": self._api_call_count,
                    "manual_capture_count": manual_capture_count,
                    "skipped_count": skipped_count,
                },
            )
