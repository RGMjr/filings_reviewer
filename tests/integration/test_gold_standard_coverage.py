"""
Integration tests for gold standard coverage in candidate generation.

These tests verify that key gold standard values are correctly captured as
review candidates. They serve as regression tests to prevent the stale segment
issue discovered in 2024-12-24 from recurring.

Test Categories:
- Farfetch: "Active Consumers", "Number of Orders" metrics
- Samsara Vision: "Customer A/B/C" revenue concentration
- Keyword Coverage: Verify company-specific terminology is matched

Note: These tests require the gold standard filings to be in the database.
Run `scripts/ingest_golden_set.py` if filings are missing.
"""

import logging
from decimal import Decimal
from pathlib import Path

import pytest

from src.extraction.html_segmenter import HTMLSegmenter
from src.extraction.models import SourceSegment
from src.review import CandidateGenerator
from src.review.config import CandidateGenerationConfig
from src.review.models import ReviewCandidate

logger = logging.getLogger(__name__)


# =============================================================================
# Test Data
# =============================================================================

# Farfetch gold standard key values
FARFETCH_EXPECTED_VALUES = {
    # Active Consumers values
    "1118047": {
        "expected_keyword_pattern": r"active\s+consumer",
        "expected_metric": "cm_active_customers_total",
        "description": "Active Consumers (June 30, 2018)",
    },
    "796297": {
        "expected_keyword_pattern": r"active\s+consumer",
        "expected_metric": "cm_active_customers_total",
        "description": "Active Consumers (June 30, 2017)",
    },
    "935772": {
        "expected_keyword_pattern": r"active\s+consumer",
        "expected_metric": "cm_active_customers_total",
        "description": "Active Consumers (Dec 31, 2017)",
    },
    "651674": {
        "expected_keyword_pattern": r"active\s+consumer",
        "expected_metric": "cm_active_customers_total",
        "description": "Active Consumers (Dec 31, 2016)",
    },
    # Number of Orders values
    "1305297": {
        "expected_keyword_pattern": r"number\s+of\s+order",
        "expected_metric": "cm_transactions_by_cohort",
        "description": "Number of Orders (Dec 31, 2017)",
    },
    "853195": {
        "expected_keyword_pattern": r"number\s+of\s+order",
        "expected_metric": "cm_transactions_by_cohort",
        "description": "Number of Orders (June 30, 2017)",
    },
}

# Samsara Vision gold standard key values
SAMSARA_VISION_EXPECTED_VALUES = {
    "0.399": {  # 39.90%
        "expected_keyword_pattern": r"customer\s+[a-d]",
        "expected_metric": "cm_revenue_concentration",
        "description": "Customer A revenue concentration (39.90%)",
    },
    "0.202": {  # 20.20%
        "expected_keyword_pattern": r"customer\s+[a-d]",
        "expected_metric": "cm_revenue_concentration",
        "description": "Customer C revenue concentration (20.20%)",
    },
}


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def gold_standard_dir() -> Path:
    """Return the path to gold standard data directory."""
    return Path("data/gold_standard")


@pytest.fixture
def farfetch_filing_path(gold_standard_dir: Path) -> str | None:
    """Return path to Farfetch filing."""
    path = Path("data/filings/0001740915/000119312518252315/primary.htm")
    if path.exists():
        return str(path)
    return None


@pytest.fixture
def samsara_vision_filing_path(gold_standard_dir: Path) -> str | None:
    """Return path to Samsara Vision filing."""
    path = gold_standard_dir / "Samsara_Vision_Inc_" / "filing.html"
    if path.exists():
        return str(path)
    return None


@pytest.fixture
def segmenter() -> HTMLSegmenter:
    """Create a segmenter for testing."""
    return HTMLSegmenter()


@pytest.fixture
def generator() -> CandidateGenerator:
    """Create a candidate generator with default config."""
    config = CandidateGenerationConfig()
    return CandidateGenerator(config=config)


# =============================================================================
# Helper Functions
# =============================================================================


def segment_filing(path: str, filing_id: int = 1) -> list[SourceSegment]:
    """Segment a filing and return segments."""
    segmenter = HTMLSegmenter()
    return segmenter.segment_filing(filing_id, path)


