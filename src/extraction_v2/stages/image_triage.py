"""
Stage 4: Image Triage.

Classifies and prioritizes images for OCR/Vision extraction in Stage 5.

Key responsibilities:
- Classify images into: CHART, TABLE_IMAGE, DECORATIVE, LOGO, SIGNATURE, UNKNOWN
- Detect chart types (BAR, LINE, PIE, STACKED_BAR, AREA)
- Score relevance based on section context and keyword proximity
- Queue high-relevance images for processing
- Mark ambiguous images for manual capture
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import TYPE_CHECKING

from src.extraction_v2.models import (
    ChartType,
    ImageAsset,
    ImageClassification,
    SectionType,
)

if TYPE_CHECKING:
    from src.extraction_v2 import pipeline

logger = logging.getLogger(__name__)


class ImageTriageStage:
    """
    Stage 4: Image Triage - classify and prioritize images.

    Pipeline responsibilities:
    - Classify each image in context.images
    - Compute relevance scores
    - Mark high-relevance images for OCR/Vision processing
    - Mark ambiguous images for manual capture
    """

    # Thresholds
    MIN_RELEVANCE_FOR_PROCESSING: float = 0.3  # Queue for OCR/Vision
    AMBIGUOUS_RELEVANCE_THRESHOLD: float = 0.5  # Mark for manual capture if below

    # Dimension thresholds for classification
    LOGO_MAX_WIDTH: int = 300
    LOGO_MAX_HEIGHT: int = 150
    LARGE_IMAGE_MIN_WIDTH: int = 800
    LARGE_IMAGE_MIN_HEIGHT: int = 600

    # Aspect ratio thresholds
    BANNER_ASPECT_RATIO_MIN: float = 4.0  # Width/height for banners
    SQUARE_TOLERANCE: float = 0.3  # How close to 1:1 is "square"

    # Filename patterns for classification
    LOGO_PATTERNS = [
        r"\blogo\b",
        r"\bicon\b",
        r"\bbrand\b",
        r"\bemblem\b",
    ]

    SIGNATURE_PATTERNS = [
        r"\bsignature\b",
        r"\bsign[_-]?\d*\b",
        r"\bautograph\b",
    ]

    CHART_PATTERNS = [
        r"\bchart\b",
        r"\bgraph\b",
        r"\bfigures?\b",
        r"\bexhibit\b",
        r"\bdiagram\b",
        r"\bplot\b",
    ]

    DECORATIVE_PATTERNS = [
        r"\bbullet\b",
        r"\bbanner\b",
        r"\bheader\b",
        r"\bfooter\b",
        r"\bspacer\b",
        r"\bdivider\b",
        r"\bbackground\b",
        r"\bwatermark\b",
    ]

    # Chart type detection keywords
    CHART_TYPE_PATTERNS: dict[ChartType, list[str]] = {
        ChartType.BAR: ["bar chart", "bar graph", "histogram", "column chart"],
        ChartType.STACKED_BAR: ["stacked bar", "stacked chart", "stacked column"],
        ChartType.LINE: ["line chart", "line graph", "trend line", "time series"],
        ChartType.PIE: ["pie chart", "pie graph", "donut chart", "distribution"],
        ChartType.AREA: ["area chart", "area graph", "filled line"],
    }

    # High-value metric keywords for relevance scoring
    HIGH_VALUE_KEYWORDS = [
        "cohort",
        "retention",
        "churn",
        "ltv",
        "cac",
        "arr",
        "mrr",
        "nrr",
        "revenue",
        "customers",
        "subscribers",
        "users",
        "dau",
        "mau",
        "engagement",
        "conversion",
        "growth",
        "arpu",
        "gmv",
    ]

    # Section relevance bonuses
    SECTION_BONUSES: dict[SectionType, float] = {
        SectionType.MDA: 0.2,
        SectionType.BUSINESS: 0.15,
        SectionType.RISK_FACTORS: 0.1,
        SectionType.FINANCIALS: 0.05,
    }

    # Base scores by classification
    CLASSIFICATION_BASE_SCORES: dict[ImageClassification, float] = {
        ImageClassification.CHART: 0.5,
        ImageClassification.TABLE_IMAGE: 0.4,
        ImageClassification.UNKNOWN: 0.2,
        ImageClassification.DECORATIVE: 0.0,
        ImageClassification.LOGO: 0.0,
        ImageClassification.SIGNATURE: 0.0,
    }

    def __init__(self) -> None:
        """Initialize the image triage stage."""
        # Compile regex patterns for efficiency
        self._logo_patterns = [re.compile(p, re.IGNORECASE) for p in self.LOGO_PATTERNS]
        self._signature_patterns = [re.compile(p, re.IGNORECASE) for p in self.SIGNATURE_PATTERNS]
        self._chart_patterns = [re.compile(p, re.IGNORECASE) for p in self.CHART_PATTERNS]
        self._decorative_patterns = [re.compile(p, re.IGNORECASE) for p in self.DECORATIVE_PATTERNS]

    def _matches_any_pattern(self, text: str, patterns: list[re.Pattern[str]]) -> bool:
        """Check if text matches any of the compiled patterns."""
        return any(p.search(text) for p in patterns)

    def _is_logo(self, asset: ImageAsset) -> bool:
        """
        Detect if image is a logo based on filename, dimensions, and text patterns.

        Logos typically:
        - Have "logo" in filename
        - Are small (< 300x150)
        - Have square-ish aspect ratio

        Note: Very small images (< 50px) are decorative, not logos.
        """
        # Very small images are decorative bullets/spacers, not logos
        if asset.width > 0 and asset.height > 0:
            if asset.width < 50 or asset.height < 50:
                return False

        # Check filename patterns
        if self._matches_any_pattern(asset.filename, self._logo_patterns):
            return True

        # Check nearby text for logo references
        if self._matches_any_pattern(asset.nearby_text, self._logo_patterns):
            # Only if dimensions support it
            if asset.width > 0 and asset.height > 0:
                if asset.width <= self.LOGO_MAX_WIDTH and asset.height <= self.LOGO_MAX_HEIGHT:
                    return True

        # Small square-ish images are likely logos/icons (but not too small)
        if asset.width > 0 and asset.height > 0:
            if (
                50 <= asset.width <= self.LOGO_MAX_WIDTH
                and 50 <= asset.height <= self.LOGO_MAX_HEIGHT
            ):
                aspect = asset.width / asset.height if asset.height > 0 else 1.0
                if 0.5 <= aspect <= 2.0:  # Roughly square
                    return True

        return False

    def _is_signature(self, asset: ImageAsset) -> bool:
        """Detect if image is a signature."""
        # Normalize filename for matching (replace underscores/hyphens with spaces)
        filename_normalized = asset.filename.lower().replace("_", " ").replace("-", " ")

        # Check filename patterns (use normalized version)
        if self._matches_any_pattern(filename_normalized, self._signature_patterns):
            return True

        # Also check original filename for patterns without word boundaries
        filename_lower = asset.filename.lower()
        if "signature" in filename_lower or "sign" in filename_lower:
            return True

        # Check nearby text
        if self._matches_any_pattern(asset.nearby_text, self._signature_patterns):
            return True

        return False

    def _is_chart(self, asset: ImageAsset) -> bool:
        """
        Detect if image is a chart/graph based on filename and nearby text.

        Charts typically:
        - Have "chart", "graph", "figure" in filename or caption
        - Are larger images (meaningful data visualization)
        - Have metric-related keywords nearby
        """
        # Normalize filename for matching (replace underscores/hyphens with spaces)
        filename_normalized = asset.filename.lower().replace("_", " ").replace("-", " ")
        combined_text = f"{filename_normalized} {asset.nearby_text}"

        # Check chart patterns
        if self._matches_any_pattern(combined_text, self._chart_patterns):
            return True

        # Check for specific chart type keywords
        text_lower = combined_text.lower()
        for patterns in self.CHART_TYPE_PATTERNS.values():
            if any(kw in text_lower for kw in patterns):
                return True

        # Large images (or dimensionless images from SEC filings) with metric keywords are likely charts
        has_known_dimensions = asset.width > 0 or asset.height > 0
        is_large = (
            asset.width >= self.LARGE_IMAGE_MIN_WIDTH or asset.height >= self.LARGE_IMAGE_MIN_HEIGHT
        )
        if is_large or not has_known_dimensions:
            text_lower = asset.nearby_text.lower()
            metric_keywords = [
                "retention",
                "cohort",
                "revenue",
                "growth",
                "customers",
                "arr",
                "mrr",
            ]
            if any(kw in text_lower for kw in metric_keywords):
                return True

        return False

    def _is_table_image(self, asset: ImageAsset) -> bool:
        """
        Detect if image is a table rendered as an image (needs OCR).

        Table images typically:
        - Have "table" in nearby text but not as HTML
        - Are wide images (tables are usually wider than tall)
        - Have tabular content indicators
        """
        # Normalize filename for matching
        filename_normalized = asset.filename.lower().replace("_", " ").replace("-", " ")
        combined_text = f"{filename_normalized} {asset.nearby_text}".lower()

        # Explicit table references (in text or filename)
        table_keywords = ["table", "schedule", "summary of", "breakdown"]
        if any(kw in combined_text for kw in table_keywords):
            # Make sure it's not already classified as a chart
            if not self._is_chart(asset):
                return True

        # Wide aspect ratio suggests table layout
        if asset.width > 0 and asset.height > 0:
            aspect = asset.width / asset.height
            if aspect >= 2.0:  # Significantly wider than tall
                # And has financial/metric keywords
                text_lower = asset.nearby_text.lower()
                financial_keywords = ["revenue", "income", "expense", "total", "period", "year"]
                if any(kw in text_lower for kw in financial_keywords):
                    return True

        return False

    def _is_decorative(self, asset: ImageAsset) -> bool:
        """
        Detect if image is decorative (not useful for metric extraction).

        Decorative images:
        - Have decorative keywords in filename
        - Are very small
        - Have extreme aspect ratios (banners, dividers)
        - Are in non-content sections

        Note: This should be called AFTER signature/chart checks to avoid
        misclassifying wide signatures as banners.
        """
        # Check filename patterns
        if self._matches_any_pattern(asset.filename, self._decorative_patterns):
            return True

        # Check dimensions
        if asset.width > 0 and asset.height > 0:
            # Very small images
            if asset.width < 50 or asset.height < 50:
                return True

            # Banner-like aspect ratio (but not signatures)
            aspect = asset.width / asset.height
            if aspect >= self.BANNER_ASPECT_RATIO_MIN:
                # Wide banner, likely decorative unless it's a chart or signature
                if not self._is_chart(asset) and not self._is_signature(asset):
                    return True

            # Very thin vertical images
            if aspect <= 0.1:
                return True

        # Images in non-content sections
        if asset.section_type in [SectionType.EXHIBITS, SectionType.SIGNATURES]:
            return True

        return False

    def classify_image(self, asset: ImageAsset) -> ImageClassification:
        """
        Classify image based on multiple signals.

        Priority order:
        1. Logo detection (filename + dimensions)
        2. Signature detection
        3. Chart detection (filename + text patterns)
        4. Table image detection
        5. Decorative detection (fallback)
        6. Unknown

        Args:
            asset: ImageAsset to classify

        Returns:
            ImageClassification enum value
        """
        # 1. Logo detection (most restrictive first)
        if self._is_logo(asset):
            return ImageClassification.LOGO

        # 2. Signature detection
        if self._is_signature(asset):
            return ImageClassification.SIGNATURE

        # 3. Chart detection
        if self._is_chart(asset):
            return ImageClassification.CHART

        # 4. Table image detection
        if self._is_table_image(asset):
            return ImageClassification.TABLE_IMAGE

        # 5. Decorative detection (fallback for non-content)
        if self._is_decorative(asset):
            return ImageClassification.DECORATIVE

        return ImageClassification.UNKNOWN

    def detect_chart_type(self, asset: ImageAsset) -> ChartType:
        """
        Detect chart type from filename and caption.

        Only meaningful if image is classified as CHART.

        Args:
            asset: ImageAsset with CHART classification

        Returns:
            ChartType enum value
        """
        if asset.classification != ImageClassification.CHART:
            return ChartType.UNKNOWN

        # Normalize filename for matching
        filename_normalized = asset.filename.lower().replace("_", " ").replace("-", " ")
        combined_text = f"{filename_normalized} {asset.nearby_text}".lower()

        # Check patterns in priority order (more specific patterns first)
        # STACKED_BAR must be checked before BAR
        priority_order = [
            ChartType.STACKED_BAR,  # Check before BAR
            ChartType.BAR,
            ChartType.LINE,
            ChartType.PIE,
            ChartType.AREA,
        ]

        for chart_type in priority_order:
            patterns = self.CHART_TYPE_PATTERNS.get(chart_type, [])
            if any(kw in combined_text for kw in patterns):
                return chart_type

        return ChartType.UNKNOWN

    def score_relevance(self, asset: ImageAsset) -> float:
        """
        Compute relevance score (0-1) for metric extraction.

        Factors:
        - Base score by classification
        - Section context bonus (MD&A most valuable)
        - Keyword proximity bonus (cohort, retention, etc.)

        Args:
            asset: ImageAsset with classification set

        Returns:
            Relevance score (0.0 to 1.0)
        """
        # Base score by classification
        score = self.CLASSIFICATION_BASE_SCORES.get(asset.classification, 0.1)

        # Section bonus
        score += self.SECTION_BONUSES.get(asset.section_type, 0.0)

        # Keyword bonus
        text_lower = asset.nearby_text.lower()
        keyword_bonus = 0.0
        for keyword in self.HIGH_VALUE_KEYWORDS:
            if keyword in text_lower:
                keyword_bonus += 0.08  # Each keyword adds 0.08
                if keyword_bonus >= 0.3:  # Cap keyword bonus
                    break

        score += keyword_bonus

        # Cap at 1.0
        return min(1.0, score)

    def triage_images(self, images: list[ImageAsset]) -> list[ImageAsset]:
        """
        Process a batch of images: classify, score, and mark for processing.

        Updates each ImageAsset in place with:
        - classification
        - relevance_score
        - requires_manual_capture (for ambiguous cases)

        Args:
            images: List of ImageAsset objects to process

        Returns:
            List of ImageAsset objects that should be processed by OCR/Vision (relevance >= threshold)
        """
        images_for_processing: list[ImageAsset] = []

        for asset in images:
            # Classify
            asset.classification = self.classify_image(asset)

            # Detect chart type if applicable
            if asset.classification == ImageClassification.CHART:
                # Store chart type in a way that's accessible
                # (ChartData will be populated in Stage 5)
                pass  # Chart type detection happens when scoring

            # Score relevance
            asset.relevance_score = self.score_relevance(asset)

            # Mark for manual capture if ambiguous
            if (
                asset.classification == ImageClassification.UNKNOWN
                and asset.relevance_score >= self.MIN_RELEVANCE_FOR_PROCESSING
                and asset.relevance_score < self.AMBIGUOUS_RELEVANCE_THRESHOLD
            ):
                asset.requires_manual_capture = True

            # Queue for processing if relevant
            if asset.relevance_score >= self.MIN_RELEVANCE_FOR_PROCESSING:
                images_for_processing.append(asset)

        logger.info(
            f"Triage complete: {len(images)} images processed, "
            f"{len(images_for_processing)} queued for OCR/Vision"
        )

        return images_for_processing

    def process(self, context: pipeline.PipelineContext) -> pipeline.StageResult:
        """
        Process all images in context, setting classification and relevance.

        Modifies context.images in place.

        Args:
            context: Pipeline context with images list

        Returns:
            StageResult with processing metrics
        """
        # Import here to avoid circular import
        from src.extraction_v2.pipeline import PipelineStage, StageResult

        start_time = datetime.utcnow()
        errors: list[str] = []
        warnings: list[str] = []

        try:
            # Handle empty images list
            if not context.images:
                logger.info("No images to triage")
                duration_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)
                return StageResult(
                    stage=PipelineStage.IMAGE_TRIAGE,
                    success=True,
                    duration_ms=duration_ms,
                    items_processed=0,
                    items_output=0,
                    errors=errors,
                    warnings=warnings,
                    metadata={"message": "No images to process"},
                )

            # Triage all images
            images_for_processing = self.triage_images(context.images)

            # Compute statistics
            classification_counts: dict[str, int] = {}
            for asset in context.images:
                cls_name = asset.classification.value
                classification_counts[cls_name] = classification_counts.get(cls_name, 0) + 1

            duration_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)

            return StageResult(
                stage=PipelineStage.IMAGE_TRIAGE,
                success=True,
                duration_ms=duration_ms,
                items_processed=len(context.images),
                items_output=len(images_for_processing),
                errors=errors,
                warnings=warnings,
                metadata={
                    "total_images": len(context.images),
                    "images_for_processing": len(images_for_processing),
                    "classification_counts": classification_counts,
                    "manual_capture_count": sum(
                        1 for img in context.images if img.requires_manual_capture
                    ),
                },
            )

        except Exception as e:
            logger.exception(f"Image triage stage failed: {e}")
            duration_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)
            return StageResult(
                stage=PipelineStage.IMAGE_TRIAGE,
                success=False,
                duration_ms=duration_ms,
                items_processed=0,
                items_output=0,
                errors=[str(e)],
                warnings=warnings,
            )
