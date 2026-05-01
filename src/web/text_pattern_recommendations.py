"""Translate text-decision pattern findings into actionable recommendations.

Stateless render-time helper called from `review_unified.stats()`. Reads the
already-loaded `text_decision_metric_summary` + `text_decision_phrase_findings`
rows and returns one or more recommendation dicts per metric, each pointing
the reviewer at a concrete edit (YAML exclusion, FP-rule audit, keyword-
overlap review).

Three rules in v1 — see `.claude/rules/web.md` for the canonical statement of
their triggers and severity bands. Rules are independent: a metric may fire
multiple, and the helper sorts the union by severity DESC then rule name ASC.

Persisted findings vs. computed recommendations: deliberately render-time so
threshold tweaks don't require an analysis rerun. Constants below are the
only knobs.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

# --- Rule thresholds ---------------------------------------------------------
# Single source of truth so a tweak is one edit + one PR. Documented in
# .claude/rules/web.md "Recommendation rules".

# exclusion_pattern: phrase appears in >= EXCL_PCT_LOW% of rejects sourced
# from rejection_reason or segment_text. n-gram size >= EXCL_NGRAM_MIN
# (single words are too aggressive for a YAML exclusion).
EXCL_PCT_LOW = 30.0
EXCL_PCT_HIGH = 50.0  # promotes severity from medium -> high
EXCL_NGRAM_MIN = 2
EXCL_SOURCE_FIELDS = ("rejection_reason", "segment_text")

# keyword_overlap: count of corrections to one sibling metric.
OVERLAP_COUNT_LOW = 5
OVERLAP_COUNT_HIGH = 10

# fp_filter_gap: wrong_value share of rejects (only fires when reject volume
# is meaningful — see FP_REJECT_FLOOR).
FP_REJECT_FLOOR = 5
FP_PCT_LOW = 0.5
FP_PCT_HIGH = 0.7

# Sort key for severity-then-rule ordering.
_SEVERITY_RANK = {"high": 0, "medium": 1}


def compute_recommendations(
    summaries: list[dict[str, Any]],
    findings: list[dict[str, Any]],
    decisions: list[dict[str, Any]] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Map metric_id -> list of recommendation dicts.

    Empty inputs return {}; the existing stats-render tests pass empty
    fixtures and rely on this no-op behavior.

    Each recommendation dict has shape::

        {
          "rule": "exclusion_pattern" | "keyword_overlap" | "fp_filter_gap",
          "severity": "high" | "medium",
          "decision_key": str,    # stable identifier across reruns
          "title": str,
          "evidence": str,
          "action": str,
          "decision": dict | None,  # populated when `decisions` arg matches
        }

    When ``decisions`` is provided (a list of recommendation-decision rows
    from `db.get_recommendation_decisions()`), each rec gets a ``decision``
    field looked up by ``(metric_id, rule, decision_key)``. The decisions
    list may contain multiple reviewers' rows for the same key — the
    most-recent one (by ``updated_at``) wins. Skipping/omitting the arg
    leaves ``decision`` as ``None`` on every rec, preserving the prior
    contract.
    """
    if not summaries and not findings:
        return {}

    # Group findings by metric_id once so each rule's helper can scan
    # locally without re-iterating the full list.
    findings_by_metric: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for f in findings:
        findings_by_metric[f["metric_id"]].append(f)

    # Index decisions by (metric_id, rule, decision_key); keep the row with
    # the latest updated_at when multiple reviewers have decided. The DB
    # reader returns rows ordered DESC by updated_at within each key, so
    # the first row we see is the freshest — only insert if absent.
    decision_index: dict[tuple[str, str, str], dict[str, Any]] = {}
    for d in decisions or []:
        key = (d["metric_id"], d["rule"], d["decision_key"])
        decision_index.setdefault(key, d)

    out: dict[str, list[dict[str, Any]]] = {}
    for s in summaries:
        metric_id = s["metric_id"]
        recs: list[dict[str, Any]] = []
        recs.extend(_rule_exclusion_pattern(metric_id, findings_by_metric.get(metric_id, [])))
        recs.extend(_rule_keyword_overlap(metric_id, s))
        recs.extend(_rule_fp_filter_gap(metric_id, s))
        if recs:
            for r in recs:
                r["decision"] = decision_index.get((metric_id, r["rule"], r["decision_key"]))
            recs.sort(key=lambda r: (_SEVERITY_RANK[r["severity"]], r["rule"]))
            out[metric_id] = recs
    return out


