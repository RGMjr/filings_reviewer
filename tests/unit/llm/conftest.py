"""Shared fixtures for LLM module tests."""

from unittest.mock import MagicMock, patch

import pytest

from src.llm.cache import CacheConfig


@pytest.fixture
def mock_openai_response():
    """Create a mock OpenAI API response."""
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "Test response content"
    mock_response.usage.completion_tokens = 50
    mock_response.usage.total_tokens = 150
    return mock_response


@pytest.fixture
def mock_openai_client(mock_openai_response):
    """Create a mock OpenAI client."""
    with patch("src.llm.openai_client.OpenAI") as mock_openai_class:
        mock_instance = MagicMock()
        mock_instance.chat.completions.create.return_value = mock_openai_response
        mock_openai_class.return_value = mock_instance
        yield mock_instance


@pytest.fixture
def mock_tiktoken():
    """Create a mock tiktoken encoder."""
    mock_tokenizer = MagicMock()
    mock_tokenizer.encode.return_value = [1, 2, 3, 4, 5]  # 5 tokens

    with patch("src.llm.openai_client.tiktoken") as mock_tiktoken_module:
        mock_tiktoken_module.encoding_for_model.return_value = mock_tokenizer
        mock_tiktoken_module.get_encoding.return_value = mock_tokenizer
        yield mock_tiktoken_module


@pytest.fixture
def disabled_cache_config():
    """Create a cache config with caching disabled for testing."""
    return CacheConfig(enabled=False)


@pytest.fixture
def api_key_env():
    """Set up API key environment variable."""
    with patch.dict("os.environ", {"OPENAI_API_KEY": "test-api-key-12345"}):
        yield


@pytest.fixture
def sample_value_extraction_response():
    """Sample valid value extraction response."""
    return [
        {
            "metric_name": "monthly_active_users",
            "value": "10.5",
            "units": "millions",
            "period": "December 31, 2023",
            "cohort_label": None,
            "quote": "As of December 31, 2023, we had 10.5 million monthly active users.",
        },
        {
            "metric_name": "new_customers_acquired",
            "value": "500000",
            "units": "count",
            "period": "FY 2023",
            "cohort_label": None,
            "quote": "We acquired 500,000 new customers during fiscal year 2023.",
        },
    ]


@pytest.fixture
def sample_definition_extraction_response():
    """Sample valid definition extraction response."""
    return [
        {
            "metric_name": "monthly_active_users",
            "definition_text": "users who have logged in at least once in a calendar month",
            "includes_calculation": False,
            "quote": "We define monthly active users as users who have logged in at least once in a calendar month.",
        },
    ]
