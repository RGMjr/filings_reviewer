"""
LLM Integration Module

This module provides LLM API integration for metric extraction from SEC filings.
Supports OpenAI (default), Gemini, and Anthropic vision providers via VISION_PROVIDER env var.
"""

from .cache import CacheConfig, CachedResponse, LLMCache
from .openai_client import OpenAIClient
from .prompts import PromptTemplates
from .providers import VisionProvider
from .vision_client import VisionClient, VisionResponse

__all__ = [
    "CacheConfig",
    "CachedResponse",
    "LLMCache",
    "OpenAIClient",
    "PromptTemplates",
    "VisionClient",
    "VisionProvider",
    "VisionResponse",
]
