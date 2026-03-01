"""
Backward-compatibility shim. Moved to src/shared/keyword_config.py.

This file is retained temporarily so existing V1 code and tests continue to work.
New code should import from src.shared.keyword_config directly.
"""

from src.shared.keyword_config import (  # noqa: F401
    DEFAULT_CONFIG_PATH,
    KeywordConfigError,
    get_active_metrics,
    get_aliases,
    get_all_equivalent_ids,
    get_exclusion_patterns,
    get_metric_config,
    get_metric_keywords,
    get_required_context,
    get_specific_patterns,
    is_metric_deprecated,
    list_metrics,
    metrics_are_equivalent,
    reload_config,
    resolve_to_canonical,
)
