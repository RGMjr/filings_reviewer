"""Unit tests for src/shared/image_features.py."""

import pytest

from src.shared.image_features import (
    _CATEGORY_PATTERNS,
    FEATURE_NAMES,
    SEMANTIC_CATEGORIES,
    count_semantic_terms,
    derive_detection_tier,
    engineer_features,
    v2_row_to_features_input,
)

# ---------------------------------------------------------------------------
# derive_detection_tier
# ---------------------------------------------------------------------------
# Tier mapping logic previously lived inside bridge_v2_images_to_review_candidates.
# After B4 (bridge retired) the helper is the authoritative source of truth used
# by both the V2 DB projection and the ML scorer feature adapter.


def test_derive_tier_chart_high_relevance_is_tier_1():
    assert derive_detection_tier("chart", 0.7, 100, 100) == "tier_1_cohort"


def test_derive_tier_chart_at_boundary_is_tier_1():
    assert derive_detection_tier("chart", 0.6, 100, 100) == "tier_1_cohort"


def test_derive_tier_chart_below_boundary_large_dims_is_tier_2():
    assert derive_detection_tier("chart", 0.4, 400, 400) == "tier_2_large"


def test_derive_tier_table_image_large_dims_is_tier_2():
    assert derive_detection_tier("table_image", 0.3, 500, 300) == "tier_2_large"


def test_derive_tier_small_chart_is_tier_3():
    assert derive_detection_tier("chart", 0.3, 200, 200) == "tier_3_all"


def test_derive_tier_unknown_classification_is_tier_3():
    assert derive_detection_tier("unknown", 0.2, 100, 100) == "tier_3_all"


def test_derive_tier_table_image_small_dims_is_tier_3():
    assert derive_detection_tier("table_image", 0.4, 100, 100) == "tier_3_all"


def test_derive_tier_handles_nulls():
    assert derive_detection_tier(None, None, None, None) == "tier_3_all"


# ---------------------------------------------------------------------------
# v2_row_to_features_input
# ---------------------------------------------------------------------------


def test_v2_adapter_synthesizes_v1_shape():
    row = {
        "filename": "chart.jpg",
        "nearby_text": "Our cohort retention",
        "classification": "chart",
        "relevance_score": 0.8,
        "width": 600,
        "height": 400,
    }
    features = v2_row_to_features_input(row)
    assert features["cohort_confidence"] == 0.8
    assert features["cohort_keyword_nearby"] == 1  # rel >= 0.6
    assert features["keyword_count"] == 0  # V2 drops detected_keywords
    assert features["text_length"] == len("Our cohort retention")
    assert features["has_dimensions"] == 1
    assert features["image_area"] == 600 * 400
    assert features["classification"] == "chart"
    assert features["detection_tier"] == "tier_1_cohort"
    assert features["filename"] == "chart.jpg"
    assert features["source"] == "sec"


def test_v2_adapter_low_relevance_cohort_keyword_nearby_is_zero():
    row = {
        "filename": "chart.jpg", "classification": "chart",
        "relevance_score": 0.3, "width": 100, "height": 100,
    }
    assert v2_row_to_features_input(row)["cohort_keyword_nearby"] == 0


def test_v2_adapter_handles_missing_fields():
    features = v2_row_to_features_input({})
    assert features["cohort_confidence"] == 0.0
    assert features["has_dimensions"] == 0
    assert features["image_area"] == 0.0
    assert features["filename"] == ""




# ---------------------------------------------------------------------------
# count_semantic_terms
# ---------------------------------------------------------------------------


def test_count_semantic_terms_empty():
    result = count_semantic_terms("")
    assert result == {cat: 0 for cat in SEMANTIC_CATEGORIES}


def test_count_semantic_terms_none():
    result = count_semantic_terms(None)
    assert result == {cat: 0 for cat in SEMANTIC_CATEGORIES}


def test_count_semantic_terms_cohort():
    text = "Our cohort analysis shows cohorts across three vintages"
    result = count_semantic_terms(text)
    assert result["text_cohort_terms"] == 3  # cohort, cohorts, vintages


def test_count_semantic_terms_retention():
    result = count_semantic_terms("Net retention rate improved as churn declined")
    assert result["text_retention_terms"] == 2  # retention, churn


def test_count_semantic_terms_unit_econ():
    result = count_semantic_terms("LTV to CAC ratio reflects strong unit economics")
    assert result["text_unit_econ_terms"] == 2  # ltv, cac


def test_count_semantic_terms_no_substring_false_positive():
    # "quarterly" must not match "quarter"; "growth" must not double-count "grow"
    text = "quarterly results showed underlying growth trajectory"
    result = count_semantic_terms(text)
    # "quarterly" → should NOT match "quarter" (word boundary)
    assert result["text_temporal_terms"] == 0
    # "growth" → matches "growth" term only (1 count), "grow" does not match
    assert result["text_growth_terms"] == 1


def test_count_semantic_terms_case_insensitive():
    result = count_semantic_terms("COHORT retention LTV")
    assert result["text_cohort_terms"] == 1
    assert result["text_retention_terms"] == 1
    assert result["text_unit_econ_terms"] == 1


def test_count_semantic_terms_multiword():
    # "lifetime value" and "acquisition cost" are multi-word terms
    result = count_semantic_terms("lifetime value per customer and acquisition cost")
    assert result["text_unit_econ_terms"] == 2


