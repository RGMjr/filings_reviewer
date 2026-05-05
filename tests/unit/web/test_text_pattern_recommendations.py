"""Unit tests for src/web/text_pattern_recommendations.py.

Pure-function tests — no Flask, no DB. Each rule has its own class; sorting
and empty-input behavior get a class each. Empty-input behavior is
load-bearing: existing stats-render tests pass empty fixtures and rely on
compute_recommendations({}, {}) returning {}.
"""

from __future__ import annotations

from decimal import Decimal

from src.web.text_pattern_recommendations import compute_recommendations


def _summary(
    metric_id: str = "cm_x",
    *,
    total: int = 50,
    accept: int = 5,
    reject: int = 31,
    correct: int = 14,
    rejection_categories: dict | None = None,
    top_correction_targets: list | None = None,
) -> dict:
    return {
        "metric_id": metric_id,
        "total_decisions": total,
        "accept_count": accept,
        "reject_count": reject,
        "correct_count": correct,
        "rejection_categories": rejection_categories or {},
        "top_correction_targets": top_correction_targets or [],
    }


def _finding(
    *,
    metric_id: str = "cm_x",
    decision_type: str = "reject",
    phrase: str = "accounts receivable",
    ngram: int = 2,
    source_field: str = "rejection_reason",
    occurrences: int = 14,
    pct: float | Decimal = 45.20,
) -> dict:
    return {
        "metric_id": metric_id,
        "decision_type": decision_type,
        "phrase": phrase,
        "phrase_ngram_size": ngram,
        "source_field": source_field,
        "occurrence_count": occurrences,
        "pct_of_decisions": pct,
        "examples": [],
    }


# ---------------------------------------------------------------------------
# Rule: exclusion_pattern
# ---------------------------------------------------------------------------


class TestExclusionPatternRule:
    def test_fires_at_30_pct_with_bigram(self):
        out = compute_recommendations([_summary()], [_finding(pct=30.0)])
        recs = out["cm_x"]
        excl = [r for r in recs if r["rule"] == "exclusion_pattern"]
        assert len(excl) == 1
        assert excl[0]["severity"] == "medium"
        assert "accounts receivable" in excl[0]["title"]
        assert "config/metric_keywords.yaml" in excl[0]["action"]

    def test_does_not_fire_below_30_pct(self):
        out = compute_recommendations([_summary()], [_finding(pct=29.9)])
        # No rules fire at all -> metric absent from output dict.
        assert "cm_x" not in out

    def test_severity_high_at_50_pct(self):
        out = compute_recommendations([_summary()], [_finding(pct=50.0)])
        excl = [r for r in out["cm_x"] if r["rule"] == "exclusion_pattern"]
        assert excl[0]["severity"] == "high"

    def test_severity_medium_just_below_50_pct(self):
        out = compute_recommendations([_summary()], [_finding(pct=49.99)])
        excl = [r for r in out["cm_x"] if r["rule"] == "exclusion_pattern"]
        assert excl[0]["severity"] == "medium"

    def test_ignores_unigrams(self):
        out = compute_recommendations([_summary()], [_finding(ngram=1, pct=80.0)])
        assert "cm_x" not in out

    def test_ignores_reviewer_notes_source(self):
        out = compute_recommendations(
            [_summary()], [_finding(source_field="reviewer_notes", pct=80.0)]
        )
        assert "cm_x" not in out

    def test_segment_text_source_qualifies(self):
        out = compute_recommendations(
            [_summary()], [_finding(source_field="segment_text", pct=40.0)]
        )
        excl = [r for r in out["cm_x"] if r["rule"] == "exclusion_pattern"]
        assert len(excl) == 1
        assert "segment text" in excl[0]["evidence"]

    def test_correct_decision_type_does_not_fire(self):
        # The exclusion rule only mines reject phrases.
        out = compute_recommendations([_summary()], [_finding(decision_type="correct", pct=80.0)])
        assert "cm_x" not in out

    def test_decimal_pct_is_handled(self):
        # psycopg returns NUMERIC(5,2) as Decimal; helper must coerce.
        out = compute_recommendations([_summary()], [_finding(pct=Decimal("45.20"))])
        excl = [r for r in out["cm_x"] if r["rule"] == "exclusion_pattern"]
        assert excl[0]["severity"] == "medium"

    def test_multiple_phrases_per_metric_each_emit(self):
        findings = [
            _finding(phrase="accounts receivable", pct=45.0),
            _finding(phrase="bad debt", ngram=2, pct=35.0),
        ]
        out = compute_recommendations([_summary()], findings)
        excl = [r for r in out["cm_x"] if r["rule"] == "exclusion_pattern"]
        assert len(excl) == 2
        assert {r["title"] for r in excl} == {
            'Add exclusion pattern matching "accounts receivable"',
            'Add exclusion pattern matching "bad debt"',
        }


