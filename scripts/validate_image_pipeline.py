"""
Diagnostic script: validate ImageTriageStage against Farfetch gold standard.

Runs ImageTriageStage directly (bypassing V2Pipeline's _check_vision_api_availability)
against data/gold_standard/Farfetch_Limited/filing.html and reports per-image results.

Asserts that g607688g54x53.jpg is classified as CHART with relevance >= 0.3.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

# Resolve project root so this script can be run from any CWD.
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.extraction_v2.models import ImageClassification  # noqa: E402
from src.extraction_v2.pipeline import (  # noqa: E402
    PipelineConfig,
    PipelineContext,
)
from src.extraction_v2.stages.image_triage import ImageTriageStage  # noqa: E402
from src.extraction_v2.stages.ingestion import IngestionStage  # noqa: E402
from src.extraction_v2.stages.section_classification import SectionClassificationStage  # noqa: E402
from src.extraction_v2.stages.table_reconstruction import TableReconstructionStage  # noqa: E402

FILING_PATH = PROJECT_ROOT / "data" / "gold_standard" / "Farfetch_Limited" / "filing.html"
TARGET_IMAGE = "g607688g54x53.jpg"
MIN_RELEVANCE = 0.3


def main() -> None:
    if not FILING_PATH.exists():
        print(f"FAIL: filing not found at {FILING_PATH}")
        sys.exit(1)

    config = PipelineConfig(
        enable_image_extraction=True,
        enable_chart_extraction=False,  # Don't need OCR for this check
    )

    context = PipelineContext(
        html_path=FILING_PATH,
        filing_id=0,
        config=config,
    )

    # Stage 1: Ingestion (populates context.images)
    print("Running Stage 1: Ingestion...")
    IngestionStage().process(context)
    print(f"  Found {len(context.images)} images, {len(context.segments)} segments")

    # Stage 2: Section Classification
    print("Running Stage 2: Section Classification...")
    SectionClassificationStage().process(context)

    # Stage 3: Table Reconstruction
    print("Running Stage 3: Table Reconstruction...")
    TableReconstructionStage().process(context)

    # Stage 4: Image Triage (called directly — no API check)
    print("Running Stage 4: Image Triage...")
    ImageTriageStage().process(context)

    # Report results
    print(f"\n{'img_id':<35} {'classification':<18} {'chart_type':<14} {'relevance':>9}  nearby_text[:60]")
    print("-" * 120)

    target_asset = None
    for asset in context.images:
        chart_type_str = asset.chart_data.chart_type.value if asset.chart_data else "-"
        nearby_preview = asset.nearby_text[:60].replace("\n", " ")
        print(
            f"{asset.img_id:<35} {asset.classification.value:<18} {chart_type_str:<14} "
            f"{asset.relevance_score:>9.3f}  {nearby_preview}"
        )
        if asset.img_id == TARGET_IMAGE or asset.filename == TARGET_IMAGE:
            target_asset = asset

    print()

    # Assert target image classification
    if target_asset is None:
        print(f"FAIL: target image '{TARGET_IMAGE}' not found in context.images")
        sys.exit(1)

    errors = []
    if target_asset.classification != ImageClassification.CHART:
        errors.append(
            f"classification is {target_asset.classification.value!r}, expected 'chart'"
        )
    if target_asset.relevance_score < MIN_RELEVANCE:
        errors.append(
            f"relevance_score={target_asset.relevance_score:.3f} < {MIN_RELEVANCE}"
        )

    if errors:
        print(f"FAIL for '{TARGET_IMAGE}':")
        for err in errors:
            print(f"  - {err}")
        sys.exit(1)

    print(
        f"PASS: '{TARGET_IMAGE}' classified as CHART "
        f"with relevance={target_asset.relevance_score:.3f} >= {MIN_RELEVANCE}"
    )


if __name__ == "__main__":
    main()
