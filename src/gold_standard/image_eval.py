"""Image extraction evaluation metrics for the vision benchmark harness.

This module implements metric computations used to compare image-extraction
quality across vision providers.  It is intentionally dependency-light
(stdlib + dataclasses) so it can be imported in CI without OpenAI/boto3.

Metric bundle
-------------
- chart_detection_precision / recall  -- predicted chart vs reviewer label
- ocr_cell_accuracy                   -- cell/axis-label string accuracy
- ocr_axis_label_accuracy             -- axis-label subset accuracy
- title_match_score                   -- chart-title extraction quality
- legend_match_score                  -- legend text extraction quality
- tier1_fact_recall                   -- downstream Tier-1 metric-fact recall
- parse_failure_rate                  -- fraction of runs where output was unparseable
- mean_cost_usd                       -- mean cost per image
- mean_latency_ms                     -- mean latency per image (ms)

Usage example::

    from src.gold_standard.image_eval import (
        ImageEvalResult,
        ImageRunRecord,
        aggregate_results,
        chart_detection_metrics,
    )

    # Build records from benchmark runs, then aggregate.
    records = [...]
    summary = aggregate_results(records)
"""

from __future__ import annotations

import difflib
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Per-run record
# ---------------------------------------------------------------------------


@dataclass
class ImageRunRecord:
    """One benchmark run record for a single image.

    Fields
    ------
    img_id
        UUID from ``v2_image_assets``.
    reviewer_decision
        Ground-truth decision: ``"relevant"`` or ``"not_relevant"``.
    reviewer_chart_type
        Ground-truth chart type (None for not_relevant images).
    reviewer_notes
        Free-text reviewer notes (used for title/legend quality checks).
    tier1_facts_in_db
        Number of Tier-1 metric facts linked to this image in the DB.
    predicted_chart_type
        Model's predicted chart type (or ``None`` if model said no chart).
    predicted_relevant
        Whether the model predicted the image as relevant (chart/table found).
    ocr_cells_extracted
        List of cell strings the model extracted (empty list if none).
    ocr_cells_reference
        Reference cell strings from a human annotation or prior gold OCR run.
    axis_labels_extracted
        Axis label strings produced by the model.
    axis_labels_reference
        Reference axis label strings.
    title_extracted
        Chart title as extracted by the model (empty string if absent).
    legend_extracted
        Legend items as extracted by the model (empty string if absent).
    tier1_facts_extracted
        Number of Tier-1 facts produced by the extraction pipeline for this image.
    parse_failed
        True if the model output could not be parsed into structured data.
    cost_usd
        API cost for this call in USD.
    latency_ms
        API latency in milliseconds.
    raw_output
        Raw text response from the model (for audit).
    provider
        Provider identifier, e.g. ``"openai/gpt-4o"``.
    """

    img_id: str
    reviewer_decision: str  # "relevant" | "not_relevant"
    reviewer_chart_type: str | None
    reviewer_notes: str
    tier1_facts_in_db: int
    predicted_chart_type: str | None
    predicted_relevant: bool
    ocr_cells_extracted: list[str] = field(default_factory=list)
    ocr_cells_reference: list[str] = field(default_factory=list)
    axis_labels_extracted: list[str] = field(default_factory=list)
    axis_labels_reference: list[str] = field(default_factory=list)
    title_extracted: str = ""
    legend_extracted: str = ""
    tier1_facts_extracted: int = 0
    parse_failed: bool = False
    cost_usd: float = 0.0
    latency_ms: int = 0
    raw_output: str = ""
    provider: str = "unknown"
    # Wave B5.x — per-image chart-DATA fidelity (chart-read mode only).
    # ``extracted_points`` holds the flattened numeric payload that the
    # model returned (series points + annotations, normalised to
    # ``{"value": float, "period": str|None, "source": "series"|"annotation"}``);
    # ``reference_points`` holds the ground-truth rows pulled from
    # ``data/gold_standard/<company>/extracted_values.csv`` for entries
    # carrying a ``ground_truth_value_ids`` manifest field. TP/FP/FN are
    # the per-record match counters computed by the harness before the
    # record is constructed.
    extracted_points: list[dict[str, Any]] = field(default_factory=list)
    reference_points: list[dict[str, Any]] = field(default_factory=list)
    data_value_tp: int = 0
    data_value_fp: int = 0
    data_value_fn: int = 0


