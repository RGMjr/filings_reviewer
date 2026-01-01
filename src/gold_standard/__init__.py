"""Gold standard validation infrastructure for regression testing."""

from src.gold_standard.baseline import (
    BaselineMetrics,
    ComparisonResult,
    MetricScores,
    compare_to_baseline,
    load_baseline,
    save_baseline,
)
from src.gold_standard.fresh_extractor import (
    ExtractionResult,
    ParsedSecUrl,
    extract_fresh,
    extract_fresh_batch,
    find_local_filing,
    parse_sec_url,
    segment_and_generate,
)

__all__ = [
    # Baseline
    "BaselineMetrics",
    "ComparisonResult",
    "MetricScores",
    "compare_to_baseline",
    "load_baseline",
    "save_baseline",
    # Fresh extraction
    "ExtractionResult",
    "ParsedSecUrl",
    "extract_fresh",
    "extract_fresh_batch",
    "find_local_filing",
    "parse_sec_url",
    "segment_and_generate",
]
