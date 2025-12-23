"""Tests for OpenAI client module."""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from src.llm.openai_client import CostTracker, LLMResponse, OpenAIClient


class TestLLMResponse:
    """Tests for LLMResponse dataclass."""

    def test_llm_response_creation(self):
        """Test creating an LLMResponse object."""
        response = LLMResponse(
            content="Test content",
            model="gpt-4o-mini",
            input_tokens=100,
            output_tokens=50,
            total_tokens=150,
            cost=0.0001,
            latency_ms=500,
            timestamp=datetime(2024, 1, 15, 10, 30, 0),
        )

        assert response.content == "Test content"
        assert response.model == "gpt-4o-mini"
        assert response.input_tokens == 100
        assert response.output_tokens == 50
        assert response.total_tokens == 150
        assert response.cost == 0.0001
        assert response.latency_ms == 500
        assert response.timestamp == datetime(2024, 1, 15, 10, 30, 0)


class TestCostTracker:
    """Tests for CostTracker class."""

    def test_cost_tracker_initialization(self):
        """Test CostTracker initializes with zero values."""
        tracker = CostTracker()

        assert tracker.total_requests == 0
        assert tracker.total_input_tokens == 0
        assert tracker.total_output_tokens == 0
        assert tracker.total_cost == 0.0
        assert tracker.failed_requests == 0

    def test_cost_tracker_add_request(self):
        """Test adding a request to cost tracker."""
        tracker = CostTracker()
        response = LLMResponse(
            content="Test",
            model="gpt-4o-mini",
            input_tokens=100,
            output_tokens=50,
            total_tokens=150,
            cost=0.0001,
            latency_ms=500,
            timestamp=datetime.now(),
        )

        tracker.add_request(response)

        assert tracker.total_requests == 1
        assert tracker.total_input_tokens == 100
        assert tracker.total_output_tokens == 50
        assert tracker.total_cost == 0.0001

    def test_cost_tracker_add_multiple_requests(self):
        """Test adding multiple requests to cost tracker."""
        tracker = CostTracker()

        for _ in range(3):
            response = LLMResponse(
                content="Test",
                model="gpt-4o-mini",
                input_tokens=100,
                output_tokens=50,
                total_tokens=150,
                cost=0.0001,
                latency_ms=500,
                timestamp=datetime.now(),
            )
            tracker.add_request(response)

        assert tracker.total_requests == 3
        assert tracker.total_input_tokens == 300
        assert tracker.total_output_tokens == 150
        assert tracker.total_cost == pytest.approx(0.0003)

    def test_cost_tracker_add_failure(self):
        """Test recording a failed request."""
        tracker = CostTracker()
        tracker.add_failure()

        assert tracker.failed_requests == 1
        assert tracker.total_requests == 0  # Failed requests don't count as total

    def test_cost_tracker_summary(self):
        """Test getting summary statistics."""
        tracker = CostTracker()
        response = LLMResponse(
            content="Test",
            model="gpt-4o-mini",
            input_tokens=100,
            output_tokens=50,
            total_tokens=150,
            cost=0.0001,
            latency_ms=500,
            timestamp=datetime.now(),
        )
        tracker.add_request(response)
        tracker.add_failure()

        summary = tracker.summary()

        assert summary["total_requests"] == 1
        assert summary["successful_requests"] == 1
        assert summary["failed_requests"] == 1
        assert summary["total_input_tokens"] == 100
        assert summary["total_output_tokens"] == 50
        assert summary["total_tokens"] == 150
        assert summary["total_cost_usd"] == 0.0001
        assert summary["avg_cost_per_request"] == 0.0001

    def test_cost_tracker_summary_no_requests(self):
        """Test summary with no requests handles division by zero."""
        tracker = CostTracker()
        summary = tracker.summary()

        assert summary["avg_cost_per_request"] == 0


