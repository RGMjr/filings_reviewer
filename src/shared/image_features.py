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

import logging
import os
import re
import tempfile
import threading
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Cached model loader
# ---------------------------------------------------------------------------

_MODEL_LOCK = threading.Lock()
_MODEL_CACHE: dict[str, Any] = {}  # cache-key → loaded pipeline (or sentinel)
_MODEL_ABSENT: object = object()  # sentinel: model file was not found
# Cached "active run_id" resolved from the latest_run_id pointer. Set once per
# worker per cold start, reused for the worker's lifetime to avoid one R2 GET
# per predict call. Workers naturally rotate on Render deploy / cron run, so
# the staleness window is bounded — see docs/known-issues/gh-391 closure.
_ACTIVE_RUN_ID: str | None = None
_ACTIVE_RUN_ID_RESOLVED = False

DEFAULT_MODEL_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "data"
    / "image_model"
    / "relevance_model.joblib"
)


def _materialize_from_storage(run_id: str) -> Path | None:
    """Ensure the per-run joblib exists locally; return its path or None on failure.

    Uses ``data/image_model/_cache/<run_id>/relevance_model.joblib`` as the
    materialization target. Run-id-keyed filenames sidestep races between
    concurrent gunicorn workers writing the same cache path. Atomic via
    tempfile + os.replace.

    Storage failures (ClientError, EndpointConnectionError, FileNotFoundError)
    are caught and return None — the caller treats that as "model absent" and
    falls back to the heuristic.
    """
    from src.infra.model_storage import get_model_storage, model_key_for_run
    from src.infra.paths import model_cache_dir

    target_dir = model_cache_dir() / "_cache" / run_id
    target = target_dir / "relevance_model.joblib"
    if target.exists():
        return target

    storage = get_model_storage()
    model_key = model_key_for_run(run_id, "relevance_model.joblib")
    try:
        data = storage.get_bytes(model_key)
    except FileNotFoundError:
        logger.warning(
            "Pointer references run_id=%s but %s is missing in storage", run_id, model_key
        )
        return None
    except Exception as exc:  # noqa: BLE001 — boto3 surfaces many exception types
        logger.warning("Failed to fetch %s from storage: %s", model_key, exc)
        return None

    target_dir.mkdir(parents=True, exist_ok=True)
    # Write to a sibling tempfile and rename — concurrent loaders never see a
    # half-written joblib.
    with tempfile.NamedTemporaryFile(
        dir=target_dir, prefix=".relevance_model.", suffix=".joblib.tmp", delete=False
    ) as tmp:
        tmp.write(data)
        tmp_path = Path(tmp.name)
    os.replace(tmp_path, target)
    logger.info("Materialized %s -> %s (%d bytes)", model_key, target, len(data))
    return target


def _resolve_active_run_id() -> str | None:
    """Read latest_run_id from storage; cached for the worker's lifetime.

    First call per worker reads the pointer; subsequent calls return the cached
    value. Reset via :func:`_reset_active_run_id_cache` (tests only). Workers
    rotate on Render deploy / cron run, bounding staleness — see gh-391.
    """
    global _ACTIVE_RUN_ID, _ACTIVE_RUN_ID_RESOLVED
    if _ACTIVE_RUN_ID_RESOLVED:
        return _ACTIVE_RUN_ID

    from src.infra.model_storage import LATEST_POINTER_KEY, get_model_storage

    storage = get_model_storage()
    try:
        run_id: str | None = storage.get_bytes(LATEST_POINTER_KEY).decode("utf-8").strip()
    except FileNotFoundError:
        logger.debug("No %s pointer in storage — falling back to heuristic", LATEST_POINTER_KEY)
        run_id = None
    except Exception as exc:  # noqa: BLE001
        # Don't memoize transient errors — a future call should retry.
        logger.warning("Failed to read %s: %s", LATEST_POINTER_KEY, exc)
        return None

    _ACTIVE_RUN_ID = run_id
    _ACTIVE_RUN_ID_RESOLVED = True
    return run_id


