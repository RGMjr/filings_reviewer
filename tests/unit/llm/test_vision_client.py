"""Unit tests for VisionClient.

Tests for the LLM Vision API client, including:
- MIME type detection from magic bytes
- Base64 encoding
- Cost calculation
- API response handling
"""

from unittest.mock import MagicMock, patch

import pytest

from src.llm.vision_client import (
    IMAGE_SIGNATURES,
    VisionClient,
    VisionResponse,
    detect_mime_type,
)


class TestDetectMimeType:
    """Test suite for MIME type detection from magic bytes."""

    def test_detect_jpeg(self):
        """Test detection of JPEG images."""
        # JPEG starts with FF D8 FF
        jpeg_bytes = b"\xff\xd8\xff\xe0" + b"rest of jpeg content"
        assert detect_mime_type(jpeg_bytes) == "image/jpeg"

    def test_detect_jpeg_various_markers(self):
        """Test JPEG detection with different marker types."""
        # JPEG can have different markers after FF D8 FF
        for marker in [b"\xe0", b"\xe1", b"\xdb", b"\xc0"]:
            jpeg_bytes = b"\xff\xd8\xff" + marker + b"content"
            assert detect_mime_type(jpeg_bytes) == "image/jpeg"

    def test_detect_png(self):
        """Test detection of PNG images."""
        # PNG starts with 89 50 4E 47 0D 0A 1A 0A
        png_bytes = b"\x89PNG\r\n\x1a\n" + b"rest of png content"
        assert detect_mime_type(png_bytes) == "image/png"

    def test_detect_gif87a(self):
        """Test detection of GIF87a images."""
        gif_bytes = b"GIF87a" + b"rest of gif content"
        assert detect_mime_type(gif_bytes) == "image/gif"

    def test_detect_gif89a(self):
        """Test detection of GIF89a images."""
        gif_bytes = b"GIF89a" + b"rest of gif content"
        assert detect_mime_type(gif_bytes) == "image/gif"

    def test_unknown_format_defaults_to_png(self):
        """Test that unknown formats default to PNG."""
        unknown_bytes = b"unknown format content"
        assert detect_mime_type(unknown_bytes) == "image/png"

    def test_empty_bytes_defaults_to_png(self):
        """Test that empty bytes default to PNG."""
        assert detect_mime_type(b"") == "image/png"

    def test_partial_signature_defaults_to_png(self):
        """Test that partial signatures default to PNG."""
        # Only first two bytes of JPEG signature
        partial_jpeg = b"\xff\xd8"
        assert detect_mime_type(partial_jpeg) == "image/png"

    def test_image_signatures_constant(self):
        """Test that IMAGE_SIGNATURES contains expected entries."""
        assert b"\xff\xd8\xff" in IMAGE_SIGNATURES
        assert b"\x89PNG\r\n\x1a\n" in IMAGE_SIGNATURES
        assert b"GIF87a" in IMAGE_SIGNATURES
        assert b"GIF89a" in IMAGE_SIGNATURES

    def test_detect_webp(self):
        """Test detection of WebP images."""
        # WebP format: RIFF + 4 bytes size + WEBP
        webp_bytes = b"RIFF\x00\x00\x00\x00WEBP" + b"rest of webp content"
        assert detect_mime_type(webp_bytes) == "image/webp"

    def test_detect_webp_with_size_bytes(self):
        """Test WebP detection with actual size bytes."""
        # More realistic WebP header with size bytes
        webp_bytes = b"RIFF\x24\x00\x00\x00WEBPVP8 " + b"rest"
        assert detect_mime_type(webp_bytes) == "image/webp"

    def test_detect_webp_too_short(self):
        """Test that truncated WebP headers default to PNG."""
        # Only 8 bytes - missing WEBP magic
        short_webp = b"RIFF\x00\x00\x00\x00"
        assert detect_mime_type(short_webp) == "image/png"

    def test_detect_riff_not_webp(self):
        """Test that RIFF files that aren't WebP default to PNG."""
        # RIFF WAV file (audio)
        wav_bytes = b"RIFF\x00\x00\x00\x00WAVE" + b"rest"
        assert detect_mime_type(wav_bytes) == "image/png"


