"""
Unit tests for validate_against_gold_standard.py script.

Tests cover:
- CSV parsing with various edge cases
- Value normalization (millions, billions, percentages)
- Metric ID normalization
- Matching logic between candidates and gold standard
- Precision/recall/F1 calculation
"""

# Import the module under test
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from scripts.validate_against_gold_standard import (
    GoldStandardEntry,
    ValidationResult,
    get_entries_for_company,
    load_gold_standard,
    match_candidate_to_gold_standard,
    normalize_metric_id,
    normalize_value,
    result_to_dict,
)


class TestNormalizeValue:
    """Tests for normalize_value function."""

    def test_simple_integer(self):
        """Test simple integer parsing."""
        assert normalize_value("100") == 100.0
        assert normalize_value("1234") == 1234.0

    def test_simple_float(self):
        """Test simple float parsing."""
        assert normalize_value("1.5") == 1.5
        assert normalize_value("3.14159") == pytest.approx(3.14159)

    def test_million_suffix(self):
        """Test 'million' multiplier."""
        assert normalize_value("10 million") == 10_000_000
        assert normalize_value("1.5 million") == 1_500_000
        assert normalize_value("10M") == 10_000_000
        assert normalize_value("1.5m") == 1_500_000

    def test_billion_suffix(self):
        """Test 'billion' multiplier."""
        assert normalize_value("1.5 billion") == 1_500_000_000
        assert normalize_value("2B") == 2_000_000_000
        assert normalize_value("2b") == 2_000_000_000

    def test_thousand_suffix(self):
        """Test 'thousand' multiplier."""
        assert normalize_value("500 thousand") == 500_000
        assert normalize_value("500K") == 500_000
        assert normalize_value("500k") == 500_000

    def test_currency_symbol(self):
        """Test stripping currency symbols."""
        assert normalize_value("$1.2 billion") == 1_200_000_000
        assert normalize_value("$500") == 500

    def test_commas(self):
        """Test stripping commas."""
        assert normalize_value("1,000,000") == 1_000_000
        assert normalize_value("$1,234,567") == 1_234_567

    def test_percentage(self):
        """Test percentage conversion."""
        assert normalize_value("15%") == 0.15
        assert normalize_value("100%") == 1.0
        assert normalize_value("0.5%") == 0.005

    def test_empty_and_special_values(self):
        """Test empty and special values return None."""
        assert normalize_value("") is None
        assert normalize_value("chart") is None
        assert normalize_value("n/a") is None
        assert normalize_value("N/A") is None
        assert normalize_value("-") is None

    def test_trillion(self):
        """Test trillion multiplier."""
        assert normalize_value("1 trillion") == 1_000_000_000_000
        assert normalize_value("1.5T") == 1_500_000_000_000


class TestNormalizeMetricId:
    """Tests for normalize_metric_id function."""

    def test_already_normalized(self):
        """Test IDs that are already normalized."""
        assert normalize_metric_id("cm_dau") == "cm_dau"
        assert normalize_metric_id("cm_daily_active_users") == "cm_daily_active_users"

    def test_case_normalization(self):
        """Test case is normalized to lowercase."""
        assert normalize_metric_id("CM_DAU") == "cm_dau"
        assert normalize_metric_id("Cm_Dau") == "cm_dau"

    def test_whitespace_handling(self):
        """Test whitespace is trimmed."""
        assert normalize_metric_id("  cm_dau  ") == "cm_dau"
        assert normalize_metric_id("\tcm_arr\n") == "cm_arr"

    def test_empty_string(self):
        """Test empty string stays empty."""
        assert normalize_metric_id("") == ""
        assert normalize_metric_id("   ") == ""


class TestLoadGoldStandard:
    """Tests for load_gold_standard function."""

    def test_parse_basic_csv(self):
        """Test parsing a basic gold standard CSV."""
        csv_content = """Document URL,Company,Standard Metric Name,New standard metric?,Name in the text,Raw value,Scaled value,Scale/unit,Period,Definition,Quote/context
https://example.com/filing1,Test Corp,cm_dau,,daily active users,10 million,10,million,Q1 2023,Users who log in daily,"We had 10 million daily active users"
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, encoding='utf-8-sig') as f:
            f.write(csv_content)
            temp_path = Path(f.name)

        try:
            entries = load_gold_standard(temp_path)
            assert len(entries) == 1
            assert entries[0].company == "Test Corp"
            assert entries[0].metric_id == "cm_dau"
            assert entries[0].raw_value == "10 million"
            assert entries[0].line_number == 2
        finally:
            temp_path.unlink()

    def test_parse_new_metric_column(self):
        """Test parsing entries where metric ID is in 'New standard metric?' column."""
        csv_content = """Document URL,Company,Standard Metric Name,New standard metric?,Name in the text,Raw value,Scaled value,Scale/unit,Period,Definition,Quote/context