class TestOpenAIClientInitialization:
    """Tests for OpenAIClient initialization."""

    def test_client_initializes_with_api_key(self, mock_tiktoken):
        """Test client initializes with provided API key."""
        with patch("src.llm.openai_client.OpenAI") as mock_openai:
            client = OpenAIClient(api_key="test-key-12345")

            assert client.api_key == "test-key-12345"
            mock_openai.assert_called_once_with(api_key="test-key-12345")

    def test_client_initializes_with_env_var(self, mock_tiktoken):
        """Test client initializes with environment variable."""
        with patch("src.llm.openai_client.OpenAI") as _mock_openai:
            with patch.dict("os.environ", {"OPENAI_API_KEY": "env-test-key"}):
                client = OpenAIClient()

                assert client.api_key == "env-test-key"

    def test_client_raises_without_api_key(self, mock_tiktoken):
        """Test client raises ValueError without API key."""
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(ValueError, match="OpenAI API key required"):
                OpenAIClient()

    def test_client_sets_default_parameters(self, mock_tiktoken):
        """Test client sets default parameters."""
        with patch("src.llm.openai_client.OpenAI"):
            client = OpenAIClient(api_key="test-key")

            assert client.model == "gpt-4o-mini"
            assert client.temperature == 0.1
            assert client.max_tokens == 4096
            assert client.max_retries == 3
            assert client.retry_delay == 1.0

    def test_client_accepts_custom_parameters(self, mock_tiktoken):
        """Test client accepts custom parameters."""
        with patch("src.llm.openai_client.OpenAI"):
            client = OpenAIClient(
                api_key="test-key",
                model="gpt-4o",
                temperature=0.5,
                max_tokens=2048,
                max_retries=5,
                retry_delay=2.0,
            )

            assert client.model == "gpt-4o"
            assert client.temperature == 0.5
            assert client.max_tokens == 2048
            assert client.max_retries == 5
            assert client.retry_delay == 2.0

    def test_client_initializes_tokenizer(self, mock_tiktoken):
        """Test client initializes tiktoken tokenizer."""
        with patch("src.llm.openai_client.OpenAI"):
            client = OpenAIClient(api_key="test-key")

            mock_tiktoken.encoding_for_model.assert_called_once_with("gpt-4o-mini")
            assert client.tokenizer is not None

    def test_client_fallback_tokenizer_on_key_error(self):
        """Test client falls back to cl100k_base on KeyError."""
        with patch("src.llm.openai_client.OpenAI"):
            with patch("src.llm.openai_client.tiktoken") as mock_tik:
                mock_tik.encoding_for_model.side_effect = KeyError("Unknown model")
                mock_tik.get_encoding.return_value = MagicMock()

                OpenAIClient(api_key="test-key", model="unknown-model")

                mock_tik.get_encoding.assert_called_once_with("cl100k_base")


class TestTokenCounting:
    """Tests for token counting."""

    def test_count_tokens_with_tiktoken(self, mock_tiktoken):
        """Test counting tokens with tiktoken."""
        with patch("src.llm.openai_client.OpenAI"):
            client = OpenAIClient(api_key="test-key")
            # Mock returns [1,2,3,4,5] = 5 tokens
            count = client.count_tokens("Hello world")

            assert count == 5

    def test_count_tokens_fallback_estimation(self):
        """Test fallback token estimation when tiktoken unavailable."""
        with patch("src.llm.openai_client.OpenAI"):
            with patch("src.llm.openai_client.tiktoken", None):
                client = OpenAIClient(api_key="test-key")

                # Fallback is len(text) // 4
                count = client.count_tokens("Hello world!!")  # 14 chars

                assert count == 3  # 14 // 4 = 3

    def test_count_tokens_empty_string(self, mock_tiktoken):
        """Test counting tokens for empty string."""
        mock_tiktoken.encoding_for_model.return_value.encode.return_value = []

        with patch("src.llm.openai_client.OpenAI"):
            client = OpenAIClient(api_key="test-key")
            count = client.count_tokens("")

            assert count == 0