class TestVisionResponse:
    """Test suite for VisionResponse dataclass."""

    def test_create_vision_response(self):
        """Test creating a VisionResponse instance."""
        response = VisionResponse(
            content="extracted data",
            model="gpt-4o",
            prompt_tokens=1000,
            completion_tokens=500,
            cost_usd=0.0075,
            latency_ms=2500,
        )

        assert response.content == "extracted data"
        assert response.model == "gpt-4o"
        assert response.prompt_tokens == 1000
        assert response.completion_tokens == 500
        assert response.cost_usd == 0.0075
        assert response.latency_ms == 2500

    def test_vision_response_immutability(self):
        """Test that VisionResponse fields are correctly typed."""
        response = VisionResponse(
            content="",
            model="gpt-4o",
            prompt_tokens=0,
            completion_tokens=0,
            cost_usd=0.0,
            latency_ms=0,
        )

        # Verify we can access all fields
        assert isinstance(response.content, str)
        assert isinstance(response.model, str)
        assert isinstance(response.prompt_tokens, int)
        assert isinstance(response.completion_tokens, int)
        assert isinstance(response.cost_usd, float)
        assert isinstance(response.latency_ms, int)


class TestVisionClientCostCalculation:
    """Test suite for cost calculation in VisionClient."""

    def test_cost_calculation_input_only(self):
        """Test cost calculation with only input tokens."""
        # 1M input tokens = $2.50
        # 1000 input tokens = $0.0025
        input_tokens = 1000
        output_tokens = 0

        cost = (
            (input_tokens / 1_000_000) * VisionClient.COST_PER_1M_INPUT_TOKENS
            + (output_tokens / 1_000_000) * VisionClient.COST_PER_1M_OUTPUT_TOKENS
        )

        assert cost == pytest.approx(0.0025, rel=1e-6)

    def test_cost_calculation_output_only(self):
        """Test cost calculation with only output tokens."""
        # 1M output tokens = $10.00
        # 1000 output tokens = $0.01
        input_tokens = 0
        output_tokens = 1000

        cost = (
            (input_tokens / 1_000_000) * VisionClient.COST_PER_1M_INPUT_TOKENS
            + (output_tokens / 1_000_000) * VisionClient.COST_PER_1M_OUTPUT_TOKENS
        )

        assert cost == pytest.approx(0.01, rel=1e-6)

    def test_cost_calculation_combined(self):
        """Test cost calculation with both input and output tokens."""
        # 1000 input = $0.0025, 500 output = $0.005
        input_tokens = 1000
        output_tokens = 500

        cost = (
            (input_tokens / 1_000_000) * VisionClient.COST_PER_1M_INPUT_TOKENS
            + (output_tokens / 1_000_000) * VisionClient.COST_PER_1M_OUTPUT_TOKENS
        )

        expected = 0.0025 + 0.005
        assert cost == pytest.approx(expected, rel=1e-6)

    def test_cost_calculation_realistic_image_request(self):
        """Test cost calculation for a realistic image analysis request."""
        # Typical image request: ~1000 prompt tokens (including image), ~500 output
        input_tokens = 1000
        output_tokens = 500

        cost = (
            (input_tokens / 1_000_000) * VisionClient.COST_PER_1M_INPUT_TOKENS
            + (output_tokens / 1_000_000) * VisionClient.COST_PER_1M_OUTPUT_TOKENS
        )

        # Should be around $0.0075
        assert cost == pytest.approx(0.0075, rel=1e-6)

    def test_pricing_constants(self):
        """Test that pricing constants are set correctly."""
        assert VisionClient.COST_PER_1M_INPUT_TOKENS == 2.50
        assert VisionClient.COST_PER_1M_OUTPUT_TOKENS == 10.00


class TestVisionClientInit:
    """Test suite for VisionClient initialization."""

    @patch("src.llm.vision_client.OpenAI")
    def test_default_model(self, mock_openai):
        """Test that default model is gpt-4o."""
        client = VisionClient()
        assert client.model == "gpt-4o"

    @patch("src.llm.vision_client.OpenAI")
    def test_custom_model(self, mock_openai):
        """Test initialization with custom model."""
        client = VisionClient(model="gpt-4o-mini")
        assert client.model == "gpt-4o-mini"

    @patch("src.llm.vision_client.OpenAI")
    def test_creates_openai_client(self, mock_openai):
        """Test that OpenAI client is created on init."""
        VisionClient()
        mock_openai.assert_called_once()