https://example.com/filing1,Test Corp,,cm_custom_metric,custom metric,5,5,,Q1 2023,Custom definition,"Quote here"
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, encoding='utf-8-sig') as f:
            f.write(csv_content)
            temp_path = Path(f.name)

        try:
            entries = load_gold_standard(temp_path)
            assert len(entries) == 1
            assert entries[0].metric_id == "cm_custom_metric"
            assert entries[0].is_new_metric is True
        finally:
            temp_path.unlink()

    def test_parse_multiline_quotes(self):
        """Test parsing entries with multi-line quoted fields."""
        csv_content = '''Document URL,Company,Standard Metric Name,New standard metric?,Name in the text,Raw value,Scaled value,Scale/unit,Period,Definition,Quote/context
https://example.com,Test Corp,cm_arr,,ARR,1 billion,1,billion,2023,"Annual recurring revenue, which is
calculated as the monthly
recurring revenue times 12","We define annual recurring revenue
as the sum of all subscription
fees over a 12-month period"
'''
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, encoding='utf-8-sig') as f:
            f.write(csv_content)
            temp_path = Path(f.name)

        try:
            entries = load_gold_standard(temp_path)
            assert len(entries) == 1
            assert "calculated as the monthly" in entries[0].definition
            assert "12-month period" in entries[0].source_quote
        finally:
            temp_path.unlink()

    def test_utf8_sig_encoding(self):
        """Test handling of UTF-8 BOM encoding."""
        # Write with BOM
        csv_content = """Document URL,Company,Standard Metric Name,New standard metric?,Name in the text,Raw value,Scaled value,Scale/unit,Period,Definition,Quote/context
https://example.com,Caf\u00e9 Corp,cm_users,,users,100,100,,2023,User count,"100 users"
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, encoding='utf-8-sig') as f:
            f.write(csv_content)
            temp_path = Path(f.name)

        try:
            entries = load_gold_standard(temp_path)
            assert len(entries) == 1
            assert entries[0].company == "Caf\u00e9 Corp"
        finally:
            temp_path.unlink()


class TestGetEntriesForCompany:
    """Tests for get_entries_for_company function."""

    def test_case_insensitive_match(self):
        """Test company name matching is case-insensitive."""
        entries = [
            GoldStandardEntry(
                document_url="", company="Slack Technologies", metric_id="cm_dau",
                is_new_metric=False, text_variant="", raw_value="", scaled_value="",
                scale_unit="", period="", definition="", source_quote="", line_number=1
            ),
            GoldStandardEntry(
                document_url="", company="Another Corp", metric_id="cm_arr",
                is_new_metric=False, text_variant="", raw_value="", scaled_value="",
                scale_unit="", period="", definition="", source_quote="", line_number=2
            ),
        ]

        result = get_entries_for_company(entries, "slack technologies")
        assert len(result) == 1
        assert result[0].company == "Slack Technologies"

        result = get_entries_for_company(entries, "SLACK TECHNOLOGIES")
        assert len(result) == 1

    def test_no_match_returns_empty(self):
        """Test no match returns empty list."""
        entries = [
            GoldStandardEntry(
                document_url="", company="Slack Technologies", metric_id="cm_dau",
                is_new_metric=False, text_variant="", raw_value="", scaled_value="",
                scale_unit="", period="", definition="", source_quote="", line_number=1
            ),
        ]

        result = get_entries_for_company(entries, "Unknown Corp")
        assert len(result) == 0


class TestMatchCandidateToGoldStandard:
    """Tests for match_candidate_to_gold_standard function."""

    def test_exact_metric_and_value_match(self):
        """Test matching with exact metric ID and value."""
        candidate = {
            'candidate_id': 1,
            'suggested_metric_id': 'cm_dau',
            'parsed_value': 10_000_000,
            'raw_number_text': '10 million',
            'context_text': 'We had 10 million daily active users',
        }

        gold_entries = [
            GoldStandardEntry(
                document_url="", company="Test", metric_id="cm_dau",
                is_new_metric=False, text_variant="daily active users",
                raw_value="10 million", scaled_value="10", scale_unit="million",
                period="", definition="", source_quote="", line_number=5
            ),
        ]

        matched_entries: set[int] = set()
        match, match_type = match_candidate_to_gold_standard(candidate, gold_entries, matched_entries)

        assert match is not None
        assert match.line_number == 5
        assert 'value' in match_type.lower() or 'metric' in match_type.lower()

    def test_close_value_match(self):
        """Test matching with close value (within 1%)."""
        candidate = {
            'candidate_id': 1,
            'suggested_metric_id': 'cm_revenue',
            'parsed_value': 1_005_000,  # Within 1% of 1,000,000
            'raw_number_text': '1.005 million',
            'context_text': 'Revenue of 1.005 million',
        }

        gold_entries = [
            GoldStandardEntry(
                document_url="", company="Test", metric_id="cm_revenue",
                is_new_metric=False, text_variant="revenue",
                raw_value="1 million", scaled_value="1", scale_unit="million",
                period="", definition="", source_quote="", line_number=10
            ),
        ]

        matched_entries: set[int] = set()
        match, match_type = match_candidate_to_gold_standard(candidate, gold_entries, matched_entries)

        assert match is not None
        assert match.line_number == 10

    def test_no_match_returns_none(self):
        """Test no match returns None."""
        candidate = {
            'candidate_id': 1,
            'suggested_metric_id': 'cm_unknown',
            'parsed_value': 999,
            'raw_number_text': '999',
            'context_text': 'Some unrelated text',
        }

        gold_entries = [
            GoldStandardEntry(
                document_url="", company="Test", metric_id="cm_dau",
                is_new_metric=False, text_variant="daily active users",
                raw_value="10 million", scaled_value="", scale_unit="",
                period="", definition="", source_quote="", line_number=5
            ),
        ]

        matched_entries: set[int] = set()
        match, match_type = match_candidate_to_gold_standard(candidate, gold_entries, matched_entries)

        assert match is None

    def test_already_matched_entry_skipped(self):
        """Test already matched entries are skipped."""
        candidate = {
            'candidate_id': 2,
            'suggested_metric_id': 'cm_dau',
            'parsed_value': 10_000_000,
            'raw_number_text': '10 million',
            'context_text': 'daily active users',
        }

        gold_entries = [
            GoldStandardEntry(
                document_url="", company="Test", metric_id="cm_dau",
                is_new_metric=False, text_variant="daily active users",
                raw_value="10 million", scaled_value="", scale_unit="",
                period="", definition="", source_quote="", line_number=5
            ),
        ]

        # Mark entry as already matched
        matched_entries: set[int] = {5}
        match, match_type = match_candidate_to_gold_standard(candidate, gold_entries, matched_entries)

        assert match is None


class TestMetricsCalculation:
    """Tests for precision/recall/F1 calculation."""

    def test_perfect_precision_recall(self):
        """Test 100% precision and recall."""
        # 5 gold standard entries, 5 candidates, all matched
        result = ValidationResult(
            filing_id=1,
            company_name="Test",
            gold_standard_count=5,
            candidate_count=5,
            true_positives=5,
            false_positives=0,
            false_negatives=0,
            precision=1.0,
            recall=1.0,
            f1_score=1.0,
            fp_candidates=[],
            fn_entries=[],
            tp_matches=[],
        )

        assert result.precision == 1.0
        assert result.recall == 1.0
        assert result.f1_score == 1.0

    def test_zero_true_positives(self):
        """Test edge case with zero true positives."""
        # Precision should be 0 (0 / (0 + FP))
        # Recall should be 0 (0 / (0 + FN))
        result = ValidationResult(
            filing_id=1,
            company_name="Test",
            gold_standard_count=5,
            candidate_count=3,
            true_positives=0,
            false_positives=3,
            false_negatives=5,
            precision=0.0,
            recall=0.0,
            f1_score=0.0,
            fp_candidates=[],
            fn_entries=[],
            tp_matches=[],
        )

        assert result.precision == 0.0
        assert result.recall == 0.0
        assert result.f1_score == 0.0

    def test_partial_match(self):
        """Test partial precision/recall."""
        # 10 gold standard, 15 candidates, 8 matched
        # Precision = 8 / 15 = 0.533
        # Recall = 8 / 10 = 0.8
        tp = 8
        fp = 7  # 15 - 8
        fn = 2  # 10 - 8

        precision = tp / (tp + fp)  # 8/15 = 0.533
        recall = tp / (tp + fn)  # 8/10 = 0.8
        f1 = 2 * (precision * recall) / (precision + recall)

        assert pytest.approx(precision, rel=0.01) == 0.533
        assert recall == 0.8
        assert pytest.approx(f1, rel=0.01) == 0.64


class TestResultToDict:
    """Tests for result_to_dict function."""

    def test_serializes_correctly(self):
        """Test result converts to JSON-serializable dict."""
        fn_entry = GoldStandardEntry(
            document_url="https://example.com", company="Test", metric_id="cm_missing",
            is_new_metric=False, text_variant="missing metric",
            raw_value="100", scaled_value="", scale_unit="",
            period="", definition="", source_quote="", line_number=42
        )

        result = ValidationResult(
            filing_id=123,
            company_name="Test Corp",
            gold_standard_count=10,
            candidate_count=12,
            true_positives=8,
            false_positives=4,
            false_negatives=2,
            precision=0.667,
            recall=0.8,
            f1_score=0.727,
            fp_candidates=[{'candidate_id': 1, 'suggested_metric_id': 'cm_fp'}],
            fn_entries=[fn_entry],
            tp_matches=[],
        )

        d = result_to_dict(result)

        assert d['filing_id'] == 123
        assert d['company_name'] == "Test Corp"
        assert d['metrics']['true_positives'] == 8
        assert d['metrics']['precision'] == 0.667
        assert len(d['false_positives']) == 1
        assert len(d['false_negatives']) == 1
        assert d['false_negatives'][0]['line_number'] == 42
