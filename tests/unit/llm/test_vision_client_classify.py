"""Unit tests for metric-classify helpers in VisionClient.

Covers:
- CLASSIFY_PROMPT / CLASSIFY_REJECTION_REASONS module constants
- _strip_markdown_fences
- _parse_classify_response (happy path + edge cases)
- VisionClient.analyze_image_for_metric_classification (mocked)
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from src.llm.vision_client import (
    _TIER1_METRIC_IDS,
    _TIER2_METRIC_IDS,
    CLASSIFY_PROMPT,
    CLASSIFY_REJECTION_REASONS,
    VisionClient,
    VisionResponse,
    _parse_classify_response,
    _strip_markdown_fences,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _valid_response_json(
    *,
    predicted_metrics: list[str] | None = None,
    confidence: float = 0.9,
    rejection_reason: str | None = None,
    reasoning: str = "Test reason.",
) -> str:
    """Return a valid JSON string for a classify response."""
    if predicted_metrics is None:
        predicted_metrics = []
    return json.dumps(
        {
            "predicted_metrics": predicted_metrics,
            "confidence": confidence,
            "rejection_reason": rejection_reason,
            "reasoning": reasoning,
        }
    )


def _make_vision_response(content: str) -> VisionResponse:
    return VisionResponse(
        content=content,
        model="gemini-2.5-flash-lite",
        prompt_tokens=100,
        completion_tokens=50,
        cost_usd=0.001,
        latency_ms=200,
    )


# ---------------------------------------------------------------------------
# Prompt builder / module-level constants
# ---------------------------------------------------------------------------


class TestClassifyPromptConstants:
    def test_prompt_builds_at_import_without_raising(self):
        """CLASSIFY_PROMPT is non-empty string built at module import."""
        assert isinstance(CLASSIFY_PROMPT, str)
        assert len(CLASSIFY_PROMPT) > 100

    def test_tier1_ids_match_yaml(self):
        """_TIER1_METRIC_IDS is non-empty and sorted."""
        assert len(_TIER1_METRIC_IDS) > 0
        assert list(_TIER1_METRIC_IDS) == sorted(_TIER1_METRIC_IDS)

    def test_tier2_ids_match_yaml(self):
        """_TIER2_METRIC_IDS is non-empty and sorted."""
        assert len(_TIER2_METRIC_IDS) > 0
        assert list(_TIER2_METRIC_IDS) == sorted(_TIER2_METRIC_IDS)

    def test_tier_lists_are_disjoint(self):
        """A metric should not appear in both tiers."""
        overlap = set(_TIER1_METRIC_IDS) & set(_TIER2_METRIC_IDS)
        assert overlap == set()

    def test_prompt_contains_tier1_metric(self):
        """At least one tier-1 metric id appears in the prompt text."""
        assert any(m in CLASSIFY_PROMPT for m in _TIER1_METRIC_IDS)

    def test_prompt_contains_tier2_metric(self):
        """At least one tier-2 metric id appears in the prompt text."""
        assert any(m in CLASSIFY_PROMPT for m in _TIER2_METRIC_IDS)

    def test_rejection_reasons_contains_all_seven(self):
        """CLASSIFY_REJECTION_REASONS contains exactly the required 7 values."""
        expected = {
            "decorative",
            "not_a_chart",
            "wrong_subject",
            "duplicate",
            "unreadable",
            "other",
            "table_handled_elsewhere",
        }
        assert CLASSIFY_REJECTION_REASONS == expected

    def test_table_handled_elsewhere_present(self):
        """table_handled_elsewhere is explicitly present (preemptive #93 fix)."""
        assert "table_handled_elsewhere" in CLASSIFY_REJECTION_REASONS

    def test_prompt_contains_rejection_reasons(self):
        """All rejection reason values appear in the prompt text."""
        for reason in CLASSIFY_REJECTION_REASONS:
            assert reason in CLASSIFY_PROMPT, f"Missing reason {reason!r} in prompt"


# ---------------------------------------------------------------------------
# _strip_markdown_fences
# ---------------------------------------------------------------------------


class TestStripMarkdownFences:
    def test_clean_json_unchanged(self):
        raw = '{"key": "value"}'
        assert _strip_markdown_fences(raw) == raw

    def test_strips_json_fence(self):
        raw = '```json\n{"key": "value"}\n```'
        result = _strip_markdown_fences(raw)
        assert "```" not in result
        assert '"key"' in result

    def test_strips_plain_fence(self):
        raw = '```\n{"key": 1}\n```'
        result = _strip_markdown_fences(raw)
        assert "```" not in result
        assert '"key"' in result

    def test_empty_string_unchanged(self):
        assert _strip_markdown_fences("") == ""

    def test_no_fence_unchanged(self):
        raw = "just some text"
        assert _strip_markdown_fences(raw) == raw


# ---------------------------------------------------------------------------
# _parse_classify_response — happy path
# ---------------------------------------------------------------------------


class TestParseClassifyResponseHappyPath:
    def test_valid_full_response(self):
        """A well-formed JSON response is parsed and returned."""
        # Use a known tier-1 metric
        metric = _TIER1_METRIC_IDS[0]
        raw = _valid_response_json(
            predicted_metrics=[metric],
            confidence=0.85,
            rejection_reason=None,
            reasoning="Cohort chart detected.",
        )
        result = _parse_classify_response(raw)
        assert result is not None
        assert result["predicted_metrics"] == [metric]
        assert result["confidence"] == pytest.approx(0.85)
        assert result["rejection_reason"] is None
        assert result["reasoning"] == "Cohort chart detected."

    def test_empty_metrics_with_reason(self):
        """Empty predicted_metrics + valid rejection_reason is accepted."""
        raw = _valid_response_json(
            predicted_metrics=[],
            confidence=0.0,
            rejection_reason="decorative",
        )
        result = _parse_classify_response(raw)
        assert result is not None
        assert result["predicted_metrics"] == []
        assert result["rejection_reason"] == "decorative"

    def test_confidence_clamped_above_1(self):
        """Confidence > 1.0 is clamped to 1.0."""
        raw = json.dumps(
            {
                "predicted_metrics": [],
                "confidence": 1.5,
                "rejection_reason": "other",
                "reasoning": "",
            }
        )
        result = _parse_classify_response(raw)
        assert result is not None
        assert result["confidence"] == 1.0

    def test_confidence_clamped_below_0(self):
        """Confidence < 0.0 is clamped to 0.0."""
        raw = json.dumps(
            {
                "predicted_metrics": [],
                "confidence": -0.3,
                "rejection_reason": "other",
                "reasoning": "",
            }
        )
        result = _parse_classify_response(raw)
        assert result is not None
        assert result["confidence"] == 0.0


# ---------------------------------------------------------------------------
# _parse_classify_response — edge cases
# ---------------------------------------------------------------------------


class TestParseClassifyResponseEdgeCases:
    def test_null_confidence_becomes_zero(self):
        """null confidence is coerced to 0.0."""
        raw = json.dumps(
            {
                "predicted_metrics": [],
                "confidence": None,
                "rejection_reason": "unreadable",
                "reasoning": "",
            }
        )
        result = _parse_classify_response(raw)
        assert result is not None
        assert result["confidence"] == 0.0

    def test_string_metric_wrapped_in_list(self):
        """A bare string for predicted_metrics is wrapped into a list."""
        metric = _TIER1_METRIC_IDS[0]
        raw = json.dumps(
            {
                "predicted_metrics": metric,
                "confidence": 0.9,
                "rejection_reason": None,
                "reasoning": "",
            }
        )
        result = _parse_classify_response(raw)
        assert result is not None
        assert result["predicted_metrics"] == [metric]

    def test_unknown_rejection_reason_becomes_other(self):
        """An unrecognised rejection_reason is normalised to 'other'."""
        raw = json.dumps(
            {
                "predicted_metrics": [],
                "confidence": 0.0,
                "rejection_reason": "totally_made_up",
                "reasoning": "",
            }
        )
        result = _parse_classify_response(raw)
        assert result is not None
        assert result["rejection_reason"] == "other"

    def test_malformed_json_returns_none(self):
        """Malformed JSON returns None."""
        assert _parse_classify_response("{not valid json") is None

    def test_empty_string_returns_none(self):
        """Empty input returns None."""
        assert _parse_classify_response("") is None

    def test_markdown_fenced_json_parsed(self):
        """Markdown-fenced JSON is unwrapped before parsing."""
        metric = _TIER1_METRIC_IDS[0]
        inner = json.dumps(
            {
                "predicted_metrics": [metric],
                "confidence": 0.7,
                "rejection_reason": None,
                "reasoning": "ok",
            }
        )
        fenced = f"```json\n{inner}\n```"
        result = _parse_classify_response(fenced)
        assert result is not None
        assert result["predicted_metrics"] == [metric]

    def test_metrics_and_reason_both_present_drops_reason(self):
        """When metrics are predicted AND rejection_reason is set, reason is dropped."""
        metric = _TIER1_METRIC_IDS[0]
        raw = json.dumps(
            {
                "predicted_metrics": [metric],
                "confidence": 0.8,
                "rejection_reason": "decorative",
                "reasoning": "mixed signal",
            }
        )
        result = _parse_classify_response(raw)
        assert result is not None
        assert result["predicted_metrics"] == [metric]
        assert result["rejection_reason"] is None

    def test_non_dict_json_returns_none(self):
        """A valid JSON array (not dict) returns None."""
        assert _parse_classify_response("[1, 2, 3]") is None

    def test_unknown_metric_ids_filtered(self):
        """Metric ids not in the tier lists are silently filtered out."""
        valid_metric = _TIER1_METRIC_IDS[0]
        raw = json.dumps(
            {
                "predicted_metrics": [valid_metric, "cm_does_not_exist_xyz"],
                "confidence": 0.9,
                "rejection_reason": None,
                "reasoning": "",
            }
        )
        result = _parse_classify_response(raw)
        assert result is not None
        assert result["predicted_metrics"] == [valid_metric]


# ---------------------------------------------------------------------------
# VisionClient.analyze_image_for_metric_classification — mocked
# ---------------------------------------------------------------------------


class TestAnalyzeImageForMetricClassification:
    """All tests mock analyze_image — no real API calls."""

    FAKE_IMAGE = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100  # valid PNG magic

    def _make_client(self) -> VisionClient:
        """Create a VisionClient without a real API key (provider is mocked)."""
        with patch("src.llm.providers.openai.OpenAI"):
            client = VisionClient(model="gpt-4o-mini")
        return client

    def test_uses_classify_prompt(self):
        """analyze_image is called with CLASSIFY_PROMPT."""
        client = self._make_client()
        metric = _TIER1_METRIC_IDS[0]
        response_json = json.dumps(
            {
                "predicted_metrics": [metric],
                "confidence": 0.9,
                "rejection_reason": None,
                "reasoning": "ok",
            }
        )

        with patch.object(
            client, "analyze_image", return_value=_make_vision_response(response_json)
        ) as mock_ai:
            result = client.analyze_image_for_metric_classification(self.FAKE_IMAGE)

        call_kwargs = mock_ai.call_args
        assert (
            call_kwargs.kwargs["prompt"] == CLASSIFY_PROMPT
            or call_kwargs.args[1] == CLASSIFY_PROMPT
        )
        assert result is not None

    def test_uses_json_object_response_format(self):
        """analyze_image is called with response_format={"type": "json_object"}."""
        client = self._make_client()
        metric = _TIER1_METRIC_IDS[0]
        response_json = json.dumps(
            {
                "predicted_metrics": [metric],
                "confidence": 0.9,
                "rejection_reason": None,
                "reasoning": "",
            }
        )

        with patch.object(
            client, "analyze_image", return_value=_make_vision_response(response_json)
        ) as mock_ai:
            client.analyze_image_for_metric_classification(self.FAKE_IMAGE)

        call_kwargs = mock_ai.call_args
        assert call_kwargs.kwargs.get("response_format") == {"type": "json_object"}

    def test_happy_path_returns_parsed_dict(self):
        """A valid API response returns the parsed dict."""
        client = self._make_client()
        metric = _TIER1_METRIC_IDS[0]
        response_json = json.dumps(
            {
                "predicted_metrics": [metric],
                "confidence": 0.88,
                "rejection_reason": None,
                "reasoning": "Cohort parfait visible.",
            }
        )

        with patch.object(
            client, "analyze_image", return_value=_make_vision_response(response_json)
        ):
            result = client.analyze_image_for_metric_classification(self.FAKE_IMAGE)

        assert result is not None
        assert result["predicted_metrics"] == [metric]
        assert result["confidence"] == pytest.approx(0.88)
        assert result["rejection_reason"] is None
        assert result["reasoning"] == "Cohort parfait visible."
        assert result["_cost_usd"] == pytest.approx(0.001)

    def test_api_error_returns_none(self):
        """An exception from analyze_image is caught and returns None."""
        client = self._make_client()

        with patch.object(client, "analyze_image", side_effect=RuntimeError("API down")):
            result = client.analyze_image_for_metric_classification(self.FAKE_IMAGE)

        assert result is None

    def test_unparseable_response_returns_none(self):
        """A response that fails JSON parsing returns None."""
        client = self._make_client()

        with patch.object(
            client, "analyze_image", return_value=_make_vision_response("not json at all")
        ):
            result = client.analyze_image_for_metric_classification(self.FAKE_IMAGE)

        assert result is None

    def test_default_max_tokens_is_400(self):
        """Default max_tokens passed to analyze_image is 400."""
        client = self._make_client()
        metric = _TIER1_METRIC_IDS[0]
        response_json = json.dumps(
            {
                "predicted_metrics": [metric],
                "confidence": 0.9,
                "rejection_reason": None,
                "reasoning": "",
            }
        )

        with patch.object(
            client, "analyze_image", return_value=_make_vision_response(response_json)
        ) as mock_ai:
            client.analyze_image_for_metric_classification(self.FAKE_IMAGE)

        assert mock_ai.call_args.kwargs.get("max_tokens") == 400

    def test_custom_max_tokens_forwarded(self):
        """Explicit max_tokens is forwarded to analyze_image."""
        client = self._make_client()
        metric = _TIER1_METRIC_IDS[0]
        response_json = json.dumps(
            {
                "predicted_metrics": [metric],
                "confidence": 0.9,
                "rejection_reason": None,
                "reasoning": "",
            }
        )

        with patch.object(
            client, "analyze_image", return_value=_make_vision_response(response_json)
        ) as mock_ai:
            client.analyze_image_for_metric_classification(self.FAKE_IMAGE, max_tokens=200)

        assert mock_ai.call_args.kwargs.get("max_tokens") == 200