class TestVisionClientAnalyzeImage:
    """Test suite for analyze_image method."""

    @patch("src.llm.vision_client.OpenAI")
    def test_analyze_image_success(self, mock_openai):
        """Test successful image analysis."""
        # Set up mock response
        mock_usage = MagicMock()
        mock_usage.prompt_tokens = 1000
        mock_usage.completion_tokens = 500

        mock_message = MagicMock()
        mock_message.content = '{"chart_title": "Test Chart", "metric_type": "ARR"}'

        mock_choice = MagicMock()
        mock_choice.message = mock_message

        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_response.usage = mock_usage
        mock_response.model = "gpt-4o"

        mock_client_instance = MagicMock()
        mock_client_instance.chat.completions.create.return_value = mock_response
        mock_openai.return_value = mock_client_instance

        client = VisionClient()
        result = client.analyze_image(
            image_bytes=b"\xff\xd8\xff\xe0test",
            prompt="Extract data from this chart",
        )

        assert isinstance(result, VisionResponse)
        assert result.content == '{"chart_title": "Test Chart", "metric_type": "ARR"}'
        assert result.model == "gpt-4o"
        assert result.prompt_tokens == 1000
        assert result.completion_tokens == 500

    @patch("src.llm.vision_client.OpenAI")
    def test_analyze_image_uses_correct_mime_type(self, mock_openai):
        """Test that correct MIME type is detected and used."""
        mock_usage = MagicMock()
        mock_usage.prompt_tokens = 100
        mock_usage.completion_tokens = 50

        mock_message = MagicMock()
        mock_message.content = "result"

        mock_choice = MagicMock()
        mock_choice.message = mock_message

        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_response.usage = mock_usage
        mock_response.model = "gpt-4o"

        mock_client_instance = MagicMock()
        mock_client_instance.chat.completions.create.return_value = mock_response
        mock_openai.return_value = mock_client_instance

        client = VisionClient()

        # Test with PNG image
        png_bytes = b"\x89PNG\r\n\x1a\ntest"
        client.analyze_image(image_bytes=png_bytes, prompt="test")

        # Check that the API was called with PNG MIME type
        call_args = mock_client_instance.chat.completions.create.call_args
        messages = call_args.kwargs["messages"]
        image_content = messages[0]["content"][1]["image_url"]["url"]
        assert "data:image/png;base64," in image_content

    @patch("src.llm.vision_client.OpenAI")
    def test_analyze_image_detail_parameter(self, mock_openai):
        """Test that detail parameter is passed correctly."""
        mock_usage = MagicMock()
        mock_usage.prompt_tokens = 100
        mock_usage.completion_tokens = 50

        mock_message = MagicMock()
        mock_message.content = "result"

        mock_choice = MagicMock()
        mock_choice.message = mock_message

        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_response.usage = mock_usage
        mock_response.model = "gpt-4o"

        mock_client_instance = MagicMock()
        mock_client_instance.chat.completions.create.return_value = mock_response
        mock_openai.return_value = mock_client_instance

        client = VisionClient()
        client.analyze_image(
            image_bytes=b"\xff\xd8\xff\xe0test",
            prompt="test",
            detail="low",  # Non-default value
        )

        # Check that detail parameter was passed
        call_args = mock_client_instance.chat.completions.create.call_args
        messages = call_args.kwargs["messages"]
        image_content = messages[0]["content"][1]["image_url"]
        assert image_content["detail"] == "low"

    @patch("src.llm.vision_client.OpenAI")
    def test_analyze_image_max_tokens_parameter(self, mock_openai):
        """Test that max_tokens parameter is passed correctly."""
        mock_usage = MagicMock()
        mock_usage.prompt_tokens = 100
        mock_usage.completion_tokens = 50

        mock_message = MagicMock()
        mock_message.content = "result"

        mock_choice = MagicMock()
        mock_choice.message = mock_message

        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_response.usage = mock_usage
        mock_response.model = "gpt-4o"

        mock_client_instance = MagicMock()
        mock_client_instance.chat.completions.create.return_value = mock_response
        mock_openai.return_value = mock_client_instance

        client = VisionClient()
        client.analyze_image(
            image_bytes=b"\xff\xd8\xff\xe0test",
            prompt="test",
            max_tokens=1000,  # Custom value
        )

        # Check that max_tokens was passed
        call_args = mock_client_instance.chat.completions.create.call_args
        assert call_args.kwargs["max_tokens"] == 1000

    @patch("src.llm.vision_client.OpenAI")
    def test_analyze_image_handles_none_content(self, mock_openai):
        """Test handling of None content from API."""
        mock_usage = MagicMock()
        mock_usage.prompt_tokens = 100
        mock_usage.completion_tokens = 0

        mock_message = MagicMock()
        mock_message.content = None  # API can return None

        mock_choice = MagicMock()
        mock_choice.message = mock_message

        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_response.usage = mock_usage
        mock_response.model = "gpt-4o"

        mock_client_instance = MagicMock()
        mock_client_instance.chat.completions.create.return_value = mock_response
        mock_openai.return_value = mock_client_instance

        client = VisionClient()
        result = client.analyze_image(
            image_bytes=b"\xff\xd8\xff\xe0test",
            prompt="test",
        )

        # Should handle None gracefully
        assert result.content == ""

    @patch("src.llm.vision_client.OpenAI")
    def test_analyze_image_handles_none_usage(self, mock_openai):
        """Test handling of None usage stats from API."""
        mock_message = MagicMock()
        mock_message.content = "result"

        mock_choice = MagicMock()
        mock_choice.message = mock_message

        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_response.usage = None  # API can return None usage
        mock_response.model = "gpt-4o"

        mock_client_instance = MagicMock()
        mock_client_instance.chat.completions.create.return_value = mock_response
        mock_openai.return_value = mock_client_instance

        client = VisionClient()
        result = client.analyze_image(
            image_bytes=b"\xff\xd8\xff\xe0test",
            prompt="test",
        )

        # Should handle None usage gracefully
        assert result.prompt_tokens == 0
        assert result.completion_tokens == 0
        assert result.cost_usd == 0.0

    @patch("src.llm.vision_client.OpenAI")
    def test_analyze_image_latency_tracking(self, mock_openai):
        """Test that latency is tracked."""
        mock_usage = MagicMock()
        mock_usage.prompt_tokens = 100
        mock_usage.completion_tokens = 50

        mock_message = MagicMock()
        mock_message.content = "result"

        mock_choice = MagicMock()
        mock_choice.message = mock_message

        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_response.usage = mock_usage
        mock_response.model = "gpt-4o"

        mock_client_instance = MagicMock()
        mock_client_instance.chat.completions.create.return_value = mock_response
        mock_openai.return_value = mock_client_instance

        client = VisionClient()
        result = client.analyze_image(
            image_bytes=b"\xff\xd8\xff\xe0test",
            prompt="test",
        )

        # Latency should be non-negative
        assert result.latency_ms >= 0

    @patch("src.llm.vision_client.OpenAI")
    def test_analyze_image_api_error_propagates(self, mock_openai):
        """Test that API errors propagate."""
        from openai import APIError

        mock_client_instance = MagicMock()
        error = APIError(
            message="API Error",
            request=MagicMock(),
            body=None,
        )
        # Set status_code to 400 to ensure no retries
        error.status_code = 400
        mock_client_instance.chat.completions.create.side_effect = error
        mock_openai.return_value = mock_client_instance

        client = VisionClient()

        with pytest.raises(APIError):
            client.analyze_image(
                image_bytes=b"\xff\xd8\xff\xe0test",
                prompt="test",
                max_retries=0,
            )


