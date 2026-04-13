"""
Shared feature engineering for the image relevance model.

Single source of truth for feature extraction used by both:
  - scripts/train_image_relevance_model.py  (reads from CSV DictReader rows)
  - scripts/score_image_candidates.py       (reads from DB rows, after normalize_db_row())

Expected row dict keys (common format):
  cohort_confidence    float   heuristic confidence from candidate generation
  cohort_keyword_nearby  int   1 if cohort keyword within ~1500 chars
  keyword_count        int     count of detected keywords
  text_length          int     len(preceding_text)
  preceding_text       str     raw text preceding the image (may be empty)
  has_dimensions       int     1 if both width and height are known
  image_area           float   raw pixel area (width * height, 0 if unknown)
  classification       str     "chart" / "table_image" / "unknown" / etc.
  detection_tier       str     "tier_1_cohort" / "tier_2_large" / etc.
  filename             str     image filename or URL (lowercased in engineer_features)
  source               str     "sec" or "pres"
"""

from __future__ import annotations

import re

import numpy as np

# Filename patterns common in SEC auto-generated chart images.
# e.g. g665122g20q37.jpg, g468383g1r55k94.jpg — letter 'g' prefix followed by digits.
SEC_CHART_FILENAME_RE = re.compile(r"^g\d+", re.IGNORECASE)

# ---------------------------------------------------------------------------
# Semantic category features
# ---------------------------------------------------------------------------
# Each category maps a feature name to a list of domain terms. Counts are
# computed using word-boundary regex so "quarterly" does not count as "quarter"
# and "growth" does not double-count with "grow".
#
# Term selection: validated by cross-validation on 584 training samples.
# Adding noisy categories (customer_terms, revenue_terms, etc.) hurts AP.

SEMANTIC_CATEGORIES: dict[str, list[str]] = {
    "text_cohort_terms": [
        "cohort", "cohorts", "vintage", "vintages",
    ],
    "text_retention_terms": [
        "retention", "churn", "retain", "attrition",
    ],
    "text_unit_econ_terms": [
        "ltv", "cac", "lifetime value", "acquisition cost", "payback", "arpu",
    ],
    "text_temporal_terms": [
        "year", "quarter", "month", "annual", "fiscal", "period",
    ],
    "text_growth_terms": [
        "growth", "increase", "grow", "expanding", "expansion",
    ],
}

# Compile patterns once at module load. For multi-word terms (e.g. "lifetime value")
# the \b anchors apply to the first and last word characters of the phrase.
_CATEGORY_PATTERNS: dict[str, re.Pattern[str]] = {
    category: re.compile(
        r"\b(?:" + "|".join(re.escape(term) for term in terms) + r")\b",
        re.IGNORECASE,
    )
    for category, terms in SEMANTIC_CATEGORIES.items()
}


def count_semantic_terms(text: str | None) -> dict[str, int]:
    """Return per-category match counts for a text string.

    Returns zeros for all categories if text is empty or None.
    """
    if not text:
        return {cat: 0 for cat in SEMANTIC_CATEGORIES}
    return {
        cat: len(pattern.findall(text))
        for cat, pattern in _CATEGORY_PATTERNS.items()
    }


# ---------------------------------------------------------------------------
# Feature names (must stay in sync with the vector built in engineer_features)
# ---------------------------------------------------------------------------

FEATURE_NAMES: list[str] = [
    # --- original 16 features ---
    "cohort_confidence",           # 0
    "cohort_keyword_nearby",       # 1  (strongest signal)
    "keyword_count",               # 2  (strong signal)
    "text_long",                   # 3
    "text_medium",                 # 4
    "text_short",                  # 5
    "has_dimensions",              # 6
    "image_area_clipped",          # 7
    "is_chart_classification",     # 8
    "is_unknown_classification",   # 9
    "is_tier_1",                   # 10
    "is_tier_2",                   # 11
    "filename_has_chart_hint",     # 12
    "is_source_sec",               # 13
    "is_table_image_classification",  # 14
    "log_keyword_count",           # 15
    # --- 5 semantic text features (positions 16-20) ---
    "text_cohort_terms",           # 16
    "text_retention_terms",        # 17
    "text_unit_econ_terms",        # 18
    "text_temporal_terms",         # 19
    "text_growth_terms",           # 20
]


def engineer_features(rows: list[dict]) -> np.ndarray:
    """Convert normalized row dicts to a (N x 21) feature matrix.

    See module docstring for expected key names. Call normalize_db_row() on
    raw DB rows from score_image_candidates.py before passing here.
    """
    X = []
    for r in rows:
        cohort_confidence = float(r.get("cohort_confidence") or 0.0)
        cohort_keyword_nearby = int(r.get("cohort_keyword_nearby") or 0)
        keyword_count = int(r.get("keyword_count") or 0)
        text_length = int(r.get("text_length") or 0)
        has_dimensions = int(r.get("has_dimensions") or 0)
        image_area = float(r.get("image_area") or 0.0)
        # Clip area to reduce outlier influence; 1M px is ~1000x1000
        image_area_clipped = min(image_area, 1_000_000) / 1_000_000

        classification = (r.get("classification") or "").lower()
        is_chart_classification = int(classification == "chart")
        is_unknown_classification = int(classification == "unknown")
        is_table_image_classification = int(classification == "table_image")

        tier = r.get("detection_tier") or ""
        is_tier_1 = int(tier == "tier_1_cohort")
        is_tier_2 = int(tier == "tier_2_large")

        filename = (r.get("filename") or "").lower()
        filename_has_chart_hint = int(
            "chart" in filename
            or "graph" in filename
            or bool(SEC_CHART_FILENAME_RE.match(filename))
        )

        # text_length bucketed: short (<100), medium (100-500), long (>500)
        text_short = int(text_length < 100)
        text_medium = int(100 <= text_length < 500)
        text_long = int(text_length >= 500)

        # Explicit source indicator
        is_source_sec = int((r.get("source") or "").lower() == "sec")

        # Log-transform keyword count: marginal value of extra keywords is sublinear
        log_keyword_count = float(np.log1p(keyword_count))

        # Semantic text features
        semantic = count_semantic_terms(r.get("preceding_text"))

        X.append([
            cohort_confidence,                    # 0
            cohort_keyword_nearby,                # 1
            keyword_count,                        # 2
            text_long,                            # 3
            text_medium,                          # 4
            text_short,                           # 5
            has_dimensions,                       # 6
            image_area_clipped,                   # 7
            is_chart_classification,              # 8
            is_unknown_classification,            # 9
            is_tier_1,                            # 10
            is_tier_2,                            # 11
            filename_has_chart_hint,              # 12
            is_source_sec,                        # 13
            is_table_image_classification,        # 14
            log_keyword_count,                    # 15
            semantic["text_cohort_terms"],        # 16
            semantic["text_retention_terms"],     # 17
            semantic["text_unit_econ_terms"],     # 18
            semantic["text_temporal_terms"],      # 19
            semantic["text_growth_terms"],        # 20
        ])
    return np.array(X, dtype=float)
