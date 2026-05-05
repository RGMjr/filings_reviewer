"""Unit tests for compute_cross_metric_findings and interpret_finding_row.

Both functions live in src/web/text_pattern_recommendations.py.

Pure-function tests — no Flask, no DB.  The cross_metric_exclusion rule
reads EXCL_SOURCE_FIELDS from the module scope; tests that need to override
the allowlist monkeypatch at one site:
  ``src.web.text_pattern_recommendations.EXCL_SOURCE_FIELDS``
"""

from __future__ import annotations

from unittest.mock import patch

from src.web.text_pattern_recommendations import (
    EXCL_SOURCE_FIELDS,
    compute_cross_metric_findings,
    interpret_finding_row,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _finding(
    *,
    metric_id: str = "cm_a",
    phrase: str = "accounts receivable",
    decision_type: str = "reject",
    source_field: str = "segment_text",
    ngram: int = 2,
    occurrences: int = 5,
    pct: float = 40.0,
    examples: list | None = None,
) -> dict:
    return {
        "metric_id": metric_id,
        "phrase": phrase,
        "decision_type": decision_type,
        "source_field": source_field,
        "phrase_ngram_size": ngram,
        "occurrence_count": occurrences,
        "pct_of_decisions": pct,
        "examples": examples or [],
    }


def _findings_for_phrase(
    phrase: str,
    *,
    metric_ids: list[str],
    decision_type: str = "reject",
    source_field: str = "segment_text",
    ngram: int = 2,
) -> list[dict]:
    return [
        _finding(
            metric_id=mid,
            phrase=phrase,
            decision_type=decision_type,
            source_field=source_field,
            ngram=ngram,
        )
        for mid in metric_ids
    ]


# ---------------------------------------------------------------------------
# compute_cross_metric_findings — grouping
# ---------------------------------------------------------------------------


class TestCrossMetricFindingsGrouping:
    def test_empty_input_returns_empty_list(self):
        assert compute_cross_metric_findings([]) == []

    def test_single_metric_single_phrase(self):
        out = compute_cross_metric_findings([_finding(metric_id="cm_a", phrase="foo")])
        assert len(out) == 1
        assert out[0]["phrase"] == "foo"
        assert out[0]["metric_count"] == 1
        assert out[0]["metrics"] == ["cm_a"]

    def test_same_phrase_across_three_metrics_groups_correctly(self):
        findings = _findings_for_phrase("part of", metric_ids=["cm_a", "cm_b", "cm_c"])
        out = compute_cross_metric_findings(findings)
        assert len(out) == 1
        row = out[0]
        assert row["phrase"] == "part of"
        assert row["metric_count"] == 3
        assert set(row["metrics"]) == {"cm_a", "cm_b", "cm_c"}

    def test_total_occurrence_sums_across_metrics(self):
        findings = [
            _finding(metric_id="cm_a", phrase="foo", occurrences=3),
            _finding(metric_id="cm_b", phrase="foo", occurrences=7),
        ]
        out = compute_cross_metric_findings(findings)
        assert out[0]["total_occurrence"] == 10

    def test_different_phrases_produce_separate_rows(self):
        findings = [
            _finding(phrase="alpha"),
            _finding(phrase="beta"),
        ]
        out = compute_cross_metric_findings(findings)
        assert len(out) == 2
        phrases = {r["phrase"] for r in out}
        assert phrases == {"alpha", "beta"}

    def test_different_decision_types_produce_separate_rows(self):
        findings = [
            _finding(phrase="foo", decision_type="reject"),
            _finding(phrase="foo", decision_type="correct"),
        ]
        out = compute_cross_metric_findings(findings)
        assert len(out) == 2

    def test_different_source_fields_produce_separate_rows(self):
        findings = [
            _finding(phrase="foo", source_field="segment_text"),
            _finding(phrase="foo", source_field="rejection_reason"),
        ]
        out = compute_cross_metric_findings(findings)
        assert len(out) == 2

    def test_sorted_desc_by_total_occurrence(self):
        findings = [
            _finding(metric_id="cm_a", phrase="rare", occurrences=2),
            _finding(metric_id="cm_a", phrase="common", occurrences=20),
        ]
        out = compute_cross_metric_findings(findings)
        assert out[0]["phrase"] == "common"
        assert out[1]["phrase"] == "rare"

    def test_metrics_list_is_sorted(self):
        findings = _findings_for_phrase("foo", metric_ids=["cm_z", "cm_a", "cm_m"])
        out = compute_cross_metric_findings(findings)
        assert out[0]["metrics"] == sorted(["cm_z", "cm_a", "cm_m"])

    def test_duplicate_metric_id_counted_once(self):
        # Two findings for the same (metric, phrase) — metric_count stays 1.
        findings = [
            _finding(metric_id="cm_a", phrase="foo", occurrences=3),
            _finding(metric_id="cm_a", phrase="foo", occurrences=5),
        ]
        out = compute_cross_metric_findings(findings)
        assert out[0]["metric_count"] == 1
        assert out[0]["total_occurrence"] == 8

    def test_top_examples_capped_at_five(self):
        # 6 findings each with one example → capped at 5 examples.
        findings = [
            _finding(
                metric_id=f"cm_{i}",
                phrase="foo",
                examples=[{"fact_id": i, "filing_id": i}],
            )
            for i in range(6)
        ]
        out = compute_cross_metric_findings(findings)
        assert len(out[0]["top_examples"]) == 5


# ---------------------------------------------------------------------------
# cross_metric_exclusion rule firing
# ---------------------------------------------------------------------------


class TestCrossMetricExclusionRule:
    """cross_metric_exclusion fires when:
    - decision_type == 'reject'
    - source_field in EXCL_SOURCE_FIELDS
    - phrase_ngram_size >= EXCL_NGRAM_MIN (2)
    - metric_count >= 3

    Reads EXCL_SOURCE_FIELDS from the module-level binding so monkeypatching
    at one site covers both per-metric and cross-metric rules.
    """

    def _three_metric_findings(self, **kw) -> list[dict]:
        return _findings_for_phrase("foo", metric_ids=["cm_a", "cm_b", "cm_c"], **kw)

    def test_fires_when_all_conditions_met(self):
        findings = self._three_metric_findings(
            decision_type="reject", source_field="segment_text", ngram=2
        )
        out = compute_cross_metric_findings(findings)
        assert out[0]["cross_metric_exclusion"] is True

    def test_does_not_fire_below_three_metrics(self):
        findings = _findings_for_phrase(
            "foo",
            metric_ids=["cm_a", "cm_b"],
            decision_type="reject",
            source_field="segment_text",
            ngram=2,
        )
        out = compute_cross_metric_findings(findings)
        assert out[0]["cross_metric_exclusion"] is False

    def test_does_not_fire_for_unigram(self):
        findings = self._three_metric_findings(
            decision_type="reject", source_field="segment_text", ngram=1
        )
        out = compute_cross_metric_findings(findings)
        assert out[0]["cross_metric_exclusion"] is False

    def test_does_not_fire_for_correct_decision_type(self):
        findings = self._three_metric_findings(
            decision_type="correct", source_field="segment_text", ngram=2
        )
        out = compute_cross_metric_findings(findings)
        assert out[0]["cross_metric_exclusion"] is False

    def test_does_not_fire_for_excluded_source_field(self):
        # rejection_reason is NOT in EXCL_SOURCE_FIELDS after PR 4.
        assert "rejection_reason" not in EXCL_SOURCE_FIELDS
        findings = self._three_metric_findings(
            decision_type="reject", source_field="rejection_reason", ngram=2
        )
        out = compute_cross_metric_findings(findings)
        assert out[0]["cross_metric_exclusion"] is False

    def test_monkeypatch_source_field_affects_rule(self):
        """Patching EXCL_SOURCE_FIELDS at one site covers the cross-metric rule."""
        findings = self._three_metric_findings(
            decision_type="reject", source_field="rejection_reason", ngram=2
        )
        with patch(
            "src.web.text_pattern_recommendations.EXCL_SOURCE_FIELDS",
            ("rejection_reason",),
        ):
            out = compute_cross_metric_findings(findings)
        assert out[0]["cross_metric_exclusion"] is True

    def test_severity_medium_at_three_metrics(self):
        findings = self._three_metric_findings(
            decision_type="reject", source_field="segment_text", ngram=2
        )
        out = compute_cross_metric_findings(findings)
        assert out[0]["severity"] == "medium"

    def test_severity_medium_at_four_metrics(self):
        findings = _findings_for_phrase(
            "foo",
            metric_ids=["cm_a", "cm_b", "cm_c", "cm_d"],
            decision_type="reject",
            source_field="segment_text",
            ngram=2,
        )
        out = compute_cross_metric_findings(findings)
        assert out[0]["severity"] == "medium"

    def test_severity_high_at_five_metrics(self):
        findings = _findings_for_phrase(
            "foo",
            metric_ids=["cm_a", "cm_b", "cm_c", "cm_d", "cm_e"],
            decision_type="reject",
            source_field="segment_text",
            ngram=2,
        )
        out = compute_cross_metric_findings(findings)
        assert out[0]["severity"] == "high"
        assert out[0]["cross_metric_exclusion"] is True

    def test_severity_none_when_rule_does_not_fire(self):
        # 2 metrics only → rule doesn't fire → severity is None.
        findings = _findings_for_phrase(
            "foo",
            metric_ids=["cm_a", "cm_b"],
            decision_type="reject",
            source_field="segment_text",
            ngram=2,
        )
        out = compute_cross_metric_findings(findings)
        assert out[0]["severity"] is None


# ---------------------------------------------------------------------------
# interpret_finding_row — all five branches
# ---------------------------------------------------------------------------


class TestInterpretFindingRow:
    def _row(
        self,
        *,
        decision_type: str = "reject",
        source_field: str = "segment_text",
        ngram: int = 2,
    ) -> dict:
        return {
            "decision_type": decision_type,
            "source_field": source_field,
            "phrase_ngram_size": ngram,
            "phrase": "foo",
        }

    def test_accept_any_source(self):
        out = interpret_finding_row(self._row(decision_type="accept"))
        assert "positive" in out["interpretation"].lower()
        assert "keyword" in out["suggested_action"].lower()

    def test_correct_any_source(self):
        out = interpret_finding_row(self._row(decision_type="correct"))
        assert "sibling" in out["interpretation"].lower()
        assert "keyword_overlap" in out["suggested_action"]

    def test_reject_rejection_reason_bigram_historical(self):
        """Historical pre-PR-509 row: rejection_reason source, ngram>=2."""
        out = interpret_finding_row(
            self._row(decision_type="reject", source_field="rejection_reason", ngram=2)
        )
        assert (
            "historical" in out["interpretation"].lower()
            or "reviewer" in out["interpretation"].lower()
        )
        assert "PR 4" in out["suggested_action"] or "exclusion" in out["suggested_action"].lower()

    def test_reject_segment_text_bigram(self):
        out = interpret_finding_row(
            self._row(decision_type="reject", source_field="segment_text", ngram=2)
        )
        assert (
            "extracted text" in out["interpretation"].lower()
            or "rejected" in out["interpretation"].lower()
        )
        assert (
            "exclusion" in out["suggested_action"].lower()
            or "filter" in out["suggested_action"].lower()
        )

    def test_reject_segment_text_unigram(self):
        out = interpret_finding_row(
            self._row(decision_type="reject", source_field="segment_text", ngram=1)
        )
        assert (
            "single" in out["interpretation"].lower()
            or "aggressive" in out["interpretation"].lower()
        )
        assert (
            "FP" in out["suggested_action"]
            or "single" in out["suggested_action"].lower()
            or "fp" in out["suggested_action"].lower()
            or "rule" in out["suggested_action"].lower()
        )

    def test_fallback_for_unknown_combination(self):
        out = interpret_finding_row(
            self._row(decision_type="reject", source_field="reviewer_notes", ngram=3)
        )
        # Should not raise; must return both keys.
        assert "interpretation" in out
        assert "suggested_action" in out

    def test_returns_both_keys_always(self):
        for decision_type in ("accept", "correct", "reject"):
            for source_field in ("segment_text", "rejection_reason", "reviewer_notes"):
                for ngram in (1, 2, 3):
                    out = interpret_finding_row(
                        self._row(
                            decision_type=decision_type,
                            source_field=source_field,
                            ngram=ngram,
                        )
                    )
                    assert set(out.keys()) >= {
                        "interpretation",
                        "suggested_action",
                    }, f"Missing keys for ({decision_type}, {source_field}, {ngram})"