def generate_candidates(
    segments: list[SourceSegment],
    filing_id: int = 1,
    company_id: int = 1,
) -> list[ReviewCandidate]:
    """Generate candidates from segments.

    Note: CandidateGenerator expects dict segments (from database),
    not SourceSegment objects. We convert them here.
    """
    config = CandidateGenerationConfig()
    generator = CandidateGenerator(config=config)

    # Convert SourceSegment objects to dicts as expected by the generator
    segment_dicts = [seg.to_dict() for seg in segments]

    return generator.generate_for_filing(
        filing_id=filing_id,
        company_id=company_id,
        segments=segment_dicts,
    )


def find_candidate_by_value(
    candidates: list[ReviewCandidate],
    target_value: str,
    tolerance: float = 0.01,
) -> ReviewCandidate | None:
    """Find a candidate matching a target value (with tolerance for percentages)."""
    target = Decimal(target_value)
    for candidate in candidates:
        if candidate.parsed_value is None:
            continue
        diff = abs(candidate.parsed_value - target)
        # Allow for floating point differences
        if diff < Decimal(str(tolerance)) * max(abs(target), Decimal("1")):
            return candidate
    return None


def value_in_segments(segments: list[SourceSegment], value: str) -> bool:
    """Check if a value appears in any segment text."""
    for segment in segments:
        if value in segment.raw_text:
            return True
    return False


# =============================================================================
# Farfetch Tests
# =============================================================================


class TestFarfetchGoldStandard:
    """Tests for Farfetch filing gold standard coverage."""

    @pytest.mark.skipif(
        not Path("data/filings/0001740915/000119312518252315/primary.htm").exists(),
        reason="Farfetch filing not available"
    )
    def test_segmentation_captures_active_consumers(
        self, farfetch_filing_path: str
    ) -> None:
        """Verify segmenter captures 'Active Consumers' text."""
        segments = segment_filing(farfetch_filing_path)

        # Check that key value is in segments
        assert value_in_segments(segments, "1,118,047"), (
            "Value '1,118,047' not found in segments. "
            "Segmenter may have changed - re-segment the filing."
        )

        # Check for Active Consumers keyword
        found_keyword = any(
            "Active Consumer" in seg.raw_text for seg in segments
        )
        assert found_keyword, (
            "'Active Consumers' not found in any segment. "
            "Check segmenter is capturing relevant content."
        )

    @pytest.mark.skipif(
        not Path("data/filings/0001740915/000119312518252315/primary.htm").exists(),
        reason="Farfetch filing not available"
    )
    def test_candidate_generation_finds_active_consumers(
        self, farfetch_filing_path: str
    ) -> None:
        """Verify candidate generator finds Active Consumers values."""
        segments = segment_filing(farfetch_filing_path)
        candidates = generate_candidates(segments)

        # Must generate some candidates
        assert len(candidates) > 0, "No candidates generated for Farfetch"

        # Check for the key value
        candidate = find_candidate_by_value(candidates, "1118047")
        assert candidate is not None, (
            "Value 1,118,047 (Active Consumers) not found as candidate. "
            "Keywords may need updating."
        )

        # Verify it's matched to correct metric
        assert candidate.suggested_metric_id == "cm_active_customers_total", (
            f"Expected cm_active_customers_total but got {candidate.suggested_metric_id}. "
            "Check keyword patterns."
        )

    @pytest.mark.skipif(
        not Path("data/filings/0001740915/000119312518252315/primary.htm").exists(),
        reason="Farfetch filing not available"
    )
    def test_candidate_generation_finds_number_of_orders(
        self, farfetch_filing_path: str
    ) -> None:
        """Verify candidate generator finds Number of Orders values."""
        segments = segment_filing(farfetch_filing_path)
        candidates = generate_candidates(segments)

        # Check for the key value
        candidate = find_candidate_by_value(candidates, "1305297")
        assert candidate is not None, (
            "Value 1,305,297 (Number of Orders) not found as candidate. "
            "Keywords may need updating."
        )

        # Verify it's matched to transaction metric
        assert candidate.suggested_metric_id == "cm_transactions_by_cohort", (
            f"Expected cm_transactions_by_cohort but got {candidate.suggested_metric_id}. "
            "Check keyword patterns."
        )

    @pytest.mark.skipif(
        not Path("data/filings/0001740915/000119312518252315/primary.htm").exists(),
        reason="Farfetch filing not available"
    )
    def test_farfetch_gold_standard_coverage(
        self, farfetch_filing_path: str
    ) -> None:
        """Verify all key Farfetch gold standard values are captured."""
        segments = segment_filing(farfetch_filing_path)
        candidates = generate_candidates(segments)

        found_values = []
        missing_values = []

        for value, expected in FARFETCH_EXPECTED_VALUES.items():
            candidate = find_candidate_by_value(candidates, value)
            if candidate:
                found_values.append(value)
            else:
                missing_values.append(f"{value} ({expected['description']})")

        coverage = len(found_values) / len(FARFETCH_EXPECTED_VALUES) * 100

        # Require at least 80% coverage
        assert coverage >= 80, (
            f"Gold standard coverage too low: {coverage:.1f}%. "
            f"Missing values: {missing_values}"
        )

        logger.info(
            f"Farfetch gold standard coverage: {coverage:.1f}% "
            f"({len(found_values)}/{len(FARFETCH_EXPECTED_VALUES)})"
        )


