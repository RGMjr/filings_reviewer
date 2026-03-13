"""Tests for vision provider abstraction and factory.

Tests:
- create_vision_provider returns correct provider type
- Unknown provider raises ValueError
- OpenAIVisionProvider implements analyze_image
- ClaudeVisionProvider implements analyze_image (mocked)
- VisionClient alias still works
- PipelineConfig has vision_provider and vision_model fields
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.llm.vision_client import OpenAIVisionProvider, VisionClient, VisionResponse
from src.llm.vision_factory import create_vision_provider


class TestVisionFactory:
    """Tests for create_vision_provider factory."""

    def test_openai_provider_returned(self) -> None:
        """create_vision_provider('openai') returns OpenAIVisionProvider."""
        with patch("src.llm.vision_client.OpenAI"):
            provider = create_vision_provider("openai")
        assert isinstance(provider, OpenAIVisionProvider)

    def test_openai_provider_default_model(self) -> None:
        """OpenAI provider uses gpt-4o by default."""
        with patch("src.llm.vision_client.OpenAI"):
            provider = create_vision_provider("openai")
        assert isinstance(provider, OpenAIVisionProvider)
        assert provider.model == "gpt-4o"

    def test_openai_provider_custom_model(self) -> None:
        """OpenAI provider uses the given model override."""
        with patch("src.llm.vision_client.OpenAI"):
            provider = create_vision_provider("openai", model="gpt-4o-mini")
        assert isinstance(provider, OpenAIVisionProvider)
        assert provider.model == "gpt-4o-mini"

    def test_claude_provider_returned(self) -> None:
        """create_vision_provider('claude') returns ClaudeVisionProvider."""
        with patch("anthropic.Anthropic"):
            provider = create_vision_provider("claude")
        from src.llm.claude_vision_provider import ClaudeVisionProvider

        assert isinstance(provider, ClaudeVisionProvider)

    def test_claude_provider_default_model(self) -> None:
        """Claude provider uses claude-opus-4-5 by default."""
        with patch("anthropic.Anthropic"):
            provider = create_vision_provider("claude")
        assert provider.model == "claude-opus-4-5"

    def test_claude_provider_custom_model(self) -> None:
        """Claude provider uses the given model override."""
        with patch("anthropic.Anthropic"):
            provider = create_vision_provider("claude", model="claude-haiku-4-5-20251001")
        assert provider.model == "claude-haiku-4-5-20251001"

    def test_unknown_provider_raises_value_error(self) -> None:
        """Unknown provider name raises ValueError."""
        with pytest.raises(ValueError, match="Unknown vision provider"):
            create_vision_provider("gemini")

    def test_unknown_provider_error_message_contains_name(self) -> None:
        """ValueError message includes the bad provider name."""
        with pytest.raises(ValueError, match="'badprovider'"):
            create_vision_provider("badprovider")


class TestVisionClientAlias:
    """Tests that VisionClient backward-compat alias still works."""

    def test_vision_client_is_openai_provider(self) -> None:
        """VisionClient is an alias for OpenAIVisionProvider."""
        assert VisionClient is OpenAIVisionProvider

    def test_vision_client_instantiates(self) -> None:
        """VisionClient can be instantiated (same as OpenAIVisionProvider)."""
        with patch("src.llm.vision_client.OpenAI"):
            client = VisionClient()
        assert isinstance(client, OpenAIVisionProvider)


class TestClaudeVisionProvider:
    """Tests for ClaudeVisionProvider.analyze_image (mocked API)."""

    def _make_provider(self) -> object:
        """Create a ClaudeVisionProvider with a mocked Anthropic client."""
        with patch("anthropic.Anthropic"):
            from src.llm.claude_vision_provider import ClaudeVisionProvider

            return ClaudeVisionProvider()

    def test_analyze_image_returns_vision_response(self) -> None:
        """analyze_image returns a VisionResponse on success."""
        from src.llm.claude_vision_provider import ClaudeVisionProvider

        provider = self._make_provider()
        assert isinstance(provider, ClaudeVisionProvider)

        # Build a realistic Anthropic response mock
        mock_usage = MagicMock()
        mock_usage.input_tokens = 500
        mock_usage.output_tokens = 100

        mock_content_block = MagicMock()
        mock_content_block.text = '{"chart_type": "bar"}'

        mock_response = MagicMock()
        mock_response.content = [mock_content_block]
        mock_response.usage = mock_usage

        provider._client.messages.create.return_value = mock_response

        image_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        result = provider.analyze_image(image_bytes=image_bytes, prompt="Extract data")

        assert isinstance(result, VisionResponse)
        assert result.content == '{"chart_type": "bar"}'
        assert result.prompt_tokens == 500
        assert result.completion_tokens == 100
        assert result.model == "claude-opus-4-5"

    def test_analyze_image_empty_bytes_raises(self) -> None:
        """Empty image_bytes raises ValueError."""
        provider = self._make_provider()
        with pytest.raises(ValueError, match="image_bytes cannot be empty"):
            provider.analyze_image(image_bytes=b"", prompt="Extract data")

    def test_analyze_image_empty_prompt_raises(self) -> None:
        """Empty prompt raises ValueError."""
        provider = self._make_provider()
        with pytest.raises(ValueError, match="prompt cannot be empty"):
            provider.analyze_image(image_bytes=b"\x89PNG\r\n", prompt="   ")

    def test_api_error_propagates(self) -> None:
        """anthropic.APIError is re-raised."""
        import anthropic

        from src.llm.claude_vision_provider import ClaudeVisionProvider

        provider = self._make_provider()
        assert isinstance(provider, ClaudeVisionProvider)
        provider._client.messages.create.side_effect = anthropic.APIError(
            message="rate limit", request=MagicMock(), body=None
        )

        with pytest.raises(anthropic.APIError):
            provider.analyze_image(image_bytes=b"\x89PNG", prompt="Extract data")


class TestPipelineConfigVisionFields:
    """Tests that PipelineConfig has vision_provider and vision_model fields."""

    def test_default_vision_provider(self) -> None:
        """vision_provider defaults to 'openai'."""
        from src.extraction_v2.pipeline import PipelineConfig

        config = PipelineConfig()
        assert config.vision_provider == "openai"

    def test_default_vision_model_is_none(self) -> None:
        """vision_model defaults to None (use provider default)."""
        from src.extraction_v2.pipeline import PipelineConfig

        config = PipelineConfig()
        assert config.vision_model is None

    def test_vision_provider_can_be_set(self) -> None:
        """vision_provider can be configured to 'claude'."""
        from src.extraction_v2.pipeline import PipelineConfig

        config = PipelineConfig(vision_provider="claude", vision_model="claude-opus-4-5")
        assert config.vision_provider == "claude"
        assert config.vision_model == "claude-opus-4-5"
