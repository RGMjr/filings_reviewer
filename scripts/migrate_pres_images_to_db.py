#!/usr/bin/env python3
"""
Migrate presentation image review data from JSON files to PostgreSQL.

Reads per-filing candidate JSON files and the consolidated decisions JSON from
data/presentation_gold_standard/ and writes them into the image_review_candidates
and image_review_decisions tables.

Usage:
    # Preview what would be migrated (no writes)
    python3 scripts/migrate_pres_images_to_db.py --dry-run

    # Migrate all keys
    python3 scripts/migrate_pres_images_to_db.py

    # Migrate a single key
    python3 scripts/migrate_pres_images_to_db.py --key CART_S-1_2023-09-15

    # Use a non-default data directory
    python3 scripts/migrate_pres_images_to_db.py --data-dir /path/to/data
"""

import argparse
import json
import logging
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

# Add project root to path so src.* imports resolve
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

from src.infra.db import DatabaseAdapter

logger = logging.getLogger(__name__)

# ============================================================================
# Accession number normalization
# ============================================================================

_ACCESSION_RAW_RE = re.compile(r"/(\d{18})/")


def _normalize_accession(raw: str) -> str:
    """Convert 18-digit raw accession to dashed format.

    Example: '000119312523235646' -> '0001193125-23-235646'
    """
    if len(raw) != 18 or not raw.isdigit():
        raise ValueError(f"Unexpected raw accession format: {raw!r}")
    return f"{raw[:10]}-{raw[10:12]}-{raw[12:]}"


def extract_accession_from_url(url: str) -> str | None:
    """Extract and normalize the accession number embedded in a SEC EDGAR URL.

    URL pattern: https://www.sec.gov/Archives/edgar/data/{CIK}/{ACCESSION_RAW}/{filename}
    """
    match = _ACCESSION_RAW_RE.search(url)
    if not match:
        return None
    return _normalize_accession(match.group(1))


# ============================================================================
# Filing lookup
# ============================================================================


def lookup_filing(db: DatabaseAdapter, accession_number: str) -> dict | None:
    """Return {filing_id, company_id} for the given accession number, or None."""
    rows = db.query(
        "SELECT filing_id, company_id FROM filings WHERE accession_number = %s",
        (accession_number,),
    )
    if not rows:
        return None
    row = rows[0]
    return {"filing_id": int(row["filing_id"]), "company_id": int(row["company_id"])}


# ============================================================================
# Per-key migration
# ============================================================================


def migrate_key(
    key: str,
    candidates: list[dict],
    decisions_by_img_id: dict[str, dict],
    db: DatabaseAdapter | None,
    dry_run: bool,
    filing_info: dict | None,
) -> dict:
    """Migrate one filing key's candidates and decisions.

    Args:
        key: Filing key, e.g. 'CART_S-1_2023-09-15'
        candidates: List of candidate dicts from the JSON file
        decisions_by_img_id: Mapping of img_id -> decision dict (for this key)
        db: DatabaseAdapter (None only in dry-run without DB)
        dry_run: If True, log actions but do not write
        filing_info: {filing_id, company_id} or None (if not found in DB)

    Returns:
        Stats dict with counts for this key
    """
    stats: dict[str, int] = defaultdict(int)

    if filing_info is None:
        logger.warning(
            f"[{key}] Filing not found in DB — skipping all {len(candidates)} candidates"
        )
        stats["skipped_no_filing"] = len(candidates)
        return dict(stats)

    filing_id = filing_info["filing_id"]
    company_id = filing_info["company_id"]

    for cand in candidates:
        img_id: str = cand.get("img_id", "")
        if not img_id:
            logger.warning(f"[{key}] Candidate missing img_id, skipping")
            stats["errors"] += 1
            continue

        image_url: str = cand.get("image_url", "")
        if not image_url:
            logger.warning(f"[{key}] Candidate {img_id} missing image_url, skipping")
            stats["errors"] += 1
            continue

        # Clamp relevance_score to [0, 1]
        raw_score = cand.get("relevance_score", 0.0)
        try:
            cohort_confidence = float(raw_score)
        except (TypeError, ValueError):
            cohort_confidence = 0.0
        cohort_confidence = max(0.0, min(1.0, cohort_confidence))

        width = cand.get("width") or None
        height = cand.get("height") or None
        # Treat 0 as None (missing dimension)
        if width == 0:
            width = None
        if height == 0:
            height = None

        preceding_text = cand.get("nearby_text") or None

        decision_data = decisions_by_img_id.get(img_id)

        if dry_run:
            action = "would insert candidate"
            if decision_data:
                dec = decision_data.get("decision", "")
                if dec == "skip":
                    action += " + would set status=skipped"
                elif dec in ("relevant", "not_relevant"):
                    action += f" + would insert decision ({dec})"
            logger.info(f"[{key}] {action}: {img_id}")
            stats["candidates_would_insert"] += 1
            if decision_data:
                stats["decisions_would_insert"] += 1
            continue

        # Insert candidate
        try:
            candidate_id = db.insert_image_review_candidate(
                filing_id=filing_id,
                company_id=company_id,
                image_src=img_id,
                image_url=image_url,
                source_segment_id=None,
                image_width=width,
                image_height=height,
                image_alt=None,
                preceding_text=preceding_text,
                detected_keywords=None,
                cohort_keyword_nearby=None,
                image_index=None,
                cohort_confidence=cohort_confidence,
                is_decorative=False,
                detection_tier="presentation",
            )
        except Exception as exc:
            logger.error(f"[{key}] Error inserting candidate {img_id}: {exc}")
            stats["errors"] += 1
            continue

        if candidate_id == 0:
            # Conflict returned 0 — shouldn't happen because insert_image_review_candidate
            # fetches the existing row on conflict, but guard anyway
            logger.warning(f"[{key}] Could not resolve candidate_id for {img_id}")
            stats["errors"] += 1
            continue

        stats["candidates_inserted"] += 1

        # Handle decision if present
        if not decision_data:
            continue

        decision_val = decision_data.get("decision", "")

        if decision_val == "skip":
            # Set candidate status to skipped, no decision row
            try:
                db.update_image_candidate_status(candidate_id, "skipped")
                stats["skipped_decisions"] += 1
            except Exception as exc:
                logger.error(f"[{key}] Error marking {img_id} skipped: {exc}")
                stats["errors"] += 1
            continue

        if decision_val not in ("relevant", "not_relevant"):
            logger.warning(
                f"[{key}] Unknown decision value {decision_val!r} for {img_id}, skipping decision"
            )
            stats["errors"] += 1
            continue

        chart_type = decision_data.get("chart_type") or None
        rejection_reason = decision_data.get("rejection_reason") or None
        notes = decision_data.get("notes") or None

        try:
            db.insert_image_review_decision(
                image_candidate_id=candidate_id,
                decision=decision_val,
                chart_type=chart_type,
                rejection_reason=rejection_reason,
                reviewer_id="migration",
                reviewer_notes=notes,
                review_time_seconds=None,
            )
            stats["decisions_inserted"] += 1
        except Exception as exc:
            logger.error(f"[{key}] Error inserting decision for {img_id}: {exc}")
            stats["errors"] += 1

    return dict(stats)


