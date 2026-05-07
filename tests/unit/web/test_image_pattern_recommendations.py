"""Unit tests for src/web/image_pattern_recommendations.py.

All tests are pure Python — no DB or Flask context needed.
"""

from __future__ import annotations

from src.web.image_pattern_recommendations import compute_image_add_findings

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _row(
    metric_id: str,
    img_id: str,
    filing_id: int,
    nearby_text: str | None = "purchase transactions volume quarterly growth",
) -> dict:
    return {
        "confirmed_metric_id": metric_id,
        "img_id": img_id,
        "filing_id": filing_id,
        "nearby_text": nearby_text,
    }


# ---------------------------------------------------------------------------
# Empty-input contract
# ---------------------------------------------------------------------------


def test_empty_input_returns_empty_list():
    assert compute_image_add_findings([]) == []


# ---------------------------------------------------------------------------
# Single-metric basic structure
# ---------------------------------------------------------------------------


def test_single_metric_returns_one_finding():
    rows = [
        _row("cm_active_customers_total", "img-1", 1, "active customers monthly growth"),
        _row("cm_active_customers_total", "img-2", 2, "active customers monthly growth"),
    ]
    findings = compute_image_add_findings(rows)
    assert len(findings) == 1
    f = findings[0]
    assert f["metric_id"] == "cm_active_customers_total"
    assert f["add_count"] == 2
    assert f["image_count"] == 2


def test_finding_contains_min_occurrences():
    rows = [_row("cm_x", "img-1", 1), _row("cm_x", "img-2", 2)]
    findings = compute_image_add_findings(rows)
    assert findings[0]["min_occurrences"] == 2  # default constant echoed


def test_add_count_counts_rows_not_distinct_images():
    """Same img_id appearing twice (two different reviewers) → add_count 2."""
    rows = [
        _row("cm_x", "img-1", 1),
        _row("cm_x", "img-1", 1),  # duplicate img_id
    ]
    findings = compute_image_add_findings(rows)
    assert findings[0]["add_count"] == 2
    assert findings[0]["image_count"] == 1  # one distinct image


# ---------------------------------------------------------------------------
# N-gram threshold
# ---------------------------------------------------------------------------


def test_phrase_below_min_occurrences_excluded():
    """A phrase appearing only once (below min_occurrences=2) is excluded."""
    rows = [
        _row("cm_x", "img-1", 1, "unique phrase only here"),
        _row("cm_x", "img-2", 2, "completely different text about orders"),
    ]
    findings = compute_image_add_findings(rows, min_occurrences=2)
    # "unique phrase" appears in 1 row → excluded
    phrases = [p["phrase"] for p in findings[0]["top_phrases"]]
    assert "unique phrase" not in phrases


def test_phrase_meeting_threshold_included():
    """A bigram appearing in all rows (100%) is included."""
    rows = [
        _row("cm_x", "img-1", 1, "purchase transactions quarterly"),
        _row("cm_x", "img-2", 2, "purchase transactions quarterly"),
        _row("cm_x", "img-3", 3, "purchase transactions quarterly"),
    ]
    findings = compute_image_add_findings(rows)
    phrases = [p["phrase"] for p in findings[0]["top_phrases"]]
    assert "purchase transactions" in phrases


def test_pct_threshold_filters_rare_phrases():
    """A phrase appearing in 1/10 rows (10%) is at the edge; below 10% excluded."""
    rows = [_row("cm_x", f"img-{i}", i, "purchase transactions growth") for i in range(10)]
    # Replace one row's text so "purchase transactions" still appears in 9/10 (90%)
    # but introduce a phrase appearing in only 1 row → below 10% threshold on min_pct>10
    rows[9] = _row("cm_x", "img-9", 9, "rare phrase zebra")
    findings = compute_image_add_findings(rows, min_pct=15.0)
    phrases = [p["phrase"] for p in findings[0]["top_phrases"]]
    assert "rare phrase" not in phrases


# ---------------------------------------------------------------------------
# Stopword suppression
# ---------------------------------------------------------------------------


def test_stopwords_suppressed():
    """Common stopwords don't appear as phrase tokens."""
    rows = [
        _row("cm_x", "img-1", 1, "for the period ended quarterly revenue"),
        _row("cm_x", "img-2", 2, "for the period ended quarterly revenue"),
    ]
    findings = compute_image_add_findings(rows)
    all_phrase_text = " ".join(p["phrase"] for p in findings[0]["top_phrases"])
    # "for", "the" are stopwords — should not appear as tokens
    assert " for " not in f" {all_phrase_text} "
    assert " the " not in f" {all_phrase_text} "


# ---------------------------------------------------------------------------
# Sample-image cap
# ---------------------------------------------------------------------------


def test_sample_images_capped():
    """sample_images is capped at IMG_MAX_SAMPLE_IMAGES (default 3)."""
    rows = [_row("cm_x", f"img-{i}", i) for i in range(10)]
    findings = compute_image_add_findings(rows)
    assert len(findings[0]["sample_images"]) <= 3


def test_sample_images_distinct_img_ids():
    """sample_images contains distinct img_ids."""
    rows = [_row("cm_x", "img-1", 1)] * 5  # same img_id repeated
    findings = compute_image_add_findings(rows)
    img_ids = [s["img_id"] for s in findings[0]["sample_images"]]
    assert len(img_ids) == len(set(img_ids))


# ---------------------------------------------------------------------------
# Multi-metric ordering
# ---------------------------------------------------------------------------


def test_findings_sorted_by_add_count_desc():
    """Metrics with more adds appear first."""
    rows = [_row("cm_low", f"img-low-{i}", i) for i in range(2)] + [
        _row("cm_high", f"img-high-{i}", i) for i in range(5)
    ]
    findings = compute_image_add_findings(rows)
    assert findings[0]["metric_id"] == "cm_high"
    assert findings[1]["metric_id"] == "cm_low"


# ---------------------------------------------------------------------------
# Rows without nearby_text
# ---------------------------------------------------------------------------


def test_rows_without_nearby_text_contribute_to_count_not_phrases():
    """Rows with None nearby_text count toward add_count but not phrase mining."""
    rows = [
        _row("cm_x", "img-1", 1, None),
        _row("cm_x", "img-2", 2, None),
    ]
    findings = compute_image_add_findings(rows)
    assert findings[0]["add_count"] == 2
    assert findings[0]["top_phrases"] == []