class TestCostCalculation:
    """Tests for cost calculation."""

    def test_calculate_cost_gpt4o_mini(self, mock_tiktoken):
        """Test cost calculation for gpt-4o-mini."""
        with patch("src.llm.openai_client.OpenAI"):
            client = OpenAIClient(api_key="test-key", model="gpt-4o-mini")

            # 1000 input tokens, 500 output tokens
            # Input: (1000 / 1_000_000) * 0.15 = 0.00015
            # Output: (500 / 1_000_000) * 0.60 = 0.0003
            # Total: 0.00045
            cost = client.calculate_cost(input_tokens=1000, output_tokens=500)

            assert cost == pytest.approx(0.00045)

    def test_calculate_cost_gpt4o(self, mock_tiktoken):
        """Test cost calculation for gpt-4o."""
        with patch("src.llm.openai_client.OpenAI"):
            client = OpenAIClient(api_key="test-key", model="gpt-4o")

            # 1000 input tokens, 500 output tokens
            # Input: (1000 / 1_000_000) * 2.50 = 0.0025
            # Output: (500 / 1_000_000) * 10.00 = 0.005
            # Total: 0.0075
            cost = client.calculate_cost(input_tokens=1000, output_tokens=500)

            assert cost == pytest.approx(0.0075)

    def test_calculate_cost_unknown_model_uses_default(self, mock_tiktoken):
        """Test unknown model uses gpt-4o-mini pricing as default."""
        with patch("src.llm.openai_client.OpenAI"):
            with patch("src.llm.openai_client.tiktoken") as mock_tik:
                mock_tik.encoding_for_model.side_effect = KeyError()
                mock_tik.get_encoding.return_value = MagicMock()

                client = OpenAIClient(api_key="test-key", model="unknown-model")

                cost = client.calculate_cost(input_tokens=1000, output_tokens=500)

                # Should use gpt-4o-mini pricing
                assert cost == pytest.approx(0.00045)

    def test_calculate_cost_zero_tokens(self, mock_tiktoken):
        """Test cost calculation with zero tokens."""
        with patch("src.llm.openai_client.OpenAI"):
            client = OpenAIClient(api_key="test-key")

            cost = client.calculate_cost(input_tokens=0, output_tokens=0)

            assert cost == 0.0


