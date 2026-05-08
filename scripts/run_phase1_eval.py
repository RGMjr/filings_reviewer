"""Phase-1 dual-corpus smoke eval for the LLM presence classifier.

Runs the classifier across 10 filings drawn from two corpora (gold +
reviewed) and writes a diffable CSV plus a per-metric/run summary JSON.

This is the cheap, fast, qualitative pre-flight that runs *before* paying
for the larger held-out + reviewed-corpus quantitative eval. It surfaces
prompt failures, parse errors, and disagreement patterns. The Tier-1
zero-tolerance gate is unchanged by this script.

Paths
-----

  Path B (default, ``--path direct``)
      Loads gold-CSV quotes (gold corpus) or paraphrase-eligible
      v2_segments (reviewed corpus) and calls
      ``PresenceClassifierClient.classify_segment`` directly. Mirrors the
      orchestration in ``scripts/calibrate_llm_thresholds.run_sweep``.
      Cheap; bypasses the V2 pipeline's keyword/paraphrase merging.

  Path A (``--path pipeline``)
      Runs the full V2 pipeline per filing with
      ``enable_llm_presence_classifier=True`` and ``retain_context=True``,
      then reads ``PipelineResult.context.llm_presence_signals`` for
      classifier scores and ``PipelineResult.context.candidates`` for the
      keyword baseline.  Requires both ``ANTHROPIC_API_KEY`` and
      ``DATABASE_URL`` (gold filings need the DB for HTML path resolution).
      ``--dry-run`` is not supported for Path A.

Smoke-test exit codes
---------------------

  0 — all criteria pass
  1 — hard failure: prompt/parse errors, or a metric breached criterion #3
  2 — preconditions not met (missing API key, missing DB for reviewed
      corpus, gold corpus didn't cover required metrics, ``--path
      pipeline`` selected)

Cost
----

Real-API runs cost approximately ``$0.20-0.40 per filing`` on Haiku
(Sonnet fallback raises this); 10 filings ≈ ``$2-4`` per run. **Do NOT
call this from any pytest test** — mock the classifier.

Determinism
-----------

``run_id`` defaults to a UTC timestamp so re-runs don't overwrite prior
outputs. Re-runs with the same prompts, thresholds, gold/reviewed
selections, and ``--run-id`` produce byte-identical CSVs in dry-run
mode. The classifier itself is non-deterministic at the model level, so
byte-identical output is not guaranteed across separate live-API runs.

Gold-negative caveat
--------------------

Gold "negatives" (no row in ``golden_set_*.csv`` for a (filing, metric)
pair) are weakly-true negatives — the gold set is incomplete. Per-metric
precision against gold in ``summary.json`` is biased high by definition.
The summary annotates this for downstream readers.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import random
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Paths and constants
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[1]
GOLD_CSV = REPO_ROOT / "data" / "gold_standard" / "golden_set_260408.csv"
SPLIT_FILE = REPO_ROOT / "data" / "gold_standard" / "split_v1.json"
DEFAULT_OUT_DIR = REPO_ROOT / "data" / "eval"
RECALL_AUG_FILE = REPO_ROOT / "config" / "llm_classifier" / "recall_augmentation.yaml"

# The plan's named "must-cover" Tier-1 set in the gold corpus. Coverage is
# enforced only for the subset that is also enrolled (has a prompt YAML);
# unenrolled members produce a warning, not a hard fail (the classifier
# physically cannot score them).
PLAN_REQUIRED_GOLD_METRICS = (
    "cm_net_revenue_retention",
    "cm_revenue_concentration",
    "cm_revenue_by_cohort",
    "cm_customer_acquisition_cost",
    "cm_large_customers_period_end",
)

# Reviewed-corpus over-representation hint. Coverage is reported, not gated.
PLAN_PREFERRED_REVIEWED_METRICS = (
    "cm_customer_retention_rate",
    "cm_lifetime_value_per_customer",
)

# Smoke-test thresholds (criteria #2 and #3 from the worker prompt).
DISAGREEMENT_SAMPLE_THRESHOLD = 30
CATASTROPHIC_REGRESSION_DELTA = 0.20  # 20pt recall drop
CATASTROPHIC_REGRESSION_MIN_FILINGS = 3

# Caps on segments scored per reviewed-corpus filing, to keep the smoke
# test cheap. Gold corpus has its own natural cap (gold quotes per filing
# are limited).
MAX_REVIEWED_SEGMENTS_PER_FILING = 30

logger = logging.getLogger("run_phase1_eval")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FilingSelection:
    corpus: str  # "gold" or "reviewed"
    filing_url: str
    filing_id: int | None  # None for gold filings without DB lookup
    issuer_key: str
    company: str | None = None


@dataclass
class EvalRow:
    run_id: str
    run_started_at: str
    run_finished_at: str
    corpus: str
    filing_url: str
    filing_id: int | None
    issuer_key: str
    metric_id: str
    ground_truth: bool | None  # None = label unknown
    classifier_present: bool | None
    classifier_score: float | None
    classifier_model: str | None
    classifier_sonnet_fallback: bool | None
    keyword_present: bool | None
    agreement: str  # "agree" | "disagree" | "n/a"
    classification: str  # "TP" | "FP" | "FN" | "TN" | "skipped"
    prompt_version: str | None
    section_type: str | None
    notes: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "run_started_at": self.run_started_at,
            "run_finished_at": self.run_finished_at,
            "corpus": self.corpus,
            "filing_url": self.filing_url,
            "filing_id": self.filing_id if self.filing_id is not None else "",
            "issuer_key": self.issuer_key,
            "metric_id": self.metric_id,
            "ground_truth": _bool_str(self.ground_truth),
            "classifier_present": _bool_str(self.classifier_present),
            "classifier_score": (
                f"{self.classifier_score:.4f}" if self.classifier_score is not None else ""
            ),
            "classifier_model": self.classifier_model or "",
            "classifier_sonnet_fallback": _bool_str(self.classifier_sonnet_fallback),
            "keyword_present": _bool_str(self.keyword_present),
            "agreement": self.agreement,
            "classification": self.classification,
            "prompt_version": self.prompt_version or "",
            "section_type": self.section_type or "",
            "notes": self.notes,
        }


CSV_FIELDS = (
    "run_id",
    "run_started_at",
    "run_finished_at",
    "corpus",
    "filing_url",
    "filing_id",
    "issuer_key",
    "metric_id",
    "ground_truth",
    "classifier_present",
    "classifier_score",
    "classifier_model",
    "classifier_sonnet_fallback",
    "keyword_present",
    "agreement",
    "classification",
    "prompt_version",
    "section_type",
    "notes",
)


@dataclass
class SmokeResult:
    prompt_errors: list[dict[str, Any]] = field(default_factory=list)
    catastrophic_metrics: list[dict[str, Any]] = field(default_factory=list)
    disagreements_total: int = 0
    stratified_30_sample: list[dict[str, Any]] = field(default_factory=list)
    pass_prompt_errors: bool = True
    pass_disagreement_count: bool = True
    pass_catastrophic_regression: bool = True

    @property
    def has_hard_failure(self) -> bool:
        return not (self.pass_prompt_errors and self.pass_catastrophic_regression)


def _bool_str(value: bool | None) -> str:
    if value is None:
        return ""
    return "true" if value else "false"


# ---------------------------------------------------------------------------
# Configuration discovery
# ---------------------------------------------------------------------------


def _load_recall_augmentation() -> tuple[list[str], list[str]]:
    """Return ``(enrolled_metrics, section_whitelist)`` from recall_augmentation.yaml."""
    import yaml

    raw = yaml.safe_load(RECALL_AUG_FILE.read_text())
    enrolled = list(raw.get("enrolled_metrics") or [])
    sections = list(raw.get("section_whitelist") or [])
    return enrolled, sections


def discover_required_gold_metrics(enrolled: list[str]) -> tuple[list[str], list[str]]:
    """Split the plan's required-coverage list into ``(scoreable, skipped)``.

    Scoreable = enrolled metrics (the classifier has a prompt YAML).
    Skipped = named in the plan but not enrolled — the classifier
    physically cannot score them.
    """
    enrolled_set = set(enrolled)
    scoreable = [m for m in PLAN_REQUIRED_GOLD_METRICS if m in enrolled_set]
    skipped = [m for m in PLAN_REQUIRED_GOLD_METRICS if m not in enrolled_set]
    return scoreable, skipped


# ---------------------------------------------------------------------------
# Gold-CSV reading (mirrors calibrate_llm_thresholds primitives)
# ---------------------------------------------------------------------------


import re  # noqa: E402

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_LETTER_RE = re.compile(r"[A-Za-z]")
_MIN_QUOTE_PROSE_CHARS = 50
_MAX_QUOTE_PROSE_CHARS = 1500


def _extract_prose(raw: str) -> str:
    if not raw:
        return ""
    no_tags = _HTML_TAG_RE.sub(" ", raw)
    return " ".join(no_tags.split())


def _is_usable_prose(prose: str) -> bool:
    if not prose:
        return False
    if not _LETTER_RE.search(prose):
        return False
    return _MIN_QUOTE_PROSE_CHARS <= len(prose) <= _MAX_QUOTE_PROSE_CHARS


@dataclass(frozen=True)
class _Splits:
    train_urls: frozenset[str]
    test_urls: frozenset[str]
    calibration_urls: frozenset[str]
    issuer_lookup: dict[str, str]
    company_lookup: dict[str, str]


def _load_splits(split_file: Path = SPLIT_FILE) -> _Splits:
    raw = json.loads(split_file.read_text())
    splits = raw["splits"]
    issuer_lookup: dict[str, str] = {}
    company_lookup: dict[str, str] = {}
    for rows in splits.values():
        for r in rows:
            issuer_lookup[r["url"]] = r["issuer_key"]
            company_lookup[r["url"]] = r.get("company") or r["issuer_key"]
    return _Splits(
        train_urls=frozenset(r["url"] for r in splits["train"]),
        test_urls=frozenset(r["url"] for r in splits["test"]),
        calibration_urls=frozenset(r["url"] for r in splits["calibration"]),
        issuer_lookup=issuer_lookup,
        company_lookup=company_lookup,
    )


def _gold_metrics_per_filing(gold_csv: Path, target_urls: frozenset[str]) -> dict[str, set[str]]:
    """Return ``{filing_url: {metric_id, ...}}`` for every gold row."""
    metrics: dict[str, set[str]] = {}
    with gold_csv.open(encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            url = row["Document URL"].strip()
            if url not in target_urls:
                continue
            metric = (row.get("Standard Metric Name") or "").strip()
            if not metric.startswith("cm_"):
                continue
            metrics.setdefault(url, set()).add(metric)
    return metrics


def _gold_quotes_per_filing(gold_csv: Path, target_urls: frozenset[str]) -> dict[str, list[str]]:
    """Return ``{filing_url: [unique_prose, ...]}`` for usable quotes."""
    quotes: dict[str, list[str]] = {url: [] for url in target_urls}
    seen: dict[str, set[str]] = {url: set() for url in target_urls}
    with gold_csv.open(encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            url = row["Document URL"].strip()
            if url not in target_urls:
                continue
            quote = (row.get("Quote/context") or "").strip()
            prose = _extract_prose(quote)
            if not _is_usable_prose(prose):
                continue
            if prose in seen[url]:
                continue
            seen[url].add(prose)
            quotes[url].append(prose)
    return quotes


# ---------------------------------------------------------------------------
# Gold corpus selection
# ---------------------------------------------------------------------------


def select_gold_corpus(
    splits: _Splits,
    gold_metrics: dict[str, set[str]],
    required_metrics: list[str],
    *,
    limit: int = 5,
) -> tuple[list[FilingSelection], list[str]]:
    """Deterministic gold-corpus selection.

    Greedy: pick the filing covering the largest number of still-uncovered
    required metrics; tie-break by URL (deterministic). Prefer test-split
    filings; calibration-split as fallback. Train is excluded — few-shots
    were mined from train.

    Returns ``(filings, missing_required)`` — ``missing_required`` is
    empty on success. Caller decides what to do with a non-empty list.
    """
    eligible_urls = list(splits.test_urls) + [
        u for u in splits.calibration_urls if u not in splits.test_urls
    ]
    test_priority = {u: 0 for u in splits.test_urls}
    for u in splits.calibration_urls:
        test_priority.setdefault(u, 1)

    uncovered = set(required_metrics)
    chosen: list[str] = []
    pool = sorted(eligible_urls, key=lambda u: (test_priority.get(u, 2), u))

    while pool and len(chosen) < limit and uncovered:
        # Greedy: pick the URL whose gold metrics overlap the most with
        # uncovered required metrics. Ties: lowest test_priority (test
        # before calibration), then URL string.
        best_url = None
        best_score = -1
        for url in pool:
            overlap = len(gold_metrics.get(url, set()) & uncovered)
            if overlap > best_score:
                best_score = overlap
                best_url = url
        if best_url is None or best_score == 0:
            break
        chosen.append(best_url)
        pool.remove(best_url)
        uncovered -= gold_metrics.get(best_url, set())

    # Top up to limit with the next test/calibration filings if still under.
    while len(chosen) < limit and pool:
        chosen.append(pool.pop(0))

    selections = [
        FilingSelection(
            corpus="gold",
            filing_url=url,
            filing_id=None,  # gold-only path doesn't need it
            issuer_key=splits.issuer_lookup.get(url, ""),
            company=splits.company_lookup.get(url),
        )
        for url in chosen
    ]
    missing = sorted(uncovered)
    return selections, missing


# ---------------------------------------------------------------------------
# Reviewed corpus selection (DB-backed)
# ---------------------------------------------------------------------------


def select_reviewed_corpus(
    db_url: str,
    *,
    exclude_urls: frozenset[str],
    limit: int = 5,
) -> list[FilingSelection]:
    """Pick the top-N filings by reviewer-decision density on text facts.

    Excludes any filing already in ``exclude_urls`` (typically the
    selected gold filings). Returns deterministic order: count DESC,
    then filing_id ASC.
    """
    import psycopg

    # The column is ``filings.sec_html_url`` (not ``html_url``); aliasing
    # to ``html_url`` keeps the row-unpacking variable name stable below.
    sql = """
        SELECT f.filing_id,
               f.sec_html_url AS html_url,
               c.name AS company_name,
               COUNT(rd.decision_id) AS decision_count
          FROM v2_review_decisions rd
          JOIN v2_metric_facts mf ON mf.fact_id = rd.fact_id
          JOIN filings f ON f.filing_id = mf.filing_id
          JOIN companies c ON c.cik = f.cik
         WHERE mf.source_type = 'text'
         GROUP BY f.filing_id, f.sec_html_url, c.name
         ORDER BY decision_count DESC, f.filing_id ASC
         LIMIT 50
    """
    with psycopg.connect(db_url) as conn, conn.cursor() as cur:
        cur.execute(sql)
        rows = cur.fetchall()

    selections: list[FilingSelection] = []
    for filing_id, html_url, company_name, _count in rows:
        if html_url in exclude_urls:
            continue
        selections.append(
            FilingSelection(
                corpus="reviewed",
                filing_url=html_url or "",
                filing_id=int(filing_id),
                issuer_key="",  # not tracked for reviewed corpus
                company=company_name,
            )
        )
        if len(selections) >= limit:
            break
    return selections


# ---------------------------------------------------------------------------
# Label construction
# ---------------------------------------------------------------------------


def build_gold_labels(
    gold_csv: Path,
    target_urls: frozenset[str],
    metric_ids: list[str],
) -> dict[tuple[str, str], bool]:
    """Per-(filing_url, metric_id) gold label.

    Positive: any row exists for that pair. Negative: no row exists
    (weakly-true negative — gold is incomplete).
    """
    metrics_per_filing = _gold_metrics_per_filing(gold_csv, target_urls)
    labels: dict[tuple[str, str], bool] = {}
    for url in target_urls:
        present_metrics = metrics_per_filing.get(url, set())
        for metric in metric_ids:
            labels[(url, metric)] = metric in present_metrics
    return labels


def build_reviewed_labels(
    db_url: str,
    filing_ids: list[int],
    metric_ids: list[str],
) -> dict[tuple[int, str], bool | None]:
    """Per-(filing_id, metric_id) reviewer label.

    Positive: at least one ``decision='accept'`` on a fact for that pair.
    Negative: at least one ``decision='reject'`` AND no accepts for that pair.
    Unknown (None): no review activity at all for that pair.
    """
    import psycopg

    if not filing_ids:
        return {}

    sql = """
        SELECT mf.filing_id,
               mf.canonical_metric_id,
               BOOL_OR(rd.decision = 'accept') AS any_accept,
               BOOL_OR(rd.decision = 'reject') AS any_reject
          FROM v2_review_decisions rd
          JOIN v2_metric_facts mf ON mf.fact_id = rd.fact_id
         WHERE mf.filing_id = ANY(%(filing_ids)s)
           AND mf.canonical_metric_id = ANY(%(metric_ids)s)
         GROUP BY mf.filing_id, mf.canonical_metric_id
    """
    activity: dict[tuple[int, str], tuple[bool, bool]] = {}
    with psycopg.connect(db_url) as conn, conn.cursor() as cur:
        cur.execute(sql, {"filing_ids": filing_ids, "metric_ids": metric_ids})
        for filing_id, metric_id, any_accept, any_reject in cur.fetchall():
            activity[(int(filing_id), metric_id)] = (bool(any_accept), bool(any_reject))

    labels: dict[tuple[int, str], bool | None] = {}
    for filing_id in filing_ids:
        for metric in metric_ids:
            key = (filing_id, metric)
            entry = activity.get(key)
            if entry is None:
                labels[key] = None  # no review activity
            else:
                any_accept, any_reject = entry
                if any_accept:
                    labels[key] = True
                elif any_reject:
                    labels[key] = False
                else:
                    labels[key] = None
    return labels


# ---------------------------------------------------------------------------
# Keyword baseline (Path B): segments × facts join
# ---------------------------------------------------------------------------


def keyword_baseline_path_b(
    db_url: str,
    filing_ids: list[int],
    metric_ids: list[str],
) -> dict[tuple[int, str], bool]:
    """For each (filing_id, metric_id), True iff a fact exists for the metric."""
    import psycopg

    if not filing_ids:
        return {}

    sql = """
        SELECT mf.filing_id, mf.canonical_metric_id
          FROM v2_metric_facts mf
         WHERE mf.filing_id = ANY(%(filing_ids)s)
           AND mf.canonical_metric_id = ANY(%(metric_ids)s)
         GROUP BY mf.filing_id, mf.canonical_metric_id
    """
    with psycopg.connect(db_url) as conn, conn.cursor() as cur:
        cur.execute(sql, {"filing_ids": filing_ids, "metric_ids": metric_ids})
        present = {(int(f), m) for f, m in cur.fetchall()}

    return {(f, m): (f, m) in present for f in filing_ids for m in metric_ids}


# ---------------------------------------------------------------------------
# v2_segments loader (Path B reviewed corpus)
# ---------------------------------------------------------------------------


def _load_paraphrase_segments(
    db_url: str,
    filing_id: int,
    section_whitelist: list[str],
    *,
    limit: int = MAX_REVIEWED_SEGMENTS_PER_FILING,
) -> list[tuple[str, str, str]]:
    """Return ``[(segment_id, section_type, text), ...]`` capped at ``limit``."""
    import psycopg

    if not section_whitelist:
        return []

    sql = """
        SELECT segment_id::text, section_type, COALESCE(text_content, '')
          FROM v2_segments
         WHERE filing_id = %(filing_id)s
           AND section_type = ANY(%(sections)s)
           AND segment_type IN ('paragraph', 'list', 'definition', 'methodology')
           AND COALESCE(text_content, '') <> ''
         ORDER BY sequence_idx ASC
         LIMIT %(limit)s
    """
    with psycopg.connect(db_url) as conn, conn.cursor() as cur:
        cur.execute(
            sql,
            {
                "filing_id": filing_id,
                "sections": list(section_whitelist),
                "limit": limit,
            },
        )
        rows = cur.fetchall()
    out: list[tuple[str, str, str]] = []
    for seg_id, section_type, text in rows:
        prose = _extract_prose(text)
        if _is_usable_prose(prose):
            out.append((str(seg_id), section_type or "", prose))
    return out


# ---------------------------------------------------------------------------
# Path A helpers: HTML resolution, DB enrichment, pipeline evaluation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _PathAFiling:
    """Filing enriched with DB metadata for Path A (full V2 pipeline) evaluation."""

    selection: FilingSelection
    filing_id: int
    html_storage_path: str | None
    cik: str
    accession_number: str


def _normalize_to_filings_url(url: str) -> str:
    """Normalize a gold-split URL to the form ``filings.sec_html_url`` uses.

    The gold-split file (`data/gold_standard/split_v1.json`) sometimes carries
    a document-filename suffix (e.g. ``.../<accession>/d745413ds1a.htm``);
    the ``filings`` table normalizes to the accession directory
    (e.g. ``.../<accession>/``). Strip a trailing ``.htm`` / ``.html`` filename
    and ensure a trailing slash so we can exact-match the DB column.
    """
    parts = url.rstrip("/").split("/")
    if parts and parts[-1].lower().endswith((".htm", ".html")):
        parts = parts[:-1]
    return "/".join(parts) + "/"


def _enrich_filings_for_path_a(
    filings: list[FilingSelection],
    db_url: str,
) -> list[_PathAFiling]:
    """Query the DB to resolve html_storage_path, cik, and accession_number.

    Gold filings (filing_id=None) are matched by html_url.  Reviewed filings
    are matched by filing_id (already present on FilingSelection).

    Raises RuntimeError if a gold filing's URL isn't found — it means the
    gold corpus and the production DB have diverged.
    """
    import psycopg

    gold = [f for f in filings if f.corpus == "gold"]
    reviewed = [f for f in filings if f.corpus == "reviewed"]
    result: list[_PathAFiling] = []

    with psycopg.connect(db_url) as conn, conn.cursor() as cur:
        if gold:
            # ``filings.sec_html_url`` is the actual column; aliased to
            # ``html_url`` so the unpacking shape below stays stable.
            # Gold split URLs may carry a document filename suffix that the
            # DB doesn't store — normalize before matching.
            gold_db_urls = [_normalize_to_filings_url(f.filing_url) for f in gold]
            cur.execute(
                "SELECT filing_id, sec_html_url AS html_url, html_storage_path, cik, accession_number"
                " FROM filings WHERE sec_html_url = ANY(%s)",
                (gold_db_urls,),
            )
            by_url: dict[str, Any] = {row[1]: row for row in cur.fetchall()}
            for f in gold:
                lookup_url = _normalize_to_filings_url(f.filing_url)
                row = by_url.get(lookup_url)
                if row is None:
                    raise RuntimeError(
                        f"Gold filing not found in DB (sec_html_url={lookup_url!r}, "
                        f"split URL={f.filing_url!r}). "
                        "Corpus and DB have diverged; cannot run --path pipeline."
                    )
                filing_id, _, html_storage_path, cik, accession_number = row
                result.append(
                    _PathAFiling(
                        selection=f,
                        filing_id=int(filing_id),
                        html_storage_path=html_storage_path,
                        cik=cik or "",
                        accession_number=accession_number or "",
                    )
                )

        if reviewed:
            ids = [f.filing_id for f in reviewed if f.filing_id is not None]
            if ids:
                cur.execute(
                    "SELECT filing_id, html_storage_path, cik, accession_number"
                    " FROM filings WHERE filing_id = ANY(%s)",
                    (ids,),
                )
                by_id: dict[int, Any] = {int(row[0]): row for row in cur.fetchall()}
                for f in reviewed:
                    if f.filing_id is None:
                        continue
                    row = by_id.get(f.filing_id)
                    if row is None:
                        continue
                    _, html_storage_path, cik, accession_number = row
                    result.append(
                        _PathAFiling(
                            selection=f,
                            filing_id=f.filing_id,
                            html_storage_path=html_storage_path,
                            cik=cik or "",
                            accession_number=accession_number or "",
                        )
                    )

    return result


def _find_gold_filing_html(company: str, gold_root: Path) -> Path | None:
    """Find a gold-standard cache directory for ``company`` regardless of
    historical naming convention.

    The local ``data/gold_standard/`` cache uses inconsistent slugs across
    filings (some with trailing periods, some without; spaces, commas, and
    periods all variously kept or replaced). This helper does a tolerant
    match: lowercase, strip non-alphanumerics on both the company name and
    each candidate directory name, then exact-match. Returns the path to
    ``filing.html`` inside the matched directory if it exists.
    """
    if not gold_root.is_dir():
        return None
    needle = re.sub(r"[^a-z0-9]", "", company.lower())
    if not needle:
        return None
    for d in gold_root.iterdir():
        if not d.is_dir():
            continue
        slug = re.sub(r"[^a-z0-9]", "", d.name.lower())
        if slug == needle:
            html = d / "filing.html"
            if html.exists():
                return html
    return None


def _resolve_filing_html(paf: _PathAFiling) -> tuple[Path, Path | None]:
    """Resolve a filing's HTML to a local path, downloading from R2 if needed.

    Mirrors batch_v2_extraction.py:204-249 exactly.

    Returns (resolved_path, temp_path):
    - temp_path is set when a NamedTemporaryFile was created; caller must
      delete it after use.
    """
    import os
    import tempfile

    html_path = paf.html_storage_path
    temp_path: Path | None = None

    if html_path and html_path.startswith("filings/"):
        try:
            from src.infra.filing_storage import get_filing_storage

            data = get_filing_storage().get_bytes(html_path)
            tmp = tempfile.NamedTemporaryFile(mode="wb", suffix=".htm", delete=False)
            tmp.write(data)
            tmp.close()
            resolved = Path(tmp.name)
            temp_path = resolved
            logger.info(
                "Path A filing %d: R2 key %s (%d bytes) -> %s",
                paf.filing_id,
                html_path,
                len(data),
                resolved,
            )
            return resolved, temp_path
        except Exception as r2_err:
            logger.warning(
                "Path A filing %d: R2 read failed for %s: %s; falling through to disk",
                paf.filing_id,
                html_path,
                r2_err,
            )
            html_path = None

    if html_path:
        resolved = Path(html_path)
    else:
        if os.environ.get("APP_ENV") == "production":
            raise RuntimeError(
                f"Filing {paf.filing_id}: no html_storage_path; "
                "refusing gold-standard fallback in production"
            )
        company = paf.selection.company or paf.selection.issuer_key
        gold_root = REPO_ROOT / "data" / "gold_standard"
        resolved = _find_gold_filing_html(company, gold_root) or (
            gold_root / company.replace(" ", "_") / "filing.html"
        )
        logger.warning(
            "Path A filing %d: no html_storage_path; falling back to %s",
            paf.filing_id,
            resolved,
        )

    if not resolved.exists():
        raise RuntimeError(f"Filing {paf.filing_id}: HTML not found: {resolved}")

    return resolved, temp_path


def evaluate_filing_pipeline(
    paf: _PathAFiling,
    metric_ids: list[str],
) -> tuple[dict[str, _AggregatedScore], dict[str, bool], list[dict[str, Any]]]:
    """Run the full V2 pipeline on a filing and extract LLM presence signals.

    Returns ``(per_metric_aggregate, kw_present, errors)``.

    ``kw_present[metric_id]`` is True iff CandidateGenerationStage emitted at
    least one candidate for that metric — the keyword baseline for criterion #3.
    """
    from src.extraction_v2.pipeline import PipelineConfig, V2Pipeline

    errors: list[dict[str, Any]] = []
    resolved_path, temp_path = _resolve_filing_html(paf)

    try:
        pipeline_config = PipelineConfig(
            enable_image_extraction=False,
            enable_chart_extraction=False,
            enable_llm_presence_classifier=True,
            retain_context=True,
            # Bump per-segment concurrency for the eval — Anthropic's prompt
            # cache benefits from concurrent reads on the same prefix and
            # the smoke run otherwise serializes hundreds of API calls.
            llm_presence_concurrency=8,
        )
        pipeline = V2Pipeline(config=pipeline_config)
        result = pipeline.process(
            html_path=resolved_path,
            filing_id=paf.filing_id,
            cik=paf.cik,
            accession_number=paf.accession_number,
        )
    except Exception as exc:
        errors.append(
            {
                "filing_url": paf.selection.filing_url,
                "metric_id": None,
                "exception": f"{type(exc).__name__}: {exc}",
                "stage": "pipeline",
            }
        )
        return {}, {}, errors
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink()
            except OSError:
                pass

    if result.context is None:
        errors.append(
            {
                "filing_url": paf.selection.filing_url,
                "metric_id": None,
                "exception": ("PipelineResult.context is None despite retain_context=True"),
                "stage": "pipeline",
            }
        )
        return {}, {}, errors

    # Max-score aggregation per metric across all LLM signals.
    aggregates: dict[str, _AggregatedScore] = {}
    for sig in result.context.llm_presence_signals:
        existing = aggregates.get(sig.metric_id)
        if existing is None or sig.score > existing.score:
            aggregates[sig.metric_id] = _AggregatedScore(
                score=sig.score,
                present=sig.present,
                model=sig.model,
                sonnet_fallback=sig.sonnet_fallback,
                prompt_version=sig.prompt_version,
                section_type=sig.section_type,
            )

    # Backfill metrics not scored (no matching segments / no signals).
    for metric in metric_ids:
        aggregates.setdefault(
            metric,
            _AggregatedScore(
                score=0.0,
                present=False,
                model="(none)",
                sonnet_fallback=False,
                prompt_version="(none)",
                section_type=None,
            ),
        )

    # Keyword baseline: True iff CandidateGenerationStage produced at least
    # one candidate for this metric.
    kw_present = {m: any(c.metric_id == m for c in result.context.candidates) for m in metric_ids}

    return aggregates, kw_present, errors


# ---------------------------------------------------------------------------
# Classifier orchestration (Path B)
# ---------------------------------------------------------------------------


@dataclass
class _AggregatedScore:
    score: float
    present: bool
    model: str
    sonnet_fallback: bool
    prompt_version: str
    section_type: str | None  # for paraphrase-positive segments only


def evaluate_filing_direct(
    filing: FilingSelection,
    metric_ids: list[str],
    client: Any,
    *,
    gold_quotes: list[str] | None = None,
    db_url: str | None = None,
    section_whitelist: list[str] | None = None,
) -> tuple[dict[str, _AggregatedScore], list[dict[str, Any]]]:
    """Run the classifier across one filing's relevant texts.

    For ``corpus='gold'``: ``gold_quotes`` MUST be provided.
    For ``corpus='reviewed'``: ``db_url`` and ``section_whitelist`` MUST be
    provided (segments are loaded from DB).

    Returns ``(per_metric_aggregate, errors)`` — errors are a list of
    ``{"filing_url", "metric_id"|None, "exception", "stage"}`` dicts.
    """
    if filing.corpus == "gold":
        if gold_quotes is None:
            raise ValueError("gold_quotes required for gold corpus")
        texts: list[tuple[str, str | None]] = [(q, None) for q in gold_quotes]
    elif filing.corpus == "reviewed":
        if db_url is None or section_whitelist is None or filing.filing_id is None:
            raise ValueError("db_url + section_whitelist + filing_id required for reviewed")
        loaded = _load_paraphrase_segments(db_url, filing.filing_id, section_whitelist)
        texts = [(text, section_type) for _, section_type, text in loaded]
    else:
        raise ValueError(f"unknown corpus: {filing.corpus}")

    aggregates: dict[str, _AggregatedScore] = {}
    errors: list[dict[str, Any]] = []

    for text, section_type in texts:
        try:
            # ``classify_segment`` returns ``(classifications, token_counts)``
            # since the gh-531 token-threading fix (PR #535). Token totals
            # are discarded here — see follow-up fragment for surfacing them
            # in summary.tokens.
            results, _tokens = client.classify_segment(text, metric_ids)
        except ValueError as exc:  # parse / shape errors — hard fail per criterion #1
            errors.append(
                {
                    "filing_url": filing.filing_url,
                    "metric_id": None,
                    "exception": str(exc),
                    "stage": "classify_segment",
                }
            )
            continue
        except Exception as exc:  # noqa: BLE001 — non-prompt failures: API/network
            errors.append(
                {
                    "filing_url": filing.filing_url,
                    "metric_id": None,
                    "exception": f"{type(exc).__name__}: {exc}",
                    "stage": "classify_segment",
                }
            )
            continue
        for sc in results:
            existing = aggregates.get(sc.metric_id)
            if existing is None or sc.score > existing.score:
                aggregates[sc.metric_id] = _AggregatedScore(
                    score=sc.score,
                    present=sc.present,
                    model=sc.model,
                    sonnet_fallback=sc.sonnet_fallback,
                    prompt_version=sc.prompt_version,
                    section_type=section_type,
                )

    # Backfill metrics that were never scored (no usable texts) with a
    # zero-score, present=False placeholder so the CSV row is emitted.
    for metric in metric_ids:
        aggregates.setdefault(
            metric,
            _AggregatedScore(
                score=0.0,
                present=False,
                model="(none)",
                sonnet_fallback=False,
                prompt_version="(none)",
                section_type=None,
            ),
        )
    return aggregates, errors


# ---------------------------------------------------------------------------
# Smoke-test criteria
# ---------------------------------------------------------------------------


def compute_smoke_criteria(
    rows: list[EvalRow],
    errors: list[dict[str, Any]],
    *,
    rng_seed: int = 42,
) -> SmokeResult:
    """Encode the three pass/fail criteria from the worker prompt."""
    result = SmokeResult()

    # Criterion #1: zero-tolerance on prompt/parse errors.
    parse_errors = [e for e in errors if "Classifier response" in e.get("exception", "")]
    result.prompt_errors = parse_errors
    result.pass_prompt_errors = len(parse_errors) == 0

    # Criterion #2: informational disagreement-count gate (gold corpus only).
    gold_disagreements = [r for r in rows if r.corpus == "gold" and r.agreement == "disagree"]
    result.disagreements_total = len(gold_disagreements)
    if len(gold_disagreements) > DISAGREEMENT_SAMPLE_THRESHOLD:
        result.pass_disagreement_count = False  # informational; doesn't fail run
        result.stratified_30_sample = _stratified_disagreement_sample(
            gold_disagreements, sample_size=DISAGREEMENT_SAMPLE_THRESHOLD, seed=rng_seed
        )

    # Criterion #3: catastrophic per-metric regression (gold corpus only).
    catastrophic = _check_catastrophic_regression(rows)
    result.catastrophic_metrics = catastrophic
    result.pass_catastrophic_regression = len(catastrophic) == 0

    return result


def _stratified_disagreement_sample(
    rows: list[EvalRow], *, sample_size: int, seed: int
) -> list[dict[str, Any]]:
    """Sample up to ``sample_size`` rows stratified across metrics."""
    rng = random.Random(seed)
    by_metric: dict[str, list[EvalRow]] = {}
    for r in rows:
        by_metric.setdefault(r.metric_id, []).append(r)
    metrics = sorted(by_metric)
    for pool in by_metric.values():
        rng.shuffle(pool)
    chosen: list[EvalRow] = []
    while len(chosen) < sample_size and any(by_metric.values()):
        for m in metrics:
            if not by_metric[m]:
                continue
            chosen.append(by_metric[m].pop(0))
            if len(chosen) >= sample_size:
                break
    return [
        {
            "filing_url": r.filing_url,
            "metric_id": r.metric_id,
            "ground_truth": r.ground_truth,
            "classifier_present": r.classifier_present,
            "classifier_score": r.classifier_score,
        }
        for r in chosen
    ]


def _check_catastrophic_regression(rows: list[EvalRow]) -> list[dict[str, Any]]:
    """Per-metric: is classifier recall >20pt below keyword-baseline recall?"""
    by_metric: dict[str, list[EvalRow]] = {}
    for r in rows:
        if r.corpus != "gold":
            continue
        if r.ground_truth is None:
            continue
        by_metric.setdefault(r.metric_id, []).append(r)

    breaches: list[dict[str, Any]] = []
    for metric, metric_rows in by_metric.items():
        if len(metric_rows) < CATASTROPHIC_REGRESSION_MIN_FILINGS:
            continue
        positives = [r for r in metric_rows if r.ground_truth]
        if not positives:
            continue
        # classifier recall on this metric
        clf_recall = sum(1 for r in positives if r.classifier_present) / len(positives)
        # keyword baseline recall on this metric — only count rows where
        # we have a baseline measurement
        kw_positives = [r for r in positives if r.keyword_present is not None]
        if not kw_positives:
            continue
        kw_recall = sum(1 for r in kw_positives if r.keyword_present) / len(kw_positives)
        delta = kw_recall - clf_recall
        if delta > CATASTROPHIC_REGRESSION_DELTA:
            breaches.append(
                {
                    "metric_id": metric,
                    "classifier_recall": round(clf_recall, 4),
                    "keyword_baseline_recall": round(kw_recall, 4),
                    "delta": round(delta, 4),
                    "n_positives": len(positives),
                }
            )
    return breaches


# ---------------------------------------------------------------------------
# Per-metric P/R/F1 aggregation
# ---------------------------------------------------------------------------


def _per_metric_prf(rows: list[EvalRow], corpus: str) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    by_metric: dict[str, list[EvalRow]] = {}
    for r in rows:
        if r.corpus != corpus:
            continue
        if r.ground_truth is None:
            continue
        by_metric.setdefault(r.metric_id, []).append(r)
    for metric, metric_rows in by_metric.items():
        tp = sum(1 for r in metric_rows if r.ground_truth and r.classifier_present)
        fp = sum(1 for r in metric_rows if not r.ground_truth and r.classifier_present)
        fn = sum(1 for r in metric_rows if r.ground_truth and not r.classifier_present)
        precision = tp / (tp + fp) if (tp + fp) > 0 else 1.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
        out[metric] = {
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
            "n": len(metric_rows),
        }
    return out


# ---------------------------------------------------------------------------
# Output writers
# ---------------------------------------------------------------------------


def write_csv(rows: list[EvalRow], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for r in rows:
            writer.writerow(r.as_dict())


def write_summary(summary: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, indent=2, sort_keys=True))


# ---------------------------------------------------------------------------
# Run orchestrator
# ---------------------------------------------------------------------------


def _classify_eval_row(
    *,
    run_id: str,
    run_started_at: str,
    run_finished_at: str,
    filing: FilingSelection,
    metric_id: str,
    ground_truth: bool | None,
    aggregate: _AggregatedScore | None,
    keyword_present: bool | None,
) -> EvalRow:
    classifier_present: bool | None = aggregate.present if aggregate else None
    if ground_truth is None or classifier_present is None:
        agreement = "n/a"
        classification = "skipped"
    elif ground_truth and classifier_present:
        agreement = "agree"
        classification = "TP"
    elif ground_truth and not classifier_present:
        agreement = "disagree"
        classification = "FN"
    elif not ground_truth and classifier_present:
        agreement = "disagree"
        classification = "FP"
    else:
        agreement = "agree"
        classification = "TN"
    return EvalRow(
        run_id=run_id,
        run_started_at=run_started_at,
        run_finished_at=run_finished_at,
        corpus=filing.corpus,
        filing_url=filing.filing_url,
        filing_id=filing.filing_id,
        issuer_key=filing.issuer_key,
        metric_id=metric_id,
        ground_truth=ground_truth,
        classifier_present=classifier_present,
        classifier_score=aggregate.score if aggregate else None,
        classifier_model=aggregate.model if aggregate else None,
        classifier_sonnet_fallback=aggregate.sonnet_fallback if aggregate else None,
        keyword_present=keyword_present,
        agreement=agreement,
        classification=classification,
        prompt_version=aggregate.prompt_version if aggregate else None,
        section_type=aggregate.section_type if aggregate else None,
        notes="",
    )


def run_eval(
    *,
    run_id: str,
    out_dir: Path,
    path_mode: str,
    gold_only: bool,
    reviewed_only: bool,
    limit: int | None,
    dry_run: bool,
    forced_gold_url: str | None = None,
) -> tuple[int, dict[str, Any]]:
    """Execute the eval. Returns (exit_code, summary_dict).

    ``forced_gold_url`` (--filing-url) bypasses the deterministic greedy
    gold corpus selector and forces a single gold filing by its split-JSON
    URL. Reviewed corpus is suppressed when it is set.
    """
    run_started_at = datetime.now(UTC).isoformat()

    if path_mode == "pipeline":
        if dry_run:
            return 2, {
                "error": (
                    "--path pipeline does not support --dry-run. "
                    "Use --path direct for dry-run corpus/label checks."
                ),
                "run_started_at": run_started_at,
            }
        if not os.environ.get("DATABASE_URL"):
            return 2, {
                "error": (
                    "DATABASE_URL is required for --path pipeline "
                    "(gold filings need DB for HTML path resolution)."
                ),
                "run_started_at": run_started_at,
            }
        if not os.environ.get("ANTHROPIC_API_KEY"):
            return 2, {
                "error": "ANTHROPIC_API_KEY is required for --path pipeline.",
                "run_started_at": run_started_at,
            }

    if gold_only and reviewed_only:
        return 2, {"error": "--gold-only and --reviewed-only are mutually exclusive"}

    enrolled, section_whitelist = _load_recall_augmentation()
    scoreable_required, skipped_required = discover_required_gold_metrics(enrolled)
    metric_ids = list(enrolled)  # universe scored by classifier

    splits = _load_splits()

    # ---- Gold corpus ----
    gold_filings: list[FilingSelection] = []
    gold_missing: list[str] = []
    if forced_gold_url and not reviewed_only:
        # --filing-url overrides the deterministic greedy selector. The URL
        # must match a row in split_v1.json (test or calibration only —
        # never train, since few-shots were mined from train).
        eligible = splits.test_urls | splits.calibration_urls
        if forced_gold_url not in eligible:
            return 2, {
                "error": (
                    f"--filing-url {forced_gold_url!r} is not in test or "
                    f"calibration split. Eligible URLs: see split_v1.json. "
                    f"Train-split URLs are deliberately excluded."
                ),
                "run_started_at": run_started_at,
            }
        gold_filings = [
            FilingSelection(
                corpus="gold",
                filing_url=forced_gold_url,
                filing_id=None,
                issuer_key=splits.issuer_lookup.get(forced_gold_url, ""),
                company=splits.company_lookup.get(forced_gold_url),
            )
        ]
        gold_missing = []
        # --filing-url implies single-filing iteration; reviewed corpus is
        # noisy in that mode, suppress it.
        gold_only = True
    elif not reviewed_only:
        eligible = splits.test_urls | splits.calibration_urls
        gold_metrics_per_filing = _gold_metrics_per_filing(GOLD_CSV, eligible)
        gold_filings, gold_missing = select_gold_corpus(
            splits, gold_metrics_per_filing, scoreable_required, limit=limit or 5
        )
        # When the operator deliberately runs a smaller corpus via --limit
        # (validation / iteration), incomplete required-metric coverage is
        # expected and informational. Hard-fail only at the default limit
        # where missing coverage signals real corpus/DB drift.
        if gold_missing and limit is None:
            return 2, {
                "error": (
                    f"Gold corpus selection failed to cover required metrics: "
                    f"{gold_missing}. split_v1 may have evolved; the eval cannot "
                    f"run without coverage."
                ),
                "scoreable_required": scoreable_required,
                "skipped_required": skipped_required,
                "selected_gold_filings": [f.filing_url for f in gold_filings],
            }
        if gold_missing and limit is not None:
            logger.warning(
                "smoke eval --limit %d: gold corpus does not cover required "
                "metrics %s — proceeding because --limit was explicitly set",
                limit,
                gold_missing,
            )

    # ---- Reviewed corpus ----
    reviewed_filings: list[FilingSelection] = []
    db_url = os.environ.get("DATABASE_URL")
    if not gold_only:
        if not db_url:
            return 2, {
                "error": (
                    "Reviewed corpus requires DATABASE_URL. Use --gold-only to "
                    "skip the reviewed corpus."
                )
            }
        gold_urls = frozenset(f.filing_url for f in gold_filings)
        reviewed_filings = select_reviewed_corpus(db_url, exclude_urls=gold_urls, limit=limit or 5)

    # ---- Dry run early-out ----
    if dry_run:
        rows: list[EvalRow] = []
        run_finished_at = datetime.now(UTC).isoformat()
        # Header-only CSV writes 0 rows; the integration test asserts the
        # header is present and the summary has empty rollups.
        csv_path = out_dir / f"phase1_10filing_{run_id}.csv"
        summary_path = out_dir / f"phase1_10filing_{run_id}_summary.json"
        write_csv(rows, csv_path)
        summary: dict[str, Any] = {
            "run_id": run_id,
            "run_started_at": run_started_at,
            "run_finished_at": run_finished_at,
            "path": path_mode,
            "dry_run": True,
            "scoreable_required_metrics": scoreable_required,
            "skipped_required_metrics_unenrolled": skipped_required,
            "preferred_reviewed_metrics": list(PLAN_PREFERRED_REVIEWED_METRICS),
            "selected_gold_filings": [f.filing_url for f in gold_filings],
            "selected_reviewed_filings": [
                {
                    "filing_url": f.filing_url,
                    "filing_id": f.filing_id,
                    "company": f.company,
                }
                for f in reviewed_filings
            ],
            "gold_negative_caveat": (
                "Gold negatives are weakly-true negatives — gold-set absence "
                "does not mean labeled absent. Per-metric precision against "
                "gold is biased high by definition."
            ),
            "per_metric": {"gold": {}, "reviewed": {}},
            "smoke": {
                "pass_prompt_errors": True,
                "pass_disagreement_count": True,
                "pass_catastrophic_regression": True,
                "prompt_errors": [],
                "catastrophic_metrics": [],
                "disagreements_total": 0,
                "stratified_30_sample": [],
            },
            "errors": [],
        }
        write_summary(summary, summary_path)
        return 0, summary

    # ---- Live run ----
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return 2, {
            "error": (
                "ANTHROPIC_API_KEY is required for live eval. Use --dry-run "
                "to exercise corpus/label/CSV plumbing without API calls."
            )
        }

    # Build labels.
    gold_labels = build_gold_labels(
        GOLD_CSV,
        frozenset(f.filing_url for f in gold_filings),
        metric_ids,
    )
    reviewed_filing_ids = [f.filing_id for f in reviewed_filings if f.filing_id is not None]
    reviewed_labels = (
        build_reviewed_labels(db_url, reviewed_filing_ids, metric_ids)
        if (reviewed_filing_ids and db_url)
        else {}
    )

    # Keyword baseline (path-direct) — only for filings with filing_ids
    # AND a DB connection. Gold corpus filings don't carry filing_ids, so
    # baseline is None for them by default.
    kw_baseline_reviewed: dict[tuple[int, str], bool] = {}
    if reviewed_filing_ids and db_url:
        kw_baseline_reviewed = keyword_baseline_path_b(db_url, reviewed_filing_ids, metric_ids)

    rows: list[EvalRow] = []
    errors: list[dict[str, Any]] = []

    if path_mode == "pipeline":
        # Path A: run V2 pipeline per filing; keyword baseline from context.candidates.
        try:
            enriched = _enrich_filings_for_path_a(gold_filings + reviewed_filings, db_url)
        except RuntimeError as enrich_err:
            return 2, {"error": str(enrich_err), "run_started_at": run_started_at}

        for paf in enriched:
            aggregates_a, kw_present_a, fil_errors = evaluate_filing_pipeline(paf, metric_ids)
            errors.extend(fil_errors)
            for metric in metric_ids:
                if paf.selection.corpus == "gold":
                    gt = gold_labels.get((paf.selection.filing_url, metric))
                else:
                    gt = reviewed_labels.get((paf.filing_id, metric))
                rows.append(
                    _classify_eval_row(
                        run_id=run_id,
                        run_started_at=run_started_at,
                        run_finished_at="",
                        filing=paf.selection,
                        metric_id=metric,
                        ground_truth=gt,
                        aggregate=aggregates_a.get(metric),
                        keyword_present=kw_present_a.get(metric),
                    )
                )

    else:
        # Path B (direct): call PresenceClassifierClient on gold quotes / v2_segments.
        from src.llm.presence_classifier_client import PresenceClassifierClient

        client = PresenceClassifierClient()

        # Gold filings: score gold-CSV quotes.
        if gold_filings:
            gold_quotes_map = _gold_quotes_per_filing(
                GOLD_CSV, frozenset(f.filing_url for f in gold_filings)
            )
            for filing in gold_filings:
                quotes = gold_quotes_map.get(filing.filing_url, [])
                aggregates, fil_errors = evaluate_filing_direct(
                    filing,
                    metric_ids,
                    client,
                    gold_quotes=quotes,
                )
                errors.extend(fil_errors)
                for metric in metric_ids:
                    gt = gold_labels.get((filing.filing_url, metric))
                    rows.append(
                        _classify_eval_row(
                            run_id=run_id,
                            run_started_at=run_started_at,
                            run_finished_at="",  # filled below
                            filing=filing,
                            metric_id=metric,
                            ground_truth=gt,
                            aggregate=aggregates.get(metric),
                            keyword_present=None,
                        )
                    )

        # Reviewed filings: score paraphrase-eligible v2_segments.
        for filing in reviewed_filings:
            aggregates, fil_errors = evaluate_filing_direct(
                filing,
                metric_ids,
                client,
                db_url=db_url,
                section_whitelist=section_whitelist,
            )
            errors.extend(fil_errors)
            for metric in metric_ids:
                gt = reviewed_labels.get((filing.filing_id, metric))
                kw = kw_baseline_reviewed.get((filing.filing_id, metric))
                rows.append(
                    _classify_eval_row(
                        run_id=run_id,
                        run_started_at=run_started_at,
                        run_finished_at="",
                        filing=filing,
                        metric_id=metric,
                        ground_truth=gt,
                        aggregate=aggregates.get(metric),
                        keyword_present=kw,
                    )
                )

    run_finished_at = datetime.now(UTC).isoformat()
    for r in rows:
        r.run_finished_at = run_finished_at

    # Smoke-test criteria.
    smoke = compute_smoke_criteria(rows, errors)

    # Output.
    csv_path = out_dir / f"phase1_10filing_{run_id}.csv"
    summary_path = out_dir / f"phase1_10filing_{run_id}_summary.json"
    write_csv(rows, csv_path)

    summary: dict[str, Any] = {
        "run_id": run_id,
        "run_started_at": run_started_at,
        "run_finished_at": run_finished_at,
        "path": path_mode,
        "dry_run": False,
        "scoreable_required_metrics": scoreable_required,
        "skipped_required_metrics_unenrolled": skipped_required,
        "preferred_reviewed_metrics": list(PLAN_PREFERRED_REVIEWED_METRICS),
        "selected_gold_filings": [f.filing_url for f in gold_filings],
        "selected_reviewed_filings": [
            {
                "filing_url": f.filing_url,
                "filing_id": f.filing_id,
                "company": f.company,
            }
            for f in reviewed_filings
        ],
        "gold_negative_caveat": (
            "Gold negatives are weakly-true negatives — gold-set absence "
            "does not mean labeled absent. Per-metric precision against "
            "gold is biased high by definition."
        ),
        "per_metric": {
            "gold": _per_metric_prf(rows, "gold"),
            "reviewed": _per_metric_prf(rows, "reviewed"),
        },
        "smoke": {
            "pass_prompt_errors": smoke.pass_prompt_errors,
            "pass_disagreement_count": smoke.pass_disagreement_count,
            "pass_catastrophic_regression": smoke.pass_catastrophic_regression,
            "prompt_errors": smoke.prompt_errors,
            "catastrophic_metrics": smoke.catastrophic_metrics,
            "disagreements_total": smoke.disagreements_total,
            "stratified_30_sample": smoke.stratified_30_sample,
        },
        "errors": errors,
    }
    write_summary(summary, summary_path)

    exit_code = 1 if smoke.has_hard_failure else 0
    return exit_code, summary


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="run_phase1_eval",
        description=__doc__.split("\n\n")[0],
    )
    p.add_argument("--gold-only", action="store_true", help="skip reviewed corpus")
    p.add_argument("--reviewed-only", action="store_true", help="skip gold corpus")
    p.add_argument("--limit", type=int, default=None, help="filings per corpus (default 5)")
    p.add_argument(
        "--filing-url",
        default=None,
        help=(
            "force-select a single gold-corpus filing by its split-JSON URL "
            "(bypasses the deterministic greedy selector). Useful for "
            "iterating on a specific filing — e.g. validating a prompt "
            "tweak. Reviewed corpus is skipped when this flag is set; "
            "use Path A only."
        ),
    )
    p.add_argument(
        "--run-id",
        default=None,
        help="override timestamp run_id (default: UTC YYYYMMDDTHHMM)",
    )
    p.add_argument(
        "--out-dir",
        type=Path,
        default=DEFAULT_OUT_DIR,
        help=f"output directory (default {DEFAULT_OUT_DIR})",
    )
    p.add_argument(
        "--path",
        choices=("pipeline", "direct"),
        default="direct",
        help="default 'direct' (cheap smoke); 'pipeline' is reserved for follow-up",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="build labels + select corpora + write empty CSV; no API/DB writes",
    )
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    run_id = args.run_id or datetime.now(UTC).strftime("%Y%m%dT%H%M")
    exit_code, summary = run_eval(
        run_id=run_id,
        out_dir=args.out_dir,
        path_mode=args.path,
        gold_only=args.gold_only,
        reviewed_only=args.reviewed_only,
        limit=args.limit,
        dry_run=args.dry_run,
        forced_gold_url=args.filing_url,
    )
    if exit_code != 0:
        logger.error(
            "smoke eval exit_code=%d: %s", exit_code, summary.get("error", "<see summary>")
        )
    else:
        logger.info("smoke eval complete: run_id=%s", run_id)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
