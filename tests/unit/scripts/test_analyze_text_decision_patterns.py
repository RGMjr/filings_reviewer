"""Unit tests for the n-gram mining logic in
scripts/analyze_text_decision_patterns.py.

Pure-Python helpers (_tokenize, _ngrams, _segment_window,
_mine_phrases_for_metric, _build_metric_summary) are exercised against
synthetic decision dicts — no DB. The DB-touching orchestration path is
covered separately by an integration test (omitted from this PR; the
scripts.md rule places that under tests/integration/).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

_SCRIPT_PATH = Path(__file__).resolve().parents[3] / "scripts" / "analyze_text_decision_patterns.py"


def _load_module() -> Any:
    spec = importlib.util.spec_from_file_location("analyze_text_decision_patterns", _SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


M = _load_module()


def _decision(
    *,
    fact_id: str,
    decision: str,
    reason: str | None = None,
    notes: str | None = None,
    segment: str | None = None,
    value_raw: str = "100",
    metric_id: str = "cm_x",
    assigned: str | None = None,
    category: str | None = None,
) -> dict:
    return {
        "fact_id": fact_id,
        "filing_id": 1,
        "canonical_metric_id": metric_id,
        "decision": decision,
        "rejection_category": category,
        "rejection_reason": reason,
        "reviewer_notes": notes,
        "assigned_metric_id": assigned,
        "value_raw": value_raw,
        "segment_text": segment,
    }


class TestTokenize:
    def test_drops_short_and_stopwords(self):
        tokens = M._tokenize("The quick accounts receivable for the customer")
        # 'the', 'for', 'customer' are stopwords; everything else >= 3 chars.
        assert "accounts" in tokens
        assert "receivable" in tokens
        assert "the" not in tokens
        assert "for" not in tokens
        assert "customer" not in tokens

    def test_lowercases_and_handles_none(self):
        assert M._tokenize(None) == []
        assert M._tokenize("") == []
        assert "accounts" in M._tokenize("ACCOUNTS Receivable")


class TestNgrams:
    def test_emits_correct_size(self):
        toks = ["accounts", "receivable", "balance", "growth"]
        assert M._ngrams(toks, 1) == toks
        assert M._ngrams(toks, 2) == [
            "accounts receivable",
            "receivable balance",
            "balance growth",
        ]
        assert M._ngrams(toks, 3) == [
            "accounts receivable balance",
            "receivable balance growth",
        ]
        # Too short for n=5 → empty.
        assert M._ngrams(toks, 5) == []


class TestSegmentWindow:
    def test_clips_around_value(self):
        text = "x " * 500 + "VALUE 12,345 here" + " y" * 500
        win = M._segment_window(text, "12,345")
        assert "12,345" in win
        assert len(win) < len(text)

    def test_falls_back_when_value_missing(self):
        # Returns up to 2*window characters of the head.
        text = "a" * 1000
        win = M._segment_window(text, "no-such-substring")
        assert len(win) == 2 * M.SEGMENT_WINDOW_CHARS


class TestMinePhrasesForMetric:
    def test_finds_high_incidence_phrase_in_rejection_reason(self):
        # 5 of 6 rejects share "accounts receivable"; the threshold is 10%
        # and 83% clears.
        rows = [
            _decision(
                fact_id=f"00000000-0000-0000-0000-00000000000{i}",
                decision="reject",
                reason="this is accounts receivable not customer count",
            )
            for i in range(5)
        ]
        rows.append(
            _decision(
                fact_id="00000000-0000-0000-0000-000000000099",
                decision="reject",
                reason="duplicate of fact 5",
            )
        )

        findings = M._mine_phrases_for_metric(
            rows, "cm_x", decision_type="reject", metric_keyword_tokens=set()
        )
        phrases = {(f["phrase"], f["source_field"]) for f in findings}
        assert ("accounts receivable", "rejection_reason") in phrases
        # Verify count + pct.
        ar = next(
            f
            for f in findings
            if f["phrase"] == "accounts receivable" and f["source_field"] == "rejection_reason"
        )
        assert ar["occurrence_count"] == 5
        assert ar["pct_of_decisions"] == 83.33
        assert ar["phrase_ngram_size"] == 2

    def test_filters_below_pct_threshold(self):
        # 1/6 cite "outlier phrase" — below the 10% threshold.
        rows = [
            _decision(fact_id=str(i), decision="reject", reason="generic noise") for i in range(6)
        ]
        # And one ringer with a unique 1-of-7 phrase.
        rows.append(_decision(fact_id="ringer", decision="reject", reason="some outlier phrase"))
        findings = M._mine_phrases_for_metric(
            rows, "cm_x", decision_type="reject", metric_keyword_tokens=set()
        )
        # 1/7 = 14.3%, BUT MIN_OCCURRENCES is 2, so single occurrences are
        # dropped. "noise" appears in 6/7 rows and SHOULD survive (~86%).
        phrases = {f["phrase"] for f in findings}
        assert "outlier" not in phrases
        assert "noise" in phrases

    def test_metric_keyword_tokens_are_suppressed(self):
        # The metric's own keyword "customer" should not surface as a finding
        # even though it appears in every reject reason.
        rows = [
            _decision(
                fact_id=str(i),
                decision="reject",
                reason="this customer is wrong: it should be growth",
            )
            for i in range(5)
        ]
        findings = M._mine_phrases_for_metric(
            rows,
            "cm_x",
            decision_type="reject",
            metric_keyword_tokens={"customer"},
        )
        phrases = {f["phrase"] for f in findings}
        # 'customer' is suppressed; 'growth' / 'wrong' should not be.
        assert "customer" not in phrases
        # Suppression also blocks ngrams containing the token.
        assert not any("customer" in p for p in phrases)

    def test_examples_are_capped_and_carry_filing_id(self):
        rows = [
            _decision(
                fact_id=f"fact-{i}",
                decision="reject",
                reason="accounts receivable balance issue",
            )
            for i in range(20)
        ]
        # Decorate two rows with a different filing_id to verify denormalization.
        rows[0]["filing_id"] = 42
        rows[1]["filing_id"] = 7
        findings = M._mine_phrases_for_metric(
            rows, "cm_x", decision_type="reject", metric_keyword_tokens=set()
        )
        ar = next(f for f in findings if f["phrase"] == "accounts receivable balance")
        # MAX_EXAMPLES caps the list.
        assert len(ar["examples"]) == M.MAX_EXAMPLES
        # All examples carry both fact_id and filing_id.
        for ex in ar["examples"]:
            assert "fact_id" in ex
            assert "filing_id" in ex
        # The first two filings are seeded with custom ids.
        filing_ids = {ex["filing_id"] for ex in ar["examples"]}
        assert 42 in filing_ids or 7 in filing_ids

    def test_empty_returns_empty(self):
        assert (
            M._mine_phrases_for_metric(
                [], "cm_x", decision_type="reject", metric_keyword_tokens=set()
            )
            == []
        )


class TestBuildMetricSummary:
    def test_groups_and_counts_by_metric(self):
        rows = [
            _decision(fact_id="1", decision="accept"),
            _decision(fact_id="2", decision="reject", category="wrong_value"),
            _decision(fact_id="3", decision="reject", category="wrong_value"),
            _decision(fact_id="4", decision="reject", category="not_a_metric"),
            _decision(
                fact_id="5",
                decision="correct",
                assigned="cm_y",
            ),
            _decision(
                fact_id="6",
                decision="correct",
                assigned="cm_y",
            ),
            _decision(fact_id="7", decision="reject", metric_id="cm_z"),
        ]
        out = M._build_metric_summary(rows)
        # Two metrics rolled up.
        by_metric = {s["metric_id"]: s for s in out}
        assert "cm_x" in by_metric and "cm_z" in by_metric

        x = by_metric["cm_x"]
        assert x["total_decisions"] == 6
        assert x["accept_count"] == 1
        assert x["reject_count"] == 3
        assert x["correct_count"] == 2
        assert x["rejection_categories"] == {"wrong_value": 2, "not_a_metric": 1}
        # Top correction targets sorted by count.
        assert x["top_correction_targets"] == [{"target_metric_id": "cm_y", "count": 2}]

        z = by_metric["cm_z"]
        assert z["total_decisions"] == 1
        assert z["reject_count"] == 1
        # No category set on the cm_z reject → empty histogram.
        assert z["rejection_categories"] == {}
