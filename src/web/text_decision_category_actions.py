"""Category-level recommendation actions for the text-decision Patterns tab.

Maps each ``rejection_category`` enum value to a reviewer-facing ``label``,
a one-line ``description`` and ``example`` (rendered as inline help on the
Reject form in ``unified_review.html``), a concrete root-cause ``action`` for
engineers, and a ``target_file`` path. The ``CATEGORY_ACTIONS`` dict is the
single authoritative reference; ``compute_category_rollup`` sums
``rejection_categories`` JSONB across all per-metric summary rows for a run
and returns a list sorted by count DESC.

The ``label`` value is shared between the Reject-form dropdown options and
the Patterns-tab category-rollup cards — keep them reviewer-facing.

No persistence: category-level cards are render-time only and do NOT
participate in the ``text_pattern_recommendation_decisions`` accept/dismiss/
defer flow (see plan §Approach "No new persistence" choice).

This module does not import from extraction code — it is a pure web-layer
helper and must remain importable in tests without a full pipeline install.
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Canonical category → action mapping
# ---------------------------------------------------------------------------
# Severity thresholds: (medium_pct, high_pct) where pct is the category's
# share of all run rejects. ``part_of_date`` gets a lower floor because the
# date-component pattern is well-documented and even a modest volume warrants
# attention.

# Insertion order is reviewer-decision-tree order — iterating ``CATEGORY_ACTIONS``
# in the Reject-form dropdown emits options top-down: in-scope check first
# (Not a customer metric, Date component) → wrong identification (Wrong metric
# type) → wrong details (Wrong number, Wrong time period) → already-captured
# (Duplicate) → escape hatch (Other). ``compute_category_rollup`` re-sorts by
# count, so the rollup display is unaffected.

CATEGORY_ACTIONS: dict[str, dict[str, Any]] = {
    "not_a_metric": {
        "label": "Not a customer metric",
        "description": (
            "The number isn't a customer metric at all — the keyword matched unrelated prose."
        ),
        "example": '"We had 17 offices…" matched as a customer count.',
        "action": (
            "Keyword too aggressive — tighten YAML keywords for the affected metrics. "
            "Look for broad terms (e.g. plain nouns) that match unrelated prose."
        ),
        "target_file": "config/metric_keywords.yaml",
        "severity_thresholds": (15.0, 35.0),
    },
    "part_of_date": {
        "label": "Date component (year, month, day)",
        "description": "The number is part of a date, not a value.",
        "example": 'The "2023" in "December 31, 2023."',
        "action": (
            "Audit ``_is_part_of_date`` regex; widen calendar-component coverage "
            "(month names, ordinals, fiscal quarter labels)."
        ),
        "target_file": "src/review/false_positive_filter.py",
        "severity_thresholds": (10.0, 25.0),  # medium at 10%, high at 25%
    },
    "wrong_metric": {
        "label": "Wrong metric type",
        "description": ("The number IS a customer metric, but the wrong one was assigned."),
        "example": 'Tagged as "active users" but it\'s actually "paying subscribers."',
        "action": (
            "See per-metric ``keyword_overlap`` recommendations — the same segment text "
            "is matching a sibling metric's keyword pattern."
        ),
        "target_file": "config/metric_keywords.yaml",
        "severity_thresholds": (15.0, 35.0),
    },
    "wrong_value": {
        "label": "Wrong number",
        "description": (
            "Right metric, but the value is wrong (off by magnitude, picked the "
            "wrong number from the segment, unit error)."
        ),
        "example": "Extracted 2.5 when the text says 2.5 million.",
        "action": (
            "See per-metric ``fp_filter_gap`` recommendations — a value-extraction or "
            "unit-normalisation bug is producing plausible-looking but incorrect values."
        ),
        "target_file": "src/extraction_v2/stages/false_positive_filter.py",
        "severity_thresholds": (15.0, 35.0),
    },
    "wrong_period": {
        "label": "Wrong time period",
        "description": ("Right metric and number, but the period attached is wrong."),
        "example": "Tagged FY2023 when the text refers to FY2022.",
        "action": (
            "Period-binding bug — review segment time-window detection and period inference logic."
        ),
        "target_file": "src/extraction_v2/stages/period_binding.py",
        "severity_thresholds": (15.0, 35.0),
    },
    "duplicate": {
        "label": "Duplicate (already captured elsewhere)",
        "description": ("This same value is already extracted as another fact in this filing."),
        "example": "The same number appears in two segments and both got promoted.",
        "action": (
            "Dedup logic gap — review fact-promotion uniqueness constraints. "
            "Check whether the same value is emitted from multiple segment sources."
        ),
        "target_file": "src/extraction_v2/persistence/v2_persistence.py",
        "severity_thresholds": (10.0, 20.0),
    },
    "other": {
        "label": "Other (please add details below)",
        "description": (
            "Anything that doesn't fit the categories above — fill in the Reason field."
        ),
        "example": "(free text)",
        "action": "Read free-text reasons in the per-metric phrase tables.",
        "target_file": "",
        "severity_thresholds": (20.0, 40.0),
    },
}


# ---------------------------------------------------------------------------
# Rollup helper
# ---------------------------------------------------------------------------


def compute_category_rollup(summaries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sum rejection_categories JSONB across all per-metric summaries for a run.

    Returns a list of category rows ordered DESC by count. Each row has::

        {
          "category": str,
          "count": int,
          "pct_of_rejects": float,   # 0-100
          "label": str,
          "action": str,
          "target_file": str,
          "severity": "high" | "medium" | None,
        }

    ``severity`` is ``None`` when the category's share falls below its
    medium threshold (i.e. no action card is warranted).

    Empty input → empty list (mirrors ``compute_recommendations`` empty
    contract used by ``_stub_analytics_helpers`` test fixtures).
    """
    if not summaries:
        return []

    # Aggregate counts across metrics.
    totals: dict[str, int] = {}
    for s in summaries:
        cats = s.get("rejection_categories") or {}
        for cat, cnt in cats.items():
            totals[cat] = totals.get(cat, 0) + int(cnt)

    if not totals:
        return []

    grand_total = sum(totals.values())
    if grand_total == 0:
        return []

    rows: list[dict[str, Any]] = []
    for cat, count in sorted(totals.items(), key=lambda kv: kv[1], reverse=True):
        pct = round((count / grand_total) * 100, 1)
        meta = CATEGORY_ACTIONS.get(
            cat,
            {
                "label": cat.replace("_", " ").title(),
                "action": "Review per-metric phrase tables for this category.",
                "target_file": "",
                "severity_thresholds": (20.0, 40.0),
            },
        )
        medium_floor, high_floor = meta["severity_thresholds"]
        if pct >= high_floor:
            severity: str | None = "high"
        elif pct >= medium_floor:
            severity = "medium"
        else:
            severity = None

        rows.append(
            {
                "category": cat,
                "count": count,
                "pct_of_rejects": pct,
                "label": meta["label"],
                "action": meta["action"],
                "target_file": meta["target_file"],
                "severity": severity,
            }
        )

    return rows
