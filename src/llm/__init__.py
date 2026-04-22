"""
LLM Integration Module

This module provides LLM API integration for metric extraction from SEC filings.
Supports OpenAI (default), Gemini, and Anthropic vision providers via VISION_PROVIDER env var.
"""

from src.llm.cache import CacheConfig, CachedResponse, LLMCache
from src.llm.openai_client import OpenAIClient
from src.llm.prompts import PromptTemplates
from src.llm.providers import VisionProvider
from src.llm.vision_client import VisionClient, VisionResponse

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
