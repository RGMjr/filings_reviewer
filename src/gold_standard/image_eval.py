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
    # metric-classify mode — presence-first classification. ``predicted_metrics``
    # is the set the model emitted; ``reference_metrics`` is the hand-annotated
    # ground truth from the manifest (``ground_truth_metric_ids``).
    # ``classification_confidence`` is the model's self-reported confidence over
    # the predicted set. ``rejection_reason`` carries the model's reason when
    # ``predicted_metrics`` is empty (matches the
    # ``v2_image_review_decisions.rejection_reason`` enum; table images emit
    # ``"other"``). ``reviewer_action`` is the single-word bucket a reviewer
    # would take given the prediction vs reference (one of
    # ``accept``/``reject``/``correct``/``add``/``partial``/``skip``).
    predicted_metrics: list[str] = field(default_factory=list)
    reference_metrics: list[str] = field(default_factory=list)
    classification_confidence: float = 0.0
    rejection_reason: str | None = None
    reviewer_action: str = ""


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

    # metric-classify mode — reviewer-disposition rates over the full corpus
    # and micro-averaged metric-tag P/R/F1 over records that carry a
    # non-empty ``reference_metrics``. Rates sum to 1.0 over ``n_images``.
    # ``auto_disposition_rate`` (accept + skip) is the human-hours-saved
    # headline number; ``calibration_ece`` is expected calibration error on
    # classification confidence for the same n_scored subset.
    accept_rate: float = 0.0
    reject_rate: float = 0.0
    correct_rate: float = 0.0
    add_rate: float = 0.0
    partial_rate: float = 0.0
    skip_rate: float = 0.0
    auto_disposition_rate: float = 0.0
    metric_tag_precision: float = 0.0
    metric_tag_recall: float = 0.0
    metric_tag_f1: float = 0.0
    calibration_ece: float = 0.0
    n_images_scored_on_metric_tags: int = 0

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


REVIEWER_ACTIONS: tuple[str, ...] = (
    "accept",
    "reject",
    "correct",
    "add",
    "partial",
    "skip",
)


def reviewer_action(predicted: list[str], reference: list[str]) -> str:
    """Return the single-word reviewer action given predicted vs reference sets.

    Buckets (see ``REVIEWER_ACTIONS``):

    - ``skip``    — both sets empty (auto-skip, zero reviewer time)
    - ``accept``  — sets equal and non-empty (single-click accept)
    - ``add``     — predicted is empty OR a proper subset of reference
                    (pipeline missed at least one metric — costly)
    - ``reject``  — predicted non-empty, reference empty (all bogus)
    - ``correct`` — sets disjoint with both non-empty (full replacement)
    - ``partial`` — overlap but neither is a subset (mixed acc/rej/add)

    This is the scorer the ``--mode metric-classify`` harness uses to
    translate per-image prediction outcomes into reviewer-workflow cost.
    """
    pset, rset = set(predicted), set(reference)
    if not pset and not rset:
        return "skip"
    if pset == rset:
        return "accept"
    if not pset and rset:
        return "add"
    if pset and not rset:
        return "reject"
    if pset < rset:
        return "add"
    if pset.isdisjoint(rset):
        return "correct"
    return "partial"


def metric_tag_match(predicted: list[str], reference: list[str]) -> tuple[int, int, int]:
    """Per-image TP/FP/FN from predicted vs reference metric_id sets.

    Used for micro-averaged set-overlap P/R/F1 across the corpus. Returns
    ``(0, 0, 0)`` for fully empty inputs so empty/empty pairs do not
    inflate the denominator.
    """
    pset, rset = set(predicted), set(reference)
    if not pset and not rset:
        return 0, 0, 0
    tp = len(pset & rset)
    fp = len(pset - rset)
    fn = len(rset - pset)
    return tp, fp, fn


