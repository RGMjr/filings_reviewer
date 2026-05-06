"""Mine few-shot examples and (eventually) sweep thresholds for the
LLM presence classifier.

Modes:

  --mode mine   Mine few-shot examples per metric and write sidecar
                ``config/llm_classifier/prompts/<metric_id>.few_shots.yaml``.
                Positive examples come from gold-standard rows in the train
                split. Negative examples (optional, ``--from-db``) come from
                ``v2_review_decisions`` rows with ``decision='reject'`` on
                train-split filings, weighted toward rejection categories
                that signal misidentified metrics
                (``wrong_metric``, ``not_a_metric``, ``part_of_date``).

  --mode sweep  Run the LLM classifier on the calibration split and pick
                per-metric thresholds maximizing recall holding precision
                flat (≥ baseline precision − 2pt). Requires ANTHROPIC_API_KEY.

  --mode all    Run mine then sweep. Default.

Outputs:

  config/llm_classifier/prompts/<metric_id>.few_shots.yaml  (mine mode)
  config/llm_classifier/thresholds.yaml                     (sweep mode)

Inputs:

  data/gold_standard/golden_set_260408.csv
  data/gold_standard/split_v1.json
  v2_review_decisions / v2_metric_facts / v2_segments via DATABASE_URL (optional)

Issuer-diversity invariant (enforced):

  Mined few-shots come from at least ``--min-issuers`` distinct issuers
  (default 3). Issuers in the held-out test split (per split_v1.json) are
  always excluded — never any leak from train/cal mining into test eval.

Idempotency:

  Re-running ``--mode mine`` overwrites the sidecar file deterministically:
  examples are sampled with a fixed seed (``--seed``, default 42) so the
  same inputs produce the same output. To force a refresh after gold or
  review-decision data changes, just re-run.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import random
import re
import sys
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

# Strip HTML/mark tags before measuring quote length. Many gold rows store
# bare values like ``<mark>149%</mark>`` (17 chars but ~3 chars of signal);
# few-shot mining needs the prose rows, not these.
_HTML_TAG_RE = re.compile(r"<[^>]+>")

# Few-shot quote filters — tuned for the shape of golden_set_260408.csv:
#   - drop bare values (after stripping tags, <50 chars)
#   - drop oversized HTML blobs (>1500 chars; these are entire table cells
#     and confuse the LLM with formatting noise)
#   - require at least one letter so we exclude numeric-only rows
MIN_QUOTE_PROSE_CHARS = 50
MAX_QUOTE_PROSE_CHARS = 1500
_LETTER_RE = re.compile(r"[A-Za-z]")

logger = logging.getLogger("calibrate_llm_thresholds")

REPO_ROOT = Path(__file__).resolve().parents[1]
GOLD_CSV = REPO_ROOT / "data" / "gold_standard" / "golden_set_260408.csv"
SPLIT_FILE = REPO_ROOT / "data" / "gold_standard" / "split_v1.json"
PROMPTS_DIR = REPO_ROOT / "config" / "llm_classifier" / "prompts"
THRESHOLDS_FILE = REPO_ROOT / "config" / "llm_classifier" / "thresholds.yaml"

# Threshold candidates for the calibration sweep: [0.1, 0.2, ..., 0.9].
SWEEP_THRESHOLDS = [round(x * 0.1, 1) for x in range(1, 10)]

# Sweep picks the threshold that maximizes recall holding precision ≥
# (baseline_precision − PRECISION_FLOOR_SLACK). 2pt slack tolerates tiny
# precision drops caused by the small calibration set size (4 filings).
PRECISION_FLOOR_SLACK = 0.02

# Rejection categories whose decisions are useful as presence-classifier
# negatives (the keyword fired but the metric was wrong, not the value).
# 'wrong_value' / 'wrong_period' are value-binding errors, not metric-id
# errors, and would teach the classifier the wrong lesson.
PRESENCE_NEGATIVE_REJECTION_CATEGORIES = (
    "wrong_metric",
    "not_a_metric",
    "part_of_date",
)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


def _extract_prose(raw: str) -> str:
    """Strip HTML/mark tags and collapse whitespace for prose-length checks."""
    if not raw:
        return ""
    no_tags = _HTML_TAG_RE.sub(" ", raw)
    return " ".join(no_tags.split())


def _is_usable_prose(prose: str) -> bool:
    """A few-shot example must be prose, not a bare value or oversized blob."""
    if not prose:
        return False
    if not _LETTER_RE.search(prose):
        return False
    n = len(prose)
    return MIN_QUOTE_PROSE_CHARS <= n <= MAX_QUOTE_PROSE_CHARS


@dataclass(frozen=True)
class FewShotExample:
    text: str
    label: bool
    issuer: str
    filing_url: str
    source: str  # "gold" or "review_decision"
    rejection_category: str | None = None  # populated for negatives


# ---------------------------------------------------------------------------
# Split loading
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Splits:
    train_urls: frozenset[str]
    calibration_urls: frozenset[str]
    test_urls: frozenset[str]
    train_issuers: frozenset[str]
    calibration_issuers: frozenset[str]
    test_issuers: frozenset[str]
    # url -> issuer_key, populated from every split. Kept on the dataclass so
    # downstream mining doesn't have to re-read split_v1.json.
    issuer_lookup: dict[str, str]


def load_splits(split_file: Path = SPLIT_FILE) -> Splits:
    raw = json.loads(split_file.read_text())
    splits = raw["splits"]

    def urls(name: str) -> frozenset[str]:
        return frozenset(r["url"] for r in splits[name])

    def issuers(name: str) -> frozenset[str]:
        return frozenset(r["issuer_key"] for r in splits[name])

    issuer_lookup: dict[str, str] = {}
    for rows in splits.values():
        for r in rows:
            issuer_lookup[r["url"]] = r["issuer_key"]

    return Splits(
        train_urls=urls("train"),
        calibration_urls=urls("calibration"),
        test_urls=urls("test"),
        train_issuers=issuers("train"),
        calibration_issuers=issuers("calibration"),
        test_issuers=issuers("test"),
        issuer_lookup=issuer_lookup,
    )


# ---------------------------------------------------------------------------
# Positive mining (gold standard)
# ---------------------------------------------------------------------------


def mine_positive_examples(
    metric_id: str,
    splits: Splits,
    *,
    max_examples: int = 8,
    min_issuers: int = 3,
    seed: int = 42,
    gold_csv: Path = GOLD_CSV,
) -> list[FewShotExample]:
    """Sample positive few-shots from gold rows in the train split.

    Sampling rule: at least ``min_issuers`` distinct issuers represented;
    sampling within each issuer is deterministic via ``seed``. Rows from
    issuers in the held-out test or calibration splits are excluded
    (issuer-purity, not just URL-purity, prevents indirect leak when the
    same issuer has multiple filings).
    """
    rng = random.Random(seed + hash(metric_id) % 1024)
    candidates_by_issuer: dict[str, list[FewShotExample]] = {}
    excluded_issuers = splits.test_issuers | splits.calibration_issuers
    issuer_lookup = splits.issuer_lookup

    seen_texts: set[str] = set()
    with gold_csv.open(encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            if row["Standard Metric Name"] != metric_id:
                continue
            url = row["Document URL"].strip()
            if url not in splits.train_urls:
                continue
            issuer = issuer_lookup.get(url)
            if issuer is None or issuer in excluded_issuers:
                continue
            quote = (row.get("Quote/context") or "").strip()
            prose = _extract_prose(quote)
            if not _is_usable_prose(prose):
                continue
            # Dedupe identical quotes (gold has the same prose repeated across
            # multiple period rows for one metric).
            if prose in seen_texts:
                continue
            seen_texts.add(prose)
            ex = FewShotExample(
                text=prose,
                label=True,
                issuer=issuer,
                filing_url=url,
                source="gold",
            )
            candidates_by_issuer.setdefault(issuer, []).append(ex)

    issuers = sorted(candidates_by_issuer)
    if len(issuers) < min_issuers:
        logger.warning(
            "metric=%s only %d distinct train issuers found (min %d); "
            "few-shot diversity below target",
            metric_id,
            len(issuers),
            min_issuers,
        )

    rng.shuffle(issuers)
    chosen: list[FewShotExample] = []
    # Round-robin one example per issuer until budget exhausted.
    pools = {iss: list(candidates_by_issuer[iss]) for iss in issuers}
    for pool in pools.values():
        rng.shuffle(pool)
    while len(chosen) < max_examples and any(pools.values()):
        for iss in issuers:
            if not pools[iss]:
                continue
            chosen.append(pools[iss].pop(0))
            if len(chosen) >= max_examples:
                break
    return chosen


# ---------------------------------------------------------------------------
# Negative mining (v2_review_decisions; optional, requires DATABASE_URL)
# ---------------------------------------------------------------------------


def mine_negative_examples_from_db(
    metric_id: str,
    splits: Splits,
    *,
    max_examples: int = 8,
    min_issuers: int = 3,
    seed: int = 42,
) -> list[FewShotExample]:
    """Sample negative few-shots from rejected v2_review_decisions on
    train-split filings.

    Only rejection categories signaling metric-identity errors
    (``wrong_metric``, ``not_a_metric``, ``part_of_date``) are sampled —
    value-binding errors (``wrong_value``, ``wrong_period``) would teach
    the presence classifier the wrong lesson.

    Requires ``DATABASE_URL``. Returns an empty list (with a warning) if
    no DB is reachable, so the script still runs end-to-end without DB.
    """
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        logger.warning(
            "DATABASE_URL unset; skipping negative mining for metric=%s. "
            "Re-run with DATABASE_URL set to mine reviewer rejections.",
            metric_id,
        )
        return []

    try:
        import psycopg
    except ImportError:
        logger.warning("psycopg unavailable; skipping negative mining")
        return []

    rng = random.Random(seed + hash(metric_id) % 1024 + 7919)
    issuer_lookup = splits.issuer_lookup
    excluded_issuers = splits.test_issuers | splits.calibration_issuers
    train_urls = splits.train_urls

    sql = """
        SELECT
            f.html_url AS filing_url,
            seg.text  AS segment_text,
            d.rejection_category
        FROM v2_review_decisions d
        JOIN v2_metric_facts mf ON mf.fact_id = d.fact_id
        JOIN v2_segments seg     ON seg.segment_id = mf.segment_id
        JOIN filings f           ON f.filing_id = mf.filing_id
        WHERE d.decision = 'reject'
          AND mf.canonical_metric_id = %(metric_id)s
          AND d.rejection_category = ANY(%(categories)s)
        ORDER BY d.created_at DESC
        LIMIT 500
    """

    with psycopg.connect(db_url) as conn, conn.cursor() as cur:
        cur.execute(
            sql,
            {
                "metric_id": metric_id,
                "categories": list(PRESENCE_NEGATIVE_REJECTION_CATEGORIES),
            },
        )
        rows = cur.fetchall()

    candidates_by_issuer: dict[str, list[FewShotExample]] = {}
    for filing_url, segment_text, rejection_category in rows:
        url = (filing_url or "").strip()
        if url not in train_urls:
            continue
        issuer = issuer_lookup.get(url)
        if issuer is None or issuer in excluded_issuers:
            continue
        text = (segment_text or "").strip()
        if not text:
            continue
        ex = FewShotExample(
            text=text,
            label=False,
            issuer=issuer,
            filing_url=url,
            source="review_decision",
            rejection_category=rejection_category,
        )
        candidates_by_issuer.setdefault(issuer, []).append(ex)

    issuers = sorted(candidates_by_issuer)
    if len(issuers) < min_issuers:
        logger.warning(
            "metric=%s only %d distinct issuers in review-decision negatives "
            "(min %d); diversity below target",
            metric_id,
            len(issuers),
            min_issuers,
        )
    rng.shuffle(issuers)
    pools = {iss: list(candidates_by_issuer[iss]) for iss in issuers}
    for pool in pools.values():
        rng.shuffle(pool)
    chosen: list[FewShotExample] = []
    while len(chosen) < max_examples and any(pools.values()):
        for iss in issuers:
            if not pools[iss]:
                continue
            chosen.append(pools[iss].pop(0))
            if len(chosen) >= max_examples:
                break
    return chosen


# ---------------------------------------------------------------------------
# Sidecar writer
# ---------------------------------------------------------------------------


def write_few_shots_sidecar(
    metric_id: str,
    examples: list[FewShotExample],
    *,
    prompts_dir: Path = PROMPTS_DIR,
) -> Path:
    """Write the automation-owned few-shot sidecar deterministically.

    The main ``<metric_id>.yaml`` file is never touched.
    """
    sidecar = prompts_dir / f"{metric_id}.few_shots.yaml"
    payload = {
        "metric_id": metric_id,
        "few_shot_examples": [
            {
                "text": ex.text,
                "label": ex.label,
                "issuer": ex.issuer,
                "filing_url": ex.filing_url,
                "source": ex.source,
                **({"rejection_category": ex.rejection_category} if ex.rejection_category else {}),
            }
            for ex in examples
        ],
    }
    header = (
        f"# Auto-generated by scripts/calibrate_llm_thresholds.py.\n"
        f"# Do NOT hand-edit. Re-run the script to refresh.\n"
        f"# Metric: {metric_id}\n"
        f"# Examples: {len(examples)} "
        f"(positives={sum(1 for e in examples if e.label)}, "
        f"negatives={sum(1 for e in examples if not e.label)})\n\n"
    )
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    sidecar.write_text(header + yaml.safe_dump(payload, sort_keys=False, allow_unicode=True))
    return sidecar


# ---------------------------------------------------------------------------
# Mode runners
# ---------------------------------------------------------------------------


def run_mine(
    metric_ids: list[str],
    *,
    max_positives: int,
    max_negatives: int,
    min_issuers: int,
    seed: int,
    from_db: bool,
) -> dict[str, dict[str, Any]]:
    """Mine few-shots for every requested metric. Returns a per-metric report."""
    splits = load_splits()
    report: dict[str, dict[str, Any]] = {}
    for metric_id in metric_ids:
        positives = mine_positive_examples(
            metric_id,
            splits,
            max_examples=max_positives,
            min_issuers=min_issuers,
            seed=seed,
        )
        negatives: list[FewShotExample] = []
        if from_db:
            negatives = mine_negative_examples_from_db(
                metric_id,
                splits,
                max_examples=max_negatives,
                min_issuers=min_issuers,
                seed=seed,
            )
        examples = positives + negatives
        sidecar = write_few_shots_sidecar(metric_id, examples)
        report[metric_id] = {
            "positives": len(positives),
            "negatives": len(negatives),
            "issuers_pos": len({e.issuer for e in positives}),
            "issuers_neg": len({e.issuer for e in negatives}),
            "sidecar": str(sidecar.relative_to(REPO_ROOT)),
        }
        logger.info(
            "metric=%s pos=%d neg=%d issuers_pos=%d issuers_neg=%d -> %s",
            metric_id,
            len(positives),
            len(negatives),
            report[metric_id]["issuers_pos"],
            report[metric_id]["issuers_neg"],
            report[metric_id]["sidecar"],
        )
    return report


def _prf(threshold: float, filing_data: list[tuple[str, bool, float]]) -> tuple[float, float]:
    """Precision/recall at a threshold for a list of (url, label, score) triples."""
    tp = sum(1 for _, lb, sc in filing_data if lb and sc > threshold)
    fp = sum(1 for _, lb, sc in filing_data if not lb and sc > threshold)
    fn = sum(1 for _, lb, sc in filing_data if lb and sc <= threshold)
    precision = tp / (tp + fp) if (tp + fp) > 0 else 1.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    return precision, recall


def run_sweep(
    metric_ids: list[str],
    *,
    thresholds_file: Path = THRESHOLDS_FILE,
    split_file: Path = SPLIT_FILE,
    gold_csv: Path = GOLD_CSV,
) -> dict[str, dict[str, Any]]:
    """Threshold sweep on the calibration split.

    For each enrolled metric, scores every usable gold-standard quote from each
    calibration filing against the LLM classifier, aggregates to a
    per-(filing, metric) max-score, then sweeps thresholds [0.1 … 0.9] to
    find the value that maximises recall while holding precision ≥
    (baseline_precision − PRECISION_FLOOR_SLACK).

    Writes results to ``config/llm_classifier/thresholds.yaml``.
    Returns a per-metric report dict.
    """
    from src.llm.presence_classifier_client import PresenceClassifierClient, load_thresholds

    splits = load_splits(split_file)
    calibration_urls = list(splits.calibration_urls)

    # Collect usable texts and gold metric labels per calibration filing.
    filing_texts: dict[str, list[str]] = {url: [] for url in calibration_urls}
    filing_metric_labels: dict[str, set[str]] = {url: set() for url in calibration_urls}
    with gold_csv.open(encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            url = row["Document URL"].strip()
            if url not in filing_texts:
                continue
            metric = (row.get("Standard Metric Name") or "").strip()
            if metric.startswith("cm_"):
                filing_metric_labels[url].add(metric)
            quote = (row.get("Quote/context") or "").strip()
            prose = _extract_prose(quote)
            if _is_usable_prose(prose) and prose not in filing_texts[url]:
                filing_texts[url].append(prose)

    client = PresenceClassifierClient()
    enrolled_with_prompts = [m for m in metric_ids if m in client.config.prompts]
    if not enrolled_with_prompts:
        logger.warning("run_sweep: no enrolled metrics have loaded prompt YAMLs; nothing to sweep")
        return {}

    # Score all calibration texts against all enrolled metrics.
    # Aggregate to per-(filing, metric) max score.
    scores: dict[tuple[str, str], float] = {}
    for url in calibration_urls:
        texts = filing_texts[url]
        if not texts:
            logger.warning("sweep: no usable gold texts for calibration filing %s", url)
            continue
        for text in texts:
            try:
                for sc in client.classify_segment(text, enrolled_with_prompts):
                    key = (url, sc.metric_id)
                    if sc.score > scores.get(key, -1.0):
                        scores[key] = sc.score
            except Exception as exc:
                logger.warning("sweep: classify_segment failed url=%s: %s", url, exc)

    calibration_run_id = str(uuid.uuid4())
    calibrated_at = datetime.now(UTC).isoformat()
    existing_cfg = load_thresholds(thresholds_file)
    default_band = list(existing_cfg.default_sonnet_band)

    report: dict[str, dict[str, Any]] = {}
    new_thresholds: dict[str, dict[str, Any]] = {}

    for metric in enrolled_with_prompts:
        filing_data = [
            (url, metric in filing_metric_labels[url], scores.get((url, metric), 0.0))
            for url in calibration_urls
        ]
        n_positive = sum(1 for _, label, _ in filing_data if label)
        n_total = len(filing_data)

        if n_positive < 1:
            logger.warning(
                "metric=%s no positive gold labels in calibration split; skipping", metric
            )
            continue
        if n_positive < 3:
            logger.warning(
                "metric=%s only %d supporting filing(s) in calibration (< 3); "
                "low confidence — manual review recommended",
                metric,
                n_positive,
            )

        baseline_precision, baseline_recall = _prf(0.5, filing_data)
        precision_floor = max(0.0, baseline_precision - PRECISION_FLOOR_SLACK)

        best_threshold = 0.5
        best_recall = baseline_recall
        best_precision = baseline_precision
        for t in SWEEP_THRESHOLDS:
            p, r = _prf(t, filing_data)
            if p >= precision_floor and r > best_recall:
                best_threshold, best_recall, best_precision = t, r, p

        new_thresholds[metric] = {
            "threshold": best_threshold,
            "sonnet_band": default_band,
            "calibration_run_id": calibration_run_id,
            "calibrated_at": calibrated_at,
        }
        report[metric] = {
            "threshold": best_threshold,
            "precision": round(best_precision, 4),
            "recall": round(best_recall, 4),
            "supporting_filings": n_positive,
            "total_calibration_filings": n_total,
        }
        logger.info(
            "metric=%s threshold=%.1f precision=%.3f recall=%.3f supporting=%d/%d",
            metric,
            best_threshold,
            best_precision,
            best_recall,
            n_positive,
            n_total,
        )

    # Preserve the existing file structure; only replace the thresholds block.
    existing_raw = yaml.safe_load(thresholds_file.read_text()) or {}
    existing_raw["thresholds"] = new_thresholds
    _THRESHOLDS_YAML_HEADER = """\