# ---------------------------------------------------------------------------
# Rule: keyword_overlap
# ---------------------------------------------------------------------------


class TestKeywordOverlapRule:
    def test_fires_at_count_5(self):
        s = _summary(top_correction_targets=[{"target_metric_id": "cm_y", "count": 5}])
        out = compute_recommendations([s], [])
        recs = out["cm_x"]
        ovl = [r for r in recs if r["rule"] == "keyword_overlap"]
        assert len(ovl) == 1
        assert ovl[0]["severity"] == "medium"
        assert "cm_y" in ovl[0]["title"]

    def test_does_not_fire_below_5(self):
        s = _summary(top_correction_targets=[{"target_metric_id": "cm_y", "count": 4}])
        out = compute_recommendations([s], [])
        assert "cm_x" not in out

    def test_severity_high_at_10(self):
        s = _summary(top_correction_targets=[{"target_metric_id": "cm_y", "count": 10}])
        out = compute_recommendations([s], [])
        ovl = [r for r in out["cm_x"] if r["rule"] == "keyword_overlap"]
        assert ovl[0]["severity"] == "high"

    def test_multiple_targets_each_emit(self):
        s = _summary(
            top_correction_targets=[
                {"target_metric_id": "cm_y", "count": 12},
                {"target_metric_id": "cm_z", "count": 6},
            ]
        )
        out = compute_recommendations([s], [])
        ovl = [r for r in out["cm_x"] if r["rule"] == "keyword_overlap"]
        assert len(ovl) == 2
        assert {r["severity"] for r in ovl} == {"high", "medium"}

    def test_handles_missing_target_metric_id(self):
        # Defensive: malformed JSON shouldn't crash.
        s = _summary(top_correction_targets=[{"count": 10}])
        out = compute_recommendations([s], [])
        assert "cm_x" not in out


# ---------------------------------------------------------------------------
# Rule: fp_filter_gap
# ---------------------------------------------------------------------------


class TestFpFilterGapRule:
    def test_fires_at_50_pct_with_floor_volume(self):
        s = _summary(reject=10, rejection_categories={"wrong_value": 5})
        out = compute_recommendations([s], [])
        gap = [r for r in out["cm_x"] if r["rule"] == "fp_filter_gap"]
        assert len(gap) == 1
        assert gap[0]["severity"] == "medium"
        assert "false_positive_filter.py" in gap[0]["action"]

    def test_severity_high_at_70_pct(self):
        s = _summary(reject=10, rejection_categories={"wrong_value": 7})
        out = compute_recommendations([s], [])
        gap = [r for r in out["cm_x"] if r["rule"] == "fp_filter_gap"]
        assert gap[0]["severity"] == "high"

    def test_ignores_below_5_reject_floor(self):
        # 100% wrong_value but only 4 rejects — too small to act on.
        s = _summary(reject=4, rejection_categories={"wrong_value": 4})
        out = compute_recommendations([s], [])
        assert "cm_x" not in out

    def test_does_not_fire_below_50_pct(self):
        s = _summary(reject=10, rejection_categories={"wrong_value": 4})
        out = compute_recommendations([s], [])
        gap = [r for r in out.get("cm_x", []) if r["rule"] == "fp_filter_gap"]
        assert gap == []

    def test_handles_zero_wrong_value(self):
        s = _summary(reject=20, rejection_categories={"not_a_metric": 20})
        out = compute_recommendations([s], [])
        assert "cm_x" not in out


# ---------------------------------------------------------------------------
# Sorting
# ---------------------------------------------------------------------------