def _reset_active_run_id_cache() -> None:
    """Clear the cached pointer resolution. Tests only."""
    global _ACTIVE_RUN_ID, _ACTIVE_RUN_ID_RESOLVED
    _ACTIVE_RUN_ID = None
    _ACTIVE_RUN_ID_RESOLVED = False


def _load_joblib_into_cache(local_path: Path, cache_key: str) -> Any | None:
    """joblib.load + cache write + sentinel-on-failure. Caller holds _MODEL_LOCK."""
    try:
        import joblib  # optional heavy import; only at prediction time

        pipeline = joblib.load(local_path)
        _MODEL_CACHE[cache_key] = pipeline
        logger.info("Loaded image relevance model from %s", local_path)
        return pipeline
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to load image relevance model from %s: %s", local_path, exc)
        _MODEL_CACHE[cache_key] = _MODEL_ABSENT
        return None


def _load_model(model_path: Path | None = None) -> Any | None:
    """Load (and cache) the sklearn pipeline.

    Resolution order:

    1. Explicit ``model_path`` always loads from local disk (test fixtures
       and ad-hoc CLI use this path).
    2. With ``R2_BUCKET`` set, read the ``latest_run_id.txt`` pointer from
       storage, materialize the per-run joblib to
       ``data/image_model/_cache/<run_id>/relevance_model.joblib``, load.
    3. Otherwise fall back to ``DEFAULT_MODEL_PATH`` on local disk
       (pre-gh-391 behavior, dev mode).

    Returns the fitted pipeline, or None if the model is absent or fails to
    load — callers fall back to the heuristic. Cached per resolved key so
    subsequent calls are free of I/O.
    """
    use_storage = model_path is None and os.environ.get("R2_BUCKET") is not None

    if use_storage:
        run_id = _resolve_active_run_id()
        if run_id is None:
            return None
        cache_key = f"r2:{run_id}"
        with _MODEL_LOCK:
            if cache_key in _MODEL_CACHE:
                cached = _MODEL_CACHE[cache_key]
                return None if cached is _MODEL_ABSENT else cached
            local_path = _materialize_from_storage(run_id)
            if local_path is None:
                _MODEL_CACHE[cache_key] = _MODEL_ABSENT
                return None
            return _load_joblib_into_cache(local_path, cache_key)

    resolved = str((model_path or DEFAULT_MODEL_PATH).resolve())
    with _MODEL_LOCK:
        if resolved in _MODEL_CACHE:
            cached = _MODEL_CACHE[resolved]
            return None if cached is _MODEL_ABSENT else cached
        path = Path(resolved)
        if not path.exists():
            logger.debug(
                "Image relevance model not found at %s — falling back to heuristic", resolved
            )
            _MODEL_CACHE[resolved] = _MODEL_ABSENT
            return None
        return _load_joblib_into_cache(path, resolved)


