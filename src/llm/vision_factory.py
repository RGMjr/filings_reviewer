"""Factory for creating vision providers.

Creates the appropriate VisionProvider implementation based on the
provider name, enabling easy switching between OpenAI and Claude.
"""

from __future__ import annotations

from src.llm.vision_provider import VisionProvider


def create_vision_provider(
    provider: str,
    model: str | None = None,
) -> VisionProvider:
    """Create a VisionProvider for the given provider name.

    Args:
        provider: Provider name. One of "openai" or "claude".
        model: Model override. If None, uses provider default.

    Returns:
        Configured VisionProvider instance.

    Raises:
        ValueError: If provider name is not recognized.
    """
    if provider == "openai":
        from src.llm.vision_client import OpenAIVisionProvider

        return OpenAIVisionProvider(model=model or "gpt-4o")
    elif provider == "claude":
        from src.llm.claude_vision_provider import ClaudeVisionProvider

        return ClaudeVisionProvider(model=model or "claude-opus-4-5")
    else:
        raise ValueError(
            f"Unknown vision provider: {provider!r}. "
            "Supported providers: 'openai', 'claude'."
        )
