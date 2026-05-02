"""
Per-site vision model env knobs (PR 2 of vision cost experiments).

Validates that:
- PipelineConfig defaults triage sites to Gemini regardless of VISION_PROVIDER.
- Env overrides flow into config via _apply_env_feature_flags.
- The auxiliary cheap client is used for full_page_ocr and prescan, not
  stage.vision_client.
- Cost telemetry continues to attribute correctly after the call-site swap.
- _build_cheap_ocr_client restores VISION_PROVIDER and VISION_MODEL_OCR after
  building the client.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.extraction_v2.models import ImageAsset, ImageClassification
from src.extraction_v2.pipeline import PipelineConfig, PipelineContext, V2Pipeline
from src.extraction_v2.stages.ocr_extraction import OCRExtractionStage, _build_cheap_ocr_client
from src.llm.vision_client import PageTextExtraction

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _route_image_cache_to_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from src.infra.image_storage import get_image_storage
    from src.infra.paths import image_cache_dir

    monkeypatch.setenv("IMAGE_CACHE_DIR", str(tmp_path))
    monkeypatch.delenv("R2_BUCKET", raising=False)
    image_cache_dir.cache_clear()
    get_image_storage.cache_clear()
    yield  # type: ignore[misc]
    image_cache_dir.cache_clear()
    get_image_storage.cache_clear()


def _write_full_page_jpg(path: Path) -> None:
    path.write_bytes(b"\xff\xd8\xff\xe0fake-jpeg-bytes")


def _full_page_scan_asset(filename: str) -> ImageAsset:
    return ImageAsset(
        img_id="p1",
        filename=filename,
        file_path=filename,
        width=1055,
        height=1365,
        classification=ImageClassification.FULL_PAGE_SCAN,
        relevance_score=0.6,
    )


def _prescan_asset(filename: str) -> ImageAsset:
    return ImageAsset(
        img_id="u1",
        filename=filename,
        file_path=filename,
        nearby_text="",
        width=800,
        height=600,
        classification=ImageClassification.UNKNOWN,
        relevance_score=0.25,
    )


def _make_context(
    tmp_path: Path,
    images: list[ImageAsset],
    config: PipelineConfig,
) -> PipelineContext:
    return PipelineContext(
        html_path=tmp_path / "test.html",
        filing_id=1,
        config=config,
        images=images,
    )


def _text_extraction(cost: float = 0.01) -> PageTextExtraction:
    return PageTextExtraction(
        text="Revenue $100M",
        contains_chart=False,
        contains_table=False,
        chart_hint="none",
        cost_usd=cost,
        raw_response="",
    )


# ---------------------------------------------------------------------------
# 1. Default config — triage sites default to Gemini
# ---------------------------------------------------------------------------


class TestDefaultConfig:
    def test_full_page_ocr_defaults_to_gemini(self) -> None:
        cfg = PipelineConfig()
        assert cfg.vision_full_page_ocr_provider == "gemini"
        assert cfg.vision_full_page_ocr_model == "gemini-2.5-flash-lite"

    def test_prescan_defaults_to_gemini(self) -> None:
        cfg = PipelineConfig()
        assert cfg.vision_prescan_provider == "gemini"
        assert cfg.vision_prescan_model == "gemini-2.5-flash-lite"


# ---------------------------------------------------------------------------
# 2. Env overrides flow into config
# ---------------------------------------------------------------------------


class TestEnvOverrides:
    def test_vision_model_full_page_ocr_env_flows_into_config(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("VISION_MODEL_FULL_PAGE_OCR", "gemini-2.0-flash-lite")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        pipeline = V2Pipeline()
        assert pipeline.config.vision_full_page_ocr_model == "gemini-2.0-flash-lite"

    def test_vision_provider_prescan_env_flows_into_config(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("VISION_PROVIDER_PRESCAN", "anthropic")
        monkeypatch.setenv("VISION_MODEL_PRESCAN", "claude-haiku-4-5")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        pipeline = V2Pipeline()
        assert pipeline.config.vision_prescan_provider == "anthropic"
        assert pipeline.config.vision_prescan_model == "claude-haiku-4-5"


# ---------------------------------------------------------------------------
# 3. Legacy-mode safety: VISION_PROVIDER=openai does not bleed into triage defaults
# ---------------------------------------------------------------------------


class TestLegacyModeSafety:
    def test_global_openai_provider_does_not_override_triage_defaults(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("VISION_PROVIDER", "openai")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        pipeline = V2Pipeline()
        assert pipeline.config.vision_full_page_ocr_provider == "gemini"
        assert pipeline.config.vision_prescan_provider == "gemini"


# ---------------------------------------------------------------------------
# 4. Auxiliary client used at correct sites; main vision_client not called
# ---------------------------------------------------------------------------


class TestAuxiliaryClientRouting:
    def test_full_page_ocr_uses_cheap_client_not_main_client(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        jpg = tmp_path / "page.jpg"
        _write_full_page_jpg(jpg)

        cheap_client = MagicMock()
        cheap_client.analyze_image_for_text.return_value = _text_extraction(cost=0.002)

        main_client = MagicMock()

        monkeypatch.setattr(
            "src.extraction_v2.stages.ocr_extraction._build_cheap_ocr_client",
            lambda provider, model: cheap_client,
        )

        stage = OCRExtractionStage(vision_client=main_client)
        ctx = _make_context(
            tmp_path,
            [_full_page_scan_asset(jpg.name)],
            PipelineConfig(enable_full_page_ocr=True),
        )
        stage.process(ctx)

        cheap_client.analyze_image_for_text.assert_called_once()
        main_client.analyze_image_for_text.assert_not_called()

    def test_prescan_uses_cheap_client_not_main_client(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        png = tmp_path / "ambig.png"
        png.write_bytes(
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
            b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
            b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
        )

        cheap_client = MagicMock()
        cheap_client.analyze_image_for_text.return_value = PageTextExtraction(
            text="no tier-1 keyword here",
            contains_chart=False,
            contains_table=False,
            chart_hint="none",
            cost_usd=0.001,
            raw_response="",
        )

        main_client = MagicMock()

        monkeypatch.setattr(
            "src.extraction_v2.stages.ocr_extraction._build_cheap_ocr_client",
            lambda provider, model: cheap_client,
        )

        stage = OCRExtractionStage(vision_client=main_client)
        ctx = _make_context(
            tmp_path,
            [_prescan_asset(png.name)],
            PipelineConfig(enable_image_keyword_prescan=True),
        )
        stage.process(ctx)

        cheap_client.analyze_image_for_text.assert_called_once()
        main_client.analyze_image_for_text.assert_not_called()


# ---------------------------------------------------------------------------
# 5. Cost telemetry attributes correctly post-swap
# ---------------------------------------------------------------------------


class TestCostTelemetryPostSwap:
    def test_full_page_ocr_cost_attributed_correctly(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        jpg = tmp_path / "page.jpg"
        _write_full_page_jpg(jpg)

        cheap_client = MagicMock()
        cheap_client.analyze_image_for_text.return_value = _text_extraction(cost=0.0123)

        monkeypatch.setattr(
            "src.extraction_v2.stages.ocr_extraction._build_cheap_ocr_client",
            lambda provider, model: cheap_client,
        )

        stage = OCRExtractionStage(vision_client=MagicMock())
        ctx = _make_context(
            tmp_path,
            [_full_page_scan_asset(jpg.name)],
            PipelineConfig(enable_full_page_ocr=True),
        )
        result = stage.process(ctx)

        spend = result.metadata["vision_spend_usd_by_site"]
        assert spend["full_page_ocr"] == pytest.approx(0.0123)


# ---------------------------------------------------------------------------
# 6. Env restore after _build_cheap_ocr_client
# ---------------------------------------------------------------------------


class TestEnvRestore:
    def test_build_cheap_ocr_client_restores_env_after_construction(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("VISION_PROVIDER", "openai")
        monkeypatch.setenv("VISION_MODEL_OCR", "gpt-4o")

        # Intercept VisionClient() construction so no real API client is built.
        monkeypatch.setattr(
            "src.llm.vision_client.VisionClient.__init__",
            lambda self: None,
        )

        _build_cheap_ocr_client("gemini", "gemini-2.5-flash-lite")

        assert os.environ.get("VISION_PROVIDER") == "openai"
        assert os.environ.get("VISION_MODEL_OCR") == "gpt-4o"

    def test_build_cheap_ocr_client_restores_absent_env_vars(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("VISION_PROVIDER", raising=False)
        monkeypatch.delenv("VISION_MODEL_OCR", raising=False)

        monkeypatch.setattr(
            "src.llm.vision_client.VisionClient.__init__",
            lambda self: None,
        )

        _build_cheap_ocr_client("gemini", "gemini-2.5-flash-lite")

        assert "VISION_PROVIDER" not in os.environ
        assert "VISION_MODEL_OCR" not in os.environ