def predict_relevance(features: dict, *, model_path: Path | None = None) -> float | None:
    """Return a predicted relevance score (0–1) for a single image feature dict.

    ``features`` must be in the same format accepted by ``engineer_features``
    (i.e. the keys listed in the module docstring).

    Returns ``None`` when the model is absent or fails — callers should fall
    back to the heuristic relevance score in that case.
    """
    pipeline = _load_model(model_path)
    if pipeline is None:
        return None
    try:
        X = engineer_features([features])
        prob: float = float(pipeline.predict_proba(X)[0, 1])
        return prob
    except Exception as exc:  # noqa: BLE001
        logger.warning("predict_relevance failed: %s", exc)
        return None


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
        "cohort",
        "cohorts",
        "vintage",
        "vintages",
    ],
    "text_retention_terms": [
        "retention",
        "churn",
        "retain",
        "attrition",
    ],
    "text_unit_econ_terms": [
        "ltv",
        "cac",
        "lifetime value",
        "acquisition cost",
        "payback",
        "arpu",
    ],
    "text_temporal_terms": [
        "year",
        "quarter",
        "month",
        "annual",
        "fiscal",
        "period",
    ],
    "text_growth_terms": [
        "growth",
        "increase",
        "grow",
        "expanding",
        "expansion",
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
    return {cat: len(pattern.findall(text)) for cat, pattern in _CATEGORY_PATTERNS.items()}


# ---------------------------------------------------------------------------
# Feature names (must stay in sync with the vector built in engineer_features)
# ---------------------------------------------------------------------------

FEATURE_NAMES: list[str] = [
    # --- original 16 features ---
    "cohort_confidence",  # 0
    "cohort_keyword_nearby",  # 1  (strongest signal)
    "keyword_count",  # 2  (strong signal)
    "text_long",  # 3
    "text_medium",  # 4
    "text_short",  # 5
    "has_dimensions",  # 6
    "image_area_clipped",  # 7
    "is_chart_classification",  # 8
    "is_unknown_classification",  # 9
    "is_tier_1",  # 10
    "is_tier_2",  # 11
    "filename_has_chart_hint",  # 12
    "is_source_sec",  # 13
    "is_table_image_classification",  # 14
    "log_keyword_count",  # 15
    # --- 5 semantic text features (positions 16-20) ---
    "text_cohort_terms",  # 16
    "text_retention_terms",  # 17
    "text_unit_econ_terms",  # 18
    "text_temporal_terms",  # 19
    "text_growth_terms",  # 20
]


def derive_detection_tier(
    classification: str | None,
    relevance_score: float | None,
    width: int | None,
    height: int | None,
) -> str:
    """
    Map V2 image attributes to the V1 detection-tier label.

    Logic mirrors `bridge_v2_images_to_review_candidates` so UI tier badges
    render consistently for V2-native rows.
    """
    cls = (classification or "").lower()
    rel = float(relevance_score or 0.0)
    w = int(width or 0)
    h = int(height or 0)
    if cls == "chart" and rel >= 0.6:
        return "tier_1_cohort"
    if cls in ("chart", "table_image") and w >= 300 and h >= 300:
        return "tier_2_large"
    return "tier_3_all"


def v2_row_to_features_input(row: dict) -> dict:
    """
    Convert a raw `v2_image_assets` row to the common feature-dict format
    expected by `engineer_features`.

    V2 does not carry V1's `detected_keywords[]`, `cohort_keyword_nearby`, or
    `image_index`. The model was trained with those features so we synthesize
    sensible proxies (constant 0 for `keyword_count`; `relevance_score >= 0.6`
    for `cohort_keyword_nearby` — matching the V1 bridge heuristic).
    """
    nearby_text = row.get("nearby_text") or ""
    relevance = float(row.get("relevance_score") or 0.0)
    width = row.get("width")
    height = row.get("height")
    has_dimensions = int(width is not None and height is not None)
    image_area = (float(width) * float(height)) if has_dimensions else 0.0

    return {
        "cohort_confidence": relevance,
        "cohort_keyword_nearby": int(relevance >= 0.6),
        "keyword_count": 0,
        "text_length": len(nearby_text),
        "preceding_text": nearby_text,
        "has_dimensions": has_dimensions,
        "image_area": image_area,
        "classification": row.get("classification") or "",
        "detection_tier": derive_detection_tier(
            row.get("classification"), relevance, width, height
        ),
        "filename": row.get("filename") or "",
        "source": "sec",
    }


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

        X.append(
            [
                cohort_confidence,  # 0
                cohort_keyword_nearby,  # 1
                keyword_count,  # 2
                text_long,  # 3
                text_medium,  # 4
                text_short,  # 5
                has_dimensions,  # 6
                image_area_clipped,  # 7
                is_chart_classification,  # 8
                is_unknown_classification,  # 9
                is_tier_1,  # 10
                is_tier_2,  # 11
                filename_has_chart_hint,  # 12
                is_source_sec,  # 13
                is_table_image_classification,  # 14
                log_keyword_count,  # 15
                semantic["text_cohort_terms"],  # 16
                semantic["text_retention_terms"],  # 17
                semantic["text_unit_econ_terms"],  # 18
                semantic["text_temporal_terms"],  # 19
                semantic["text_growth_terms"],  # 20
            ]
        )
    return np.array(X, dtype=float)
