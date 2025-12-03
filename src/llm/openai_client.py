"""
OpenAI API Client with error handling, retry logic, and cost tracking.

This module provides a robust wrapper around the OpenAI API with:
- Automatic retry with exponential backoff
- Token counting and cost tracking
- Rate limiting
- Comprehensive error handling
"""

import logging
import time
import os
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
from datetime import datetime

try:
    import tiktoken
except ImportError:
    tiktoken = None

try:
    from openai import OpenAI, APIError, RateLimitError, APIConnectionError
except ImportError:
    raise ImportError("OpenAI package not installed. Run: pip install openai tiktoken")

logger = logging.getLogger(__name__)


@dataclass
class LLMResponse:
    """Response from LLM with metadata."""

    content: str
    model: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cost: float
    latency_ms: int
    timestamp: datetime


@dataclass
class CostTracker:
    """Track cumulative LLM API costs."""

    total_requests: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cost: float = 0.0
    failed_requests: int = 0

    def add_request(self, response: LLMResponse):
        """Add a successful request to tracking."""
        self.total_requests += 1
        self.total_input_tokens += response.input_tokens
        self.total_output_tokens += response.output_tokens
        self.total_cost += response.cost

    def add_failure(self):
        """Record a failed request."""
        self.failed_requests += 1

    def summary(self) -> Dict[str, Any]:
        """Get summary statistics."""
        return {
            "total_requests": self.total_requests,
            "successful_requests": self.total_requests,
            "failed_requests": self.failed_requests,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_tokens": self.total_input_tokens + self.total_output_tokens,
            "total_cost_usd": round(self.total_cost, 4),
            "avg_cost_per_request": (
                round(self.total_cost / self.total_requests, 4)
                if self.total_requests > 0
                else 0
            ),
        }