class TestInputValidation:
    """Test suite for input validation."""

    @patch("src.llm.vision_client.OpenAI")
    def test_empty_image_bytes_raises_error(self, mock_openai):
        """Test that empty image bytes raise ValueError."""
        client = VisionClient()

        with pytest.raises(ValueError, match="image_bytes cannot be empty"):
            client.analyze_image(image_bytes=b"", prompt="test")

    @patch("src.llm.vision_client.OpenAI")
    def test_empty_prompt_raises_error(self, mock_openai):
        """Test that empty prompt raises ValueError."""
        client = VisionClient()

        with pytest.raises(ValueError, match="prompt cannot be empty"):
            client.analyze_image(image_bytes=b"\xff\xd8\xff\xe0test", prompt="")

    @patch("src.llm.vision_client.OpenAI")
    def test_whitespace_only_prompt_raises_error(self, mock_openai):
        """Test that whitespace-only prompt raises ValueError."""
        client = VisionClient()

        with pytest.raises(ValueError, match="prompt cannot be empty"):
            client.analyze_image(image_bytes=b"\xff\xd8\xff\xe0test", prompt="   ")

    @patch("src.llm.vision_client.OpenAI")
    def test_validation_before_api_call(self, mock_openai):
        """Test that validation happens before API call is made."""
        mock_client_instance = MagicMock()
        mock_openai.return_value = mock_client_instance

        client = VisionClient()

        # Should raise without calling API
        with pytest.raises(ValueError):
            client.analyze_image(image_bytes=b"", prompt="test")

        # Verify API was never called
        mock_client_instance.chat.completions.create.assert_not_called()


