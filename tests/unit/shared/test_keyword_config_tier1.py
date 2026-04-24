"""Tests for get_tier1_keywords_re() and its wiring into OCRExtractionStage."""

import re

import pytest

from src.shared.keyword_config import get_tier1_keywords_re, reload_config


@pytest.fixture(autouse=True)
def _reset_cache():
    reload_config()
    yield
    reload_config()


def test_get_tier1_keywords_re_returns_compiled_pattern():
    re_ = get_tier1_keywords_re()
    assert isinstance(re_, re.Pattern)
    assert re_.flags & re.IGNORECASE


def test_tier1_re_matches_key_phrases():
    """Spot-check representative phrases from several Tier-1 metrics."""
    re_ = get_tier1_keywords_re()
    # cm_net_revenue_retention
    assert re_.search("net revenue retention")
    # cm_gross_revenue_retention
    assert re_.search("gross revenue retention")
    # cm_revenue_by_cohort
    assert re_.search("cohort revenue")
    # cm_customer_acquisition_cost
    assert re_.search("customer acquisition cost")
    # cm_large_customers_period_end — absent from the old hardcoded regex (pre-#83)
    assert re_.search("large customers")
    assert re_.search("enterprise customers")
    # cm_customers_period_end_by_tenure
    assert re_.search("customers by tenure")
    # cm_lifetime_value_per_customer
    assert re_.search("lifetime value")


def test_ocr_stage_tier1_re_sourced_from_keyword_config():
    """OCRExtractionStage.TIER1_KEYWORDS_RE must be built by get_tier1_keywords_re()."""
    from src.extraction_v2.stages.ocr_extraction import OCRExtractionStage

    # Compare compiled pattern strings — more robust than `is` across reload boundaries
    assert OCRExtractionStage.TIER1_KEYWORDS_RE.pattern == get_tier1_keywords_re().pattern