class OpenAIClient:
    """
    OpenAI API client with robust error handling and cost tracking.

    Features:
    - Automatic retry with exponential backoff
    - Token counting using tiktoken
    - Cost tracking per request and cumulative
    - Rate limiting
    - Comprehensive error handling
    """

    # Pricing per 1M tokens (as of 2025-01)
    PRICING = {
        "gpt-4o": {"input": 2.50, "output": 10.00},
        "gpt-4o-mini": {"input": 0.15, "output": 0.60},
        "gpt-4o-2024-08-06": {"input": 2.50, "output": 10.00},
        "gpt-4o-mini-2024-07-18": {"input": 0.15, "output": 0.60},
    }

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "gpt-4o-mini",
        temperature: float = 0.1,
        max_tokens: int = 4096,
        max_retries: int = 3,
        retry_delay: float = 1.0,
    ):
        """
        Initialize OpenAI client.

        Args:
            api_key: OpenAI API key (defaults to OPENAI_API_KEY env var)
            model: Model to use (default: gpt-4o-mini)
            temperature: Sampling temperature (0.0-2.0, default: 0.1 for deterministic)
            max_tokens: Maximum tokens in response
            max_retries: Number of retries on failure
            retry_delay: Initial delay between retries (exponential backoff)
        """
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError(
                "OpenAI API key required. Set OPENAI_API_KEY env var or pass api_key parameter."
            )

        self.client = OpenAI(api_key=self.api_key)
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.max_retries = max_retries
        self.retry_delay = retry_delay

        # Initialize tokenizer for counting
        if tiktoken:
            try:
                self.tokenizer = tiktoken.encoding_for_model(model)
            except KeyError:
                # Fallback to cl100k_base for newer models
                self.tokenizer = tiktoken.get_encoding("cl100k_base")
                logger.warning(
                    f"No tokenizer for {model}, using cl100k_base as fallback"
                )
        else:
            self.tokenizer = None
            logger.warning("tiktoken not installed, token counting will be estimated")

        # Cost tracking
        self.cost_tracker = CostTracker()

        logger.info(f"OpenAI client initialized with model: {model}")

    def count_tokens(self, text: str) -> int:
        """
        Count tokens in text.

        Args:
            text: Input text

        Returns:
            Token count
        """
        if self.tokenizer:
            return len(self.tokenizer.encode(text))
        else:
            # Rough estimate: 1 token ≈ 4 characters
            return len(text) // 4

    def calculate_cost(self, input_tokens: int, output_tokens: int) -> float:
        """
        Calculate cost for a request.

        Args:
            input_tokens: Number of input tokens
            output_tokens: Number of output tokens

        Returns:
            Cost in USD
        """
        pricing = self.PRICING.get(self.model, self.PRICING["gpt-4o-mini"])

        input_cost = (input_tokens / 1_000_000) * pricing["input"]
        output_cost = (output_tokens / 1_000_000) * pricing["output"]

        return input_cost + output_cost

    def complete(
        self,
        prompt: str,
        system_message: Optional[str] = None,
        **kwargs,
    ) -> LLMResponse:
        """
        Send completion request to OpenAI API with retry logic.

        Args:
            prompt: User prompt
            system_message: Optional system message
            **kwargs: Additional arguments to pass to API

        Returns:
            LLMResponse with content and metadata

        Raises:
            APIError: If all retries fail
        """
        # Build messages
        messages = []
        if system_message:
            messages.append({"role": "system", "content": system_message})
        messages.append({"role": "user", "content": prompt})

        # Count input tokens
        input_text = (system_message or "") + prompt
        input_tokens = self.count_tokens(input_text)

        # Retry loop with exponential backoff
        last_error = None
        for attempt in range(self.max_retries):
            try:
                start_time = time.time()

                # Make API call
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                    **kwargs,
                )

                latency_ms = int((time.time() - start_time) * 1000)

                # Extract response
                content = response.choices[0].message.content
                output_tokens = response.usage.completion_tokens
                total_tokens = response.usage.total_tokens

                # Calculate cost
                cost = self.calculate_cost(input_tokens, output_tokens)

                # Create response object
                llm_response = LLMResponse(
                    content=content,
                    model=self.model,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    total_tokens=total_tokens,
                    cost=cost,
                    latency_ms=latency_ms,
                    timestamp=datetime.now(),
                )

                # Track cost
                self.cost_tracker.add_request(llm_response)

                logger.debug(
                    f"LLM request successful: {output_tokens} tokens, ${cost:.4f}, {latency_ms}ms"
                )

                return llm_response

            except RateLimitError as e:
                last_error = e
                delay = self.retry_delay * (2**attempt)
                logger.warning(
                    f"Rate limit hit, retrying in {delay}s (attempt {attempt + 1}/{self.max_retries})"
                )
                time.sleep(delay)

            except APIConnectionError as e:
                last_error = e
                delay = self.retry_delay * (2**attempt)
                logger.warning(
                    f"Connection error, retrying in {delay}s (attempt {attempt + 1}/{self.max_retries})"
                )
                time.sleep(delay)

            except APIError as e:
                last_error = e
                # Don't retry on 4xx errors (except rate limit)
                if hasattr(e, "status_code") and 400 <= e.status_code < 500:
                    logger.error(f"API error (non-retryable): {e}")
                    self.cost_tracker.add_failure()
                    raise
                else:
                    delay = self.retry_delay * (2**attempt)
                    logger.warning(
                        f"API error, retrying in {delay}s (attempt {attempt + 1}/{self.max_retries})"
                    )
                    time.sleep(delay)

        # All retries exhausted
        self.cost_tracker.add_failure()
        logger.error(f"All {self.max_retries} retries exhausted")
        raise last_error

    def complete_batch(
        self,
        prompts: List[str],
        system_message: Optional[str] = None,
        delay_between_requests: float = 0.1,
    ) -> List[LLMResponse]:
        """
        Send multiple completion requests with rate limiting.

        Args:
            prompts: List of user prompts
            system_message: Optional system message for all prompts
            delay_between_requests: Delay between requests (seconds)

        Returns:
            List of LLMResponse objects
        """
        responses = []

        for i, prompt in enumerate(prompts):
            logger.info(f"Processing prompt {i + 1}/{len(prompts)}")

            try:
                response = self.complete(prompt, system_message=system_message)
                responses.append(response)
            except Exception as e:
                logger.error(f"Failed to process prompt {i + 1}: {e}")
                # Continue with next prompt
                continue

            # Rate limiting delay
            if i < len(prompts) - 1:
                time.sleep(delay_between_requests)

        return responses

    def get_cost_summary(self) -> Dict[str, Any]:
        """Get cumulative cost tracking summary."""
        return self.cost_tracker.summary()

    def reset_cost_tracker(self):
        """Reset cost tracking to zero."""
        self.cost_tracker = CostTracker()
        logger.info("Cost tracker reset")