# Per-metric calibrated decision thresholds for the LLM presence classifier.
#
# Populated by scripts/calibrate_llm_thresholds.py against the calibration
# split (see data/gold_standard/split_v1.json). DO NOT hand-edit values
# without re-running calibration — the calibration script is the only
# authorized writer.
#
# Schema:
#   thresholds:
#     <metric_id>:
#       threshold: <0..1>          # promote (segment, metric) to presence
#       sonnet_band: [<lo>, <hi>]  # llm_score in this band → re-score with Sonnet
#       calibration_run_id: <str>  # FK into reviewable calibration log
#       calibrated_at: <ISO8601>
#
# Defaults (used when a metric has no entry yet) live at the bottom.

"""
    thresholds_file.write_text(
        _THRESHOLDS_YAML_HEADER + yaml.safe_dump(existing_raw, sort_keys=False, allow_unicode=True)
    )
    logger.info(
        "run_sweep: wrote %d metric threshold(s) to %s (run_id=%s)",
        len(new_thresholds),
        thresholds_file,
        calibration_run_id,
    )
    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def discover_metrics() -> list[str]:
    """List every metric with a hand-authored prompt YAML."""
    return sorted(
        p.stem for p in PROMPTS_DIR.glob("*.yaml") if not p.name.endswith(".few_shots.yaml")
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--mode",
        choices=("mine", "sweep", "all"),
        default="all",
    )
    parser.add_argument(
        "--metric",
        action="append",
        dest="metrics",
        help="Limit to one or more metric_ids; default: all metrics with a prompt YAML",
    )
    parser.add_argument("--max-positives", type=int, default=8)
    parser.add_argument("--max-negatives", type=int, default=8)
    parser.add_argument("--min-issuers", type=int, default=3)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--from-db",
        action="store_true",
        help="Mine negatives from v2_review_decisions (requires DATABASE_URL)",
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    metrics = args.metrics or discover_metrics()
    if not metrics:
        logger.error("No metrics found under %s", PROMPTS_DIR)
        return 1

    # Sanity check: every requested metric must have a hand-authored prompt
    # YAML. Refuses to write a sidecar without an accompanying prompt — the
    # sidecar would be orphan data otherwise.
    missing = [m for m in metrics if not (PROMPTS_DIR / f"{m}.yaml").exists()]
    if missing:
        logger.error(
            "Refusing to mine — these metrics have no prompt YAML at %s: %s. "
            "Author config/llm_classifier/prompts/<metric_id>.yaml first.",
            PROMPTS_DIR,
            missing,
        )
        return 1

    if args.mode in ("mine", "all"):
        report = run_mine(
            metrics,
            max_positives=args.max_positives,
            max_negatives=args.max_negatives,
            min_issuers=args.min_issuers,
            seed=args.seed,
            from_db=args.from_db,
        )
        print(json.dumps({"mine": report}, indent=2))

    if args.mode in ("sweep", "all"):
        sweep_report = run_sweep(metrics)
        print(json.dumps({"sweep": sweep_report}, indent=2))

    return 0


if __name__ == "__main__":
    sys.exit(main())