class TestComplete:
    """Tests for the complete() method."""

    def test_complete_successful_response(self, mock_tiktoken, mock_openai_response):
        """Test successful completion request."""
        with patch("src.llm.openai_client.OpenAI") as mock_openai_class:
            mock_instance = MagicMock()
            mock_instance.chat.completions.create.return_value = mock_openai_response
            mock_openai_class.return_value = mock_instance

            client = OpenAIClient(api_key="test-key")
            response = client.complete("Test prompt")

            assert response.content == "Test response content"
            assert response.model == "gpt-4o-mini"
            assert response.output_tokens == 50
            assert response.total_tokens == 150

    def test_complete_includes_system_message(self, mock_tiktoken, mock_openai_response):
        """Test that system message is included in request."""
        with patch("src.llm.openai_client.OpenAI") as mock_openai_class:
            mock_instance = MagicMock()
            mock_instance.chat.completions.create.return_value = mock_openai_response
            mock_openai_class.return_value = mock_instance

            client = OpenAIClient(api_key="test-key")
            client.complete("Test prompt", system_message="You are a helpful assistant")

            call_args = mock_instance.chat.completions.create.call_args
            messages = call_args[1]["messages"]

            assert len(messages) == 2
            assert messages[0]["role"] == "system"
            assert messages[0]["content"] == "You are a helpful assistant"
            assert messages[1]["role"] == "user"

    def test_complete_tracks_cost(self, mock_tiktoken, mock_openai_response):
        """Test that completion tracks cost."""
        with patch("src.llm.openai_client.OpenAI") as mock_openai_class:
            mock_instance = MagicMock()
            mock_instance.chat.completions.create.return_value = mock_openai_response
            mock_openai_class.return_value = mock_instance

            client = OpenAIClient(api_key="test-key")
            client.complete("Test prompt")

            summary = client.get_cost_summary()
            assert summary["total_requests"] == 1
            # Cost is calculated from tokens, which are mocked
            assert summary["total_cost_usd"] >= 0

    def test_complete_retry_on_rate_limit(self, mock_tiktoken, mock_openai_response):
        """Test retry on rate limit error."""
        from openai import RateLimitError

        with patch("src.llm.openai_client.OpenAI") as mock_openai_class:
            mock_instance = MagicMock()
            # Fail first two times, succeed on third
            mock_instance.chat.completions.create.side_effect = [
                RateLimitError(
                    "Rate limited",
                    response=MagicMock(status_code=429),
                    body=None,
                ),
                RateLimitError(
                    "Rate limited",
                    response=MagicMock(status_code=429),
                    body=None,
                ),
                mock_openai_response,
            ]
            mock_openai_class.return_value = mock_instance

            with patch("time.sleep"):  # Don't actually sleep
                client = OpenAIClient(api_key="test-key")
                response = client.complete("Test prompt")

                assert response.content == "Test response content"
                assert mock_instance.chat.completions.create.call_count == 3

    def test_complete_max_retries_exhausted(self, mock_tiktoken):
        """Test that error is raised when max retries exhausted."""
        from openai import RateLimitError

        with patch("src.llm.openai_client.OpenAI") as mock_openai_class:
            mock_instance = MagicMock()
            mock_instance.chat.completions.create.side_effect = RateLimitError(
                "Rate limited",
                response=MagicMock(status_code=429),
                body=None,
            )
            mock_openai_class.return_value = mock_instance

            with patch("time.sleep"):
                client = OpenAIClient(api_key="test-key", max_retries=3)

                with pytest.raises(RateLimitError):
                    client.complete("Test prompt")

                assert mock_instance.chat.completions.create.call_count == 3

    def test_complete_non_retryable_error_raises(self, mock_tiktoken):
        """Test that non-retryable errors are raised."""
        with patch("src.llm.openai_client.OpenAI") as mock_openai_class:
            mock_instance = MagicMock()
            # Use a generic exception to test the error path
            mock_instance.chat.completions.create.side_effect = ValueError("Bad request")
            mock_openai_class.return_value = mock_instance

            client = OpenAIClient(api_key="test-key")

            with pytest.raises(ValueError):
                client.complete("Test prompt")

            # Should only try once since ValueError isn't retried
            assert mock_instance.chat.completions.create.call_count == 1

    def test_complete_retry_on_connection_error(self, mock_tiktoken, mock_openai_response):
        """Test retry on API connection error."""
        from openai import APIConnectionError

        with patch("src.llm.openai_client.OpenAI") as mock_openai_class:
            mock_instance = MagicMock()
            # Fail first two times with connection error, succeed on third
            mock_instance.chat.completions.create.side_effect = [
                APIConnectionError(request=MagicMock()),
                APIConnectionError(request=MagicMock()),
                mock_openai_response,
            ]
            mock_openai_class.return_value = mock_instance

            with patch("time.sleep"):  # Don't actually sleep
                client = OpenAIClient(api_key="test-key")
                response = client.complete("Test prompt")

                assert response.content == "Test response content"
                assert mock_instance.chat.completions.create.call_count == 3

    def test_complete_api_error_4xx_non_retryable(self, mock_tiktoken):
        """Test that 4xx API errors (except rate limit) are not retried."""
        from openai import APIError

        with patch("src.llm.openai_client.OpenAI") as mock_openai_class:
            mock_instance = MagicMock()
            # Create a mock APIError with status_code attribute
            error = MagicMock(spec=APIError)
            error.status_code = 400
            # Make it raise as an APIError by setting up the exception
            actual_error = APIError.__new__(APIError)
            actual_error.status_code = 400
            mock_instance.chat.completions.create.side_effect = actual_error
            mock_openai_class.return_value = mock_instance

            with patch("time.sleep"):
                client = OpenAIClient(api_key="test-key")

                with pytest.raises(APIError):
                    client.complete("Test prompt")

                # Should only try once since 4xx errors are not retried
                assert mock_instance.chat.completions.create.call_count == 1
                # Should track the failure
                assert client.cost_tracker.failed_requests == 1

    def test_complete_api_error_5xx_retryable(self, mock_tiktoken, mock_openai_response):
        """Test that 5xx API errors are retried."""
        from openai import APIError

        with patch("src.llm.openai_client.OpenAI") as mock_openai_class:
            mock_instance = MagicMock()
            # Create APIError without calling __init__ to avoid signature issues
            error = APIError.__new__(APIError)
            error.status_code = 500
            # Fail first two times, succeed on third
            mock_instance.chat.completions.create.side_effect = [
                error,
                error,
                mock_openai_response,
            ]
            mock_openai_class.return_value = mock_instance

            with patch("time.sleep"):
                client = OpenAIClient(api_key="test-key")
                response = client.complete("Test prompt")

                assert response.content == "Test response content"
                assert mock_instance.chat.completions.create.call_count == 3


