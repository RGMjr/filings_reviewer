"""Mine image Add-decision nearby_text for keyword-detector recall gaps.

Stateless render-time helper called from `review_unified.stats()`. Takes
the list of rows returned by `db.get_image_add_substrate()` and returns
per-metric n-gram findings that point the operator at phrases to add to
`config/metric_keywords.yaml`.

Mirrors the structure of `src/web/text_pattern_recommendations.py` so a
maintainer working on both surfaces sees parallel code. Constants use the
`IMG_` prefix to avoid confusion with the text-side constants.

Pure function — no DB calls. Unit-testable without mocks.
"""

from __future__ import annotations

import logging
import re
from collections import Counter, defaultdict
from typing import Any

logger = logging.getLogger(__name__)

# --- Constants ---------------------------------------------------------------
# Tighten IMG_MIN_PCT upward if findings contain boilerplate noise.

IMG_MIN_OCCURRENCES: int = 2
IMG_MIN_PCT: float = 10.0
IMG_TOP_N_PER_METRIC: int = 5
IMG_NGRAM_SIZES: tuple[int, ...] = (2, 3, 4)
IMG_MAX_SAMPLE_IMAGES: int = 3

# Copied from scripts/analyze_text_decision_patterns.py — scripts/ is not on
# the src import path so the list is duplicated here rather than imported.
_IMG_STOPWORDS: frozenset[str] = frozenset(
    """
    a an and any as at be been being but by can could did do does each
    either few for from had has have having he her here him his how i if
    in into is it its just may me might more most must my no nor not now
    of off on only or our out over per s shall she should so some such
    t than that the their them then there these they this those through
    to too under until up upon us used we were what when where whether
    which while who whom why will with within without would you your
    company customer customers data financial fiscal include including
    information measure metric metrics period periods quarter quarters
    revenue revenues number percent total
    """.split()
)

_TOKEN_RE = re.compile(r"[a-z][a-z0-9_]+")


def _tokenize(text: str | None, extra_stopwords: set[str] | None = None) -> list[str]:
    if not text:
        return []
    tokens = _TOKEN_RE.findall(text.lower())
    blocked = _IMG_STOPWORDS | (extra_stopwords or set())
    return [t for t in tokens if len(t) >= 3 and t not in blocked]


def _ngrams(tokens: list[str], n: int) -> list[str]:
    if len(tokens) < n:
        return []
    return [" ".join(tokens[i : i + n]) for i in range(len(tokens) - n + 1)]


def _load_metric_keyword_tokens() -> dict[str, set[str]]:
    """Per-metric token blocklist derived from config/metric_keywords.yaml."""
    try:
        from src.shared.keyword_config import get_metric_keywords

        keywords = get_metric_keywords()
    except Exception:  # noqa: BLE001
        return {}

    out: dict[str, set[str]] = {}
    for metric_id, patterns in keywords.items():
        toks: set[str] = set()
        for pat in patterns or []:
            for t in _TOKEN_RE.findall((pat or "").lower()):
                if len(t) >= 3:
                    toks.add(t)
        out[metric_id] = toks
    return out


def compute_image_add_findings(
    rows: list[dict[str, Any]],
    *,
    min_occurrences: int = IMG_MIN_OCCURRENCES,
    min_pct: float = IMG_MIN_PCT,
    top_n_per_metric: int = IMG_TOP_N_PER_METRIC,
    ngram_sizes: tuple[int, ...] = IMG_NGRAM_SIZES,
) -> list[dict[str, Any]]:
    """Mine nearby_text n-grams per metric for Add decisions.

    Returns one dict per metric ranked by add_count DESC::

        {
            "metric_id": str,
            "add_count": int,
            "image_count": int,
            "min_occurrences": int,
            "top_phrases": [
                {"phrase": str, "count": int, "pct_of_adds": float}, ...
            ],
            "sample_images": [{"img_id": str, "filing_id": int}, ...],
        }

    Empty input returns []. Rows without nearby_text contribute to
    add_count / image_count / sample_images but not to phrase mining.
    """
    if not rows:
        return []

    metric_keyword_tokens = _load_metric_keyword_tokens()

    # Group by metric.
    by_metric: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_metric[row["confirmed_metric_id"]].append(row)

    findings: list[dict[str, Any]] = []

    for metric_id, metric_rows in by_metric.items():
        add_count = len(metric_rows)
        image_count = len({r["img_id"] for r in metric_rows})

        # Collect sample images (distinct img_id, stable order via first seen).
        seen_imgs: set[str] = set()
        sample_images: list[dict[str, Any]] = []
        for r in metric_rows:
            img_id = r["img_id"]
            if img_id not in seen_imgs:
                seen_imgs.add(img_id)
                sample_images.append({"img_id": img_id, "filing_id": r["filing_id"]})
            if len(sample_images) >= IMG_MAX_SAMPLE_IMAGES:
                break

        # Mine n-grams from nearby_text.
        extra_stop = metric_keyword_tokens.get(metric_id, set())
        phrase_counter: Counter[str] = Counter()
        for r in metric_rows:
            tokens = _tokenize(r.get("nearby_text"), extra_stop)
            for n in ngram_sizes:
                phrase_counter.update(_ngrams(tokens, n))

        top_phrases: list[dict[str, Any]] = []
        for phrase, count in phrase_counter.most_common():
            pct = 100.0 * count / add_count
            if count < min_occurrences or pct < min_pct:
                continue
            top_phrases.append({"phrase": phrase, "count": count, "pct_of_adds": pct})
            if len(top_phrases) >= top_n_per_metric:
                break

        findings.append(
            {
                "metric_id": metric_id,
                "add_count": add_count,
                "image_count": image_count,
                "min_occurrences": min_occurrences,
                "top_phrases": top_phrases,
                "sample_images": sample_images,
            }
        )

    findings.sort(key=lambda f: f["add_count"], reverse=True)
    return findings
