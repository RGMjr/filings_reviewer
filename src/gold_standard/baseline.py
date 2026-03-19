"""
Baseline metrics management for gold standard validation.

Provides infrastructure to save, load, and compare validation metrics
over time to detect regressions in extraction quality.

Future Improvements (deferred - not needed for current requirements):
- Schema versioning: Add schema_version field for future-proofing JSON format changes
- Per-company deltas: Add company_deltas dict to ComparisonResult with exact delta values
- 100% coverage: Add tests for malformed JSON edge cases (currently at 95%)
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass
class MetricScores:
    """Precision, recall, and F1 scores for a validation run."""

    precision: float  # 0.0-1.0
    recall: float  # 0.0-1.0
    f1: float  # 0.0-1.0

    def __post_init__(self) -> None:
        """Validate score ranges."""
        for field_name in ("precision", "recall", "f1"):
            value = getattr(self, field_name)
            if not isinstance(value, (int, float)):
                raise TypeError(f"{field_name} must be a number, got {type(value).__name__}")
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{field_name} must be between 0.0 and 1.0, got {value}")


@dataclass
class BaselineMetrics:
    """
    Complete baseline metrics for a gold standard validation run.

    Stores overall metrics and per-company breakdown for comparison.
    """

    baseline_date: str  # ISO format datetime
    description: str | None
    overall: MetricScores
    by_company: dict[str, MetricScores]
    unique_recall: float | None = None  # Recall after deduplicating repeated gold entries

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dictionary."""
        d: dict[str, Any] = {
            "baseline_date": self.baseline_date,
            "description": self.description,
            "overall": asdict(self.overall),
            "by_company": {
                company: asdict(scores) for company, scores in self.by_company.items()
            },
        }
        if self.unique_recall is not None:
            d["unique_recall"] = self.unique_recall
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BaselineMetrics:
        """Create from dictionary (e.g., loaded from JSON)."""
        # Validate required fields
        required_fields = ["baseline_date", "overall", "by_company"]
        for field in required_fields:
            if field not in data:
                raise ValueError(f"Missing required field: {field}")

        # Parse overall scores
        overall_data = data["overall"]
        if not isinstance(overall_data, dict):
            raise ValueError("'overall' must be a dictionary")

        try:
            overall = MetricScores(
                precision=overall_data["precision"],
                recall=overall_data["recall"],
                f1=overall_data["f1"],
            )
        except KeyError as e:
            raise ValueError(f"Missing field in 'overall': {e}") from e

        # Parse per-company scores
        by_company_data = data["by_company"]
        if not isinstance(by_company_data, dict):
            raise ValueError("'by_company' must be a dictionary")

        by_company: dict[str, MetricScores] = {}
        for company, scores in by_company_data.items():
            if not isinstance(scores, dict):
                raise ValueError(f"Scores for company '{company}' must be a dictionary")
            try:
                by_company[company] = MetricScores(
                    precision=scores["precision"],
                    recall=scores["recall"],
                    f1=scores["f1"],
                )
            except KeyError as e:
                raise ValueError(
                    f"Missing field in scores for company '{company}': {e}"
                ) from e

        return cls(
            baseline_date=data["baseline_date"],
            description=data.get("description"),
            overall=overall,
            by_company=by_company,
            unique_recall=data.get("unique_recall"),
        )


@dataclass
class ComparisonResult:
    """Result of comparing current metrics against a baseline."""

    precision_delta: float  # Positive = improvement
    recall_delta: float
    f1_delta: float
    has_regression: bool  # True if any metric dropped beyond tolerance
    regressed_companies: list[str]  # Companies with regressions
    regressed_metrics: list[str]  # Which overall metrics regressed

    def summary(self) -> str:
        """Generate a human-readable summary."""
        parts = []
        parts.append(f"Precision: {self.precision_delta:+.1%}")
        parts.append(f"Recall: {self.recall_delta:+.1%}")
        parts.append(f"F1: {self.f1_delta:+.1%}")

        if self.has_regression:
            parts.append(f"REGRESSION DETECTED in: {', '.join(self.regressed_metrics)}")
            if self.regressed_companies:
                parts.append(f"Regressed companies: {', '.join(self.regressed_companies)}")

        return " | ".join(parts)