# ---------------------------------------------------------------------------
# Aggregate result
# ---------------------------------------------------------------------------


@dataclass
class ImageEvalResult:
    """Aggregated evaluation metrics across a corpus of benchmark runs.

    All rate/fraction fields are in [0.0, 1.0].
    Cost and latency are per-image means.
    """

    # Chart detection
    chart_detection_precision: float
    chart_detection_recall: float
    chart_detection_f1: float

    # OCR quality
    ocr_cell_accuracy: float  # token-level edit-distance ratio, averaged
    ocr_axis_label_accuracy: float

    # Title / legend extraction quality
    title_match_score: float  # SequenceMatcher ratio, averaged
    legend_match_score: float

    # Downstream fact recall
    tier1_fact_recall: float  # facts_extracted / facts_in_db (images with >0 in db)

    # Infrastructure
    parse_failure_rate: float
    mean_cost_usd: float
    mean_latency_ms: float

    # Corpus size
    n_images: int
    n_relevant: int  # ground-truth relevant
    n_not_relevant: int

    # Wave B5.x — chart-DATA fidelity (chart-read mode only). Micro-averaged
    # TP/FP/FN over records that carry ``reference_points``; unscored
    # records do not contribute. ``n_images_scored_on_data`` is how many
    # records had non-empty ``reference_points``.
    data_value_precision: float = 0.0
    data_value_recall: float = 0.0
    data_value_f1: float = 0.0
    n_images_scored_on_data: int = 0

    # Extra diagnostics
    extra: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Individual metric helpers
# ---------------------------------------------------------------------------


def _str_similarity(a: str, b: str) -> float:
    """Return SequenceMatcher similarity ratio for two strings.

    Normalises both strings to lowercase before comparing so that casing
    differences (common in axis labels) do not count as full mismatches.
    Returns 0.0 if both strings are empty.
    """
    a_norm = a.strip().lower()
    b_norm = b.strip().lower()
    if not a_norm and not b_norm:
        return 1.0  # both empty → perfect match by convention
    if not a_norm or not b_norm:
        return 0.0
    return difflib.SequenceMatcher(None, a_norm, b_norm).ratio()


def _list_cell_accuracy(extracted: list[str], reference: list[str]) -> float:
    """Compute average token-level similarity between two cell lists.

    Pairs cells by position (shorter list padded with empty strings).  This
    is intentionally simple — full alignment would require Hungarian matching
    and is overkill for a benchmark signal.
    """
    if not reference:
        return 1.0 if not extracted else 0.0
    max_len = max(len(extracted), len(reference))
    scores = []
    for i in range(max_len):
        ext = extracted[i] if i < len(extracted) else ""
        ref = reference[i] if i < len(reference) else ""
        scores.append(_str_similarity(ext, ref))
    return sum(scores) / len(scores)


def chart_detection_metrics(
    records: list[ImageRunRecord],
) -> tuple[float, float, float]:
    """Compute chart detection precision, recall, and F1.

    Ground truth positive = reviewer_decision == "relevant".
    Predicted positive = predicted_relevant == True.

    Returns
    -------
    (precision, recall, f1)  each in [0.0, 1.0]
    """
    tp = sum(1 for r in records if r.reviewer_decision == "relevant" and r.predicted_relevant)
    fp = sum(1 for r in records if r.reviewer_decision != "relevant" and r.predicted_relevant)
    fn = sum(1 for r in records if r.reviewer_decision == "relevant" and not r.predicted_relevant)

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
    return precision, recall, f1


def ocr_cell_accuracy_score(records: list[ImageRunRecord]) -> float:
    """Mean cell-list accuracy over all records that have reference cells."""
    relevant = [r for r in records if r.ocr_cells_reference]
    if not relevant:
        return 1.0
    return sum(
        _list_cell_accuracy(r.ocr_cells_extracted, r.ocr_cells_reference) for r in relevant
    ) / len(relevant)


def ocr_axis_label_accuracy_score(records: list[ImageRunRecord]) -> float:
    """Mean axis-label accuracy over all records that have reference labels."""
    relevant = [r for r in records if r.axis_labels_reference]
    if not relevant:
        return 1.0
    return sum(
        _list_cell_accuracy(r.axis_labels_extracted, r.axis_labels_reference) for r in relevant
    ) / len(relevant)


