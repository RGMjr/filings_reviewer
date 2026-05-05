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

import logging
from collections import defaultdict
from typing import Any

logger = logging.getLogger(__name__)

# --- Rule thresholds ---------------------------------------------------------
# Single source of truth so a tweak is one edit + one PR. Documented in
# .claude/rules/web.md "Recommendation rules".

# exclusion_pattern: phrase appears in >= EXCL_PCT_LOW% of rejects sourced
# from segment_text. n-gram size >= EXCL_NGRAM_MIN (single words are too
# aggressive for a YAML exclusion). rejection_reason and reviewer_notes are
# excluded — the rejection_category enum already carries categorical policy
# signal without free-text noise (dropped in PR 4 of the analysis-loop
# improvement plan, 2026-05-05).
EXCL_PCT_LOW = 30.0
EXCL_PCT_HIGH = 50.0  # promotes severity from medium -> high
EXCL_NGRAM_MIN = 2
EXCL_SOURCE_FIELDS = ("segment_text",)

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
    config_snapshot_hash: str | None = None,
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
          "config_drift": bool,    # True when config changed since this run
          "is_stale": bool,        # True when decision_key absent from latest run
        }

    When ``decisions`` is provided (a list of recommendation-decision rows
    from `db.get_recommendation_decisions()`), each rec gets a ``decision``
    field looked up by ``(metric_id, rule, decision_key)``. The decisions
    list may contain multiple reviewers' rows for the same key — the
    most-recent one (by ``updated_at``) wins. Skipping/omitting the arg
    leaves ``decision`` as ``None`` on every rec, preserving the prior
    contract.

    ``config_snapshot_hash`` is the hash stored on the analysis run row. When
    it differs from the current hash (computed at call time from the live
    config files), ``config_drift`` is set to ``True`` on every card so the
    template can render a freshness badge. When ``config_snapshot_hash`` is
    ``None`` (legacy runs from before this feature), ``config_drift`` is
    ``False`` — legacy cards are never false-flagged.

    ``is_stale`` is ``True`` for a persisted decision whose ``decision_key``
    is no longer present in the current run's findings/summaries. Stale
    decisions are render-only archived — the DB row is never modified.
    """
    if not summaries and not findings:
        return {}

    # Compute config_drift: compare stored hash against current live hash.
    # NULL stored hash (legacy run) → False so legacy cards are not flagged.
    config_drift: bool = False
    if config_snapshot_hash is not None:
        try:
            from src.extraction_v2.config_hash import compute_config_hash

            current_hash = compute_config_hash()
            config_drift = current_hash != config_snapshot_hash
        except Exception:  # noqa: BLE001
            logger.warning("Could not compute config hash for drift check", exc_info=True)

    # Build the set of (metric_id, rule, decision_key) tuples that are active
    # in the current run. Keys are derived per-rule:
    #   exclusion_pattern: decision_key = phrase (from findings rows)
    #   keyword_overlap:   decision_key = target_metric_id (from summary JSONB)
    #   fp_filter_gap:     decision_key = literal "wrong_value" (from summary)
    # A persisted decision whose triple is absent from this set is stale.
    current_keys: set[tuple[str, str, str]] = set()
    for f in findings:
        mid = f["metric_id"]
        if (
            f.get("decision_type") == "reject"
            and f.get("source_field") in EXCL_SOURCE_FIELDS
            and int(f.get("phrase_ngram_size", 0)) >= EXCL_NGRAM_MIN
            and float(f.get("pct_of_decisions", 0)) >= EXCL_PCT_LOW
        ):
            current_keys.add((mid, "exclusion_pattern", f["phrase"]))
    for s in summaries:
        mid = s["metric_id"]
        for t in s.get("top_correction_targets") or []:
            if int(t.get("count", 0)) >= OVERLAP_COUNT_LOW and t.get("target_metric_id"):
                current_keys.add((mid, "keyword_overlap", t["target_metric_id"]))
        reject_count = int(s.get("reject_count") or 0)
        if reject_count >= FP_REJECT_FLOOR:
            cats = s.get("rejection_categories") or {}
            wrong_value = int(cats.get("wrong_value") or 0)
            if wrong_value > 0 and wrong_value / reject_count >= FP_PCT_LOW:
                current_keys.add((mid, "fp_filter_gap", "wrong_value"))

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
                r["config_drift"] = config_drift
                r["is_stale"] = False  # Active recommendations are never stale
            recs.sort(key=lambda r: (_SEVERITY_RANK[r["severity"]], r["rule"]))
            out[metric_id] = recs

    # Inject stale cards from persisted decisions whose (metric_id, rule,
    # decision_key) triple no longer appears in the current run. These are
    # rendered in the archived section — the rule no longer fires so they
    # don't belong in the active panel, but the decision row is preserved
    # as audit history and shown with reduced visual weight.
    seen_active: set[tuple[str, str, str]] = {
        (mid, r["rule"], r["decision_key"]) for mid, recs_list in out.items() for r in recs_list
    }
    for d in decisions or []:
        triple = (d["metric_id"], d["rule"], d["decision_key"])
        if triple in current_keys:
            # The rule still fires — already handled above or will be.
            continue
        if triple in seen_active:
            # Already emitted as an active card (shouldn't happen, but guard).
            continue
        metric_id = d["metric_id"]
        stale_rec: dict[str, Any] = {
            "rule": d["rule"],
            "severity": "medium",  # Unknown — rule no longer fires
            "decision_key": d["decision_key"],
            "title": f"[Archived] {d['rule'].replace('_', ' ').title()}: {d['decision_key']}",
            "evidence": "This recommendation no longer surfaces in the latest analysis run.",
            "action": "No action required — the finding has dropped below detection thresholds.",
            "decision": d,
            "config_drift": config_drift,
            "is_stale": True,
        }
        if metric_id not in out:
            out[metric_id] = []
        out[metric_id].append(stale_rec)
        seen_active.add(triple)

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
