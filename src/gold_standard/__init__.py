"""Gold standard validation infrastructure for regression testing."""

from src.gold_standard.baseline import (
    BaselineMetrics,
    ComparisonResult,
    MetricScores,
    compare_to_baseline,
    load_baseline,
    save_baseline,
)

__all__ = [
    "BaselineMetrics",
    "ComparisonResult",
    "MetricScores",
    "compare_to_baseline",
    "load_baseline",
    "save_baseline",
]