def title_match_score(records: list[ImageRunRecord]) -> float:
    """Mean title similarity against reviewer_notes where notes are non-empty.

    We use reviewer_notes as a proxy for the expected chart title because
    reviewers frequently note the chart title when it is relevant.  This is an
    imperfect but practical signal.
    """
    with_notes = [r for r in records if r.reviewer_notes.strip()]
    if not with_notes:
        return 1.0
    return sum(_str_similarity(r.title_extracted, r.reviewer_notes) for r in with_notes) / len(
        with_notes
    )


def legend_match_score(records: list[ImageRunRecord]) -> float:
    """Mean legend similarity against reviewer_notes (same proxy as title)."""
    with_notes = [r for r in records if r.reviewer_notes.strip()]
    if not with_notes:
        return 1.0
    return sum(_str_similarity(r.legend_extracted, r.reviewer_notes) for r in with_notes) / len(
        with_notes
    )


def tier1_fact_recall_score(records: list[ImageRunRecord]) -> float:
    """Fraction of DB Tier-1 facts that were re-extracted by the model.

    Only considers images where at least one Tier-1 fact exists in the DB
    (``tier1_facts_in_db > 0``).  Images without DB facts do not contribute
    to this metric to avoid diluting the signal with images that never had
    extractable facts.
    """
    images_with_facts = [r for r in records if r.tier1_facts_in_db > 0]
    if not images_with_facts:
        return 1.0
    total_in_db = sum(r.tier1_facts_in_db for r in images_with_facts)
    total_extracted = sum(r.tier1_facts_extracted for r in images_with_facts)
    return min(total_extracted / total_in_db, 1.0)


def parse_failure_rate(records: list[ImageRunRecord]) -> float:
    """Fraction of runs where the model output could not be parsed."""
    if not records:
        return 0.0
    return sum(1 for r in records if r.parse_failed) / len(records)


def data_value_match(
    extracted: list[dict[str, Any]],
    reference: list[dict[str, Any]],
    rel_tol: float = 0.02,
) -> tuple[int, int, int]:
    """Compare extracted chart data against ground-truth values.

    Used by the Wave B5.x chart-read harness to score per-point fidelity
    for corpus entries that have an explicit ``ground_truth_value_ids``
    mapping to CSV chart rows.

    Parameters
    ----------
    extracted
        Flattened model output. Each dict must carry a numeric ``"value"``;
        other keys are ignored.
    reference
        Ground-truth rows. Each dict must carry a numeric ``"value"``
        (already cast to float); other keys are ignored.
    rel_tol
        Relative tolerance for a numeric match. Two values ``a`` and ``b``
        match when ``abs(a - b) <= rel_tol * max(abs(a), abs(b), 1.0)``.
        The ``max(..., 1.0)`` floor keeps very small values (e.g. 0.0)
        from demanding absurd precision.

    Returns
    -------
    tuple[int, int, int]
        ``(tp, fp, fn)`` counted greedily: every reference point is
        matched against at most one extracted point (first hit wins), so
        duplicates in the extracted list do not inflate TP. Unmatched
        extracted → FP; unmatched reference → FN.
    """
    if not reference and not extracted:
        return 0, 0, 0

    def _coerce(d: dict[str, Any]) -> float | None:
        v = d.get("value")
        if v is None:
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    extracted_values: list[float] = []
    for d in extracted:
        v = _coerce(d)
        if v is not None:
            extracted_values.append(v)
    reference_values: list[float] = []
    for d in reference:
        v = _coerce(d)
        if v is not None:
            reference_values.append(v)

    used: set[int] = set()
    tp = 0
    for ref_val in reference_values:
        for i, ext_val in enumerate(extracted_values):
            if i in used:
                continue
            denom = max(abs(ref_val), abs(ext_val), 1.0)
            if abs(ref_val - ext_val) <= rel_tol * denom:
                used.add(i)
                tp += 1
                break

    fn = len(reference_values) - tp
    fp = len(extracted_values) - len(used)
    return tp, fp, fn


def data_value_scores(records: list[ImageRunRecord]) -> tuple[float, float, float, int]:
    """Micro-average chart-data TP/FP/FN across records and compute P/R/F1.

    Only records with a non-empty ``reference_points`` contribute to the
    aggregates. Returns ``(precision, recall, f1, n_scored)``. When no
    record carries reference points, every number is 0.0 / 0.
    """
    scored = [r for r in records if r.reference_points]
    if not scored:
        return 0.0, 0.0, 0.0, 0
    tp = sum(r.data_value_tp for r in scored)
    fp = sum(r.data_value_fp for r in scored)
    fn = sum(r.data_value_fn for r in scored)
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
    return precision, recall, f1, len(scored)