class TestRetryLogic:
    """Test suite for retry logic with exponential backoff."""

    @patch("src.llm.vision_client.OpenAI")
    @patch("src.llm.vision_client.time.sleep")
    def test_rate_limit_retries_with_backoff(self, mock_sleep, mock_openai):
        """Test that rate limit errors trigger retries with backoff."""
        from openai import RateLimitError

        mock_usage = MagicMock()
        mock_usage.prompt_tokens = 100
        mock_usage.completion_tokens = 50

        mock_message = MagicMock()
        mock_message.content = "result"

        mock_choice = MagicMock()
        mock_choice.message = mock_message

        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_response.usage = mock_usage
        mock_response.model = "gpt-4o"

        mock_client_instance = MagicMock()
        # Fail twice with rate limit, then succeed
        rate_error = RateLimitError(
            message="Rate limit exceeded",
            response=MagicMock(status_code=429),
            body=None,
        )
        mock_client_instance.chat.completions.create.side_effect = [
            rate_error,
            rate_error,
            mock_response,
        ]
        mock_openai.return_value = mock_client_instance

        client = VisionClient()
        result = client.analyze_image(
            image_bytes=b"\xff\xd8\xff\xe0test",
            prompt="test",
            max_retries=3,
        )

        # Should succeed after retries
        assert result.content == "result"
        # Should have slept twice (backoff: 1s, 2s)
        assert mock_sleep.call_count == 2
        # Verify backoff pattern
        mock_sleep.assert_any_call(1.0)
        mock_sleep.assert_any_call(2.0)

    @patch("src.llm.vision_client.OpenAI")
    @patch("src.llm.vision_client.time.sleep")
    def test_connection_error_retries(self, mock_sleep, mock_openai):
        """Test that connection errors trigger retries."""
        from openai import APIConnectionError

        mock_usage = MagicMock()
        mock_usage.prompt_tokens = 100
        mock_usage.completion_tokens = 50

        mock_message = MagicMock()
        mock_message.content = "result"

        mock_choice = MagicMock()
        mock_choice.message = mock_message

        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_response.usage = mock_usage
        mock_response.model = "gpt-4o"

        mock_client_instance = MagicMock()
        # Fail once with connection error, then succeed
        conn_error = APIConnectionError(request=MagicMock())
        mock_client_instance.chat.completions.create.side_effect = [
            conn_error,
            mock_response,
        ]
        mock_openai.return_value = mock_client_instance

        client = VisionClient()
        result = client.analyze_image(
            image_bytes=b"\xff\xd8\xff\xe0test",
            prompt="test",
            max_retries=2,
        )

        assert result.content == "result"
        assert mock_sleep.call_count == 1

    @patch("src.llm.vision_client.OpenAI")
    @patch("src.llm.vision_client.time.sleep")
    def test_server_error_retries(self, mock_sleep, mock_openai):
        """Test that 5xx server errors trigger retries."""
        from openai import APIError

        mock_usage = MagicMock()
        mock_usage.prompt_tokens = 100
        mock_usage.completion_tokens = 50

        mock_message = MagicMock()
        mock_message.content = "result"

        mock_choice = MagicMock()
        mock_choice.message = mock_message

        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_response.usage = mock_usage
        mock_response.model = "gpt-4o"

        mock_client_instance = MagicMock()
        # Fail once with 500 error, then succeed
        server_error = APIError(
            message="Internal Server Error",
            request=MagicMock(),
            body=None,
        )
        server_error.status_code = 500
        mock_client_instance.chat.completions.create.side_effect = [
            server_error,
            mock_response,
        ]
        mock_openai.return_value = mock_client_instance

        client = VisionClient()
        result = client.analyze_image(
            image_bytes=b"\xff\xd8\xff\xe0test",
            prompt="test",
            max_retries=2,
        )

        assert result.content == "result"
        assert mock_sleep.call_count == 1

    @patch("src.llm.vision_client.OpenAI")
    def test_client_error_no_retry(self, mock_openai):
        """Test that 4xx client errors don't trigger retries."""
        from openai import APIError

        mock_client_instance = MagicMock()
        client_error = APIError(
            message="Bad Request",
            request=MagicMock(),
            body=None,
        )
        client_error.status_code = 400
        mock_client_instance.chat.completions.create.side_effect = client_error
        mock_openai.return_value = mock_client_instance

        client = VisionClient()

        with pytest.raises(APIError):
            client.analyze_image(
                image_bytes=b"\xff\xd8\xff\xe0test",
                prompt="test",
                max_retries=3,
            )

        # Should only call once (no retries)
        assert mock_client_instance.chat.completions.create.call_count == 1

    @patch("src.llm.vision_client.OpenAI")
    @patch("src.llm.vision_client.time.sleep")
    def test_max_retries_exhausted(self, mock_sleep, mock_openai):
        """Test that error is raised after max retries exhausted."""
        from openai import RateLimitError

        mock_client_instance = MagicMock()
        rate_error = RateLimitError(
            message="Rate limit exceeded",
            response=MagicMock(status_code=429),
            body=None,
        )
        mock_client_instance.chat.completions.create.side_effect = rate_error
        mock_openai.return_value = mock_client_instance

        client = VisionClient()

        with pytest.raises(RateLimitError):
            client.analyze_image(
                image_bytes=b"\xff\xd8\xff\xe0test",
                prompt="test",
                max_retries=2,
            )

        # Should have made 3 attempts (1 initial + 2 retries)
        assert mock_client_instance.chat.completions.create.call_count == 3
        # Should have slept twice
        assert mock_sleep.call_count == 2

    @patch("src.llm.vision_client.OpenAI")
    def test_default_max_retries(self, mock_openai):
        """Test that default max_retries value is used."""
        mock_usage = MagicMock()
        mock_usage.prompt_tokens = 100
        mock_usage.completion_tokens = 50

        mock_message = MagicMock()
        mock_message.content = "result"

        mock_choice = MagicMock()
        mock_choice.message = mock_message

        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_response.usage = mock_usage
        mock_response.model = "gpt-4o"

        mock_client_instance = MagicMock()
        mock_client_instance.chat.completions.create.return_value = mock_response
        mock_openai.return_value = mock_client_instance

        client = VisionClient()
        # Verify default is accessible
        assert client.DEFAULT_MAX_RETRIES == 3


