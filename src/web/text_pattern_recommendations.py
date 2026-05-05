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


def compute_cross_metric_findings(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Aggregate phrase findings across metrics to surface shared signals.

    Groups ``text_decision_phrase_findings`` rows by ``(phrase, decision_type,
    source_field)`` across all metrics and returns rows with ``metric_count``
    and a ``cross_metric_exclusion`` recommendation when the phrase fires the
    new cross-metric rule:

    - ``decision_type == 'reject'``
    - ``source_field in EXCL_SOURCE_FIELDS`` (module-level constant — same
      allowlist as ``_rule_exclusion_pattern``; do NOT hardcode a local copy)
    - ``phrase_ngram_size >= EXCL_NGRAM_MIN``
    - ``metric_count >= 3``

    Severity: ``high`` when ``metric_count >= 5``, else ``medium``.

    Returns rows ordered DESC by ``total_occurrence``.  Empty input → empty
    list (mirrors the ``compute_recommendations`` empty contract).

    **Cross-plan contract:** ``EXCL_SOURCE_FIELDS`` is read from the module
    scope at call time.  Test stubs MUST monkeypatch
    ``src.web.text_pattern_recommendations.EXCL_SOURCE_FIELDS`` (one site)
    so both the per-metric ``exclusion_pattern`` rule and this function see
    the same binding.  Do NOT introduce a per-rule local copy inside this
    function.
    """
    if not findings:
        return []

    # Group by (phrase, decision_type, source_field).
    groups: dict[tuple[str, str, str], dict[str, Any]] = {}
    for f in findings:
        key = (f["phrase"], f["decision_type"], f["source_field"])
        if key not in groups:
            groups[key] = {
                "phrase": f["phrase"],
                "decision_type": f["decision_type"],
                "source_field": f["source_field"],
                "phrase_ngram_size": int(f.get("phrase_ngram_size", 0)),
                "total_occurrence": 0,
                "metric_ids": set(),
                "top_examples": [],
            }
        g = groups[key]
        g["total_occurrence"] += int(f.get("occurrence_count", 0))
        g["metric_ids"].add(f["metric_id"])
        # Collect up to 5 examples across metrics.
        for ex in f.get("examples") or []:
            if len(g["top_examples"]) < 5:
                g["top_examples"].append(ex)

    rows: list[dict[str, Any]] = []
    for g in groups.values():
        metric_count = len(g["metric_ids"])
        metrics_list = sorted(g["metric_ids"])

        # Determine cross_metric_exclusion rule eligibility.
        # EXCL_SOURCE_FIELDS is read from the module-level binding so
        # monkeypatching at one site covers both per-metric and cross-metric.
        fires_excl = (
            g["decision_type"] == "reject"
            and g["source_field"] in EXCL_SOURCE_FIELDS
            and g["phrase_ngram_size"] >= EXCL_NGRAM_MIN
            and metric_count >= 3
        )
        if fires_excl:
            severity: str | None = "high" if metric_count >= 5 else "medium"
        else:
            severity = None

        rows.append(
            {
                "phrase": g["phrase"],
                "decision_type": g["decision_type"],
                "source_field": g["source_field"],
                "phrase_ngram_size": g["phrase_ngram_size"],
                "total_occurrence": g["total_occurrence"],
                "metric_count": metric_count,
                "metrics": metrics_list,
                "top_examples": g["top_examples"],
                "cross_metric_exclusion": fires_excl,
                "severity": severity,
            }
        )

    rows.sort(key=lambda r: r["total_occurrence"], reverse=True)
    return rows


def interpret_finding_row(row: dict[str, Any]) -> dict[str, str]:
    """Return a human-readable interpretation and suggested action for a phrase row.

    Mapping covers five branches by ``(decision_type, source_field, ngram_size)``::

        reject + rejection_reason + n>=2  → historical exclusion candidate
            (pre-PR-509 runs; rejection_reason no longer mined after PR 4)
        reject + segment_text + n>=2      → YAML exclusion / context filter
        reject + segment_text + n=1       → single-word signal (too aggressive alone)
        correct + segment_text (any n)    → sibling-metric routing signal
        accept (any source)               → confirmed positive / keyword candidate

    The ``rejection_reason`` branch is kept to cover historical findings rows
    from pre-PR-509 runs that remain in ``text_decision_phrase_findings`` until
    the next analysis run displaces them.  New runs after PR 4 (2026-05-05) do
    not produce ``source_field='rejection_reason'`` rows.

    Returns ``{"interpretation": str, "suggested_action": str}``.
    """
    decision_type = row.get("decision_type", "")
    source_field = row.get("source_field", "")
    ngram_size = int(row.get("phrase_ngram_size", 0))

    if decision_type == "accept":
        return {
            "interpretation": "Confirmed positive signal.",
            "suggested_action": "Keyword candidate — verify YAML coverage for this phrase.",
        }

    if decision_type == "correct":
        return {
            "interpretation": ("Phrase often appears when reviewers reroute to a sibling metric."),
            "suggested_action": (
                "See keyword_overlap recommendation or tighten YAML for this metric."
            ),
        }

    if decision_type == "reject":
        # Historical branch: rejection_reason source from pre-PR-509 runs.
        # New analysis runs (post PR 4) do not produce source_field='rejection_reason'
        # rows — this branch exists only to handle DB rows that predate the change.
        if source_field == "rejection_reason" and ngram_size >= 2:
            return {
                "interpretation": ("Reviewer-cited reason (historical) — exclusion candidate."),
                "suggested_action": (
                    "Add to YAML exclusions or audit FP rule for this category. "
                    "Note: rejection_reason is no longer mined after PR 4 (2026-05-05); "
                    "these rows reflect pre-PR-4 analysis runs."
                ),
            }
        if source_field == "segment_text" and ngram_size >= 2:
            return {
                "interpretation": ("Phrase appears in extracted text of rejected facts."),
                "suggested_action": ("Consider YAML exclusion or context filter for this phrase."),
            }
        if source_field == "segment_text" and ngram_size == 1:
            return {
                "interpretation": (
                    "Single-word reject signal — too aggressive for exclusion alone."
                ),
                "suggested_action": (
                    "Review FP rules for this metric; a single word rarely "
                    "justifies a blanket YAML exclusion."
                ),
            }

    # Fallback for any future source/decision combinations.
    return {
        "interpretation": "Signal — review in context.",
        "suggested_action": "Inspect the per-metric phrase table for details.",
    }


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
