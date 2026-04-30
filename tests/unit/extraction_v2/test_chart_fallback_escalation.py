"""
Chart-read fallback escalation (PR 3 of vision cost experiments).

Validates that:
- PipelineConfig defaults to Sonnet fallback at threshold 0.7.
- Env overrides flow into config via _apply_env_feature_flags.
- No fallback fires when primary confidence >= threshold.
- Fallback fires and replaces primary when primary confidence < threshold and
  fallback confidence > primary confidence.
- Fallback does NOT replace primary when its confidence <= primary confidence.
- Fallback exceptions are non-fatal (primary response is preserved).
- Empty VISION_CHART_FALLBACK_MODEL disables the fallback entirely.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.extraction_v2.models import ImageAsset, ImageClassification
from src.extraction_v2.pipeline import PipelineConfig, PipelineContext, V2Pipeline
from src.extraction_v2.stages.ocr_extraction import OCRExtractionStage
from src.llm.vision_client import VisionResponse

# ---------------------------------------------------------------------------
# Fixtures — route image storage to tmp so get_bytes() resolves
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_dummy_png(path: Path) -> None:
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
        b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )


def _chart_payload(confidence: float = 0.9) -> dict[str, Any]:
    return {
        "chart_type": "bar",
        "title": "Revenue",
        "x_axis_label": "Year",
        "y_axis_label": "USD",
        "confidence": confidence,
        "series": [{"name": "Revenue", "points": [{"x": "2021", "y": 100.0, "label": "100"}]}],
        "annotations": [],
    }


def _vision_response(payload: dict[str, Any], *, cost: float) -> VisionResponse:
    return VisionResponse(
        content=json.dumps(payload),
        model="mock",
        prompt_tokens=10,
        completion_tokens=10,
        cost_usd=cost,
        latency_ms=1,
    )


def _chart_ocr_response(cost: float = 0.005) -> VisionResponse:
    return VisionResponse(
        content=json.dumps({"text": "Revenue\n2021\n100", "labels": ["Revenue"]}),
        model="mock",
        prompt_tokens=5,
        completion_tokens=5,
        cost_usd=cost,
        latency_ms=1,
    )


class _SequencedVisionClient:
    """Returns pre-built VisionResponses in order."""

    def __init__(self, responses: list[VisionResponse]) -> None:
        self.responses = list(responses)
        self.call_count = 0

    def analyze_image(self, image_bytes: bytes, prompt: str, **_: Any) -> VisionResponse:
        if self.call_count >= len(self.responses):
            raise IndexError(f"no more responses (call_count={self.call_count})")
        resp = self.responses[self.call_count]
        self.call_count += 1
        return resp

    def analyze_image_targeted(self, **_: Any) -> VisionResponse:
        return self.analyze_image(image_bytes=b"", prompt="")


def _make_context(
    tmp_path: Path, images: list[ImageAsset], config: PipelineConfig
) -> PipelineContext:
    return PipelineContext(
        html_path=tmp_path / "test.html",
        filing_id=1,
        config=config,
        images=images,
    )


def _chart_asset(tmp_path: Path) -> ImageAsset:
    png = tmp_path / "chart.png"
    _write_dummy_png(png)
    return ImageAsset(
        img_id="c1",
        filename="chart.png",
        nearby_text="Revenue",
        width=800,
        height=600,
        classification=ImageClassification.CHART,
        relevance_score=0.9,
        file_path=png.name,
    )


# ---------------------------------------------------------------------------
# 1. Default config
# ---------------------------------------------------------------------------


class TestDefaultConfig:
    def test_fallback_model_default(self) -> None:
        cfg = PipelineConfig()
        assert cfg.vision_chart_fallback_model == "claude-sonnet-4-6"

    def test_fallback_provider_default(self) -> None:
        cfg = PipelineConfig()
        assert cfg.vision_chart_fallback_provider == "anthropic"

    def test_confidence_threshold_default(self) -> None:
        cfg = PipelineConfig()
        assert cfg.vision_chart_confidence_threshold == 0.7


# ---------------------------------------------------------------------------
# 2. Env override flow
# ---------------------------------------------------------------------------


class TestEnvOverrides:
    def test_fallback_model_env_flows_into_config(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("VISION_CHART_FALLBACK_MODEL", "claude-opus-4-7")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        pipeline = V2Pipeline()
        assert pipeline.config.vision_chart_fallback_model == "claude-opus-4-7"

    def test_confidence_threshold_env_flows_into_config(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("VISION_CHART_CONFIDENCE_THRESHOLD", "0.8")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        pipeline = V2Pipeline()
        assert pipeline.config.vision_chart_confidence_threshold == 0.8

    def test_invalid_threshold_logs_warning_and_keeps_default(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        monkeypatch.setenv("VISION_CHART_CONFIDENCE_THRESHOLD", "not-a-float")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        import logging

        with caplog.at_level(logging.WARNING):
            pipeline = V2Pipeline()
        assert pipeline.config.vision_chart_confidence_threshold == 0.7
        assert "VISION_CHART_CONFIDENCE_THRESHOLD" in caplog.text

    def test_empty_fallback_model_env_disables_fallback(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("VISION_CHART_FALLBACK_MODEL", "")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        pipeline = V2Pipeline()
        assert pipeline.config.vision_chart_fallback_model == ""


# ---------------------------------------------------------------------------
# 3. No escalation when primary confidence >= threshold
# ---------------------------------------------------------------------------


class TestNoEscalationAboveThreshold:
    def test_fallback_client_never_called_when_confidence_high(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("VISION_ROUTING_MODE", "legacy")
        asset = _chart_asset(tmp_path)
        primary_client = _SequencedVisionClient(
            [_vision_response(_chart_payload(confidence=0.9), cost=0.02)]
        )
        config = PipelineConfig(vision_chart_confidence_threshold=0.7)
        stage = OCRExtractionStage(vision_client=primary_client)
        fallback_client = MagicMock()
        monkeypatch.setattr(stage, "_get_chart_fallback_client", lambda ctx: fallback_client)

        stage.process(_make_context(tmp_path, [asset], config))

        fallback_client.analyze_image_targeted.assert_not_called()
        assert stage._chart_fallback_escalations == 0


# ---------------------------------------------------------------------------
# 4. Escalation replaces primary when fallback has higher confidence
# ---------------------------------------------------------------------------


class TestEscalationReplacesLowConfidence:
    def test_fallback_used_when_primary_confidence_below_threshold(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("VISION_ROUTING_MODE", "legacy")
        asset = _chart_asset(tmp_path)

        primary_resp = _vision_response(_chart_payload(confidence=0.5), cost=0.01)
        fallback_resp = _vision_response(_chart_payload(confidence=0.85), cost=0.03)

        primary_client = _SequencedVisionClient([primary_resp])
        fallback_client = _SequencedVisionClient([fallback_resp])

        config = PipelineConfig(vision_chart_confidence_threshold=0.7)
        stage = OCRExtractionStage(vision_client=primary_client)
        monkeypatch.setattr(stage, "_get_chart_fallback_client", lambda ctx: fallback_client)

        result = stage.process(_make_context(tmp_path, [asset], config))

        assert stage._chart_fallback_escalations == 1
        # Both calls' costs land in chart_read_premium
        spend = result.metadata["vision_spend_usd_by_site"]
        assert spend["chart_read_premium"] == pytest.approx(0.01 + 0.03)
        assert result.metadata["chart_fallback_escalations"] == 1

    def test_asset_confidence_reflects_fallback_response(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("VISION_ROUTING_MODE", "legacy")
        asset = _chart_asset(tmp_path)

        primary_client = _SequencedVisionClient(
            [_vision_response(_chart_payload(confidence=0.5), cost=0.01)]
        )
        fallback_client = _SequencedVisionClient(
            [_vision_response(_chart_payload(confidence=0.85), cost=0.03)]
        )
        config = PipelineConfig(vision_chart_confidence_threshold=0.7)
        stage = OCRExtractionStage(vision_client=primary_client)
        monkeypatch.setattr(stage, "_get_chart_fallback_client", lambda ctx: fallback_client)

        stage.process(_make_context(tmp_path, [asset], config))

        assert asset.confidence == pytest.approx(0.85)


# ---------------------------------------------------------------------------
# 5. Fallback rejected when its confidence is lower than primary's
# ---------------------------------------------------------------------------


class TestFallbackRejectedWhenLowerConfidence:
    def test_primary_kept_when_fallback_confidence_lower(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("VISION_ROUTING_MODE", "legacy")
        asset = _chart_asset(tmp_path)

        primary_client = _SequencedVisionClient(
            [_vision_response(_chart_payload(confidence=0.5), cost=0.01)]
        )
        fallback_client = _SequencedVisionClient(
            [_vision_response(_chart_payload(confidence=0.4), cost=0.03)]
        )
        config = PipelineConfig(vision_chart_confidence_threshold=0.7)
        stage = OCRExtractionStage(vision_client=primary_client)
        monkeypatch.setattr(stage, "_get_chart_fallback_client", lambda ctx: fallback_client)

        result = stage.process(_make_context(tmp_path, [asset], config))

        # Escalation count stays 0 — we didn't actually replace the primary
        assert stage._chart_fallback_escalations == 0
        assert result.metadata["chart_fallback_escalations"] == 0
        # Both calls' costs still accumulate
        spend = result.metadata["vision_spend_usd_by_site"]
        assert spend["chart_read_premium"] == pytest.approx(0.01 + 0.03)
        # Asset confidence reflects primary (not replaced by lower fallback)
        assert asset.confidence == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# 6. Fallback exception is non-fatal
# ---------------------------------------------------------------------------


class TestFallbackExceptionNonFatal:
    def test_primary_preserved_on_fallback_exception(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        import logging

        monkeypatch.setenv("VISION_ROUTING_MODE", "legacy")
        asset = _chart_asset(tmp_path)

        primary_client = _SequencedVisionClient(
            [_vision_response(_chart_payload(confidence=0.5), cost=0.01)]
        )
        broken_fallback = MagicMock()
        broken_fallback.analyze_image_targeted.side_effect = RuntimeError("API down")

        config = PipelineConfig(vision_chart_confidence_threshold=0.7)
        stage = OCRExtractionStage(vision_client=primary_client)
        monkeypatch.setattr(stage, "_get_chart_fallback_client", lambda ctx: broken_fallback)

        with caplog.at_level(logging.WARNING):
            result = stage.process(_make_context(tmp_path, [asset], config))

        # No exception bubbled up; asset was still processed
        assert asset.processed is True
        assert result.metadata["chart_fallback_escalations"] == 0
        # Warning logged about the failure
        assert "fallback" in caplog.text.lower()


# ---------------------------------------------------------------------------
# 7. Disable fallback via empty VISION_CHART_FALLBACK_MODEL
# ---------------------------------------------------------------------------


class TestFallbackDisabled:
    def test_empty_fallback_model_skips_escalation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("VISION_ROUTING_MODE", "legacy")
        asset = _chart_asset(tmp_path)

        primary_client = _SequencedVisionClient(
            [_vision_response(_chart_payload(confidence=0.3), cost=0.01)]
        )
        # Even though confidence is well below 0.7, fallback is disabled
        config = PipelineConfig(
            vision_chart_confidence_threshold=0.7,
            vision_chart_fallback_model="",
        )
        stage = OCRExtractionStage(vision_client=primary_client)
        fallback_client = MagicMock()
        monkeypatch.setattr(stage, "_get_chart_fallback_client", lambda ctx: fallback_client)

        stage.process(_make_context(tmp_path, [asset], config))

        fallback_client.analyze_image_targeted.assert_not_called()
        assert stage._chart_fallback_escalations == 0