def test_count_semantic_terms_all_zero_for_irrelevant():
    result = count_semantic_terms("We offer pet food and accessories through our website.")
    for cat in SEMANTIC_CATEGORIES:
        assert result[cat] == 0


# ---------------------------------------------------------------------------
# FEATURE_NAMES
# ---------------------------------------------------------------------------


def test_feature_names_length_matches_vector():
    row = _minimal_row()
    X = engineer_features([row])
    assert X.shape == (1, len(FEATURE_NAMES))


def test_feature_names_has_semantic_entries():
    for cat in SEMANTIC_CATEGORIES:
        assert cat in FEATURE_NAMES


def test_feature_names_count():
    assert len(FEATURE_NAMES) == 21


# ---------------------------------------------------------------------------
# engineer_features
# ---------------------------------------------------------------------------


def _minimal_row() -> dict:
    """A row with all fields at their defaults/zeros."""
    return {
        "cohort_confidence": 0.0,
        "cohort_keyword_nearby": 0,
        "keyword_count": 0,
        "text_length": 0,
        "preceding_text": "",
        "has_dimensions": 0,
        "image_area": 0.0,
        "classification": "",
        "detection_tier": "",
        "filename": "",
        "source": "",
    }


def test_engineer_features_minimal_row():
    row = _minimal_row()
    X = engineer_features([row])
    assert X.shape == (1, 21)
    assert X.dtype == float
    # All semantic features are zero for empty text
    assert X[0, 16] == 0.0  # text_cohort_terms
    assert X[0, 17] == 0.0  # text_retention_terms
    assert X[0, 18] == 0.0  # text_unit_econ_terms
    assert X[0, 19] == 0.0  # text_temporal_terms
    assert X[0, 20] == 0.0  # text_growth_terms


def test_engineer_features_missing_keys():
    """engineer_features must not crash when optional keys are absent."""
    X = engineer_features([{}])
    assert X.shape == (1, 21)


def test_engineer_features_semantic_positions():
    row = _minimal_row()
    row["preceding_text"] = "cohort retention LTV fiscal year growth"
    X = engineer_features([row])
    assert X[0, 16] > 0, "text_cohort_terms at position 16"
    assert X[0, 17] > 0, "text_retention_terms at position 17"
    assert X[0, 18] > 0, "text_unit_econ_terms at position 18"
    assert X[0, 19] > 0, "text_temporal_terms at position 19"
    assert X[0, 20] > 0, "text_growth_terms at position 20"


def test_engineer_features_text_length_buckets():
    short_row = dict(_minimal_row(), text_length=50)
    medium_row = dict(_minimal_row(), text_length=200)
    long_row = dict(_minimal_row(), text_length=600)

    X = engineer_features([short_row, medium_row, long_row])
    feat_idx = {name: i for i, name in enumerate(FEATURE_NAMES)}

    # short: text_short=1, text_medium=0, text_long=0
    assert X[0, feat_idx["text_short"]] == 1.0
    assert X[0, feat_idx["text_medium"]] == 0.0
    assert X[0, feat_idx["text_long"]] == 0.0

    # medium: text_short=0, text_medium=1, text_long=0
    assert X[1, feat_idx["text_short"]] == 0.0
    assert X[1, feat_idx["text_medium"]] == 1.0
    assert X[1, feat_idx["text_long"]] == 0.0

    # long: text_short=0, text_medium=0, text_long=1
    assert X[2, feat_idx["text_short"]] == 0.0
    assert X[2, feat_idx["text_medium"]] == 0.0
    assert X[2, feat_idx["text_long"]] == 1.0


def test_engineer_features_image_area_clipped():
    row = dict(_minimal_row(), has_dimensions=1, image_area=2_000_000.0)
    X = engineer_features([row])
    feat_idx = {name: i for i, name in enumerate(FEATURE_NAMES)}
    # 2M pixels clips to 1M -> 1.0
    assert X[0, feat_idx["image_area_clipped"]] == pytest.approx(1.0)


def test_engineer_features_source_sec():
    sec_row = dict(_minimal_row(), source="sec")
    pres_row = dict(_minimal_row(), source="pres")
    X = engineer_features([sec_row, pres_row])
    feat_idx = {name: i for i, name in enumerate(FEATURE_NAMES)}
    assert X[0, feat_idx["is_source_sec"]] == 1.0
    assert X[1, feat_idx["is_source_sec"]] == 0.0


def test_engineer_features_filename_chart_hint():
    sec_chart = dict(_minimal_row(), filename="g665122g20q37.jpg")
    named_chart = dict(_minimal_row(), filename="customer_chart.png")
    no_hint = dict(_minimal_row(), filename="logo_white.png")
    X = engineer_features([sec_chart, named_chart, no_hint])
    feat_idx = {name: i for i, name in enumerate(FEATURE_NAMES)}
    assert X[0, feat_idx["filename_has_chart_hint"]] == 1.0
    assert X[1, feat_idx["filename_has_chart_hint"]] == 1.0
    assert X[2, feat_idx["filename_has_chart_hint"]] == 0.0


def test_engineer_features_multiple_rows():
    rows = [_minimal_row() for _ in range(5)]
    X = engineer_features(rows)
    assert X.shape == (5, 21)


def test_category_patterns_compiled():
    """All patterns in _CATEGORY_PATTERNS should be compiled regex objects."""
    import re
    for cat, pattern in _CATEGORY_PATTERNS.items():
        assert isinstance(pattern, re.Pattern), f"{cat} pattern not compiled"