class TestSorting:
    def test_high_severity_first(self):
        # exclusion_pattern medium + keyword_overlap high on same metric.
        s = _summary(
            top_correction_targets=[{"target_metric_id": "cm_y", "count": 12}],
        )
        out = compute_recommendations([s], [_finding(pct=35.0)])
        recs = out["cm_x"]
        assert recs[0]["severity"] == "high"
        assert recs[0]["rule"] == "keyword_overlap"
        assert recs[1]["severity"] == "medium"

    def test_within_severity_sorted_by_rule_name(self):
        # All three rules at medium severity → alphabetical: exclusion_pattern,
        # fp_filter_gap, keyword_overlap.
        s = _summary(
            reject=10,
            rejection_categories={"wrong_value": 6},
            top_correction_targets=[{"target_metric_id": "cm_y", "count": 5}],
        )
        out = compute_recommendations([s], [_finding(pct=35.0)])
        rules = [r["rule"] for r in out["cm_x"]]
        assert rules == ["exclusion_pattern", "fp_filter_gap", "keyword_overlap"]


# ---------------------------------------------------------------------------
# Empty inputs
# ---------------------------------------------------------------------------


class TestEmpty:
    def test_empty_lists_return_empty_dict(self):
        assert compute_recommendations([], []) == {}

    def test_summaries_without_findings_can_still_fire(self):
        # keyword_overlap and fp_filter_gap read from summary, not findings.
        s = _summary(
            reject=10,
            rejection_categories={"wrong_value": 8},
            top_correction_targets=[{"target_metric_id": "cm_y", "count": 11}],
        )
        out = compute_recommendations([s], [])
        rules = sorted(r["rule"] for r in out["cm_x"])
        assert rules == ["fp_filter_gap", "keyword_overlap"]

    def test_findings_for_unknown_metric_are_ignored(self):
        # No summary for cm_z → rule should not run on it.
        out = compute_recommendations([_summary("cm_x")], [_finding(metric_id="cm_z")])
        assert "cm_z" not in out


# ---------------------------------------------------------------------------
# decision_key field on rec output (PR 1 prep for decision-merge)
# ---------------------------------------------------------------------------


class TestDecisionKey:
    def test_exclusion_pattern_key_is_phrase(self):
        out = compute_recommendations([_summary()], [_finding(phrase="accounts receivable")])
        excl = [r for r in out["cm_x"] if r["rule"] == "exclusion_pattern"][0]
        assert excl["decision_key"] == "accounts receivable"

    def test_keyword_overlap_key_is_target_metric(self):
        s = _summary(top_correction_targets=[{"target_metric_id": "cm_y", "count": 12}])
        out = compute_recommendations([s], [])
        ovl = [r for r in out["cm_x"] if r["rule"] == "keyword_overlap"][0]
        assert ovl["decision_key"] == "cm_y"

    def test_fp_filter_gap_key_is_literal(self):
        s = _summary(reject=10, rejection_categories={"wrong_value": 7})
        out = compute_recommendations([s], [])
        gap = [r for r in out["cm_x"] if r["rule"] == "fp_filter_gap"][0]
        assert gap["decision_key"] == "wrong_value"


# ---------------------------------------------------------------------------
# Decision merging — `decisions` arg attaches matching decision rows
# ---------------------------------------------------------------------------