def _rule_exclusion_pattern(
    metric_id: str, metric_findings: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Surface phrases dominant enough to justify a YAML exclusion entry."""
    recs: list[dict[str, Any]] = []
    for f in metric_findings:
        if f["decision_type"] != "reject":
            continue
        if f["source_field"] not in EXCL_SOURCE_FIELDS:
            continue
        if int(f["phrase_ngram_size"]) < EXCL_NGRAM_MIN:
            continue
        pct = float(f["pct_of_decisions"])
        if pct < EXCL_PCT_LOW:
            continue
        severity = "high" if pct >= EXCL_PCT_HIGH else "medium"
        phrase = f["phrase"]
        count = int(f["occurrence_count"])
        source_label = f["source_field"].replace("_", " ")
        recs.append(
            {
                "rule": "exclusion_pattern",
                "severity": severity,
                "decision_key": phrase,
                "title": f'Add exclusion pattern matching "{phrase}"',
                "evidence": (
                    f'"{phrase}" appears in {count} rejects ({pct:.1f}%) '
                    f"sourced from {source_label}."
                ),
                "action": (
                    f"Add to the exclusions list under {metric_id} in config/metric_keywords.yaml."
                ),
            }
        )
    return recs


def _rule_keyword_overlap(metric_id: str, summary: dict[str, Any]) -> list[dict[str, Any]]:
    """Surface metrics that reviewers frequently re-route to a sibling."""
    targets = summary.get("top_correction_targets") or []
    recs: list[dict[str, Any]] = []
    for t in targets:
        count = int(t.get("count", 0))
        if count < OVERLAP_COUNT_LOW:
            continue
        target_metric = t.get("target_metric_id")
        if not target_metric:
            continue
        severity = "high" if count >= OVERLAP_COUNT_HIGH else "medium"
        recs.append(
            {
                "rule": "keyword_overlap",
                "severity": severity,
                "decision_key": target_metric,
                "title": f"Review keyword overlap with {target_metric}",
                "evidence": (f"Reviewers corrected {metric_id} → {target_metric} {count} times."),
                "action": (
                    f"Tighten keywords on {metric_id} or expand {target_metric}'s "
                    "in config/metric_keywords.yaml."
                ),
            }
        )
    return recs


def _rule_fp_filter_gap(metric_id: str, summary: dict[str, Any]) -> list[dict[str, Any]]:
    """Surface metrics whose rejects are dominated by wrong_value."""
    reject_count = int(summary.get("reject_count") or 0)
    if reject_count < FP_REJECT_FLOOR:
        return []
    cats = summary.get("rejection_categories") or {}
    wrong_value = int(cats.get("wrong_value") or 0)
    if wrong_value == 0:
        return []
    pct = wrong_value / reject_count
    if pct < FP_PCT_LOW:
        return []
    severity = "high" if pct >= FP_PCT_HIGH else "medium"
    return [
        {
            "rule": "fp_filter_gap",
            "severity": severity,
            "decision_key": "wrong_value",
            "title": "Check FP filter for value-extraction bug",
            "evidence": (
                f"{wrong_value} of {reject_count} rejects ({pct * 100:.1f}%) "
                f"cited wrong_value — looks like a value-extraction bug, "
                "not a keyword bug."
            ),
            "action": (
                f"Review {metric_id}'s handling in "
                "src/extraction_v2/stages/false_positive_filter.py."
            ),
        }
    ]
