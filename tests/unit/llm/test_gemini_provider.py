"""Unit tests for the Gemini vision provider adapter.

Covers:
- _is_thinking_model helper
- GeminiVisionProvider.call_api with mocked google-genai SDK
  - thinking_config is set for Pro models (legacy-091 regression guard)
  - thinking_config is NOT set for Flash / non-thinking models
  - response_mime_type is set when response_format=json_object
  - empty response.text is handled gracefully
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.llm.providers.gemini import _is_thinking_model

# ---------------------------------------------------------------------------
# _is_thinking_model
# ---------------------------------------------------------------------------


class TestIsThinkingModel:
    def test_pro_exact(self):
        assert _is_thinking_model("gemini-2.5-pro") is True

    def test_pro_preview_suffix(self):
        assert _is_thinking_model("gemini-2.5-pro-preview-05-06") is True

    def test_pro_case_insensitive(self):
        assert _is_thinking_model("Gemini-2.5-Pro") is True

    def test_flash_not_thinking(self):
        assert _is_thinking_model("gemini-2.5-flash-lite") is False

    def test_flash_not_thinking_plain(self):
        assert _is_thinking_model("gemini-2.0-flash") is False

    def test_old_pro_not_thinking(self):
        # Gemini 1.5 Pro does not have extended thinking
        assert _is_thinking_model("gemini-1.5-pro") is False

    def test_openai_model_not_thinking(self):
        assert _is_thinking_model("gpt-4o") is False

    def test_empty_string_not_thinking(self):
        assert _is_thinking_model("") is False


# ---------------------------------------------------------------------------
# GeminiVisionProvider.call_api — mocked SDK
# ---------------------------------------------------------------------------

# Minimal PNG bytes (just the magic header + padding)
_FAKE_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100


def _make_fake_response(text: str | None = '{"ok": true}') -> MagicMock:
    """Return a mock Gemini GenerateContentResponse."""
    resp = MagicMock()
    resp.text = text
    usage = MagicMock()
    usage.prompt_token_count = 100
    usage.candidates_token_count = 20
    resp.usage_metadata = usage
    return resp


class TestGeminiProviderCallApi:
    """All tests mock the google-genai SDK — no real API calls."""

    def _make_provider(self, model: str = "gemini-2.0-flash"):
        """Instantiate GeminiVisionProvider with mocked SDK."""
        with patch.dict("os.environ", {"GOOGLE_API_KEY": "test-key"}):
            with patch("google.genai.Client"):
                from src.llm.providers.gemini import GeminiVisionProvider

                provider = GeminiVisionProvider(model=model)
                # Replace the real client with a mock
                provider._client = MagicMock()
                provider._client.models.generate_content.return_value = (
                    _make_fake_response()
                )
                return provider

    def test_thinking_disabled_for_pro_model(self):
        """For Gemini 2.5 Pro, thinking_config with budget=0 is set."""
        provider = self._make_provider(model="gemini-2.5-pro")

        import google.genai.types as genai_types

        captured_configs: list[genai_types.GenerateContentConfig] = []
        real_gcc = genai_types.GenerateContentConfig

        def capture_config(**kwargs):
            cfg = real_gcc(**kwargs)
            captured_configs.append(cfg)
            return cfg

        with patch("google.genai.types.GenerateContentConfig", side_effect=capture_config):
            provider.call_api(
                image_bytes=_FAKE_PNG,
                mime_type="image/png",
                prompt="Classify this chart. Return JSON.",
                max_tokens=400,
                response_format={"type": "json_object"},
            )

        assert captured_configs, "GenerateContentConfig was not instantiated"
        cfg = captured_configs[0]
        assert cfg.thinking_config is not None, (
            "thinking_config should be set for Gemini 2.5 Pro (legacy-091)"
        )
        assert cfg.thinking_config.thinking_budget == 0, (
            "thinking_budget should be 0 to disable thinking"
        )

    def test_thinking_not_set_for_flash_model(self):
        """For Gemini Flash (non-thinking), thinking_config is not set."""
        provider = self._make_provider(model="gemini-2.5-flash-lite")

        import google.genai.types as genai_types

        captured_configs: list[genai_types.GenerateContentConfig] = []
        real_gcc = genai_types.GenerateContentConfig

        def capture_config(**kwargs):
            cfg = real_gcc(**kwargs)
            captured_configs.append(cfg)
            return cfg

        with patch("google.genai.types.GenerateContentConfig", side_effect=capture_config):
            provider.call_api(
                image_bytes=_FAKE_PNG,
                mime_type="image/png",
                prompt="Classify this chart. Return JSON.",
                max_tokens=400,
                response_format={"type": "json_object"},
            )

        assert captured_configs, "GenerateContentConfig was not instantiated"
        cfg = captured_configs[0]
        assert cfg.thinking_config is None, (
            "thinking_config should NOT be set for Flash models"
        )

    def test_response_mime_type_set_for_json_mode(self):
        """response_mime_type='application/json' is set when json_object is requested."""
        provider = self._make_provider(model="gemini-2.0-flash")

        import google.genai.types as genai_types

        captured_configs: list[genai_types.GenerateContentConfig] = []
        real_gcc = genai_types.GenerateContentConfig

        def capture_config(**kwargs):
            cfg = real_gcc(**kwargs)
            captured_configs.append(cfg)
            return cfg

        with patch("google.genai.types.GenerateContentConfig", side_effect=capture_config):
            provider.call_api(
                image_bytes=_FAKE_PNG,
                mime_type="image/png",
                prompt="Return JSON.",
                max_tokens=400,
                response_format={"type": "json_object"},
            )

        assert captured_configs
        cfg = captured_configs[0]
        assert cfg.response_mime_type == "application/json"

    def test_response_mime_type_not_set_without_json_mode(self):
        """response_mime_type is not set when response_format is None."""
        provider = self._make_provider(model="gemini-2.0-flash")

        import google.genai.types as genai_types

        captured_configs: list[genai_types.GenerateContentConfig] = []
        real_gcc = genai_types.GenerateContentConfig

        def capture_config(**kwargs):
            cfg = real_gcc(**kwargs)
            captured_configs.append(cfg)
            return cfg

        with patch("google.genai.types.GenerateContentConfig", side_effect=capture_config):
            provider.call_api(
                image_bytes=_FAKE_PNG,
                mime_type="image/png",
                prompt="Describe this chart.",
                max_tokens=400,
                response_format=None,
            )

        assert captured_configs
        cfg = captured_configs[0]
        assert cfg.response_mime_type is None

    def test_empty_response_text_returns_empty_content(self):
        """When response.text is None or empty, VisionResponse.content is ''."""
        provider = self._make_provider(model="gemini-2.5-pro")
        provider._client.models.generate_content.return_value = _make_fake_response(
            text=None
        )

        resp = provider.call_api(
            image_bytes=_FAKE_PNG,
            mime_type="image/png",
            prompt="Classify this chart. Return JSON.",
            max_tokens=400,
            response_format={"type": "json_object"},
        )

        assert resp.content == ""

    def test_happy_path_returns_response_content(self):
        """A normal response is returned with the text content."""
        provider = self._make_provider(model="gemini-2.5-pro")
        expected_json = '{"predicted_metrics": [], "confidence": 0.0}'
        provider._client.models.generate_content.return_value = _make_fake_response(
            text=expected_json
        )

        resp = provider.call_api(
            image_bytes=_FAKE_PNG,
            mime_type="image/png",
            prompt="Classify this chart. Return JSON.",
            max_tokens=400,
            response_format={"type": "json_object"},
        )

        assert resp.content == expected_json
        assert resp.model == "gemini-2.5-pro"
        assert resp.prompt_tokens == 100
        assert resp.completion_tokens == 20

    def test_pro_preview_model_also_disables_thinking(self):
        """gemini-2.5-pro-preview-05-06 also gets thinking_config set."""
        provider = self._make_provider(model="gemini-2.5-pro-preview-05-06")

        import google.genai.types as genai_types

        captured_configs: list[genai_types.GenerateContentConfig] = []
        real_gcc = genai_types.GenerateContentConfig

        def capture_config(**kwargs):
            cfg = real_gcc(**kwargs)
            captured_configs.append(cfg)
            return cfg

        with patch("google.genai.types.GenerateContentConfig", side_effect=capture_config):
            provider.call_api(
                image_bytes=_FAKE_PNG,
                mime_type="image/png",
                prompt="Classify this chart. Return JSON.",
                max_tokens=400,
                response_format={"type": "json_object"},
            )

        assert captured_configs
        cfg = captured_configs[0]
        assert cfg.thinking_config is not None
        assert cfg.thinking_config.thinking_budget == 0