def save_baseline(
    metrics: BaselineMetrics,
    path: str | Path,
) -> None:
    """
    Save baseline metrics to a JSON file.

    Args:
        metrics: The baseline metrics to save
        path: File path to write to (will create parent directories)

    Raises:
        OSError: If file cannot be written
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(metrics.to_dict(), f, indent=2, ensure_ascii=False)


def load_baseline(path: str | Path) -> BaselineMetrics:
    """
    Load baseline metrics from a JSON file.

    Args:
        path: File path to read from

    Returns:
        BaselineMetrics loaded from file

    Raises:
        FileNotFoundError: If baseline file doesn't exist
        ValueError: If JSON structure is invalid
    """
    path = Path(path)

    if not path.exists():
        raise FileNotFoundError(
            f"Baseline file not found: {path}. "
            f"Run validation with --update-baseline to create one."
        )

    with open(path, encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in baseline file: {e}") from e

    if not isinstance(data, dict):
        raise ValueError("Baseline file must contain a JSON object at top level")

    return BaselineMetrics.from_dict(data)


def compare_to_baseline(
    current: BaselineMetrics,
    baseline: BaselineMetrics,
    tolerance: float = 0.0,
) -> ComparisonResult:
    """
    Compare current metrics against a baseline.

    Args:
        current: Current validation metrics
        baseline: Previous baseline metrics
        tolerance: Regression tolerance (e.g., 0.01 allows 1% regression)

    Returns:
        ComparisonResult with deltas and regression flags
    """
    precision_delta = current.overall.precision - baseline.overall.precision
    recall_delta = current.overall.recall - baseline.overall.recall
    f1_delta = current.overall.f1 - baseline.overall.f1

    # Check for overall metric regressions
    regressed_metrics: list[str] = []
    if precision_delta < -tolerance:
        regressed_metrics.append("precision")
    if recall_delta < -tolerance:
        regressed_metrics.append("recall")
    if f1_delta < -tolerance:
        regressed_metrics.append("f1")

    # Check for per-company regressions
    regressed_companies: list[str] = []
    for company, baseline_scores in baseline.by_company.items():
        if company not in current.by_company:
            # Company missing in current run - could be a regression or data change
            continue

        current_scores = current.by_company[company]

        # Check if any metric regressed for this company
        company_regressed = False
        if current_scores.precision - baseline_scores.precision < -tolerance:
            company_regressed = True
        if current_scores.recall - baseline_scores.recall < -tolerance:
            company_regressed = True
        if current_scores.f1 - baseline_scores.f1 < -tolerance:
            company_regressed = True

        if company_regressed:
            regressed_companies.append(company)

    has_regression = bool(regressed_metrics) or bool(regressed_companies)

    return ComparisonResult(
        precision_delta=precision_delta,
        recall_delta=recall_delta,
        f1_delta=f1_delta,
        has_regression=has_regression,
        regressed_companies=sorted(regressed_companies),
        regressed_metrics=regressed_metrics,
    )


def create_baseline_from_results(
    results: list[dict[str, Any]],
    description: str | None = None,
    unique_recall: float | None = None,
) -> BaselineMetrics:
    """
    Create a baseline from validation results.

    Args:
        results: List of validation result dicts (from validate_against_gold_standard)
        description: Optional description for this baseline

    Returns:
        BaselineMetrics ready to save
    """
    if not results:
        raise ValueError("Cannot create baseline from empty results")

    # Calculate overall metrics
    total_tp = sum(r.get("true_positives", 0) for r in results)
    total_fp = sum(r.get("false_positives", 0) for r in results)
    total_fn = sum(r.get("false_negatives", 0) for r in results)

    overall_precision = total_tp / (total_tp + total_fp) if (total_tp + total_fp) > 0 else 0.0
    overall_recall = total_tp / (total_tp + total_fn) if (total_tp + total_fn) > 0 else 0.0
    overall_f1 = (
        2 * (overall_precision * overall_recall) / (overall_precision + overall_recall)
        if (overall_precision + overall_recall) > 0
        else 0.0
    )

    overall = MetricScores(
        precision=overall_precision,
        recall=overall_recall,
        f1=overall_f1,
    )

    # Build per-company breakdown
    by_company: dict[str, MetricScores] = {}
    for r in results:
        company_name = r.get("company_name")
        if not company_name:
            continue

        by_company[company_name] = MetricScores(
            precision=r.get("precision", 0.0),
            recall=r.get("recall", 0.0),
            f1=r.get("f1_score", 0.0),
        )

    return BaselineMetrics(
        baseline_date=datetime.now(UTC).isoformat(),
        description=description,
        overall=overall,
        by_company=by_company,
        unique_recall=unique_recall,
    )