def reviewer_action_counts(records: list[ImageRunRecord]) -> dict[str, int]:
    """Count records in each reviewer-action bucket.

    Reads the pre-computed ``reviewer_action`` field on each record; falls
    back to recomputing from ``predicted_metrics`` / ``reference_metrics``
    when the field is blank so the helper is robust to manually constructed
    records. Every bucket in :data:`REVIEWER_ACTIONS` is present in the
    result, even if its count is 0, so callers can index safely.
    """
    counts = dict.fromkeys(REVIEWER_ACTIONS, 0)
    for rec in records:
        action = rec.reviewer_action or reviewer_action(
            rec.predicted_metrics, rec.reference_metrics
        )
        if action in counts:
            counts[action] += 1
    return counts


def expected_calibration_error(records: list[ImageRunRecord], n_bins: int = 10) -> float:
    """Binned ECE over records with scoring evidence.

    Only records that carry a non-empty ``reference_metrics`` contribute —
    calibration is only meaningful where ground truth exists. Accuracy
    per bin is the fraction of records whose ``reviewer_action`` is
    ``accept`` (predicted set matches reference exactly); ``skip`` bins
    are excluded because they have no confidence signal. The bins
    partition ``[0.0, 1.0]`` uniformly; the final number is the
    sample-weighted average of ``|accuracy - mean_confidence|`` per
    non-empty bin. Returns 0.0 when no record has reference metrics.
    """
    if n_bins <= 0:
        raise ValueError("n_bins must be positive")
    scored = [r for r in records if r.reference_metrics]
    if not scored:
        return 0.0

    bin_confidences: list[list[float]] = [[] for _ in range(n_bins)]
    bin_correct: list[list[int]] = [[] for _ in range(n_bins)]
    for rec in scored:
        conf = max(0.0, min(1.0, float(rec.classification_confidence)))
        # Uniform bin in [0, 1); confidence of 1.0 falls in the last bin.
        idx = min(n_bins - 1, int(conf * n_bins))
        bin_confidences[idx].append(conf)
        action = rec.reviewer_action or reviewer_action(
            rec.predicted_metrics, rec.reference_metrics
        )
        bin_correct[idx].append(1 if action == "accept" else 0)

    total = len(scored)
    ece = 0.0
    for confs, corrs in zip(bin_confidences, bin_correct, strict=False):
        if not confs:
            continue
        bin_weight = len(confs) / total
        bin_acc = sum(corrs) / len(corrs)
        bin_conf = sum(confs) / len(confs)
        ece += bin_weight * abs(bin_acc - bin_conf)
    return ece


def metric_tag_scores(
    records: list[ImageRunRecord],
) -> tuple[float, float, float, int]:
    """Micro-average metric-tag TP/FP/FN across scored records → P/R/F1.

    Only records whose ``reference_metrics`` is non-empty contribute, so
    ``skip`` records (both sides empty) do not dilute the tag-level view.
    """
    scored = [r for r in records if r.reference_metrics]
    if not scored:
        return 0.0, 0.0, 0.0, 0
    tp = fp = fn = 0
    for rec in scored:
        rtp, rfp, rfn = metric_tag_match(rec.predicted_metrics, rec.reference_metrics)
        tp += rtp
        fp += rfp
        fn += rfn
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
    return precision, recall, f1, len(scored)


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
    tag_p, tag_r, tag_f1, tag_n = metric_tag_scores(records)
    action_counts = reviewer_action_counts(records)
    rates = {action: count / n for action, count in action_counts.items()}
    ece = expected_calibration_error(records)

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
        accept_rate=rates["accept"],
        reject_rate=rates["reject"],
        correct_rate=rates["correct"],
        add_rate=rates["add"],
        partial_rate=rates["partial"],
        skip_rate=rates["skip"],
        auto_disposition_rate=rates["accept"] + rates["skip"],
        metric_tag_precision=tag_p,
        metric_tag_recall=tag_r,
        metric_tag_f1=tag_f1,
        calibration_ece=ece,
        n_images_scored_on_metric_tags=tag_n,
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