# =============================================================================
# Samsara Vision Tests
# =============================================================================


class TestSamsaraVisionGoldStandard:
    """Tests for Samsara Vision filing gold standard coverage."""

    @pytest.mark.skipif(
        not Path("data/gold_standard/Samsara_Vision_Inc_/filing.html").exists(),
        reason="Samsara Vision filing not available"
    )
    def test_segmentation_captures_customer_table(
        self, samsara_vision_filing_path: str
    ) -> None:
        """Verify segmenter captures customer concentration table."""
        segments = segment_filing(samsara_vision_filing_path)

        # Check that percentage values are in segments
        found_39 = value_in_segments(segments, "39.90%")
        found_20 = value_in_segments(segments, "20.20%")

        assert found_39, (
            "Value '39.90%' not found in segments. "
            "Check segmenter table handling."
        )
        assert found_20, (
            "Value '20.20%' not found in segments. "
            "Check segmenter table handling."
        )

    @pytest.mark.skipif(
        not Path("data/gold_standard/Samsara_Vision_Inc_/filing.html").exists(),
        reason="Samsara Vision filing not available"
    )
    def test_candidate_generation_finds_customer_concentration(
        self, samsara_vision_filing_path: str
    ) -> None:
        """Verify candidate generator finds Customer A/B/C values."""
        segments = segment_filing(samsara_vision_filing_path)
        candidates = generate_candidates(segments)

        # Must generate some candidates
        assert len(candidates) > 0, "No candidates generated for Samsara Vision"

        # Check for Customer A value (39.90%)
        candidate = find_candidate_by_value(candidates, "0.399", tolerance=0.01)
        assert candidate is not None, (
            "Value 39.90% (Customer A) not found as candidate. "
            "Customer A/B/C/D keywords may need updating."
        )

        # Verify it's matched to revenue concentration
        assert candidate.suggested_metric_id == "cm_revenue_concentration", (
            f"Expected cm_revenue_concentration but got {candidate.suggested_metric_id}. "
            "Check keyword patterns."
        )

    @pytest.mark.skipif(
        not Path("data/gold_standard/Samsara_Vision_Inc_/filing.html").exists(),
        reason="Samsara Vision filing not available"
    )
    def test_samsara_vision_gold_standard_coverage(
        self, samsara_vision_filing_path: str
    ) -> None:
        """Verify all key Samsara Vision gold standard values are captured."""
        segments = segment_filing(samsara_vision_filing_path)
        candidates = generate_candidates(segments)

        found_values = []
        missing_values = []

        for value, expected in SAMSARA_VISION_EXPECTED_VALUES.items():
            candidate = find_candidate_by_value(candidates, value, tolerance=0.01)
            if candidate:
                found_values.append(value)
            else:
                missing_values.append(f"{value} ({expected['description']})")

        coverage = len(found_values) / len(SAMSARA_VISION_EXPECTED_VALUES) * 100

        # Require 100% coverage for Samsara Vision (it's a small gold standard)
        assert coverage == 100, (
            f"Gold standard coverage incomplete: {coverage:.1f}%. "
            f"Missing values: {missing_values}"
        )

        logger.info(
            f"Samsara Vision gold standard coverage: {coverage:.1f}% "
            f"({len(found_values)}/{len(SAMSARA_VISION_EXPECTED_VALUES)})"
        )


