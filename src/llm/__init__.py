"""
LLM Integration Module

This module provides OpenAI API integration for metric extraction from SEC filings.
"""

from .openai_client import OpenAIClient
from .prompts import PromptTemplates

__all__ = ["OpenAIClient", "PromptTemplates"]