class TestDecisionMerging:
    def test_omitted_decisions_arg_leaves_decision_none(self):
        out = compute_recommendations([_summary()], [_finding()])
        rec = out["cm_x"][0]
        assert rec["decision"] is None

    def test_empty_decisions_list_leaves_decision_none(self):
        out = compute_recommendations([_summary()], [_finding()], [])
        rec = out["cm_x"][0]
        assert rec["decision"] is None

    def test_matching_decision_attaches(self):
        decision = {
            "id": "d1",
            "metric_id": "cm_x",
            "rule": "exclusion_pattern",
            "decision_key": "accounts receivable",
            "decision": "accepted",
            "reviewer_id": "RGM",
            "reviewer_note": None,
            "pr_number": None,
            "pr_url": None,
            "updated_at": "2026-05-01T20:00:00+00:00",
        }
        out = compute_recommendations([_summary()], [_finding()], [decision])
        rec = [r for r in out["cm_x"] if r["rule"] == "exclusion_pattern"][0]
        assert rec["decision"] is not None
        assert rec["decision"]["decision"] == "accepted"
        assert rec["decision"]["reviewer_id"] == "RGM"

    def test_decision_for_different_key_does_not_attach(self):
        decision = {
            "id": "d2",
            "metric_id": "cm_x",
            "rule": "exclusion_pattern",
            "decision_key": "different phrase",
            "decision": "dismissed",
            "reviewer_id": "RGM",
            "reviewer_note": None,
            "pr_number": None,
            "pr_url": None,
            "updated_at": "2026-05-01T20:00:00+00:00",
        }
        out = compute_recommendations([_summary()], [_finding()], [decision])
        rec = [r for r in out["cm_x"] if r["rule"] == "exclusion_pattern"][0]
        assert rec["decision"] is None

    def test_first_decision_in_list_wins_when_keys_collide(self):
        # The DB reader returns rows ordered DESC by updated_at, so the
        # caller passes the freshest row first. compute_recommendations
        # uses `setdefault` to honor that — first wins.
        decisions = [
            {
                "id": "d-fresh",
                "metric_id": "cm_x",
                "rule": "exclusion_pattern",
                "decision_key": "accounts receivable",
                "decision": "accepted",
                "reviewer_id": "RGM",
                "reviewer_note": None,
                "pr_number": None,
                "pr_url": None,
                "updated_at": "2026-05-01T20:00:00+00:00",
            },
            {
                "id": "d-old",
                "metric_id": "cm_x",
                "rule": "exclusion_pattern",
                "decision_key": "accounts receivable",
                "decision": "dismissed",
                "reviewer_id": "OTHER",
                "reviewer_note": None,
                "pr_number": None,
                "pr_url": None,
                "updated_at": "2026-04-01T20:00:00+00:00",
            },
        ]
        out = compute_recommendations([_summary()], [_finding()], decisions)
        rec = [r for r in out["cm_x"] if r["rule"] == "exclusion_pattern"][0]
        assert rec["decision"]["id"] == "d-fresh"
        assert rec["decision"]["reviewer_id"] == "RGM"


# ---------------------------------------------------------------------------
# config_drift flag — set when stored hash differs from live hash
# ---------------------------------------------------------------------------


class TestConfigDriftFlag:
    """config_drift is a card-level metadata field; it fires on any rule type.

    compute_recommendations imports compute_config_hash lazily inside the
    function body, so we patch it at the source module
    (``src.extraction_v2.config_hash.compute_config_hash``) to intercept
    the call regardless of where the import lands.
    """

    _STORED_HASH = "a" * 64  # stable fake stored hash

    def test_drift_true_when_stored_hash_differs(self) -> None:
        """Stored hash != live hash → config_drift True on every card."""
        from unittest.mock import patch

        live_hash = "b" * 64  # differs from _STORED_HASH ("a" * 64)

        with patch(
            "src.extraction_v2.config_hash.compute_config_hash",
            return_value=live_hash,
        ):
            out = compute_recommendations(
                [_summary()],
                [_finding()],
                config_snapshot_hash=self._STORED_HASH,
            )

        assert "cm_x" in out
        for rec in out["cm_x"]:
            assert rec["config_drift"] is True, (
                f"Expected config_drift=True on rule {rec['rule']!r} when hash differs"
            )

    def test_drift_false_when_stored_hash_matches(self) -> None:
        """Stored hash == live hash → config_drift False on every card."""
        from unittest.mock import patch

        matching_hash = self._STORED_HASH  # same as stored

        with patch(
            "src.extraction_v2.config_hash.compute_config_hash",
            return_value=matching_hash,
        ):
            out = compute_recommendations(
                [_summary()],
                [_finding()],
                config_snapshot_hash=self._STORED_HASH,
            )

        assert "cm_x" in out
        for rec in out["cm_x"]:
            assert rec["config_drift"] is False, (
                f"Expected config_drift=False on rule {rec['rule']!r} when hash matches"
            )

    def test_drift_false_when_stored_hash_is_none(self) -> None:
        """Stored hash is None (legacy run) → config_drift False; legacy cards not flagged."""
        from unittest.mock import patch

        with patch(
            "src.extraction_v2.config_hash.compute_config_hash",
            return_value="b" * 64,
        ):
            out = compute_recommendations(
                [_summary()],
                [_finding()],
                config_snapshot_hash=None,
            )

        assert "cm_x" in out
        for rec in out["cm_x"]:
            assert rec["config_drift"] is False, (
                f"Expected config_drift=False on rule {rec['rule']!r} for legacy None hash"
            )


