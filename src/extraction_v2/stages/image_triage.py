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
import os
import re
from collections import Counter
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from src.extraction_v2.exceptions import V2FatalError
from src.extraction_v2.models import (
    ChartType,
    ImageAsset,
    ImageClassification,
    SectionType,
)
from src.shared.image_features import predict_relevance, v2_row_to_features_input

if TYPE_CHECKING:
    from src.extraction_v2 import pipeline

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Learned triage feature flags
# ---------------------------------------------------------------------------
# Set USE_LEARNED_TRIAGE=true to enable the gradient-boosted triage gate.
# When true and the model artifact loads, predicted_relevance replaces the
# heuristic relevance_score threshold for the pass/fail decision.
# LEARNED_TRIAGE_MIN controls the minimum predicted score (default 0.4).
# When false (default), or when the model is absent, existing heuristic
# behavior is preserved exactly.
_USE_LEARNED_TRIAGE: bool = os.environ.get("USE_LEARNED_TRIAGE", "false").lower() == "true"
_LEARNED_TRIAGE_MIN: float = float(os.environ.get("LEARNED_TRIAGE_MIN", "0.4"))


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
    REPEATED_FILENAME_THRESHOLD: int = 5  # Filenames appearing more than this are decorative

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
        ImageClassification.FULL_PAGE_SCAN: 0.6,
    }

    # ------------------------------------------------------------------
    # Full-page-scan detection (Path A)
    # Fires when a filing is mostly page-image scans rather than HTML text
    # (PayPal-style 8-Ks, some investor-day 8-K decks). See plan file
    # Risk callout "Detector precision" for tuning rationale.
    # ------------------------------------------------------------------
    # Estimated characters per "page" of HTML body text, used to convert
    # total text volume into a page-equivalent count for the ratio gate.
    FULL_PAGE_SCAN_CHARS_PER_PAGE: int = 2000

    # Minimum absolute image count before the detector fires. Prevents
    # trivial filings (one cover image on a tiny 8-K) from tripping.
    FULL_PAGE_SCAN_MIN_IMAGES: int = 5

    # images_per_page gate. A filing qualifies when image_count /
    # max(1, total_text_chars/CHARS_PER_PAGE) >= this value.
    FULL_PAGE_SCAN_MIN_RATIO: float = 1.5

    # Fraction of images that must be "page-shaped" to qualify the filing.
    FULL_PAGE_SCAN_MIN_PAGE_SHAPED_FRACTION: float = 0.70

    # Page-shape bounds (portrait US Letter / A4 approximate).
    PAGE_SHAPED_ASPECT_MIN: float = 0.7
    PAGE_SHAPED_ASPECT_MAX: float = 0.85
    PAGE_SHAPED_WIDTH_MIN: int = 900
    PAGE_SHAPED_WIDTH_MAX: int = 1300

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

        # Explicit table references (in text or filename).
        # Note: no _is_chart() guard here — classify_image() checks _is_table_image
        # BEFORE _is_chart(), so table-structural signals win on conflict.
        table_keywords = ["table", "schedule", "summary of", "breakdown"]
        if any(kw in combined_text for kw in table_keywords):
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
        3. Table image detection (explicit structural signals — before chart)
        4. Chart detection (filename + text patterns)
        5. Decorative detection (fallback)
        6. Unknown

        Note on ordering (A1, 2026-04-28): _is_table_image runs before _is_chart
        so that images with explicit table signals (filename/text keyword "table",
        "schedule", etc. OR wide aspect-ratio + financial keywords) are routed to
        the table-OCR path instead of the chart path.  _is_chart's broad
        "large/dimensionless + metric keyword" branch (lines 287-298) would
        otherwise claim most PayPal-style cohort tables.  The inner
        `not self._is_chart()` guard that previously lived in _is_table_image was
        removed at the same time — it is now redundant (and was self-conflicting).

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

        # 3. Table image detection (structural signals take priority over chart)
        if self._is_table_image(asset):
            return ImageClassification.TABLE_IMAGE

        # 4. Chart detection
        if self._is_chart(asset):
            return ImageClassification.CHART

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

    def _is_page_shaped(self, asset: ImageAsset) -> bool:
        """Return True if an image has the aspect/width of a scanned page.

        Accepts images with explicit dimensions matching the portrait-page
        window, OR images with no declared dimensions (SEC filings often
        omit width/height on ``<img>`` tags for scanned exhibits) — the
        enclosing detector's ratio gate will still reject filings that
        aren't really page-scan decks.
        """
        width = asset.width
        height = asset.height
        if width <= 0 or height <= 0:
            # No dimensions: defer judgment to the filing-wide detector.
            return True
        aspect = width / height
        return (
            self.PAGE_SHAPED_ASPECT_MIN <= aspect <= self.PAGE_SHAPED_ASPECT_MAX
            and self.PAGE_SHAPED_WIDTH_MIN <= width <= self.PAGE_SHAPED_WIDTH_MAX
        )

    def _detect_full_page_scan_filing(self, context: pipeline.PipelineContext) -> bool:
        """Return True if this filing is a page-image deck.

        All three conditions must hold:
          1. ``image_count >= FULL_PAGE_SCAN_MIN_IMAGES``
          2. ``image_count / max(1, text_chars / CHARS_PER_PAGE) >=
             FULL_PAGE_SCAN_MIN_RATIO``
          3. ``page_shaped_fraction >= FULL_PAGE_SCAN_MIN_PAGE_SHAPED_FRACTION``

        This is intentionally strict — detector false positives would
        spend vision calls on normal filings. See plan file risk callout
        "Detector precision" for the rationale behind each threshold.
        """
        images = context.images
        image_count = len(images)
        if image_count < self.FULL_PAGE_SCAN_MIN_IMAGES:
            return False

        total_text_chars = sum(len(s.text or "") for s in context.segments)
        pages_of_text = max(1.0, total_text_chars / self.FULL_PAGE_SCAN_CHARS_PER_PAGE)
        images_per_page = image_count / pages_of_text
        if images_per_page < self.FULL_PAGE_SCAN_MIN_RATIO:
            return False

        page_shaped_count = sum(1 for img in images if self._is_page_shaped(img))
        page_shaped_fraction = page_shaped_count / image_count
        if page_shaped_fraction < self.FULL_PAGE_SCAN_MIN_PAGE_SHAPED_FRACTION:
            return False

        logger.info(
            "Full-page-scan detector fired: %d images, %d text chars "
            "(%.2f images/page, %.0f%% page-shaped)",
            image_count,
            total_text_chars,
            images_per_page,
            100 * page_shaped_fraction,
        )
        return True

    def _promote_to_full_page_scan(self, context: pipeline.PipelineContext) -> list[ImageAsset]:
        """Reclassify page-shaped images to FULL_PAGE_SCAN and queue them.

        Called only after ``_detect_full_page_scan_filing`` returns True.
        Overrides prior triage verdicts (UNKNOWN / CHART / TABLE_IMAGE /
        etc.) on page-shaped images only — logos and very small images
        keep their heuristic classification.
        """
        promoted: list[ImageAsset] = []
        for asset in context.images:
            if not self._is_page_shaped(asset):
                continue
            asset.classification = ImageClassification.FULL_PAGE_SCAN
            asset.relevance_score = max(
                asset.relevance_score,
                self.CLASSIFICATION_BASE_SCORES[ImageClassification.FULL_PAGE_SCAN],
            )
            asset.requires_manual_capture = False
            promoted.append(asset)
        return promoted

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

        # Pre-count filename occurrences: filenames repeated more than threshold
        # times are decorative repeating elements (headers, footers, watermarks).
        filename_counts = Counter(a.filename for a in images if a.filename)
        repeated_filenames = {
            fn for fn, count in filename_counts.items() if count > self.REPEATED_FILENAME_THRESHOLD
        }

        for asset in images:
            # Override classification for repeated decorative filenames
            if asset.filename in repeated_filenames:
                asset.classification = ImageClassification.DECORATIVE
                asset.relevance_score = 0.0
                continue

            # Classify
            asset.classification = self.classify_image(asset)

            # Score relevance
            asset.relevance_score = self.score_relevance(asset)

            # Learned triage gate (USE_LEARNED_TRIAGE=true)
            # When enabled and the model loads, write predicted_relevance onto
            # the asset and use it in place of the heuristic threshold check.
            # Falls back transparently to heuristic when model is absent.
            queued: bool
            if _USE_LEARNED_TRIAGE:
                features = v2_row_to_features_input(
                    {
                        "nearby_text": asset.nearby_text,
                        "relevance_score": asset.relevance_score,
                        "width": asset.width or None,
                        "height": asset.height or None,
                        "classification": asset.classification.value,
                        "filename": asset.filename,
                    }
                )
                score = predict_relevance(features)
                if score is not None:
                    asset.predicted_relevance = score
                    queued = score >= _LEARNED_TRIAGE_MIN
                else:
                    # Model absent — fall back to heuristic
                    queued = asset.relevance_score >= self.MIN_RELEVANCE_FOR_PROCESSING
            else:
                queued = asset.relevance_score >= self.MIN_RELEVANCE_FOR_PROCESSING

            # Mark for manual capture if ambiguous (heuristic; applies in both modes)
            if (
                asset.classification == ImageClassification.UNKNOWN
                and asset.relevance_score >= self.MIN_RELEVANCE_FOR_PROCESSING
                and asset.relevance_score < self.AMBIGUOUS_RELEVANCE_THRESHOLD
            ):
                asset.requires_manual_capture = True

            # Queue for processing if relevant
            if queued:
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

        start_time = datetime.now(UTC)
        errors: list[str] = []
        warnings: list[str] = []

        try:
            # Handle empty images list
            if not context.images:
                logger.info("No images to triage")
                duration_ms = int((datetime.now(UTC) - start_time).total_seconds() * 1000)
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

            # Path A: full-page-scan detection. Runs after per-image triage
            # because it may override prior classifications on page-shaped
            # images when the filing-wide pattern matches. ``context.config``
            # is typed as required but some test fixtures omit it, so we
            # defensively default to off when it's absent.
            full_page_scan_fired = False
            full_page_ocr_enabled = bool(
                getattr(context, "config", None)
                and getattr(context.config, "enable_full_page_ocr", False)
            )
            if full_page_ocr_enabled and self._detect_full_page_scan_filing(context):
                full_page_scan_fired = True
                promoted = self._promote_to_full_page_scan(context)
                # Merge promoted images into the to-process list, preserving
                # order and de-duplicating by identity.
                existing_ids = {id(img) for img in images_for_processing}
                for asset in promoted:
                    if id(asset) not in existing_ids:
                        images_for_processing.append(asset)
                context.full_page_scan_mode = True

            # Compute statistics
            classification_counts: dict[str, int] = {}
            for asset in context.images:
                cls_name = asset.classification.value
                classification_counts[cls_name] = classification_counts.get(cls_name, 0) + 1

            duration_ms = int((datetime.now(UTC) - start_time).total_seconds() * 1000)

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
                    "images_seen": len(context.images),
                    "images_for_processing": len(images_for_processing),
                    "classification_counts": classification_counts,
                    # Per-classification counters for downstream benchmark use (A2).
                    # Names mirror ImageClassification enum values.
                    "classified_chart": classification_counts.get("chart", 0),
                    "classified_table": classification_counts.get("table_image", 0),
                    "classified_decorative": classification_counts.get("decorative", 0),
                    "classified_logo": classification_counts.get("logo", 0),
                    "classified_signature": classification_counts.get("signature", 0),
                    "classified_unknown": classification_counts.get("unknown", 0),
                    "classified_full_page_scan": classification_counts.get("full_page_scan", 0),
                    "manual_capture_count": sum(
                        1 for img in context.images if img.requires_manual_capture
                    ),
                    "full_page_scan_mode": full_page_scan_fired,
                },
            )

        except V2FatalError:
            raise
        except Exception as e:
            raise V2FatalError(str(e), stage_name="image_triage") from e