# =============================================================================
# Keyword Pattern Tests
# =============================================================================


class TestKeywordPatterns:
    """Tests for company-specific keyword patterns."""

    def test_active_consumers_keyword_exists(self) -> None:
        """Verify 'active consumers' keyword is in metric patterns."""
        from src.extraction.keyword_config import get_metric_keywords

        keywords = get_metric_keywords().get("cm_active_customers_total", [])

        # Check for consumer patterns
        consumer_patterns = [k for k in keywords if "consumer" in k.lower()]
        assert len(consumer_patterns) > 0, (
            "'consumer' pattern not found in cm_active_customers_total keywords. "
            "Add r'\\bactive\\s+consumers?\\b' to metric_classifier.py"
        )

    def test_number_of_orders_keyword_exists(self) -> None:
        """Verify 'number of orders' keyword is in metric patterns."""
        from src.extraction.keyword_config import get_metric_keywords

        keywords = get_metric_keywords().get("cm_transactions_by_cohort", [])

        # Check for orders patterns
        orders_patterns = [k for k in keywords if "order" in k.lower()]
        assert len(orders_patterns) > 0, (
            "'orders' pattern not found in cm_transactions_by_cohort keywords. "
            "Add r'\\bnumber\\s+of\\s+orders?\\b' to metric_classifier.py"
        )

    def test_customer_abc_keyword_exists(self) -> None:
        """Verify 'Customer A/B/C' keyword is in revenue concentration patterns."""
        from src.extraction.keyword_config import get_metric_keywords

        keywords = get_metric_keywords().get("cm_revenue_concentration", [])

        # Check for Customer A/B/C pattern
        customer_patterns = [
            k for k in keywords
            if "customer" in k.lower() and ("[a-d]" in k.lower() or "[A-D]" in k)
        ]
        assert len(customer_patterns) > 0, (
            "'Customer A/B/C' pattern not found in cm_revenue_concentration keywords. "
            "Add r'\\bcustomer\\s+[A-D]\\b' to metric_classifier.py"
        )


# =============================================================================
# Regression Tests
# =============================================================================


class TestSegmentationRegression:
    """Tests to prevent segmentation regression (stale segment issue)."""

    @pytest.mark.skipif(
        not Path("data/filings/0001740915/000119312518252315/primary.htm").exists(),
        reason="Farfetch filing not available"
    )
    def test_farfetch_segment_count_reasonable(
        self, farfetch_filing_path: str
    ) -> None:
        """Verify Farfetch produces reasonable segment count (not stale)."""
        segments = segment_filing(farfetch_filing_path)

        # The stale segments had only 80 segments
        # Current segmenter produces ~89,000 segments
        # We require at least 1,000 to detect stale data
        assert len(segments) >= 1000, (
            f"Farfetch produced only {len(segments)} segments. "
            "This suggests stale segments or segmenter regression. "
            "Expected 10,000+ segments for this filing."
        )

    @pytest.mark.skipif(
        not Path("data/gold_standard/Samsara_Vision_Inc_/filing.html").exists(),
        reason="Samsara Vision filing not available"
    )
    def test_samsara_vision_segment_count_reasonable(
        self, samsara_vision_filing_path: str
    ) -> None:
        """Verify Samsara Vision produces reasonable segment count."""
        segments = segment_filing(samsara_vision_filing_path)

        # The stale segments had only 71 segments
        # Current segmenter produces ~1,800 segments
        assert len(segments) >= 500, (
            f"Samsara Vision produced only {len(segments)} segments. "
            "This suggests stale segments or segmenter regression. "
            "Expected 1,000+ segments for this filing."
        )
