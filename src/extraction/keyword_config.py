"""
Keyword Configuration Loader

Loads metric keyword patterns from external YAML configuration files,
allowing pattern updates without code changes.

Usage:
    from src.extraction.keyword_config import get_metric_keywords, get_exclusion_patterns

    # Get all keyword patterns
    keywords = get_metric_keywords()  # Returns dict[str, list[str]]

    # Get exclusion patterns
    exclusions = get_exclusion_patterns()  # Returns dict[str, list[str]]

    # Get specific patterns (for confidence bonuses)
    specific = get_specific_patterns()  # Returns list[str]
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

# Default config file location
DEFAULT_CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "metric_keywords.yaml"


class KeywordConfigError(Exception):
    """Raised when keyword configuration is invalid or cannot be loaded."""

    pass


@lru_cache(maxsize=1)
def _load_config(config_path: str | None = None) -> dict[str, Any]:
    """
    Load and cache the keyword configuration from YAML.

    Args:
        config_path: Optional path to config file. Uses default if not provided.

    Returns:
        Parsed YAML configuration dictionary.

    Raises:
        KeywordConfigError: If file cannot be loaded or parsed.
    """
    path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH

    # Allow override via environment variable
    env_path = os.environ.get("METRIC_KEYWORDS_CONFIG")
    if env_path:
        path = Path(env_path)

    if not path.exists():
        raise KeywordConfigError(f"Keyword config file not found: {path}")

    try:
        with open(path, encoding="utf-8") as f:
            config = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise KeywordConfigError(f"Failed to parse keyword config: {e}") from e

    if not isinstance(config, dict):
        raise KeywordConfigError(f"Invalid config format: expected dict, got {type(config)}")

    # Validate structure
    _validate_config(config)

    logger.info(f"Loaded keyword config from {path}: {len(config)} metrics")
    return config


def _validate_config(config: dict[str, Any]) -> None:
    """
    Validate the configuration structure.

    Args:
        config: Parsed YAML configuration.

    Raises:
        KeywordConfigError: If configuration is invalid.
    """
    for metric_id, metric_config in config.items():
        # Skip YAML anchor keys (starting with underscore)
        if metric_id.startswith("_"):
            continue

        if not isinstance(metric_config, dict):
            raise KeywordConfigError(
                f"Invalid config for {metric_id}: expected dict, got {type(metric_config)}"
            )

        if "patterns" not in metric_config:
            raise KeywordConfigError(f"Missing 'patterns' for metric {metric_id}")

        patterns = metric_config["patterns"]
        if not isinstance(patterns, list) or not patterns:
            raise KeywordConfigError(
                f"Invalid 'patterns' for {metric_id}: expected non-empty list"
            )

        # Validate each pattern is a string
        for i, pattern in enumerate(patterns):
            if not isinstance(pattern, str):
                raise KeywordConfigError(
                    f"Invalid pattern {i} for {metric_id}: expected string, got {type(pattern)}"
                )

        # Validate exclusions if present
        if "exclusions" in metric_config:
            exclusions = metric_config["exclusions"]
            if not isinstance(exclusions, list):
                raise KeywordConfigError(
                    f"Invalid 'exclusions' for {metric_id}: expected list"
                )
            for i, exc in enumerate(exclusions):
                if not isinstance(exc, str):
                    raise KeywordConfigError(
                        f"Invalid exclusion {i} for {metric_id}: expected string"
                    )

        # Validate specific_patterns if present
        if "specific_patterns" in metric_config:
            specific = metric_config["specific_patterns"]
            if not isinstance(specific, list):
                raise KeywordConfigError(
                    f"Invalid 'specific_patterns' for {metric_id}: expected list"
                )

        # Validate required_context if present
        if "required_context" in metric_config:
            req_ctx = metric_config["required_context"]
            if not isinstance(req_ctx, dict):
                raise KeywordConfigError(
                    f"Invalid 'required_context' for {metric_id}: expected dict"
                )
            if "patterns" not in req_ctx:
                raise KeywordConfigError(
                    f"Missing 'patterns' in required_context for {metric_id}"
                )
            ctx_patterns = req_ctx["patterns"]
            if not isinstance(ctx_patterns, list) or not ctx_patterns:
                raise KeywordConfigError(
                    f"Invalid 'patterns' in required_context for {metric_id}: "
                    "expected non-empty list"
                )
            for j, ctx_pattern in enumerate(ctx_patterns):
                if not isinstance(ctx_pattern, str):
                    raise KeywordConfigError(
                        f"Invalid required_context pattern {j} for {metric_id}: "
                        "expected string"
                    )
            # Validate proximity_chars if present
            if "proximity_chars" in req_ctx:
                prox = req_ctx["proximity_chars"]
                if not isinstance(prox, int) or prox <= 0:
                    raise KeywordConfigError(
                        f"Invalid 'proximity_chars' in required_context for {metric_id}: "
                        "expected positive int"
                    )


def _is_metric_key(key: str) -> bool:
    """Check if a key is a metric (not a YAML anchor starting with underscore)."""
    return not key.startswith("_")


def get_metric_keywords(config_path: str | None = None) -> dict[str, list[str]]:
    """
    Get all metric keyword patterns.

    Args:
        config_path: Optional path to config file.

    Returns:
        Dictionary mapping metric_id to list of regex patterns.
        Excludes YAML anchor keys (starting with underscore).
    """
    config = _load_config(config_path)
    return {
        metric_id: metric_config["patterns"]
        for metric_id, metric_config in config.items()
        if _is_metric_key(metric_id)
    }


def get_exclusion_patterns(config_path: str | None = None) -> dict[str, list[str]]:
    """
    Get exclusion patterns for metrics.

    Args:
        config_path: Optional path to config file.

    Returns:
        Dictionary mapping metric_id to list of exclusion regex patterns.
        Only includes metrics that have exclusions defined.
        Excludes YAML anchor keys (starting with underscore).
    """
    config = _load_config(config_path)
    return {
        metric_id: metric_config["exclusions"]
        for metric_id, metric_config in config.items()
        if _is_metric_key(metric_id) and "exclusions" in metric_config
    }


def get_specific_patterns(config_path: str | None = None) -> list[str]:
    """
    Get all specific (multi-word) patterns that get confidence bonuses.

    Args:
        config_path: Optional path to config file.

    Returns:
        List of specific pattern strings (not compiled regex).
        Excludes YAML anchor keys (starting with underscore).
    """
    config = _load_config(config_path)
    patterns: list[str] = []
    for metric_id, metric_config in config.items():
        if _is_metric_key(metric_id) and "specific_patterns" in metric_config:
            patterns.extend(metric_config["specific_patterns"])
    return patterns


def get_required_context(config_path: str | None = None) -> dict[str, dict[str, Any]]:
    """
    Get required context patterns for metrics.

    Metrics with required_context only generate review candidates when
    at least one of the context patterns appears within proximity of the
    keyword match. This filters out revenue synonyms (GMV, TCV, etc.)
    that appear without cohort or per-customer context.

    Args:
        config_path: Optional path to config file.

    Returns:
        Dictionary mapping metric_id to required context configuration.
        Only includes metrics that have required_context defined.
        Each config contains:
        - 'patterns': list of regex patterns (at least one must match)
        - 'proximity_chars': max distance for context check (default: 1500)
        Excludes YAML anchor keys (starting with underscore).
    """
    config = _load_config(config_path)
    return {
        metric_id: metric_config["required_context"]
        for metric_id, metric_config in config.items()
        if _is_metric_key(metric_id) and "required_context" in metric_config
    }


def reload_config() -> None:
    """
    Clear the cached configuration, forcing a reload on next access.

    Useful for testing or when the config file has been updated.
    """
    _load_config.cache_clear()
    logger.info("Keyword config cache cleared")


def get_metric_config(metric_id: str, config_path: str | None = None) -> dict[str, Any] | None:
    """
    Get the full configuration for a specific metric.

    Args:
        metric_id: The metric identifier (e.g., 'cm_customer_acquisition_cost').
        config_path: Optional path to config file.

    Returns:
        Dictionary with 'patterns', optional 'exclusions', and optional 'specific_patterns'.
        Returns None if metric not found.
    """
    config = _load_config(config_path)
    return config.get(metric_id)


def list_metrics(config_path: str | None = None) -> list[str]:
    """
    List all metric IDs defined in the configuration.

    Args:
        config_path: Optional path to config file.

    Returns:
        List of metric IDs.
        Excludes YAML anchor keys (starting with underscore).
    """
    config = _load_config(config_path)
    return [k for k in config.keys() if _is_metric_key(k)]