class TestBase64Encoding:
    """Test suite for base64 encoding functionality."""

    @patch("src.llm.vision_client.OpenAI")
    def test_base64_encoding_applied(self, mock_openai):
        """Test that image bytes are base64 encoded."""
        import base64

        mock_usage = MagicMock()
        mock_usage.prompt_tokens = 100
        mock_usage.completion_tokens = 50

        mock_message = MagicMock()
        mock_message.content = "result"

        mock_choice = MagicMock()
        mock_choice.message = mock_message

        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_response.usage = mock_usage
        mock_response.model = "gpt-4o"

        mock_client_instance = MagicMock()
        mock_client_instance.chat.completions.create.return_value = mock_response
        mock_openai.return_value = mock_client_instance

        client = VisionClient()

        # Use known test data
        test_bytes = b"\xff\xd8\xff\xe0test_content"
        expected_b64 = base64.standard_b64encode(test_bytes).decode("utf-8")

        client.analyze_image(image_bytes=test_bytes, prompt="test")

        # Verify base64 encoding was applied correctly
        call_args = mock_client_instance.chat.completions.create.call_args
        messages = call_args.kwargs["messages"]
        image_url = messages[0]["content"][1]["image_url"]["url"]

        # Extract base64 portion
        b64_portion = image_url.split(",")[1]
        assert b64_portion == expected_b64
