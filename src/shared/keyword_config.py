"""
Keyword Configuration Loader

Loads metric keyword patterns from external YAML configuration files,
allowing pattern updates without code changes.

Usage:
    from src.shared.keyword_config import get_metric_keywords, get_exclusion_patterns

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
from typing import Any, cast

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

        # Skip validation for deprecated metrics (patterns removed at trim time)
        if metric_config.get("status") == "deprecated":
            continue

        if "patterns" not in metric_config:
            raise KeywordConfigError(f"Missing 'patterns' for metric {metric_id}")

        patterns = metric_config["patterns"]
        if not isinstance(patterns, list) or not patterns:
            raise KeywordConfigError(f"Invalid 'patterns' for {metric_id}: expected non-empty list")

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
                raise KeywordConfigError(f"Invalid 'exclusions' for {metric_id}: expected list")
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
                raise KeywordConfigError(f"Missing 'patterns' in required_context for {metric_id}")
            ctx_patterns = req_ctx["patterns"]
            if not isinstance(ctx_patterns, list) or not ctx_patterns:
                raise KeywordConfigError(
                    f"Invalid 'patterns' in required_context for {metric_id}: "
                    "expected non-empty list"
                )
            for j, ctx_pattern in enumerate(ctx_patterns):
                if not isinstance(ctx_pattern, str):
                    raise KeywordConfigError(
                        f"Invalid required_context pattern {j} for {metric_id}: expected string"
                    )
            # Validate proximity_chars if present
            if "proximity_chars" in req_ctx:
                prox = req_ctx["proximity_chars"]
                if not isinstance(prox, int) or prox <= 0:
                    raise KeywordConfigError(
                        f"Invalid 'proximity_chars' in required_context for {metric_id}: "
                        "expected positive int"
                    )

        # Validate aliases if present
        if "aliases" in metric_config:
            aliases_list = metric_config["aliases"]
            if not isinstance(aliases_list, list):
                raise KeywordConfigError(f"Invalid 'aliases' for {metric_id}: expected list")
            for i, alias in enumerate(aliases_list):
                if not isinstance(alias, str):
                    raise KeywordConfigError(f"Invalid alias {i} for {metric_id}: expected string")
                if not alias.startswith("cm_"):
                    raise KeywordConfigError(
                        f"Invalid alias '{alias}' for {metric_id}: must start with 'cm_'"
                    )

        # Validate status if present
        if "status" in metric_config:
            status = metric_config["status"]
            if not isinstance(status, str):
                raise KeywordConfigError(f"Invalid 'status' for {metric_id}: expected string")
            if status not in ("active", "deprecated"):
                raise KeywordConfigError(
                    f"Invalid 'status' value for {metric_id}: expected 'active' or 'deprecated'"
                )

        # Validate deprecation_reason if present
        if "deprecation_reason" in metric_config:
            reason = metric_config["deprecation_reason"]
            if not isinstance(reason, str):
                raise KeywordConfigError(
                    f"Invalid 'deprecation_reason' for {metric_id}: expected string"
                )


def _is_metric_key(key: str) -> bool:
    """Check if a key is a metric (not a YAML anchor starting with underscore)."""
    return not key.startswith("_")


def is_metric_deprecated(metric_id: str, config_path: str | None = None) -> bool:
    """
    Check if a metric is deprecated.

    Args:
        metric_id: The metric identifier to check.
        config_path: Optional path to config file.

    Returns:
        True if the metric has status='deprecated', False otherwise.
    """
    config = _load_config(config_path)
    metric_config = config.get(metric_id)
    if not metric_config:
        return False
    return bool(metric_config.get("status") == "deprecated")


def get_active_metrics(config_path: str | None = None) -> list[str]:
    """
    Get all active (non-deprecated) metric IDs.

    Args:
        config_path: Optional path to config file.

    Returns:
        List of metric IDs that are not deprecated.
        Excludes YAML anchor keys (starting with underscore).
    """
    config = _load_config(config_path)
    return [
        metric_id
        for metric_id in config.keys()
        if _is_metric_key(metric_id) and config[metric_id].get("status") != "deprecated"
    ]


def get_metric_tiers(config_path: str | None = None) -> dict[str, int]:
    """
    Get the importance tier for each active metric.

    Args:
        config_path: Optional path to config file.

    Returns:
        Dictionary mapping metric_id to tier (1=must-not-miss, 2=nice-to-have).
        Metrics without an explicit tier default to 2.
    """
    config = _load_config(config_path)
    return {
        metric_id: config[metric_id].get("tier", 2)
        for metric_id in config.keys()
        if _is_metric_key(metric_id) and config[metric_id].get("status") != "deprecated"
    }


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
    # Cast is safe: _validate_config() ensures patterns are list[str]
    return {
        metric_id: cast(list[str], metric_config["patterns"])
        for metric_id, metric_config in config.items()
        if _is_metric_key(metric_id) and metric_config.get("status") != "deprecated"
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
        if _is_metric_key(metric_id) and "exclusions" in metric_config and metric_config.get("status") != "deprecated"
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
        if _is_metric_key(metric_id) and "specific_patterns" in metric_config and metric_config.get("status") != "deprecated":
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
        if _is_metric_key(metric_id) and "required_context" in metric_config and metric_config.get("status") != "deprecated"
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


# =============================================================================
# Metric ID Alias Functions
# =============================================================================


def get_aliases(config_path: str | None = None) -> dict[str, list[str]]:
    """
    Get aliases for metrics.

    Aliases allow a single canonical metric ID to match against alternative
    identifiers used in external sources (e.g., gold standard files).

    Args:
        config_path: Optional path to config file.

    Returns:
        Dictionary mapping canonical metric_id to list of alias IDs.
        Only includes metrics that have aliases defined.
        Excludes YAML anchor keys (starting with underscore).

    Example:
        >>> aliases = get_aliases()
        >>> aliases.get("cm_example_metric")
        ["cm_example_alias"]  # If defined in YAML
    """
    config = _load_config(config_path)
    return {
        metric_id: metric_config["aliases"]
        for metric_id, metric_config in config.items()
        if _is_metric_key(metric_id) and "aliases" in metric_config
    }


def resolve_to_canonical(metric_id: str, config_path: str | None = None) -> str:
    """
    Resolve an alias to its canonical metric ID.

    If the input is already a canonical ID or not found in aliases,
    returns the input unchanged.

    Args:
        metric_id: The metric ID to resolve (may be canonical or alias).
        config_path: Optional path to config file.

    Returns:
        The canonical metric ID if input was an alias, otherwise the input.

    Example:
        >>> resolve_to_canonical("cm_example_alias")
        "cm_example_metric"  # If alias is defined

        >>> resolve_to_canonical("cm_arr")
        "cm_arr"  # No alias, returns unchanged
    """
    aliases = get_aliases(config_path)

    # Build reverse lookup: alias -> canonical
    alias_to_canonical: dict[str, str] = {}
    for canonical, alias_list in aliases.items():
        for alias in alias_list:
            alias_to_canonical[alias] = canonical

    # Return canonical if found, otherwise return input
    return alias_to_canonical.get(metric_id, metric_id)


def get_all_equivalent_ids(metric_id: str, config_path: str | None = None) -> set[str]:
    """
    Get all equivalent metric IDs (canonical + aliases) for a given ID.

    Works whether input is canonical or alias.

    Args:
        metric_id: Any metric ID (canonical or alias).
        config_path: Optional path to config file.

    Returns:
        Set containing the canonical ID and all aliases.
        If metric has no aliases, returns set with just the input.

    Example:
        >>> get_all_equivalent_ids("cm_example_metric")
        {"cm_example_metric", "cm_example_alias"}  # If aliases defined

        >>> get_all_equivalent_ids("cm_arr")
        {"cm_arr"}  # No aliases, returns just the input
    """
    aliases = get_aliases(config_path)

    # First resolve to canonical
    canonical = resolve_to_canonical(metric_id, config_path)

    # Get all aliases for the canonical ID
    result = {canonical}
    if canonical in aliases:
        result.update(aliases[canonical])

    return result


def metrics_are_equivalent(
    metric_id_1: str, metric_id_2: str, config_path: str | None = None
) -> bool:
    """
    Check if two metric IDs are equivalent (same canonical or aliased).

    Args:
        metric_id_1: First metric ID.
        metric_id_2: Second metric ID.
        config_path: Optional path to config file.

    Returns:
        True if the metrics are equivalent (both resolve to same canonical).

    Example:
        >>> metrics_are_equivalent("cm_example_metric", "cm_example_alias")
        True  # If alias is defined

        >>> metrics_are_equivalent("cm_arr", "cm_mrr")
        False  # Different metrics
    """
    return resolve_to_canonical(metric_id_1, config_path) == resolve_to_canonical(
        metric_id_2, config_path
    )