# ============================================================================
# Main
# ============================================================================


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Migrate presentation image review data from JSON files to PostgreSQL",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be migrated without writing to the database",
    )
    parser.add_argument(
        "--key",
        default=None,
        metavar="KEY",
        help="Migrate only this filing key (e.g. CART_S-1_2023-09-15)",
    )
    parser.add_argument(
        "--data-dir",
        default="data/presentation_gold_standard",
        help="Directory containing image candidate JSON files and _image_decisions.json "
        "(default: data/presentation_gold_standard)",
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="Database URL (default: DATABASE_URL from environment / .env)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose (DEBUG) logging",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    # Load .env
    load_dotenv()

    database_url = args.database_url or os.environ.get("DATABASE_URL")
    if not database_url and not args.dry_run:
        print(
            "ERROR: DATABASE_URL not set. "
            "Use --database-url or set DATABASE_URL in your environment / .env file.\n"
            "       Use --dry-run to preview without a database connection.",
            file=sys.stderr,
        )
        return 1

    data_dir = Path(args.data_dir)
    if not data_dir.is_dir():
        print(f"ERROR: Data directory not found: {data_dir}", file=sys.stderr)
        return 1

    # Load consolidated decisions
    decisions_file = data_dir / "_image_decisions.json"
    if not decisions_file.exists():
        print(f"ERROR: Decisions file not found: {decisions_file}", file=sys.stderr)
        return 1

    with open(decisions_file, encoding="utf-8") as f:
        all_decisions: dict[str, dict] = json.load(f)

    logger.info(f"Loaded {len(all_decisions)} decisions from {decisions_file}")

    # Load URL index
    url_index_file = data_dir / "_url_index.json"
    if not url_index_file.exists():
        print(f"ERROR: URL index file not found: {url_index_file}", file=sys.stderr)
        return 1

    with open(url_index_file, encoding="utf-8") as f:
        url_index: dict[str, str] = json.load(f)

    logger.info(f"Loaded {len(url_index)} entries from URL index")

    # Discover candidate files
    candidate_files = sorted(data_dir.glob("*_image_candidates.json"))
    if not candidate_files:
        print(f"ERROR: No *_image_candidates.json files found in {data_dir}", file=sys.stderr)
        return 1

    # Build key -> candidates mapping from filenames
    # Filename format: {KEY}_image_candidates.json
    SUFFIX = "_image_candidates.json"
    key_to_file: dict[str, Path] = {}
    for path in candidate_files:
        if path.name.endswith(SUFFIX):
            k = path.name[: -len(SUFFIX)]
            key_to_file[k] = path

    # Filter to single key if requested
    if args.key:
        if args.key not in key_to_file:
            print(
                f"ERROR: Key {args.key!r} not found. Available keys: {sorted(key_to_file)}",
                file=sys.stderr,
            )
            return 1
        key_to_file = {args.key: key_to_file[args.key]}

    # Build per-key decisions index: key -> {img_id -> decision_dict}
    decisions_by_key: dict[str, dict[str, dict]] = defaultdict(dict)
    for composite_key, decision_obj in all_decisions.items():
        # composite_key format: "{key}:{img_id}"
        if ":" not in composite_key:
            logger.warning(f"Unexpected composite key format: {composite_key!r}, skipping")
            continue
        filing_key = decision_obj.get("key") or composite_key.split(":")[0]
        img_id = decision_obj.get("img_id") or composite_key.split(":", 1)[1]
        decisions_by_key[filing_key][img_id] = decision_obj

    # Connect to database
    db: DatabaseAdapter | None = None
    if database_url:
        try:
            db = DatabaseAdapter(database_url)
            logger.info("Connected to database")
        except Exception as exc:
            if not args.dry_run:
                print(f"ERROR: Could not connect to database: {exc}", file=sys.stderr)
                return 1
            logger.warning(f"Could not connect to database (dry-run continues): {exc}")

    # Aggregate stats
    total_stats: dict[str, int] = defaultdict(int)
    per_key_results: list[tuple[str, dict]] = []

    for key, cand_file in sorted(key_to_file.items()):
        with open(cand_file, encoding="utf-8") as f:
            candidates: list[dict] = json.load(f)

        # Resolve filing from URL index
        filing_info: dict | None = None
        filing_url = url_index.get(key)
        if filing_url is None:
            logger.warning(f"[{key}] No URL in index — cannot resolve filing")
        else:
            accession = extract_accession_from_url(filing_url)
            if accession is None:
                logger.warning(f"[{key}] Could not extract accession from URL: {filing_url}")
            elif db is None:
                # Dry-run without DB: show what we found
                logger.info(f"[{key}] Would look up accession {accession}")
            else:
                filing_info = lookup_filing(db, accession)
                if filing_info is None:
                    logger.warning(
                        f"[{key}] Filing with accession {accession} not found in DB — skipping"
                    )

        key_decisions = decisions_by_key.get(key, {})
        logger.info(
            f"[{key}] Processing {len(candidates)} candidates, {len(key_decisions)} decisions"
        )

        stats = migrate_key(
            key=key,
            candidates=candidates,
            decisions_by_img_id=key_decisions,
            db=db,
            dry_run=args.dry_run,
            filing_info=filing_info,
        )

        per_key_results.append((key, stats))
        for k, v in stats.items():
            total_stats[k] += v

    # Print summary
    print()
    print("=" * 60)
    if args.dry_run:
        print("=== Presentation Image Migration (DRY RUN) ===")
    else:
        print("=== Presentation Image Migration Complete ===")
    print("=" * 60)

    for key, stats in per_key_results:
        parts = []
        if args.dry_run:
            if stats.get("candidates_would_insert", 0):
                parts.append(f"candidates_would_insert={stats['candidates_would_insert']}")
            if stats.get("decisions_would_insert", 0):
                parts.append(f"decisions_would_insert={stats['decisions_would_insert']}")
        else:
            if stats.get("candidates_inserted", 0):
                parts.append(f"candidates_inserted={stats['candidates_inserted']}")
            if stats.get("decisions_inserted", 0):
                parts.append(f"decisions_inserted={stats['decisions_inserted']}")
            if stats.get("skipped_decisions", 0):
                parts.append(f"skipped={stats['skipped_decisions']}")
        if stats.get("skipped_no_filing", 0):
            parts.append(f"skipped_no_filing={stats['skipped_no_filing']}")
        if stats.get("errors", 0):
            parts.append(f"errors={stats['errors']}")
        status = ", ".join(parts) if parts else "nothing to do"
        print(f"  {key}: {status}")

    print()
    if args.dry_run:
        print(
            f"Total candidates that would be inserted : {total_stats.get('candidates_would_insert', 0)}"
        )
        print(
            f"Total decisions that would be inserted  : {total_stats.get('decisions_would_insert', 0)}"
        )
    else:
        print(f"Total candidates inserted : {total_stats.get('candidates_inserted', 0)}")
        print(f"Total decisions inserted  : {total_stats.get('decisions_inserted', 0)}")
        print(f"Total skipped (skip dec.) : {total_stats.get('skipped_decisions', 0)}")
    print(f"Skipped (filing not in DB): {total_stats.get('skipped_no_filing', 0)}")
    print(f"Errors                    : {total_stats.get('errors', 0)}")
    print("=" * 60)

    return 1 if total_stats.get("errors", 0) > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