class TestCompleteBatch:
    """Tests for the complete_batch() method."""

    def test_complete_batch_multiple_prompts(self, mock_tiktoken, mock_openai_response):
        """Test batch processing multiple prompts."""
        with patch("src.llm.openai_client.OpenAI") as mock_openai_class:
            mock_instance = MagicMock()
            mock_instance.chat.completions.create.return_value = mock_openai_response
            mock_openai_class.return_value = mock_instance

            with patch("time.sleep"):
                client = OpenAIClient(api_key="test-key")
                responses = client.complete_batch(["Prompt 1", "Prompt 2", "Prompt 3"])

                assert len(responses) == 3
                assert mock_instance.chat.completions.create.call_count == 3

    def test_complete_batch_with_system_message(
        self, mock_tiktoken, mock_openai_response
    ):
        """Test batch processing with system message."""
        with patch("src.llm.openai_client.OpenAI") as mock_openai_class:
            mock_instance = MagicMock()
            mock_instance.chat.completions.create.return_value = mock_openai_response
            mock_openai_class.return_value = mock_instance

            with patch("time.sleep"):
                client = OpenAIClient(api_key="test-key")
                client.complete_batch(
                    ["Prompt 1", "Prompt 2"],
                    system_message="You are helpful",
                )

                # Verify system message was passed to each call
                for call in mock_instance.chat.completions.create.call_args_list:
                    messages = call[1]["messages"]
                    assert messages[0]["role"] == "system"
                    assert messages[0]["content"] == "You are helpful"

    def test_complete_batch_continues_on_error(self, mock_tiktoken, mock_openai_response):
        """Test batch processing continues when one prompt fails."""
        with patch("src.llm.openai_client.OpenAI") as mock_openai_class:
            mock_instance = MagicMock()
            # First succeeds, second fails, third succeeds
            mock_instance.chat.completions.create.side_effect = [
                mock_openai_response,
                ValueError("Bad request"),
                mock_openai_response,
            ]
            mock_openai_class.return_value = mock_instance

            with patch("time.sleep"):
                client = OpenAIClient(api_key="test-key")
                responses = client.complete_batch(["Prompt 1", "Prompt 2", "Prompt 3"])

                # Should have 2 successful responses (skipped the failed one)
                assert len(responses) == 2

    def test_complete_batch_empty_prompts(self, mock_tiktoken):
        """Test batch processing with empty prompt list."""
        with patch("src.llm.openai_client.OpenAI"):
            client = OpenAIClient(api_key="test-key")
            responses = client.complete_batch([])

            assert len(responses) == 0


class TestCostSummary:
    """Tests for cost summary methods."""

    def test_get_cost_summary_format(self, mock_tiktoken, mock_openai_response):
        """Test cost summary returns correct format."""
        with patch("src.llm.openai_client.OpenAI") as mock_openai_class:
            mock_instance = MagicMock()
            mock_instance.chat.completions.create.return_value = mock_openai_response
            mock_openai_class.return_value = mock_instance

            client = OpenAIClient(api_key="test-key")
            client.complete("Test")

            summary = client.get_cost_summary()

            assert "total_requests" in summary
            assert "successful_requests" in summary
            assert "failed_requests" in summary
            assert "total_input_tokens" in summary
            assert "total_output_tokens" in summary
            assert "total_tokens" in summary
            assert "total_cost_usd" in summary
            assert "avg_cost_per_request" in summary

    def test_reset_cost_tracker(self, mock_tiktoken, mock_openai_response):
        """Test resetting cost tracker."""
        with patch("src.llm.openai_client.OpenAI") as mock_openai_class:
            mock_instance = MagicMock()
            mock_instance.chat.completions.create.return_value = mock_openai_response
            mock_openai_class.return_value = mock_instance

            client = OpenAIClient(api_key="test-key")
            client.complete("Test")

            # Verify we have tracked data
            assert client.get_cost_summary()["total_requests"] == 1

            # Reset
            client.reset_cost_tracker()

            # Verify reset
            assert client.get_cost_summary()["total_requests"] == 0
            assert client.get_cost_summary()["total_cost_usd"] == 0