# ---------------------------------------------------------------------------
# is_stale flag — set when decision_key absent from latest run's findings
# ---------------------------------------------------------------------------


def _decision(
    *,
    metric_id: str = "cm_x",
    rule: str = "exclusion_pattern",
    decision_key: str = "accounts receivable",
    decision: str = "deferred",
    reviewer_id: str = "RGM",
) -> dict:
    return {
        "id": "d1",
        "metric_id": metric_id,
        "rule": rule,
        "decision_key": decision_key,
        "decision": decision,
        "reviewer_id": reviewer_id,
        "reviewer_note": None,
        "pr_number": None,
        "pr_url": None,
        "updated_at": "2026-05-01T20:00:00+00:00",
    }


class TestIsStaleFlag:
    """is_stale=False when decision_key still fires; True when it no longer fires.

    Active recommendations (produced by current run) always have is_stale=False.
    Stale recommendations are injected from the decisions list for keys that
    no longer surface in findings/summaries.
    """

    def test_active_rec_is_not_stale(self) -> None:
        """A rec whose decision_key is still in current findings → is_stale=False."""
        out = compute_recommendations(
            [_summary()],
            [_finding(phrase="accounts receivable", pct=45.0)],
            [_decision(decision_key="accounts receivable")],
        )
        recs = out["cm_x"]
        excl = [r for r in recs if r["rule"] == "exclusion_pattern"]
        assert len(excl) == 1
        assert excl[0]["is_stale"] is False

    def test_decision_for_absent_key_is_stale(self) -> None:
        """A decision whose decision_key is NOT in current findings → is_stale=True."""
        # The current findings have no phrase matching "old phrase" above threshold.
        out = compute_recommendations(
            [_summary()],
            [],  # No current findings — rule won't fire
            [_decision(decision_key="old phrase")],
        )
        # Stale card injected into output under the decision's metric_id.
        assert "cm_x" in out
        stale = [r for r in out["cm_x"] if r["is_stale"]]
        assert len(stale) == 1
        assert stale[0]["decision_key"] == "old phrase"
        assert stale[0]["is_stale"] is True

    def test_empty_findings_all_decisions_stale(self) -> None:
        """Edge case: empty findings list → all decisions become is_stale=True."""
        decisions = [
            _decision(decision_key="phrase one"),
            _decision(
                metric_id="cm_x",
                rule="keyword_overlap",
                decision_key="cm_y",
            ),
        ]
        out = compute_recommendations(
            [_summary()],
            [],  # No findings
            decisions,
        )
        assert "cm_x" in out
        stale = [r for r in out["cm_x"] if r["is_stale"]]
        # Both decisions are stale (neither rule fires on empty findings/summaries).
        assert len(stale) == 2
        for rec in stale:
            assert rec["is_stale"] is True

    def test_stale_card_carries_decision(self) -> None:
        """Stale rec card has the decision attached for audit display."""
        d = _decision(decision_key="stale phrase", decision="accepted")
        out = compute_recommendations(
            [_summary()],
            [],
            [d],
        )
        stale = [r for r in out["cm_x"] if r["is_stale"]]
        assert len(stale) == 1
        assert stale[0]["decision"] is not None
        assert stale[0]["decision"]["decision"] == "accepted"

    def test_no_decisions_arg_no_stale_cards(self) -> None:
        """When decisions arg is omitted, no stale cards are injected."""
        out = compute_recommendations([_summary()], [_finding(pct=45.0)])
        recs = out.get("cm_x", [])
        stale = [r for r in recs if r.get("is_stale")]
        assert stale == []

    def test_fp_filter_gap_key_stale_when_rule_drops(self) -> None:
        """fp_filter_gap decision is stale when wrong_value ratio drops below threshold."""
        # Decision for wrong_value, but current summary shows reject_count < floor.
        d = _decision(
            metric_id="cm_x",
            rule="fp_filter_gap",
            decision_key="wrong_value",
        )
        # Summary with too few rejects to fire fp_filter_gap (below FP_REJECT_FLOOR=5).
        s = _summary(reject=3, rejection_categories={"wrong_value": 3})
        out = compute_recommendations([s], [], [d])
        assert "cm_x" in out
        stale = [r for r in out["cm_x"] if r["is_stale"]]
        assert len(stale) == 1
        assert stale[0]["decision_key"] == "wrong_value"
