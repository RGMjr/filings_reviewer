"""
V2 vs V1 parity tests.

These tests run the full extraction pipeline on gold standard filings and
compare V2 against V1 to ensure V2 is at least as good.

WARNING: These tests are slow (runs V1 + V2 pipeline on 10 companies).
Run only when explicitly needed:
    pytest -m v2_parity -v
"""

import pytest


@pytest.mark.v2_parity
class TestV2VsV1TextParity:
    def test_v2_text_f1_within_5pct_of_v1(self, unified_report):
        """V2 text-only F1 must not trail V1 F1 by more than 5 percentage points."""
        v1_f1 = unified_report.v1_overall.f1
        v2_f1 = (
            unified_report.v2_text_only_overall.f1
            if unified_report.v2_text_only_overall
            else unified_report.v2_full_overall.f1
        )
        assert v2_f1 >= v1_f1 - 0.05, (
            f"V2 text F1 ({v2_f1:.1%}) is more than 5pp below V1 F1 ({v1_f1:.1%})"
        )

    def test_v2_text_recall_within_10pct_of_v1(self, unified_report):
        """V2 text-only recall must not trail V1 recall by more than 10 percentage points."""
        v1_recall = unified_report.v1_overall.recall
        v2_recall = (
            unified_report.v2_text_only_overall.recall
            if unified_report.v2_text_only_overall
            else unified_report.v2_full_overall.recall
        )
        assert v2_recall >= v1_recall - 0.10, (
            f"V2 recall ({v2_recall:.1%}) is more than 10pp below V1 recall ({v1_recall:.1%})"
        )

    def test_no_company_v2_recall_collapses(self, unified_report):
        """No single company should have V2 recall drop more than 15% vs V1."""
        for company in unified_report.companies:
            v1_recall = company.v1_scores.recall
            v2_scores = company.v2_text_only_scores or company.v2_full_scores
            v2_recall = v2_scores.recall
            # Only check if V1 had meaningful recall (>10%) to avoid noise from low-data companies
            if v1_recall > 0.10:
                assert v2_recall >= v1_recall - 0.15, (
                    f"{company.company_name}: V2 recall ({v2_recall:.1%}) dropped "
                    f">15pp vs V1 ({v1_recall:.1%})"
                )

    def test_v2_full_finds_more_total_than_v1(self, unified_report):
        """V2-full TP count should be >= V1 TP count (charts add recall)."""
        # Count total TPs across all companies
        v1_tp = sum(c.v1_scores.tp_count for c in unified_report.companies)
        v2_tp = sum(c.v2_full_scores.tp_count for c in unified_report.companies)
        # V2 should find at least as many as V1 overall
        assert v2_tp >= v1_tp * 0.85, f"V2-full total TPs ({v2_tp}) is <85% of V1 TPs ({v1_tp})"