# ---------------------------------------------------------------------------
# Aggregate function
# ---------------------------------------------------------------------------


def aggregate_results(records: list[ImageRunRecord]) -> ImageEvalResult:
    """Compute all benchmark metrics from a list of run records.

    Parameters
    ----------
    records:
        List of :class:`ImageRunRecord` objects produced by the benchmark
        harness.  May be empty; empty input returns zeroed-out metrics with
        ``n_images=0``.

    Returns
    -------
    :class:`ImageEvalResult`
    """
    if not records:
        return ImageEvalResult(
            chart_detection_precision=0.0,
            chart_detection_recall=0.0,
            chart_detection_f1=0.0,
            ocr_cell_accuracy=0.0,
            ocr_axis_label_accuracy=0.0,
            title_match_score=0.0,
            legend_match_score=0.0,
            tier1_fact_recall=0.0,
            parse_failure_rate=0.0,
            mean_cost_usd=0.0,
            mean_latency_ms=0.0,
            n_images=0,
            n_relevant=0,
            n_not_relevant=0,
        )

    n = len(records)
    prec, rec, f1 = chart_detection_metrics(records)
    dv_p, dv_r, dv_f1, dv_n = data_value_scores(records)

    return ImageEvalResult(
        chart_detection_precision=prec,
        chart_detection_recall=rec,
        chart_detection_f1=f1,
        ocr_cell_accuracy=ocr_cell_accuracy_score(records),
        ocr_axis_label_accuracy=ocr_axis_label_accuracy_score(records),
        title_match_score=title_match_score(records),
        legend_match_score=legend_match_score(records),
        tier1_fact_recall=tier1_fact_recall_score(records),
        parse_failure_rate=parse_failure_rate(records),
        mean_cost_usd=sum(r.cost_usd for r in records) / n,
        mean_latency_ms=sum(r.latency_ms for r in records) / n,
        n_images=n,
        n_relevant=sum(1 for r in records if r.reviewer_decision == "relevant"),
        n_not_relevant=sum(1 for r in records if r.reviewer_decision != "relevant"),
        data_value_precision=dv_p,
        data_value_recall=dv_r,
        data_value_f1=dv_f1,
        n_images_scored_on_data=dv_n,
    )


# ---------------------------------------------------------------------------
# Corpus stratification helpers
# ---------------------------------------------------------------------------

# All chart_type values from migration 29
CHART_TYPES = frozenset(
    {
        "cohort_table",
        "cohort_parfait",
        "line_chart",
        "bar_chart",
        "stacked_bar",
        "other_chart",
        "mixed",
    }
)

# All rejection_reason values from migration 29
REJECTION_REASONS = frozenset(
    {
        "decorative",
        "not_a_chart",
        "wrong_subject",
        "duplicate",
        "unreadable",
        "other",
    }
)

# Tier-1 chart types — cohort data and mixed views are highest priority
TIER1_CHART_TYPES = frozenset(
    {
        "cohort_table",
        "cohort_parfait",
        "mixed",
    }
)

# Chart types likely to require good OCR (dense text labels)
HARD_OCR_CHART_TYPES = frozenset(
    {
        "cohort_table",
        "cohort_parfait",
        "stacked_bar",
        "mixed",
    }
)


def stratum_label(
    decision: str,
    chart_type: str | None,
    rejection_reason: str | None,
) -> str:
    """Return a stratum label for a corpus entry.

    Strata are:
    - ``chart/<chart_type>``  for relevant images
    - ``rejection/<reason>``  for not_relevant images
    """
    if decision == "relevant" and chart_type:
        return f"chart/{chart_type}"
    if decision == "not_relevant" and rejection_reason:
        return f"rejection/{rejection_reason}"
    return "unknown"


def is_tier1_image(chart_type: str | None) -> bool:
    """Return True if a chart_type maps to a Tier-1 chart category."""
    return chart_type in TIER1_CHART_TYPES if chart_type else False


def is_hard_ocr_image(chart_type: str | None) -> bool:
    """Return True if a chart_type is in the hard-OCR subset."""
    return chart_type in HARD_OCR_CHART_TYPES if chart_type else False
